"""Silver -> gold star schema.

dim_corridor   SCD Type 2 from config/corridors.yml
dim_date       calendar with Karnataka holidays and day type
fact_corridor_observation   one row per corridor per sample
"""
from __future__ import annotations

import csv
from datetime import UTC, datetime

from delta.tables import DeltaTable
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from src.config import GOLD_DIR, HOLIDAYS_PATH, SILVER_PATH, load_settings
from src.transform.delta_io import insert_new, is_delta, overwrite

DIM_CORRIDOR = GOLD_DIR / "dim_corridor"
DIM_DATE = GOLD_DIR / "dim_date"
FACT = GOLD_DIR / "fact_corridor_observation"

# The first load is backdated so observations captured before it still resolve.
INITIAL_VALID_FROM = "2000-01-01 00:00:00"


def corridor_source(spark: SparkSession) -> DataFrame:
    rows = [
        (c.id, c.name, c.origin.lat, c.origin.lon, c.destination.lat, c.destination.lon)
        for c in load_settings().corridors
    ]
    df = spark.createDataFrame(
        rows, "corridor_id string, corridor_name string, origin_lat double, origin_lon double, "
        "dest_lat double, dest_lon double"
    )
    attrs = F.concat_ws("|", "corridor_name", "origin_lat", "origin_lon", "dest_lat", "dest_lon")
    return df.withColumn("attr_hash", F.sha2(attrs, 256)).withColumn(
        "corridor_key", F.substring(F.sha2(F.concat_ws("|", "corridor_id", "attr_hash"), 256), 1, 16)
    )


def build_dim_corridor(spark: SparkSession, effective_at: datetime | None = None) -> None:
    source = corridor_source(spark)

    if not is_delta(spark, DIM_CORRIDOR):
        initial = (
            source.withColumn("valid_from", F.to_timestamp(F.lit(INITIAL_VALID_FROM)))
            .withColumn("valid_to", F.lit(None).cast("timestamp"))
            .withColumn("is_current", F.lit(True))
        )
        overwrite(initial, DIM_CORRIDOR)
        return

    now = F.lit(effective_at or datetime.now(UTC)).cast("timestamp")
    target = DeltaTable.forPath(spark, str(DIM_CORRIDOR))
    current = (
        target.toDF().filter("is_current").select("corridor_id", F.col("attr_hash").alias("current_hash"))
    )

    changed = (
        source.join(current, "corridor_id")
        .filter(F.col("attr_hash") != F.col("current_hash"))
        .drop("current_hash")
    )
    # Changed rows appear twice: once keyed to close the old version, once unkeyed
    # so they fall through to the insert of the new version.
    staged = changed.withColumn("merge_key", F.lit(None).cast("string")).unionByName(
        source.withColumn("merge_key", F.col("corridor_id"))
    ).withColumn("effective_at", now)

    (
        target.alias("t")
        .merge(staged.alias("s"), "t.corridor_id = s.merge_key AND t.is_current = true")
        .whenMatchedUpdate(
            condition="t.attr_hash <> s.attr_hash",
            set={"is_current": "false", "valid_to": "s.effective_at"},
        )
        .whenNotMatchedInsert(
            values={
                "corridor_id": "s.corridor_id",
                "corridor_name": "s.corridor_name",
                "origin_lat": "s.origin_lat",
                "origin_lon": "s.origin_lon",
                "dest_lat": "s.dest_lat",
                "dest_lon": "s.dest_lon",
                "attr_hash": "s.attr_hash",
                "corridor_key": "s.corridor_key",
                "valid_from": "s.effective_at",
                "valid_to": "CAST(NULL AS TIMESTAMP)",
                "is_current": "true",
            }
        )
        .whenNotMatchedBySourceUpdate(
            condition="t.is_current = true",
            set={"is_current": "false", "valid_to": "current_timestamp()"},
        )
        .execute()
    )


def load_holidays() -> list[tuple[str, str]]:
    with HOLIDAYS_PATH.open(encoding="utf-8") as handle:
        return [(row["date"], row["name"]) for row in csv.DictReader(handle)]


def build_dim_date(spark: SparkSession) -> None:
    bounds = spark.read.format("delta").load(str(SILVER_PATH)).agg(
        F.min("ist_date").alias("lo"), F.max("ist_date").alias("hi")
    )
    dates = bounds.select(
        F.explode(F.sequence("lo", F.date_add("hi", 30))).alias("ist_date")
    )
    holidays = spark.createDataFrame(load_holidays(), "date string, holiday_name string").select(
        F.to_date("date").alias("ist_date"), "holiday_name"
    )

    dim = (
        dates.join(holidays, "ist_date", "left")
        .withColumn("date_key", F.date_format("ist_date", "yyyyMMdd").cast("int"))
        .withColumn("day_name", F.date_format("ist_date", "EEEE"))
        .withColumn("is_weekend", F.dayofweek("ist_date").isin(1, 7))
        .withColumn("is_holiday", F.col("holiday_name").isNotNull())
        # Holidays behave like weekends for commute traffic, and there are too few
        # of them to support a separate baseline.
        .withColumn(
            "day_type",
            F.when(F.col("is_weekend") | F.col("is_holiday"), "weekend").otherwise("weekday"),
        )
    )
    overwrite(dim, DIM_DATE)


def build_fact(spark: SparkSession, date_from: str | None = None, date_to: str | None = None) -> None:
    silver = spark.read.format("delta").load(str(SILVER_PATH))
    if date_from:
        silver = silver.filter(F.col("ist_date") >= F.lit(date_from))
    if date_to:
        silver = silver.filter(F.col("ist_date") <= F.lit(date_to))

    corridors = spark.read.format("delta").load(str(DIM_CORRIDOR)).select(
        "corridor_key", "corridor_id", "valid_from", "valid_to"
    )
    dates = spark.read.format("delta").load(str(DIM_DATE)).select("ist_date", "date_key")

    s, c, d = silver.alias("s"), corridors.alias("c"), dates.alias("d")
    as_of = (
        (F.col("s.corridor_id") == F.col("c.corridor_id"))
        & (F.col("s.captured_at_utc") >= F.col("c.valid_from"))
        & (F.col("c.valid_to").isNull() | (F.col("s.captured_at_utc") < F.col("c.valid_to")))
    )

    fact = (
        s.join(c, as_of)
        .join(d, F.col("s.ist_date") == F.col("d.ist_date"))
        .select(
            "s.run_id",
            "s.corridor_id",
            "c.corridor_key",
            "d.date_key",
            "s.ist_hour",
            "s.ist_bucket_15",
            "s.captured_at_utc",
            "s.ist_ts",
            "s.duration_live_s",
            "s.duration_typical_s",
            "s.distance_m",
            "s.speed_kmph",
            "s.congestion_ratio",
            "s.rain_mm",
            "s.precipitation_mm",
            "s.temperature_c",
            "s.wind_speed_kmh",
            "s.is_rain",
        )
    )
    insert_new(fact, FACT, ["run_id", "corridor_id"])


def run(spark: SparkSession) -> None:
    build_dim_corridor(spark)
    build_dim_date(spark)
    build_fact(spark)
