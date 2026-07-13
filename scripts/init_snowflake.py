"""Run the sql/ DDL files in order. Single source of schema truth.

Usage: python scripts/init_snowflake.py
Requires SNOWFLAKE_* env vars (human-managed).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger

from nrfi.snowflake_loader import execute_statement


def main() -> None:
    sql_dir = Path(__file__).resolve().parents[1] / "sql"
    for path in sorted(sql_dir.glob("*.sql")):
        raw = path.read_text()
        # strip line comments, split on ';'
        cleaned = re.sub(r"--[^\n]*", "", raw)
        statements = [s.strip() for s in cleaned.split(";") if s.strip()]
        logger.info(f"{path.name}: {len(statements)} statements")
        for stmt in statements:
            execute_statement(stmt)
    logger.info("schema initialized")


if __name__ == "__main__":
    main()
