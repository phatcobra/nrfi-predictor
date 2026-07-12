"""Snowflake data warehouse connector and utilities.

Provides:
  - Snowflake engine creation with connection pooling
  - Bulk data loading from S3 (via AWS)
  - Table creation and schema management
  - Query helpers for feature engineering
  - Unistore/hybrid tables for real-time odds
"""
from __future__ import annotations

import os
from typing import Any

import pandas as pd
from loguru import logger
from sqlalchemy import create_engine, text
from snowflake.sqlalchemy import URL
from snowflake.connector import connect
import sentry_sdk

from src.config import (
    SNOWFLAKE_ACCOUNT,
    SNOWFLAKE_USER,
    SNOWFLAKE_PASSWORD,
    SNOWFLAKE_DATABASE,
    SNOWFLAKE_SCHEMA,
    SNOWFLAKE_WAREHOUSE,
    SNOWFLAKE_ROLE,
)

_ENGINE = None  # Singleton engine


def get_snowflake_engine():
    """Get or create Snowflake SQLAlchemy engine (singleton)."""
    global _ENGINE
    
    if _ENGINE is None:
        try:
            _ENGINE = create_engine(URL(
                account=SNOWFLAKE_ACCOUNT,
                user=SNOWFLAKE_USER,
                password=SNOWFLAKE_PASSWORD,
                database=SNOWFLAKE_DATABASE,
                schema=SNOWFLAKE_SCHEMA,
                warehouse=SNOWFLAKE_WAREHOUSE,
                role=SNOWFLAKE_ROLE,
            ))
            logger.info(f"Connected to Snowflake: {SNOWFLAKE_DATABASE}.{SNOWFLAKE_SCHEMA}")
        except Exception as e:
            sentry_sdk.capture_exception(e)
            logger.error(f"Snowflake connection failed: {e}")
            raise
    
    return _ENGINE


def execute_query(query: str, params: dict | None = None) -> pd.DataFrame:
    """Execute SQL query and return DataFrame."""
    engine = get_snowflake_engine()
    
    with sentry_sdk.start_span(op="db.query", description=query[:100]):
        return pd.read_sql(text(query), engine, params=params)


def bulk_insert(df: pd.DataFrame, table: str, if_exists: str = "append") -> None:
    """Bulk insert DataFrame into Snowflake table.
    
    Args:
        df: Pandas DataFrame
        table: Target table name
        if_exists: 'fail', 'replace', or 'append'
    """
    engine = get_snowflake_engine()
    
    with sentry_sdk.start_span(op="db.bulk_insert", description=f"{table}: {len(df)} rows"):
        df.to_sql(
            table,
            engine,
            if_exists=if_exists,
            index=False,
            chunksize=5000,  # Snowflake optimized chunk size
            method="multi",
        )
        logger.info(f"Inserted {len(df)} rows into {table}")


def create_schema() -> None:
    """Create Snowflake schema and tables for NRFI system."""
    engine = get_snowflake_engine()
    
    with engine.connect() as conn:
        # Ensure database and schema exist
        conn.execute(text(f"CREATE DATABASE IF NOT EXISTS {SNOWFLAKE_DATABASE}"))
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SNOWFLAKE_DATABASE}.{SNOWFLAKE_SCHEMA}"))
        conn.execute(text(f"USE SCHEMA {SNOWFLAKE_DATABASE}.{SNOWFLAKE_SCHEMA}"))
        
        # OpticOdds NRFI odds (real-time, hybrid table)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS optic_nrfi_odds (
                fixture_id VARCHAR,
                game_date DATE,
                start_time TIMESTAMP_NTZ,
                home_team VARCHAR,
                away_team VARCHAR,
                sportsbook VARCHAR,
                nrfi_american FLOAT,
                yrfi_american FLOAT,
                nrfi_prob FLOAT,
                yrfi_prob FLOAT,
                nrfi_decimal FLOAT,
                yrfi_decimal FLOAT,
                timestamp TIMESTAMP_NTZ,
                PRIMARY KEY (fixture_id, sportsbook, timestamp)
            )
        """))
        
        # SportsDataIO box scores with first-inning labels
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS sdio_team_box (
                GameID VARCHAR,
                Side VARCHAR,
                GameDate DATE,
                FirstInningRuns INT,
                TotalFirstInningRuns INT,
                NRFI INT,
                -- Add other box score columns as needed
                PRIMARY KEY (GameID, Side)
            )
        """))
        
        # Model predictions
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS nrfi_predictions (
                prediction_id VARCHAR,
                game_date DATE,
                fixture_id VARCHAR,
                home_team VARCHAR,
                away_team VARCHAR,
                model_version VARCHAR,
                nrfi_prob FLOAT,
                yrfi_prob FLOAT,
                model_features VARIANT,  -- JSON of features used
                best_nrfi_book VARCHAR,
                best_nrfi_odds FLOAT,
                edge FLOAT,  -- model_prob - market_prob
                recommended_action VARCHAR,
                created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
                PRIMARY KEY (prediction_id)
            )
        """))
        
        # Actual results (for model evaluation)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS nrfi_results (
                game_id VARCHAR PRIMARY KEY,
                game_date DATE,
                home_team VARCHAR,
                away_team VARCHAR,
                actual_nrfi INT,  # 1 = NRFI, 0 = YRFI
                first_inning_runs INT,
                prediction_id VARCHAR,  # Link to predictions table
                verified_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
            )
        """))
        
        logger.info("Snowflake schema created successfully")


def load_from_s3(s3_path: str, table: str, file_format: str = "CSV") -> None:
    """Load data from S3 into Snowflake using COPY INTO.
    
    Args:
        s3_path: S3 URI (s3://bucket/path/to/data)
        table: Target Snowflake table
        file_format: CSV, JSON, or PARQUET
    
    Requires AWS credentials configured in Snowflake (STORAGE INTEGRATION)
    """
    engine = get_snowflake_engine()
    
    with engine.connect() as conn:
        query = f"""
            COPY INTO {table}
            FROM '{s3_path}'
            FILE_FORMAT = (TYPE = {file_format})
            ON_ERROR = 'CONTINUE'
        """
        
        result = conn.execute(text(query))
        logger.info(f"Loaded data from {s3_path} into {table}")
        return result


if __name__ == "__main__":
    # Test connection and create schema
    create_schema()
    
    # Test query
    df = execute_query("SELECT CURRENT_VERSION()")
    print(df)
