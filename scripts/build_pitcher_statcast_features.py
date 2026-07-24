"""CLI wrapper for the strict-prior pitcher/Statcast feature package."""

import importlib
import sys
from pathlib import Path


def main() -> int:
    repository_root = Path(__file__).resolve().parents[1]
    if str(repository_root) not in sys.path:
        sys.path.insert(0, str(repository_root))
    module = importlib.import_module("nrfi.pitcher_statcast")
    return int(module.main())


if __name__ == "__main__":
    raise SystemExit(main())
