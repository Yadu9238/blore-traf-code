"""Poll every corridor plus current weather and append to the raw landing zone.

A run takes several samples spaced across the hour rather than one sample per
scheduler tick. GitHub drops most high-frequency cron deliveries, so sampling
density is controlled in-process where it is reliable and the scheduler is only
asked for one run per hour.

A single corridor failure must not lose the whole run, so failures are recorded
per corridor and the job only exits non-zero if nothing at all was captured.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import UTC, datetime

from src.config import RAW_DIR, SERVING_DIR, STATUS_PATH, Settings, load_settings
from src.providers import mapbox, weather
from src.providers.base import ProviderError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ingest")

SAMPLES = int(os.getenv("SAMPLES", "1"))
SAMPLE_INTERVAL_S = int(os.getenv("SAMPLE_INTERVAL_S", "300"))


def collect_once(settings: Settings) -> tuple[list[dict], list[dict]]:
    captured_at = datetime.now(UTC)
    run_id = captured_at.strftime("%Y%m%dT%H%M%SZ")

    try:
        conditions = weather.fetch_weather(settings.city_centre)
    except ProviderError as exc:
        log.warning("Weather unavailable, continuing without it: %s", exc)
        conditions = {}

    records: list[dict] = []
    failures: list[dict] = []

    for corridor in settings.corridors:
        try:
            result = mapbox.fetch_corridor(corridor, settings.mapbox_token)
        except ProviderError as exc:
            log.error("Corridor %s failed: %s", corridor.id, exc)
            failures.append({"run_id": run_id, "corridor_id": corridor.id, "error": str(exc)})
            continue

        records.append(
            {
                "run_id": run_id,
                "corridor_id": corridor.id,
                "corridor_name": corridor.name,
                "captured_at_utc": captured_at.isoformat(),
                **result,
                **conditions,
            }
        )

    return records, failures


def append_raw(records: list[dict]) -> None:
    by_day: dict[str, list[dict]] = {}
    for record in records:
        by_day.setdefault(record["captured_at_utc"][:10], []).append(record)

    for day, rows in by_day.items():
        partition = RAW_DIR / f"dt={day}"
        partition.mkdir(parents=True, exist_ok=True)
        with (partition / "records.jsonl").open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")


def main() -> int:
    settings = load_settings()
    if not settings.mapbox_token:
        log.error("MAPBOX_TOKEN is not set")
        return 1

    records: list[dict] = []
    failures: list[dict] = []

    for sample in range(1, SAMPLES + 1):
        sample_records, sample_failures = collect_once(settings)
        records.extend(sample_records)
        failures.extend(sample_failures)
        log.info("Sample %s/%s captured %s corridors", sample, SAMPLES, len(sample_records))

        if sample < SAMPLES:
            time.sleep(SAMPLE_INTERVAL_S)

    if records:
        append_raw(records)
        write_latest(records)

    write_status(records, failures, len(settings.corridors))
    log.info("Wrote %s rows from %s samples", len(records), SAMPLES)

    return 0 if records else 1


def write_latest(records: list[dict]) -> None:
    """Publish the newest sample per corridor; the web app compares it to baselines."""
    newest: dict[str, dict] = {}
    for record in records:
        current = newest.get(record["corridor_id"])
        if current is None or record["captured_at_utc"] > current["captured_at_utc"]:
            newest[record["corridor_id"]] = record

    corridors = [
        {
            "corridor_id": r["corridor_id"],
            "captured_at_utc": r["captured_at_utc"],
            "duration_live_s": r["duration_live_s"],
            "distance_m": r["distance_m"],
            "rain_mm": r.get("rain_mm"),
        }
        for r in sorted(newest.values(), key=lambda r: r["corridor_id"])
    ]

    SERVING_DIR.mkdir(parents=True, exist_ok=True)
    (SERVING_DIR / "latest.json").write_text(
        json.dumps(
            {
                "generated_at_utc": datetime.now(UTC).isoformat(),
                "captured_at_utc": max(r["captured_at_utc"] for r in corridors),
                "corridors": corridors,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def write_status(records: list[dict], failures: list[dict], corridors_total: int) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(
        json.dumps(
            {
                "last_run_utc": datetime.now(UTC).isoformat(),
                "samples_attempted": SAMPLES,
                "samples_captured": len({r["run_id"] for r in records}),
                "corridors_total": corridors_total,
                "rows_written": len(records),
                "failures": failures[-20:],
                "healthy": bool(records) and not failures,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    sys.exit(main())
