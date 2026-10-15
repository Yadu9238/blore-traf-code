"""Spark + Delta tests. Run in CI's spark job; skipped where Java or PySpark is absent."""
import shutil
from dataclasses import replace
from datetime import UTC, datetime

import pandas as pd
import pytest

pytest.importorskip("pyspark")
pytest.importorskip("delta")
if shutil.which("java") is None:
    pytest.skip("Java is required for Spark tests", allow_module_level=True)

from pyspark.sql import functions as F  # noqa: E402

from src.compact import conform  # noqa: E402
from src.config import Point, load_settings  # noqa: E402
from src.spark import get_spark  # noqa: E402
from src.transform import baseline, gold, silver  # noqa: E402


@pytest.fixture(scope="module")
def spark():
    session = get_spark("blore-traf-tests")
    yield session
    session.stop()


@pytest.fixture
def lake(tmp_path, monkeypatch):
    paths = {
        "BRONZE_DIR": tmp_path / "bronze",
        "SILVER_PATH": tmp_path / "silver",
        "QUARANTINE_PATH": tmp_path / "quarantine",
        "CHECKPOINT_DIR": tmp_path / "_checkpoints",
    }
    for name, value in paths.items():
        monkeypatch.setattr(silver, name, value, raising=False)
    monkeypatch.setattr(gold, "SILVER_PATH", paths["SILVER_PATH"])
    for module in (gold, baseline):
        monkeypatch.setattr(module, "DIM_CORRIDOR", tmp_path / "dim_corridor")
        monkeypatch.setattr(module, "DIM_DATE", tmp_path / "dim_date")
        monkeypatch.setattr(module, "FACT", tmp_path / "fact")
    monkeypatch.setattr(baseline, "BASELINE", tmp_path / "baseline")
    return paths


def bronze_row(run_id, corridor_id, captured, duration=1800.0, distance=15000.0):
    return {
        "run_id": run_id,
        "corridor_id": corridor_id,
        "corridor_name": corridor_id,
        "captured_at_utc": captured,
        "provider": "mapbox",
        "duration_live_s": duration,
        "duration_typical_s": 1500.0,
        "distance_m": distance,
        "congestion_ratio": duration / 1500.0,
        "weather_observed_at_utc": None,
        "temperature_c": 25.0,
        "precipitation_mm": 0,
        "rain_mm": 0,
        "wind_speed_kmh": 10.0,
        "cloud_cover_pct": 50,
    }


def write_bronze(directory, day, rows):
    target = directory / f"dt={day}"
    target.mkdir(parents=True, exist_ok=True)
    conform(pd.DataFrame(rows)).to_parquet(target / "part-000.parquet", index=False)


def test_to_silver_derives_ist_calendar_and_rejects_bad_rows(spark, tmp_path):
    rows = [
        bronze_row("r1", "a", datetime(2026, 10, 14, 3, 30, tzinfo=UTC)),
        bronze_row("r1", "b", datetime(2026, 10, 14, 3, 30, tzinfo=UTC), duration=0),
        bronze_row("r1", "c", datetime(2026, 10, 14, 3, 30, tzinfo=UTC), duration=100, distance=50000),
    ]
    write_bronze(tmp_path, "2026-10-14", rows)
    df = spark.read.schema(silver.BRONZE_SCHEMA).parquet(str(tmp_path))
    out = {r.corridor_id: r for r in silver.to_silver(df).collect()}

    assert out["a"].ist_hour == 9
    assert out["a"].ist_bucket_15 == 36
    assert out["a"].reject_reason is None
    assert out["b"].reject_reason == "non_positive_duration"
    assert out["c"].reject_reason == "implausible_speed"


def test_silver_stream_is_idempotent_across_reruns_and_lost_checkpoints(spark, lake):
    captured = datetime(2026, 10, 14, 3, 30, tzinfo=UTC)
    rows = [bronze_row("r1", "a", captured), bronze_row("r1", "b", captured)]
    write_bronze(lake["BRONZE_DIR"], "2026-10-14", rows)

    silver.run(spark)
    silver.run(spark)
    assert spark.read.format("delta").load(str(lake["SILVER_PATH"])).count() == 2

    shutil.rmtree(lake["CHECKPOINT_DIR"])
    silver.run(spark)
    assert spark.read.format("delta").load(str(lake["SILVER_PATH"])).count() == 2


def test_dim_corridor_versions_changed_coordinates_and_closes_removed(spark, lake, monkeypatch):
    settings = load_settings()
    gold.build_dim_corridor(spark)

    moved = replace(settings.corridors[0], origin=Point(lat=12.9200, lon=77.6250))
    changed = replace(settings, corridors=[moved, *settings.corridors[1:-1]])
    monkeypatch.setattr(gold, "load_settings", lambda: changed)
    gold.build_dim_corridor(spark, effective_at=datetime(2026, 10, 15, tzinfo=UTC))

    dim = spark.read.format("delta").load(str(gold.DIM_CORRIDOR))
    versions = dim.filter(F.col("corridor_id") == moved.id).orderBy("valid_from").collect()
    assert len(versions) == 2
    assert [v.is_current for v in versions] == [False, True]
    assert versions[0].valid_to == versions[1].valid_from

    removed = dim.filter(F.col("corridor_id") == settings.corridors[-1].id).collect()
    assert len(removed) == 1 and removed[0].is_current is False

    assert dim.filter("is_current").count() == len(settings.corridors) - 1


def test_baseline_median_and_reliability(spark, lake):
    corridor = load_settings().corridors[0].id
    rows = [
        bronze_row(f"r{i}", corridor, datetime(2026, 10, 14, 3, 30 + i, tzinfo=UTC), duration=d)
        for i, d in enumerate([1200, 1300, 1400, 1500, 1600, 1700, 1800, 1900, 9000])
    ]
    write_bronze(lake["BRONZE_DIR"], "2026-10-14", rows)

    silver.run(spark)
    gold.run(spark)
    baseline.run(spark)

    row = (
        spark.read.format("delta").load(str(baseline.BASELINE))
        .filter((F.col("corridor_id") == corridor) & (F.col("ist_hour") == 9))
        .first()
    )
    assert row.day_type == "weekday"
    assert row.sample_count == 9
    assert row.median_duration_s == 1600
    assert row.is_reliable
