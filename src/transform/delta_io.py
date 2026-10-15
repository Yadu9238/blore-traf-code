"""Idempotent Delta write helpers."""
from __future__ import annotations

from pathlib import Path

from delta.tables import DeltaTable
from pyspark.sql import DataFrame


def is_delta(df_or_spark, path: Path) -> bool:
    spark = getattr(df_or_spark, "sparkSession", df_or_spark)
    return DeltaTable.isDeltaTable(spark, str(path))


def insert_new(df: DataFrame, path: Path, keys: list[str], partition_by: list[str] | None = None) -> None:
    """Insert rows whose key is not already present. Observations are immutable, so
    reprocessing the same input is a no-op rather than an update."""
    df = df.dropDuplicates(keys)
    if not is_delta(df, path):
        writer = df.write.format("delta").mode("overwrite")
        if partition_by:
            writer = writer.partitionBy(*partition_by)
        writer.save(str(path))
        return

    condition = " AND ".join(f"t.{k} = s.{k}" for k in keys)
    (
        DeltaTable.forPath(df.sparkSession, str(path))
        .alias("t")
        .merge(df.alias("s"), condition)
        .whenNotMatchedInsertAll()
        .execute()
    )


def overwrite(df: DataFrame, path: Path) -> None:
    df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").save(str(path))
