"""Bronze -> silver: validated, deduplicated, IST-conformed observations.

Runs as Structured Streaming with Trigger.AvailableNow: each run processes every
bronze file not yet recorded in the checkpoint, then exits. Same exactly-once
semantics as a continuous stream, without paying for an idle process.
"""
from __future__ import annotations

import logging

from pyspark.sql import Column, DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, StringType, StructField, StructType, TimestampType

from src.config import BRONZE_DIR, CHECKPOINT_DIR, IST, QUARANTINE_PATH, SILVER_PATH
from src.transform.delta_io import insert_new

log = logging.getLogger("silver")

KEYS = ["run_id", "corridor_id"]

BRONZE_SCHEMA = StructType(
    [
        StructField("run_id", StringType()),
        StructField("corridor_id", StringType()),
        StructField("corridor_name", StringType()),
        StructField("captured_at_utc", TimestampType()),
        StructField("provider", StringType()),
        StructField("duration_live_s", DoubleType()),
        StructField("duration_typical_s", DoubleType()),
        StructField("distance_m", DoubleType()),
        StructField("congestion_ratio", DoubleType()),
        StructField("weather_observed_at_utc", StringType()),
        StructField("temperature_c", DoubleType()),
        StructField("precipitation_mm", DoubleType()),
        StructField("rain_mm", DoubleType()),
        StructField("wind_speed_kmh", DoubleType()),
        StructField("cloud_cover_pct", DoubleType()),
        StructField("dt", StringType()),
    ]
)

MIN_DURATION_S = 60
MAX_DURATION_S = 4 * 3600
MAX_SPEED_KMPH = 120


def _reject_reason(speed: Column) -> Column:
    return (
        F.when(F.col("corridor_id").isNull(), "missing_corridor")
        .when(F.col("captured_at_utc").isNull(), "missing_timestamp")
        .when(F.col("duration_live_s").isNull() | (F.col("duration_live_s") <= 0), "non_positive_duration")
        .when(F.col("distance_m").isNull() | (F.col("distance_m") <= 0), "non_positive_distance")
        .when(F.col("duration_live_s") < MIN_DURATION_S, "duration_too_short")
        .when(F.col("duration_live_s") > MAX_DURATION_S, "duration_too_long")
        .when(speed > MAX_SPEED_KMPH, "implausible_speed")
    )


def to_silver(bronze: DataFrame) -> DataFrame:
    """Pure transformation, shared by the stream and by tests."""
    speed = F.col("distance_m") / F.col("duration_live_s") * F.lit(3.6)
    ist_ts = F.from_utc_timestamp(F.col("captured_at_utc"), IST)

    return (
        bronze.drop("dt")
        .withColumn("speed_kmph", F.round(speed, 2))
        .withColumn("ist_ts", ist_ts)
        .withColumn("ist_date", F.to_date("ist_ts"))
        .withColumn("ist_hour", F.hour("ist_ts"))
        .withColumn("ist_bucket_15", F.hour("ist_ts") * 4 + F.floor(F.minute("ist_ts") / 15).cast("int"))
        .withColumn("is_weekend", F.dayofweek("ist_ts").isin(1, 7))
        .withColumn("is_rain", F.coalesce(F.col("rain_mm"), F.lit(0.0)) > 0)
        .withColumn("reject_reason", _reject_reason(speed))
    )


def write_batch(batch: DataFrame, batch_id: int) -> None:
    batch = batch.persist()
    try:
        good = batch.filter(F.col("reject_reason").isNull()).drop("reject_reason")
        bad = batch.filter(F.col("reject_reason").isNotNull()).withColumn("batch_id", F.lit(batch_id))

        insert_new(good, SILVER_PATH, KEYS, partition_by=["ist_date"])
        if not bad.isEmpty():
            insert_new(bad, QUARANTINE_PATH, KEYS)
        log.info("silver batch %s: %s accepted, %s quarantined", batch_id, good.count(), bad.count())
    finally:
        batch.unpersist()


def run(spark: SparkSession) -> None:
    stream = spark.readStream.schema(BRONZE_SCHEMA).parquet(str(BRONZE_DIR))

    query = (
        to_silver(stream)
        # Bronze days are sealed and arrive in order, so 48h of state is ample; the
        # insert-only merge in write_batch is what guarantees idempotency.
        .withWatermark("captured_at_utc", "48 hours")
        .dropDuplicates(["run_id", "corridor_id", "captured_at_utc"])
        .writeStream.foreachBatch(write_batch)
        .option("checkpointLocation", str(CHECKPOINT_DIR / "silver"))
        .trigger(availableNow=True)
        .start()
    )
    query.awaitTermination()
