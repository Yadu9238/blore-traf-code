from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from src import compact
from src.config import load_settings


def test_corridors_config_is_valid():
    settings = load_settings()
    assert len(settings.corridors) >= 10
    assert all(c.origin != c.destination for c in settings.corridors)


def test_coordinates_outside_bangalore_are_rejected():
    from src.config import _point

    with pytest.raises(ValueError):
        _point({"lat": 28.6139, "lon": 77.2090})  # Delhi


def test_compact_deduplicates_replayed_runs(tmp_path, monkeypatch):
    partition = tmp_path / "raw" / "dt=2026-08-17"
    partition.mkdir(parents=True)

    row = {
        "run_id": "20260817T101500Z",
        "corridor_id": "silkboard_ecity",
        "corridor_name": "Silk Board to Electronic City",
        "captured_at_utc": "2026-08-17T10:15:00+00:00",
        "duration_live_s": 2340.0,
        "duration_typical_s": 1800.0,
        "distance_m": 18200.0,
        "congestion_ratio": 1.3,
    }
    pd.DataFrame([row, row]).to_json(partition / "records.jsonl", orient="records", lines=True)

    bronze = tmp_path / "bronze"
    monkeypatch.setattr(compact, "BRONZE_DIR", bronze)

    assert compact.compact_partition(partition) == 1

    written = pd.read_parquet(bronze / "dt=2026-08-17" / "part-000.parquet")
    assert len(written) == 1
    assert written.loc[0, "corridor_id"] == "silkboard_ecity"


def test_prune_raw_removes_only_expired_partitions(tmp_path, monkeypatch):
    monkeypatch.setattr(compact, "RAW_DIR", tmp_path)
    today = datetime.now(UTC).date()

    fresh = tmp_path / f"dt={today}"
    stale = tmp_path / f"dt={today - timedelta(days=30)}"
    fresh.mkdir()
    stale.mkdir()

    removed = compact.prune_raw(today - timedelta(days=7))

    assert removed == [stale.name]
    assert fresh.exists()
    assert not stale.exists()


def test_conform_pins_numeric_types_across_dry_and_wet_days():
    dry = compact.conform(pd.DataFrame([{"captured_at_utc": "2026-10-14T03:30:00+00:00", "rain_mm": 0}]))
    wet = compact.conform(pd.DataFrame([{"captured_at_utc": "2026-10-14T03:30:00+00:00", "rain_mm": 1.2}]))
    assert dry["rain_mm"].dtype == wet["rain_mm"].dtype == "float64"
    assert str(dry["captured_at_utc"].dtype) == "datetime64[us, UTC]"


def test_conform_keeps_typed_columns_when_weather_is_missing(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    no_weather = pd.DataFrame(
        [{"run_id": "r1", "corridor_id": "a", "captured_at_utc": "2026-10-14T03:30:00+00:00",
          "duration_live_s": 900, "distance_m": 9000}]
    )
    path = tmp_path / "part.parquet"
    compact.conform(no_weather).to_parquet(path, index=False)

    schema = pq.read_schema(path)
    assert schema.names == compact.BRONZE_COLUMNS
    assert pa.types.is_string(schema.field("weather_observed_at_utc").type) or pa.types.is_large_string(
        schema.field("weather_observed_at_utc").type
    )
    assert pa.types.is_floating(schema.field("rain_mm").type)


def test_compact_only_seals_completed_utc_days(tmp_path, monkeypatch):
    raw, bronze = tmp_path / "raw", tmp_path / "bronze"
    monkeypatch.setattr(compact, "RAW_DIR", raw)
    monkeypatch.setattr(compact, "BRONZE_DIR", bronze)
    today = datetime.now(UTC).date()
    yesterday = today - timedelta(days=1)

    for day in (yesterday, today):
        partition = raw / f"dt={day}"
        partition.mkdir(parents=True)
        row = {"run_id": f"r{day}", "corridor_id": "a", "captured_at_utc": f"{day}T10:00:00+00:00"}
        pd.DataFrame([row]).to_json(partition / "records.jsonl", orient="records", lines=True)

    (bronze / f"dt={today}").mkdir(parents=True)

    assert compact.main() == 0
    assert (bronze / f"dt={yesterday}" / "part-000.parquet").exists()
    assert not (bronze / f"dt={today}").exists()


def test_write_latest_keeps_newest_sample_per_corridor(tmp_path, monkeypatch):
    import json

    from src import ingest

    monkeypatch.setattr(ingest, "SERVING_DIR", tmp_path)
    records = [
        {"corridor_id": "a", "captured_at_utc": "2026-10-14T03:30:00+00:00", "duration_live_s": 900.0,
         "distance_m": 9000.0, "rain_mm": 0.0},
        {"corridor_id": "a", "captured_at_utc": "2026-10-14T03:35:00+00:00", "duration_live_s": 960.0,
         "distance_m": 9000.0, "rain_mm": 0.0},
    ]
    ingest.write_latest(records)

    latest = json.loads((tmp_path / "latest.json").read_text())
    assert latest["captured_at_utc"] == "2026-10-14T03:35:00+00:00"
    assert [c["duration_live_s"] for c in latest["corridors"]] == [960.0]
