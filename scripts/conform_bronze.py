"""One-off: rewrite historical bronze files to the conformed schema.

Raw JSONL older than the retention window is gone, so these partitions cannot be
recompacted from source and are conformed in place instead.
"""
from __future__ import annotations

import sys

import pandas as pd
import pyarrow.parquet as pq

from src.compact import conform
from src.config import BRONZE_DIR


def main() -> int:
    changed = 0
    for path in sorted(BRONZE_DIR.glob("dt=*/*.parquet")):
        before = pq.read_schema(path)
        frame = conform(pd.read_parquet(path))
        frame.to_parquet(path, index=False, compression="snappy")
        if pq.read_schema(path) != before:
            changed += 1
    print(f"Conformed {changed} bronze files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
