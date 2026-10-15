"""Data quality gates. Writes data/serving/health.json and fails the run on breach.

health.json is written before failing so the public status reflects the breach
rather than the last good state.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from src.config import QUARANTINE_PATH, SERVING_DIR, SILVER_PATH, load_settings
from src.transform.delta_io import is_delta
from src.transform.gold import FACT

log = logging.getLogger("quality")

# GitHub's free scheduler leaves 4-6h gaps between delivered runs (incident #1);
# a tighter limit would fail on scheduler noise rather than real outages.
MAX_STALENESS = timedelta(hours=8)
MIN_CORRIDORS_PER_SAMPLE = 14
MIN_COMPLETE_SAMPLE_SHARE = 0.9
MIN_VOLUME_SHARE = 0.4
MAX_QUARANTINE_SHARE = 0.05
MAX_NULL_RATIO_SHARE = 0.10


def _check(name: str, passed: bool, observed, threshold: str) -> dict:
    return {"name": name, "passed": bool(passed), "observed": observed, "threshold": threshold}


def check_freshness(now: datetime) -> dict:
    threshold = f"latest sample < {MAX_STALENESS.total_seconds() / 3600:.0f}h old"
    latest_path = SERVING_DIR / "latest.json"
    if not latest_path.exists():
        return _check("freshness", False, "latest.json missing", threshold)
    captured = datetime.fromisoformat(json.loads(latest_path.read_text())["captured_at_utc"])
    age_h = round((now - captured).total_seconds() / 3600, 2)
    return _check("freshness", now - captured <= MAX_STALENESS, f"{age_h}h", threshold)


def run(spark: SparkSession) -> bool:
    now = datetime.now(UTC)
    corridors_total = len(load_settings().corridors)
    silver = spark.read.format("delta").load(str(SILVER_PATH))
    # Bronze is sealed by UTC day, so the newest IST date only holds 00:00-05:30.
    last_day = silver.agg(F.date_sub(F.max("ist_date"), 1)).first()[0]
    checks = [check_freshness(now)]

    day = silver.filter(F.col("ist_date") == F.lit(last_day))
    per_sample = day.groupBy("run_id").agg(F.count(F.lit(1)).alias("n"))
    samples = per_sample.count()
    complete = per_sample.filter(F.col("n") >= MIN_CORRIDORS_PER_SAMPLE).count()
    share = complete / samples if samples else 0.0
    checks.append(
        _check(
            "completeness",
            share >= MIN_COMPLETE_SAMPLE_SHARE,
            f"{complete}/{samples} samples with >= {MIN_CORRIDORS_PER_SAMPLE}/{corridors_total} corridors",
            f">= {MIN_COMPLETE_SAMPLE_SHARE:.0%}",
        )
    )

    trailing = (
        silver.filter(
            (F.col("ist_date") < F.lit(last_day))
            & (F.col("ist_date") >= F.date_sub(F.lit(last_day), 7))
        )
        .groupBy("ist_date")
        .agg(F.countDistinct("run_id").alias("samples"))
        .agg(F.percentile_approx("samples", 0.5).alias("median"))
        .first()["median"]
    )
    volume_ok = trailing is None or samples >= trailing * MIN_VOLUME_SHARE
    checks.append(
        _check(
            "volume",
            volume_ok,
            f"{samples} samples on {last_day} vs trailing median {trailing}",
            f">= {MIN_VOLUME_SHARE:.0%} of trailing 7-day median",
        )
    )

    quarantined = 0
    if is_delta(spark, QUARANTINE_PATH):
        quarantined = (
            spark.read.format("delta").load(str(QUARANTINE_PATH))
            .filter(F.to_date(F.from_utc_timestamp("captured_at_utc", "Asia/Kolkata")) == F.lit(last_day))
            .count()
        )
    accepted = day.count()
    q_share = quarantined / (accepted + quarantined) if accepted + quarantined else 0.0
    checks.append(
        _check("validity", q_share <= MAX_QUARANTINE_SHARE, f"{q_share:.1%} quarantined", "<= 5%")
    )

    recent = spark.read.format("delta").load(str(FACT)).filter(
        F.col("captured_at_utc") >= F.lit(now - timedelta(days=7))
    )
    total = recent.count()
    nulls = recent.filter(F.col("congestion_ratio").isNull()).count()
    null_share = nulls / total if total else 0.0
    checks.append(
        _check(
            "nullity", null_share <= MAX_NULL_RATIO_SHARE, f"{null_share:.1%} null congestion_ratio", "<= 10%"
        )
    )

    healthy = all(c["passed"] for c in checks)
    report = {
        "generated_at_utc": now.isoformat(),
        "evaluated_day": str(last_day),
        "healthy": healthy,
        "checks": checks,
    }
    SERVING_DIR.mkdir(parents=True, exist_ok=True)
    (SERVING_DIR / "health.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for c in checks:
        level = logging.INFO if c["passed"] else logging.ERROR
        log.log(level, "%s: %s (%s)", c["name"], c["observed"], c["threshold"])
    return healthy
