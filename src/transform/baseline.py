"""Gold -> baseline: what "normal" looks like per corridor, day type, and IST hour.

Grain is day type x hour, not weekday x 15 minutes: the first two months of
collection averaged ~10 samples a day, which leaves under one observation per
finer cell. Medians are used because a single breakdown should not move "normal".
"""
from __future__ import annotations

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from src.config import GOLD_DIR
from src.transform.delta_io import overwrite
from src.transform.gold import DIM_CORRIDOR, DIM_DATE, FACT

BASELINE = GOLD_DIR / "agg_corridor_baseline"
MIN_RELIABLE_N = 8


def current_observations(spark: SparkSession):
    """Facts joined to calendar, restricted to each corridor's current definition.

    A corrected coordinate is a different route, so its history must not be mixed
    into the new version's baseline.
    """
    fact = spark.read.format("delta").load(str(FACT))
    current = (
        spark.read.format("delta").load(str(DIM_CORRIDOR)).filter("is_current").select("corridor_key")
    )
    dates = spark.read.format("delta").load(str(DIM_DATE)).select("date_key", "day_type", "ist_date")
    return fact.join(current, "corridor_key").join(dates, "date_key")


def run(spark: SparkSession) -> None:
    observations = current_observations(spark)
    baseline = (
        observations.groupBy("corridor_id", "day_type", "ist_hour")
        .agg(
            F.percentile_approx("duration_live_s", 0.5, 10000).alias("median_duration_s"),
            F.percentile_approx("duration_live_s", 0.25, 10000).alias("p25_duration_s"),
            F.percentile_approx("duration_live_s", 0.75, 10000).alias("p75_duration_s"),
            F.percentile_approx("speed_kmph", 0.5, 10000).alias("median_speed_kmph"),
            F.count(F.lit(1)).alias("sample_count"),
            F.countDistinct("ist_date").alias("days_observed"),
        )
        .withColumn("is_reliable", F.col("sample_count") >= MIN_RELIABLE_N)
    )
    overwrite(baseline, BASELINE)
