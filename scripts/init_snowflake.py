#!/usr/bin/env python3
"""Initialize Snowflake database schema for NRFI prediction system.

This script creates all necessary databases, schemas, and tables in Snowflake
for storing:
- Raw game data from SportsDataIO and OpticOdds
- Statcast metrics
- Processed features
- Model predictions
- Historical results for backtesting
"""

import os
import sys
import json
import logging
import boto3
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from snowflake_loader import SnowflakeLoader

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def get_snowflake_credentials():
    """Fetch Snowflake credentials from AWS Secrets Manager."""
    secret_name = "nrfi-predictor/snowflake-credentials"
    region = os.getenv('AWS_REGION', 'us-east-1')
    
    try:
        client = boto3.client('secretsmanager', region_name=region)
        response = client.get_secret_value(SecretId=secret_name)
        return json.loads(response['SecretString'])
    except Exception as e:
        logger.error(f"Failed to fetch Snowflake credentials: {e}")
        logger.info("Using environment variables instead...")
        return {
            'account': os.getenv('SNOWFLAKE_ACCOUNT'),
            'user': os.getenv('SNOWFLAKE_USER'),
            'password': os.getenv('SNOWFLAKE_PASSWORD'),
            'warehouse': os.getenv('SNOWFLAKE_WAREHOUSE', 'NRFI_WH'),
            'database': os.getenv('SNOWFLAKE_DATABASE', 'NRFI_DB')
        }


def create_database_and_schemas(sf: SnowflakeLoader):
    """Create database and schemas."""
    logger.info("Creating database and schemas...")
    
    sf.execute_query("CREATE DATABASE IF NOT EXISTS NRFI_DB")
    logger.info("✓ Created database: NRFI_DB")
    
    sf.execute_query("USE DATABASE NRFI_DB")
    
    schemas = ['RAW', 'FEATURES', 'PREDICTIONS', 'MODELS']
    for schema in schemas:
        sf.execute_query(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        logger.info(f"✓ Created schema: {schema}")


def create_raw_tables(sf: SnowflakeLoader):
    """Create tables for raw data storage."""
    logger.info("Creating raw data tables...")
    
    # Games table
    sf.execute_query("""
        CREATE TABLE IF NOT EXISTS NRFI_DB.RAW.GAMES (
            game_id VARCHAR(50) PRIMARY KEY,
            game_date DATE NOT NULL,
            game_time TIME,
            season INTEGER,
            away_team VARCHAR(3),
            home_team VARCHAR(3),
            away_pitcher_id VARCHAR(50),
            home_pitcher_id VARCHAR(50),
            away_pitcher_name VARCHAR(100),
            home_pitcher_name VARCHAR(100),
            venue_id VARCHAR(20),
            venue_name VARCHAR(100),
            temperature FLOAT,
            wind_speed FLOAT,
            wind_direction VARCHAR(10),
            weather_condition VARCHAR(50),
            is_dome BOOLEAN,
            away_first_inning_runs INTEGER,
            home_first_inning_runs INTEGER,
            away_final_score INTEGER,
            home_final_score INTEGER,
            created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
    """)
    logger.info("✓ Created table: RAW.GAMES")
    
    # Pitcher game logs
    sf.execute_query("""
        CREATE TABLE IF NOT EXISTS NRFI_DB.RAW.PITCHER_GAME_LOGS (
            log_id VARCHAR(100) PRIMARY KEY,
            game_id VARCHAR(50),
            pitcher_id VARCHAR(50),
            game_date DATE,
            opponent_team VARCHAR(3),
            innings_pitched FLOAT,
            hits INTEGER,
            runs INTEGER,
            earned_runs INTEGER,
            walks INTEGER,
            strikeouts INTEGER,
            home_runs INTEGER,
            pitches INTEGER,
            strikes INTEGER,
            created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
    """)
    logger.info("✓ Created table: RAW.PITCHER_GAME_LOGS")
    
    # Pitcher inning logs (for first-inning stats)
    sf.execute_query("""
        CREATE TABLE IF NOT EXISTS NRFI_DB.RAW.PITCHER_INNING_LOGS (
            log_id VARCHAR(100) PRIMARY KEY,
            game_id VARCHAR(50),
            pitcher_id VARCHAR(50),
            game_date DATE,
            inning INTEGER,
            first_inning_runs INTEGER,
            first_inning_hits INTEGER,
            first_inning_walks INTEGER,
            first_inning_strikeouts INTEGER,
            created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
    """)
    logger.info("✓ Created table: RAW.PITCHER_INNING_LOGS")
    
    # Team game logs
    sf.execute_query("""
        CREATE TABLE IF NOT EXISTS NRFI_DB.RAW.TEAM_GAME_LOGS (
            log_id VARCHAR(100) PRIMARY KEY,
            game_id VARCHAR(50),
            team VARCHAR(3),
            game_date DATE,
            opponent_team VARCHAR(3),
            batting_avg FLOAT,
            on_base_pct FLOAT,
            slugging_pct FLOAT,
            woba FLOAT,
            runs INTEGER,
            hits INTEGER,
            home_runs INTEGER,
            created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
    """)
    logger.info("✓ Created table: RAW.TEAM_GAME_LOGS")
    
    # Team inning logs
    sf.execute_query("""
        CREATE TABLE IF NOT EXISTS NRFI_DB.RAW.TEAM_INNING_LOGS (
            log_id VARCHAR(100) PRIMARY KEY,
            game_id VARCHAR(50),
            team VARCHAR(3),
            game_date DATE,
            inning INTEGER,
            first_inning_runs INTEGER,
            first_inning_hits INTEGER,
            first_inning_batting_avg FLOAT,
            created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
    """)
    logger.info("✓ Created table: RAW.TEAM_INNING_LOGS")
    
    # Statcast pitcher data
    sf.execute_query("""
        CREATE TABLE IF NOT EXISTS NRFI_DB.RAW.STATCAST_PITCHER (
            id VARCHAR(100) PRIMARY KEY,
            pitcher_id VARCHAR(50),
            game_date DATE,
            exit_velocity FLOAT,
            barrel BOOLEAN,
            swing BOOLEAN,
            contact BOOLEAN,
            launch_angle FLOAT,
            created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
    """)
    logger.info("✓ Created table: RAW.STATCAST_PITCHER")
    
    # Statcast batter/team data
    sf.execute_query("""
        CREATE TABLE IF NOT EXISTS NRFI_DB.RAW.STATCAST_BATTER (
            id VARCHAR(100) PRIMARY KEY,
            batter_id VARCHAR(50),
            team VARCHAR(3),
            game_date DATE,
            exit_velocity FLOAT,
            barrel BOOLEAN,
            launch_angle FLOAT,
            created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
    """)
    logger.info("✓ Created table: RAW.STATCAST_BATTER")
    
    # Park factors
    sf.execute_query("""
        CREATE TABLE IF NOT EXISTS NRFI_DB.RAW.PARK_FACTORS (
            venue_id VARCHAR(20) PRIMARY KEY,
            venue_name VARCHAR(100),
            runs_factor FLOAT DEFAULT 1.0,
            hr_factor FLOAT DEFAULT 1.0,
            hits_factor FLOAT DEFAULT 1.0,
            updated_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
    """)
    logger.info("✓ Created table: RAW.PARK_FACTORS")
    
    # OpticOdds NRFI/YRFI odds
    sf.execute_query("""
        CREATE TABLE IF NOT EXISTS NRFI_DB.RAW.OPTIC_NRFI_ODDS (
            id VARCHAR(100) PRIMARY KEY,
            game_id VARCHAR(50),
            game_date DATE,
            sportsbook VARCHAR(50),
            nrfi_yes_odds FLOAT,
            nrfi_no_odds FLOAT,
            nrfi_yes_implied_prob FLOAT,
            nrfi_no_implied_prob FLOAT,
            timestamp TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
    """)
    logger.info("✓ Created table: RAW.OPTIC_NRFI_ODDS")


def create_prediction_tables(sf: SnowflakeLoader):
    """Create tables for predictions and results."""
    logger.info("Creating prediction tables...")
    
    # Daily predictions
    sf.execute_query("""
        CREATE TABLE IF NOT EXISTS NRFI_DB.PREDICTIONS.DAILY_PREDICTIONS (
            id VARCHAR(100) PRIMARY KEY,
            game_id VARCHAR(50) NOT NULL,
            game_date DATE NOT NULL,
            game_time TIME,
            away_team VARCHAR(3),
            home_team VARCHAR(3),
            away_pitcher VARCHAR(100),
            home_pitcher VARCHAR(100),
            nrfi_probability FLOAT,
            yrfi_probability FLOAT,
            recommendation VARCHAR(10),
            confidence FLOAT,
            edge_vs_odds FLOAT,
            nrfi_odds FLOAT,
            yrfi_odds FLOAT,
            model_version VARCHAR(50),
            prediction_timestamp TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
    """)
    logger.info("✓ Created table: PREDICTIONS.DAILY_PREDICTIONS")
    
    # Actual results for backtesting
    sf.execute_query("""
        CREATE TABLE IF NOT EXISTS NRFI_DB.PREDICTIONS.RESULTS (
            game_id VARCHAR(50) PRIMARY KEY,
            game_date DATE,
            actual_nrfi BOOLEAN,
            away_first_inning_runs INTEGER,
            home_first_inning_runs INTEGER,
            created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
    """)
    logger.info("✓ Created table: PREDICTIONS.RESULTS")


def create_feature_tables(sf: SnowflakeLoader):
    """Create feature store tables."""
    logger.info("Creating feature tables...")
    
    sf.execute_query("""
        CREATE TABLE IF NOT EXISTS NRFI_DB.FEATURES.GAMES_WITH_OUTCOMES (
            game_id VARCHAR(50) PRIMARY KEY,
            game_date DATE,
            away_team VARCHAR(3),
            home_team VARCHAR(3),
            away_pitcher_id VARCHAR(50),
            home_pitcher_id VARCHAR(50),
            venue_id VARCHAR(20),
            temperature FLOAT,
            wind_speed FLOAT,
            is_dome BOOLEAN,
            away_first_inning_runs INTEGER,
            home_first_inning_runs INTEGER,
            nrfi BOOLEAN,
            created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
    """)
    logger.info("✓ Created table: FEATURES.GAMES_WITH_OUTCOMES")


def create_views(sf: SnowflakeLoader):
    """Create useful views for analysis."""
    logger.info("Creating views...")
    
    # NRFI rate by pitcher
    sf.execute_query("""
        CREATE OR REPLACE VIEW NRFI_DB.FEATURES.PITCHER_NRFI_RATES AS
        SELECT 
            pitcher_id,
            COUNT(*) as total_starts,
            SUM(CASE WHEN first_inning_runs = 0 THEN 1 ELSE 0 END) as nrfi_count,
            SUM(CASE WHEN first_inning_runs = 0 THEN 1 ELSE 0 END)::FLOAT / COUNT(*) as nrfi_rate
        FROM NRFI_DB.RAW.PITCHER_INNING_LOGS
        WHERE inning = 1
        GROUP BY pitcher_id
    """)
    logger.info("✓ Created view: FEATURES.PITCHER_NRFI_RATES")


def main():
    """Main initialization function."""
    logger.info("Starting Snowflake schema initialization...")
    logger.info("="*50)
    
    try:
        # Initialize Snowflake connection
        sf = SnowflakeLoader()
        logger.info("✓ Connected to Snowflake")
        
        # Create database structure
        create_database_and_schemas(sf)
        create_raw_tables(sf)
        create_prediction_tables(sf)
        create_feature_tables(sf)
        create_views(sf)
        
        logger.info("="*50)
        logger.info("✓ Schema initialization complete!")
        logger.info("")
        logger.info("Next steps:")
        logger.info("1. Run backfill script: python scripts/backfill_data.py")
        logger.info("2. Train initial model: python src/train.py")
        logger.info("3. Generate predictions: python src/predict_daily.py")
        
    except Exception as e:
        logger.error(f"Schema initialization failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
