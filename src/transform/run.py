"""Daily transform entry point: silver -> gold -> baseline -> export -> quality -> maintenance."""
from __future__ import annotations

import argparse
import logging
import sys

from delta.tables import DeltaTable

from src.config import QUARANTINE_PATH, SILVER_PATH
from src.quality import checks
from src.spark import get_spark
from src.transform import baseline, export, gold, silver
from src.transform.delta_io import is_delta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("transform")

VACUUM_RETAIN_HOURS = 168


def maintain(spark) -> None:
    """Compact small files and drop unreferenced ones. Every daily merge adds files,
    and in a git-backed lake every orphaned file is permanent repository weight."""
    for path in [SILVER_PATH, QUARANTINE_PATH, gold.FACT]:
        if not is_delta(spark, path):
            continue
        table = DeltaTable.forPath(spark, str(path))
        table.optimize().executeCompaction()
        table.vacuum(VACUUM_RETAIN_HOURS)


STEPS = {
    "silver": silver.run,
    "gold": gold.run,
    "baseline": baseline.run,
    "export": export.run,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-quality", action="store_true")
    parser.add_argument("--skip-maintenance", action="store_true")
    args = parser.parse_args()

    spark = get_spark()
    try:
        for name, step in STEPS.items():
            log.info("step: %s", name)
            step(spark)

        healthy = True if args.skip_quality else checks.run(spark)

        if not args.skip_maintenance:
            log.info("step: maintenance")
            maintain(spark)
    finally:
        spark.stop()

    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
