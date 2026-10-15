"""Publish small JSON files the web app fetches at runtime.

Serving files are derived aggregates only, so they are licence-safe to publish.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from src.config import SERVING_DIR
from src.transform.baseline import BASELINE, MIN_RELIABLE_N, current_observations
from src.transform.gold import DIM_CORRIDOR, load_holidays

# Calm hour is searched in waking hours; 3am is always empty and tells nobody anything.
WAKING_HOURS = range(6, 24)
MIN_RAIN_OBSERVATIONS = 30


def _write(name: str, payload: dict) -> None:
    SERVING_DIR.mkdir(parents=True, exist_ok=True)
    body = {"generated_at_utc": datetime.now(UTC).isoformat(), **payload}
    (SERVING_DIR / name).write_text(json.dumps(body, indent=2, default=str) + "\n", encoding="utf-8")


def _round(value, digits=1):
    return None if value is None else round(float(value), digits)


def export_corridors(spark: SparkSession, observations) -> None:
    distances = observations.groupBy("corridor_id").agg(
        F.percentile_approx("distance_m", 0.5).alias("median_distance_m")
    )
    rows = (
        spark.read.format("delta").load(str(DIM_CORRIDOR))
        .filter("is_current")
        .join(distances, "corridor_id", "left")
        .orderBy("corridor_id")
        .collect()
    )
    _write(
        "corridors.json",
        {
            "corridors": [
                {
                    "id": r.corridor_id,
                    "name": r.corridor_name,
                    "origin": {"lat": r.origin_lat, "lon": r.origin_lon},
                    "destination": {"lat": r.dest_lat, "lon": r.dest_lon},
                    "median_distance_m": _round(r.median_distance_m, 0),
                }
                for r in rows
            ]
        },
    )


def export_baselines(spark: SparkSession) -> list:
    rows = (
        spark.read.format("delta").load(str(BASELINE))
        .orderBy("corridor_id", "day_type", "ist_hour")
        .collect()
    )
    _write(
        "baselines.json",
        {
            "grain": ["corridor_id", "day_type", "ist_hour"],
            "timezone": "Asia/Kolkata",
            "min_reliable_samples": MIN_RELIABLE_N,
            # Clients need the same calendar as the pipeline to pick weekday vs weekend.
            "holidays": [day for day, _ in load_holidays()],
            "rows": [
                {
                    "corridor_id": r.corridor_id,
                    "day_type": r.day_type,
                    "hour": r.ist_hour,
                    "median_s": _round(r.median_duration_s),
                    "p25_s": _round(r.p25_duration_s),
                    "p75_s": _round(r.p75_duration_s),
                    "n": r.sample_count,
                    "reliable": r.is_reliable,
                }
                for r in rows
            ],
        },
    )
    return rows


def export_insights(spark: SparkSession, observations, baseline_rows: list) -> None:
    coverage = observations.agg(
        F.min("ist_date").alias("first"),
        F.max("ist_date").alias("last"),
        F.countDistinct("ist_date").alias("days"),
        F.countDistinct("run_id").alias("samples"),
        F.count(F.lit(1)).alias("observations"),
    ).first()

    by_corridor: dict[str, list] = {}
    for r in baseline_rows:
        if r.day_type == "weekday" and r.is_reliable and r.ist_hour in WAKING_HOURS:
            by_corridor.setdefault(r.corridor_id, []).append(r)

    corridors = []
    for corridor_id, hours in sorted(by_corridor.items()):
        peak = max(hours, key=lambda h: h.median_duration_s)
        calm = min(hours, key=lambda h: h.median_duration_s)
        corridors.append(
            {
                "corridor_id": corridor_id,
                "peak_hour": peak.ist_hour,
                "calm_hour": calm.ist_hour,
                "peak_median_s": _round(peak.median_duration_s),
                "calm_median_s": _round(calm.median_duration_s),
                "peak_penalty_pct": _round((peak.median_duration_s / calm.median_duration_s - 1) * 100),
            }
        )
    corridors.sort(key=lambda c: c["peak_penalty_pct"], reverse=True)

    baseline = spark.read.format("delta").load(str(BASELINE)).select(
        "corridor_id", "day_type", "ist_hour", "median_duration_s"
    )
    rain = (
        observations.join(baseline, ["corridor_id", "day_type", "ist_hour"])
        .withColumn("ratio", F.col("duration_live_s") / F.col("median_duration_s"))
        .groupBy("is_rain")
        .agg(F.percentile_approx("ratio", 0.5).alias("median_ratio"), F.count(F.lit(1)).alias("n"))
        .collect()
    )
    rain_by_flag = {r.is_rain: r for r in rain}
    wet, dry = rain_by_flag.get(True), rain_by_flag.get(False)
    rain_effect = None
    if wet and dry and wet.n >= MIN_RAIN_OBSERVATIONS:
        rain_effect = {
            "slower_pct": _round((wet.median_ratio / dry.median_ratio - 1) * 100),
            "rain_observations": wet.n,
            "dry_observations": dry.n,
        }

    _write(
        "insights.json",
        {
            "coverage": {
                "first_date": coverage["first"],
                "last_date": coverage["last"],
                "days": coverage["days"],
                "samples": coverage["samples"],
                "observations": coverage["observations"],
            },
            "corridors": corridors,
            "rain_effect": rain_effect,
        },
    )


def run(spark: SparkSession) -> None:
    observations = current_observations(spark).cache()
    export_corridors(spark, observations)
    rows = export_baselines(spark)
    export_insights(spark, observations, rows)
    observations.unpersist()
