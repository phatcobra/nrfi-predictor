"""Snowflake warehouse connector with fail-closed query semantics."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd

from nrfi._obs import logger, sentry_sdk
from nrfi.config import (
    SNOWFLAKE_ACCOUNT,
    SNOWFLAKE_DATABASE,
    SNOWFLAKE_PASSWORD,
    SNOWFLAKE_ROLE,
    SNOWFLAKE_SCHEMA,
    SNOWFLAKE_USER,
    SNOWFLAKE_WAREHOUSE,
)

_ENGINE = None


def get_snowflake_engine():
    """Create the lazy singleton SQLAlchemy engine after validating credentials."""
    global _ENGINE
    if _ENGINE is None:
        from sqlalchemy import create_engine
        from snowflake.sqlalchemy import URL

        missing = [
            name for name, value in (
                ("SNOWFLAKE_ACCOUNT", SNOWFLAKE_ACCOUNT),
                ("SNOWFLAKE_USER", SNOWFLAKE_USER),
                ("SNOWFLAKE_PASSWORD", SNOWFLAKE_PASSWORD),
            ) if not value
        ]
        if missing:
            raise RuntimeError(
                f"Snowflake credentials missing: {', '.join(missing)}")
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
        logger.info(
            f"Snowflake engine ready: {SNOWFLAKE_DATABASE}.{SNOWFLAKE_SCHEMA}")
    return _ENGINE


def _is_positional(params: Sequence[Any] | dict | None) -> bool:
    return params is not None and not isinstance(params, dict)


def execute_query_df(
    query: str,
    params: Sequence[Any] | dict | None = None,
    engine=None,
) -> pd.DataFrame:
    """Execute SQL and return lower-case columns.

    SQLAlchemy ``text()`` supports named ``:parameter`` binds, not the DBAPI
    ``%s`` placeholders used by the pipeline. Positional calls therefore use
    the Snowflake DBAPI cursor directly; named or unparameterized calls use the
    SQLAlchemy path.
    """
    from sqlalchemy import text

    active_engine = engine or get_snowflake_engine()
    with sentry_sdk.start_span(op="db.query", description=query[:100]):
        if _is_positional(params):
            raw_connection = active_engine.raw_connection()
            cursor = None
            try:
                cursor = raw_connection.cursor()
                cursor.execute(query, tuple(params or ()))
                columns = [description[0] for description in cursor.description or []]
                frame = pd.DataFrame(cursor.fetchall(), columns=columns)
            finally:
                if cursor is not None:
                    cursor.close()
                raw_connection.close()
        else:
            frame = pd.read_sql(text(query), active_engine, params=params or {})
    frame.columns = [str(column).lower() for column in frame.columns]
    return frame


def execute_statement(statement: str, params: dict | None = None) -> None:
    """Execute named-bind DDL/DML inside a transaction."""
    from sqlalchemy import text

    engine = get_snowflake_engine()
    with engine.begin() as connection:
        connection.execute(text(statement), params or {})


class SnowflakeLoader:
    def __init__(self) -> None:
        self._engine = None

    @property
    def engine(self):
        if self._engine is None:
            self._engine = get_snowflake_engine()
        return self._engine

    def execute_query(
        self,
        query: str,
        params: Sequence[Any] | dict | None = None,
    ) -> list[dict]:
        return execute_query_df(query, params, engine=self.engine).to_dict("records")

    def execute_statement(self, statement: str, params: dict | None = None) -> None:
        from sqlalchemy import text

        with self.engine.begin() as connection:
            connection.execute(text(statement), params or {})

    def bulk_insert(self, table: str, records: list[dict]) -> None:
        if not records:
            logger.info(f"bulk_insert: nothing to insert into {table}")
            return
        frame = pd.DataFrame(records)
        parts = table.split(".")
        name = parts[-1]
        schema = ".".join(parts[:-1]) if len(parts) > 1 else None
        with sentry_sdk.start_span(
                op="db.bulk_insert", description=f"{table}: {len(frame)} rows"):
            frame.to_sql(
                name,
                self.engine,
                schema=schema,
                if_exists="append",
                index=False,
                chunksize=5000,
                method="multi",
            )
        logger.info(f"inserted {len(frame)} rows into {table}")

    def merge_upsert(
        self,
        table: str,
        records: list[dict],
        key_cols: Sequence[str],
    ) -> None:
        """Idempotently stage records and merge them on validated key columns."""
        if not records:
            return
        frame = pd.DataFrame(records)
        missing_keys = [key for key in key_cols if key not in frame.columns]
        if missing_keys:
            raise ValueError(f"merge keys missing from records: {missing_keys}")
        if frame[list(key_cols)].isna().any().any():
            raise ValueError("merge keys cannot contain null values")

        from sqlalchemy import text

        temporary = f"TMP_{abs(hash((table, tuple(frame.columns)))) % 10**8}"
        with self.engine.begin() as connection:
            frame.to_sql(
                temporary,
                connection,
                if_exists="replace",
                index=False,
                method="multi",
            )
            columns = list(frame.columns)
            on_clause = " AND ".join(f"t.{key} = s.{key}" for key in key_cols)
            update_columns = [column for column in columns if column not in key_cols]
            insert_columns = ", ".join(columns)
            insert_values = ", ".join(f"s.{column}" for column in columns)
            matched_clause = ""
            if update_columns:
                assignments = ", ".join(
                    f"t.{column} = s.{column}" for column in update_columns)
                matched_clause = f"WHEN MATCHED THEN UPDATE SET {assignments}"
            merge_sql = f"""
                MERGE INTO {table} t
                USING {temporary} s ON {on_clause}
                {matched_clause}
                WHEN NOT MATCHED THEN INSERT ({insert_columns})
                VALUES ({insert_values})
            """
            try:
                connection.execute(text(merge_sql))
            finally:
                connection.execute(text(f"DROP TABLE IF EXISTS {temporary}"))
        logger.info(
            f"merged {len(frame)} rows into {table} on ({', '.join(key_cols)})")


def load_from_s3(s3_path: str, table: str,
                 file_format: str = "PARQUET") -> None:
    """Load an explicitly configured S3 object; any row error aborts."""
    allowed_formats = {"CSV", "JSON", "PARQUET"}
    normalized_format = file_format.upper()
    if normalized_format not in allowed_formats:
        raise ValueError(f"unsupported file format {file_format!r}")
    if not s3_path.startswith("s3://"):
        raise ValueError("s3_path must start with s3://")
    execute_statement(
        f"COPY INTO {table} FROM '{s3_path}' "
        f"FILE_FORMAT = (TYPE = {normalized_format}) ON_ERROR = 'ABORT_STATEMENT'"
    )
    logger.info(f"loaded {s3_path} into {table}")
