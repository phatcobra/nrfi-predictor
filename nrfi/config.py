"""Central configuration for nrfi-predictor.

All secrets come from environment variables. Missing credentials remain empty
and consuming modules must fail closed. Temporal model boundaries are defined
once here so training, retraining, and holdout evaluation cannot silently drift.
"""
from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

# -- Paths --------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
MODEL_DIR = ROOT_DIR / "models"
LOGS_DIR = ROOT_DIR / "logs"
for _directory in (DATA_DIR, MODEL_DIR, LOGS_DIR):
    _directory.mkdir(parents=True, exist_ok=True)

# -- Time ---------------------------------------------------------------------
TZ_ET = ZoneInfo("America/New_York")

# -- Local staging DB ---------------------------------------------------------
DATABASE_URL: str = os.environ.get(
    "DATABASE_URL", f"sqlite:///{DATA_DIR / 'nrfi.db'}")

# -- Snowflake ----------------------------------------------------------------
SNOWFLAKE_ACCOUNT = os.environ.get("SNOWFLAKE_ACCOUNT", "")
SNOWFLAKE_USER = os.environ.get("SNOWFLAKE_USER", "")
SNOWFLAKE_PASSWORD = os.environ.get("SNOWFLAKE_PASSWORD", "")
SNOWFLAKE_DATABASE = os.environ.get("SNOWFLAKE_DATABASE", "NRFI_DB")
SNOWFLAKE_SCHEMA = os.environ.get("SNOWFLAKE_SCHEMA", "CORE")
SNOWFLAKE_WAREHOUSE = os.environ.get("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH")
SNOWFLAKE_ROLE = os.environ.get("SNOWFLAKE_ROLE", "SYSADMIN")

# -- SportsDataIO -------------------------------------------------------------
SDIO_API_KEY: str = os.environ.get(
    "SDIO_API_KEY", os.environ.get("SPORTSDATA_API_KEY", ""))
SDIO_BASE_URL = "https://api.sportsdata.io/v3/mlb"
SDIO_ENDPOINTS = {
    "games_by_date": "{base}/scores/json/GamesByDate/{date}",
    "box_scores_by_date": "{base}/stats/json/BoxScores/{date}",
    "player_game_stats": "{base}/stats/json/PlayerGameStatsByDate/{date}",
    "team_game_stats": "{base}/stats/json/TeamGameStatsByDate/{date}",
    "schedules": "{base}/scores/json/Games/{season}",
    "players": "{base}/scores/json/Players",
    "teams": "{base}/scores/json/Teams",
    "stadiums": "{base}/scores/json/Stadiums",
    "standings": "{base}/scores/json/Standings/{season}",
    "injuries": "{base}/scores/json/Injuries",
    "projections": "{base}/projections/json/PlayerGameProjectionStatsByDate/{date}",
    "starting_lineups": "{base}/stats/json/StartingLineupsByDate/{date}",
    "news": "{base}/scores/json/NewsByDate/{date}",
    "game_odds": "{base}/odds/json/GameOddsByDate/{date}",
    "in_game_odds": "{base}/odds/json/InGameOddsByDate/{date}",
    "historical_odds": "{base}/odds/json/GameOddsLineMovement/{game_id}",
    "umpires": "{base}/scores/json/Umpires",
}

# -- OpticOdds ----------------------------------------------------------------
OPTIC_API_KEY: str = os.environ.get(
    "OPTIC_API_KEY", os.environ.get("OPTICODDS_API_KEY", ""))
OPTIC_BASE_URL = os.environ.get(
    "OPTIC_BASE_URL", "https://api.opticodds.com/api/v3")
OPTIC_FI_TOTAL_MARKET_ID: str = os.environ.get(
    "OPTIC_FI_TOTAL_MARKET_ID", "")
NRFI_SPORTSBOOKS = [
    book.strip() for book in os.environ.get(
        "NRFI_SPORTSBOOKS", "DraftKings,FanDuel,BetMGM,Caesars,Pinnacle"
    ).split(",") if book.strip()
]

# -- Fail-closed thresholds ---------------------------------------------------
ODDS_MAX_AGE_SECONDS = int(os.environ.get("ODDS_MAX_AGE_SECONDS", "600"))
FEATURE_COVERAGE_MIN = float(os.environ.get("FEATURE_COVERAGE_MIN", "0.85"))
HIGH_TIER_COVERAGE_MIN = float(
    os.environ.get("HIGH_TIER_COVERAGE_MIN", "0.95"))
MIN_BOOKS_FOR_MARKET = int(os.environ.get("MIN_BOOKS_FOR_MARKET", "2"))

# -- Public baseball data -----------------------------------------------------
STATCAST_START_YEAR = 2015
RETROSHEET_START_YEAR = 2000
MLB_STATS_API_BASE = "https://statsapi.mlb.com/api/v1"

# -- Weather ------------------------------------------------------------------
OWM_API_KEY: str = os.environ.get("OWM_API_KEY", "")

# -- Model and temporal evidence boundaries ----------------------------------
MODEL_NAME = "nrfi_lgbm"
TRAIN_SEASONS = list(range(2015, 2024))
VAL_SEASONS = [2024]
TEST_SEASONS = [2025]
if not TEST_SEASONS:
    raise RuntimeError("TEST_SEASONS must contain at least one locked season")
if max(TRAIN_SEASONS + VAL_SEASONS) >= min(TEST_SEASONS):
    raise RuntimeError("training/validation seasons overlap the locked holdout")

TRAIN_START_DATE = f"{min(TRAIN_SEASONS)}-03-01"
TRAIN_END_DATE = f"{max(VAL_SEASONS)}-12-31"
HOLDOUT_START_DATE = f"{min(TEST_SEASONS)}-03-01"
HOLDOUT_END_DATE = f"{max(TEST_SEASONS)}-11-30"
CALIBRATION_METHOD = "isotonic_oof"
CV_PURGE_DAYS = 7

PITCHER_WINDOW_STARTS = [7, 14, 30, 90]
BATTER_WINDOW_STARTS = [7, 14, 30]
TEAM_WINDOW_STARTS = [7, 14, 30]

# -- API server ---------------------------------------------------------------
API_HOST = os.environ.get("API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("API_PORT", "8000"))
API_BEARER_TOKEN: str = os.environ.get("API_BEARER_TOKEN", "")
ALLOWED_ORIGINS = [
    origin.strip() for origin in os.environ.get(
        "ALLOWED_ORIGINS", "").split(",") if origin.strip()
]

# -- Automation ---------------------------------------------------------------
DAILY_PREDICTION_CRON = "0 6 * * *"
NIGHTLY_GRADING_CRON = "5 0 * * *"
WEEKLY_RETRAIN_CRON = "0 2 * * 1"


class Config:
    """Object-style access for modules that accept a config instance."""

    MODEL_DIR = str(MODEL_DIR)
    DATA_DIR = str(DATA_DIR)
    LOGS_DIR = str(LOGS_DIR)
    MODEL_NAME = MODEL_NAME
    CV_PURGE_DAYS = CV_PURGE_DAYS
    FEATURE_COVERAGE_MIN = FEATURE_COVERAGE_MIN
    ODDS_MAX_AGE_SECONDS = ODDS_MAX_AGE_SECONDS
    TRAIN_START_DATE = TRAIN_START_DATE
    TRAIN_END_DATE = TRAIN_END_DATE
    HOLDOUT_START_DATE = HOLDOUT_START_DATE
    HOLDOUT_END_DATE = HOLDOUT_END_DATE
