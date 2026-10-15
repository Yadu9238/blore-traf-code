"""Rebuild fact rows for an IST date range from silver, then refresh baselines and exports.

Use after fixing a transformation bug or correcting a corridor: deletes the range
and reinserts it, so a run is repeatable.
"""
from __future__ import annotations

import argparse
import sys

from delta.tables import DeltaTable

from src.spark import get_spark
from src.transform import baseline, export, gold


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="date_from", required=True, help="IST date, YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", required=True, help="IST date, YYYY-MM-DD")
    args = parser.parse_args()

    key_from = int(args.date_from.replace("-", ""))
    key_to = int(args.date_to.replace("-", ""))

    spark = get_spark("blore-traf-backfill")
    try:
        gold.build_dim_corridor(spark)
        gold.build_dim_date(spark)
        DeltaTable.forPath(spark, str(gold.FACT)).delete(f"date_key BETWEEN {key_from} AND {key_to}")
        gold.build_fact(spark, args.date_from, args.date_to)
        baseline.run(spark)
        export.run(spark)
    finally:
        spark.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
