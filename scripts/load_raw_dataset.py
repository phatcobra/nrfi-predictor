"""Load one observed CSV/Parquet dataset into its normalized Snowflake table.

Example:
    python scripts/load_raw_dataset.py \
      --dataset pitcher_innings \
      --file exports/pitcher_fi.parquet \
      --source mlb-model-statcast
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nrfi.raw_loader import SPECS, load_dataset


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, choices=sorted(SPECS))
    parser.add_argument("--file", required=True)
    parser.add_argument("--source", required=True)
    args = parser.parse_args()
    loaded = load_dataset(args.dataset, args.file, args.source)
    print(f"loaded {loaded} validated rows into {SPECS[args.dataset].table}")


if __name__ == "__main__":
    main()
