"""Snowflake warehouse connector.

Provides the module-level helpers plus the SnowflakeLoader class that the
pipeline modules (features, train, predict_daily, api) instantiate.

Fail-closed rules:
  - No fabricated results: query errors raise; callers decide how to null
    the affected game. Nothing here invents a default row.
  - Schema creation lives in sql/*.sql (run via scripts/init_snowflake.py),
    not in ad-hoc strings here.
"""
from __future__ import annotations

import os
from typing import Any, Sequence

import pandas as pd
import sentry_sdk
from loguru import logger
from sqlalchemy import create_engine, text
from snowflake.sqlalchemy import URL

from nrfi.config import (
    SNOWFLAKE_ACCOUNT,
    SNOWFLAKE_USER,
    SNOWFLAKE_PASSWORD,
    SNOWFLAKE_DATABASE,
    SNOWFLAKE_SCHEMA,
    SNOWFLAKE_WAREHOUSE,
    SNOWFLAKE_ROLE,
)

_ENGINE = None  # singleton


def get_snowflake_engine():
    """Get or create the Snowflake SQLAlchemy engine (lazy singleton)."""
    global _ENGINE
    if _ENGINE is None:
        missing = [
            n for n, v in (
                ("SNOWFLAKE_ACCOUNT", SNOWFLAKE_ACCOUNT),
                ("SNOWFLAKE_USER", SNOWFLAKE_USER),
                ("SNOWFLAKE_PASSWORD", SNOWFLAKE_PASSWORD),
            ) if not v
        ]
        if missing:
            raise RuntimeError(
                f"Snowflake credentials missing: {', '.join(missing)}. "
                "Set env vars (human-managed via AWS Secrets Manager); "
                "this system fails closed rather than running degraded."
            )
        _ENGINE = create_engine(
            URL(
                account=SNOWFLAKE_ACCOUNT,
                user=SNOWFLAKE_USER,
                password=SNOWFLAKE_PASSWORD,
                database=SNOWFLAKE_DATABASE,
                schema=SNOWFLAKE_SCHEMA,
                warehouse=SNOWFLAKE_WAREHOUSE,
                role=SNOWFLAKE_ROLE,
            ),
            pool_pre_ping=True,
        )
        logger.info(f"Snowflake engine ready: {SNOWFLAKE_DATABASE}.{SNOWFLAKE_SCHEMA}")
    return _ENGINE


def execute_query_df(query: str, params: Sequence[Any] | dict | None = None) -> pd.DataFrame:
    """Execute SQL, return DataFrame with lower-cased column names."""
    engine = get_snowflake_engine()
    with sentry_sdk.start_span(op="db.query", description=query[:100]):
        df = pd.read_sql(text(query), engine, params=params)
    df.columns = [c.lower() for c in df.columns]
    return df


def execute_statement(statement: str, params: dict | None = None) -> None:
    """Execute a DDL/DML statement inside a transaction."""
    engine = get_snowflake_engine()
    with engine.begin() as conn:
        conn.execute(text(statement), params or {})


class SnowflakeLoader:
    """Instance wrapper used across the pipeline.

    execute_query returns a list of dicts (lower-cased keys) because the
    feature/prediction code accesses rows as dicts. bulk_insert accepts a
    table name plus records.
    """

    def __init__(self) -> None:
        self._engine = None  # created lazily on first use

    @property
    def engine(self):
        if self._engine is None:
            self._engine = get_snowflake_engine()
        return self._engine

    def execute_query(
        self, query: str, params: Sequence[Any] | dict | None = None
    ) -> list[dict]:
        df = execute_query_df(query, params)
        return df.to_dict("records")

    def execute_statement(self, statement: str, params: dict | None = None) -> None:
        execute_statement(statement, params)

    def bulk_insert(self, table: str, records: list[dict]) -> None:
        if not records:
            logger.info(f"bulk_insert: nothing to insert into {table}")
            return
        df = pd.DataFrame(records)
        with sentry_sdk.start_span(op="db.bulk_insert", description=f"{table}: {len(df)} rows"):
            # table may be schema-qualified: DB.SCHEMA.TABLE
            parts = table.split(".")
            name = parts[-1]
            schema = ".".join(parts[:-1]) if len(parts) > 1 else None
            df.to_sql(
                name,
                self.engine,
                schema=schema,
                if_exists="append",
                index=False,
                chunksize=5000,
                method="multi",
            )
        logger.info(f"Inserted {len(df)} rows into {table}")

    def merge_upsert(
        self, table: str, records: list[dict], key_cols: Sequence[str]
    ) -> None:
        """Idempotent upsert: stage to a temp table then MERGE on key_cols."""
        if not records:
            return
        df = pd.DataFrame(records)
        tmp = f"TMP_{abs(hash(table)) % 10**8}"
        with self.engine.begin() as conn:
            df.to_sql(tmp, conn, if_exists="replace", index=False, method="multi")
            cols = list(df.columns)
            on = " AND ".join(f"t.{k} = s.{k}" for k in key_cols)
            update = ", ".join(f"t.{c} = s.{c}" for c in cols if c not in key_cols)
            insert_cols = ", ".join(cols)
            insert_vals = ", ".join(f"s.{c}" for c in cols)
            merge = f"""
                MERGE INTO {table} t
                USING {tmp} s ON {on}
                WHEN MATCHED THEN UPDATE SET {update}
                WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})
            """
            conn.execute(text(merge))
            conn.execute(text(f"DROP TABLE IF EXISTS {tmp}"))
        logger.info(f"Merged {len(df)} rows into {table} on ({', '.join(key_cols)})")


def load_from_s3(s3_path: str, table: str, file_format: str = "PARQUET") -> None:
    """COPY INTO from S3 (requires STORAGE INTEGRATION configured by a human)."""
    execute_statement(
        f"COPY INTO {table} FROM '{s3_path}' "
        f"FILE_FORMAT = (TYPE = {file_format}) ON_ERROR = 'ABORT_STATEMENT'"
    )
    logger.info(f"Loaded {s3_path} into {table}")
