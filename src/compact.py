"""Compact raw JSONL into daily Parquet and enforce raw retention.

Raw provider responses are licensed content and are deleted after
RAW_RETENTION_DAYS. The Parquet bronze layer holds only fields we derive or are
permitted to retain, and is what every downstream layer reads.

Only completed UTC days are written to bronze. Spark's file stream source tracks
files by path, so a partition rewritten during the day would be read once, partial,
and every later rewrite silently ignored.
"""
from __future__ import annotations

import logging
import shutil
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd

from src.config import BRONZE_DIR, RAW_DIR, RAW_RETENTION_DAYS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("compact")

TEXT_COLUMNS = ["run_id", "corridor_id", "corridor_name", "provider", "weather_observed_at_utc"]
NUMERIC_COLUMNS = [
    "duration_live_s",
    "duration_typical_s",
    "distance_m",
    "congestion_ratio",
    "temperature_c",
    "precipitation_mm",
    "rain_mm",
    "wind_speed_kmh",
    "cloud_cover_pct",
]
# Mirrors silver.BRONZE_SCHEMA; every bronze file carries exactly these columns.
BRONZE_COLUMNS = [
    "run_id",
    "corridor_id",
    "corridor_name",
    "captured_at_utc",
    "provider",
    "duration_live_s",
    "duration_typical_s",
    "distance_m",
    "congestion_ratio",
    "weather_observed_at_utc",
    "temperature_c",
    "precipitation_mm",
    "rain_mm",
    "wind_speed_kmh",
    "cloud_cover_pct",
]


def compact_partition(partition) -> int:
    source = partition / "records.jsonl"
    if not source.exists():
        return 0

    frame = pd.read_json(source, lines=True)
    if frame.empty:
        return 0

    frame["captured_at_utc"] = pd.to_datetime(frame["captured_at_utc"], utc=True)
    # Reruns and retries can replay a run, so the natural key is deduplicated here
    # rather than relying on the scheduler firing exactly once.
    frame = frame.drop_duplicates(subset=["run_id", "corridor_id"], keep="last")
    frame = frame.sort_values(["captured_at_utc", "corridor_id"])

    target = BRONZE_DIR / partition.name
    target.mkdir(parents=True, exist_ok=True)
    conform(frame).to_parquet(target / "part-000.parquet", index=False, compression="snappy")

    return len(frame)


def conform(frame: pd.DataFrame) -> pd.DataFrame:
    """Pin columns and physical types so every bronze file shares one schema.

    Open-Meteo returns whole numbers as JSON integers on dry days, so pandas infers
    int64 one day and float64 the next; a day where weather failed has no weather
    columns, or all-null ones that Parquet stores with no type. Spark 3.5's reader
    accepts neither, and one bad file fails the whole stream.
    """
    frame = frame.reindex(columns=BRONZE_COLUMNS)
    for column in TEXT_COLUMNS:
        frame[column] = frame[column].astype("string")
    for column in NUMERIC_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float64")
    frame["captured_at_utc"] = pd.to_datetime(frame["captured_at_utc"], utc=True).astype(
        "datetime64[us, UTC]"
    )
    return frame


def partition_date(partition: Path) -> date:
    return datetime.strptime(partition.name[3:], "%Y-%m-%d").date()


def prune_raw(cutoff) -> list[str]:
    removed = []
    for partition in sorted(RAW_DIR.glob("dt=*")):
        if partition_date(partition) < cutoff:
            shutil.rmtree(partition)
            removed.append(partition.name)
    return removed


def drop_unsealed_bronze(today: date) -> list[str]:
    removed = []
    for partition in sorted(BRONZE_DIR.glob("dt=*")):
        if partition_date(partition) >= today:
            shutil.rmtree(partition)
            removed.append(partition.name)
    return removed


def main() -> int:
    if not RAW_DIR.exists():
        log.info("No raw data yet")
        return 0

    today = datetime.now(UTC).date()
    dropped = drop_unsealed_bronze(today)
    if dropped:
        log.info("Removed unsealed bronze partitions: %s", ", ".join(dropped))

    total = 0
    for partition in sorted(RAW_DIR.glob("dt=*")):
        if partition_date(partition) >= today:
            continue
        rows = compact_partition(partition)
        total += rows
        log.info("%s -> %s rows", partition.name, rows)

    cutoff = (datetime.now(UTC) - timedelta(days=RAW_RETENTION_DAYS)).date()
    removed = prune_raw(cutoff)
    if removed:
        log.info("Pruned raw partitions past retention: %s", ", ".join(removed))

    log.info("Compacted %s rows", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
