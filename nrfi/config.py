"""Central configuration for nrfi-predictor.

All secrets come from environment variables (populated on Render from AWS
Secrets Manager by a human). Nothing here fabricates a value: missing keys
stay empty and the consuming module must fail closed.
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
for _d in (DATA_DIR, MODEL_DIR, LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# -- Time ---------------------------------------------------------------------
TZ_ET = ZoneInfo("America/New_York")

# -- Local staging DB (ingest scratch; Snowflake is the warehouse) ------------
DATABASE_URL: str = os.environ.get("DATABASE_URL", f"sqlite:///{DATA_DIR / 'nrfi.db'}")

# -- Snowflake ----------------------------------------------------------------
SNOWFLAKE_ACCOUNT   = os.environ.get("SNOWFLAKE_ACCOUNT", "")
SNOWFLAKE_USER      = os.environ.get("SNOWFLAKE_USER", "")
SNOWFLAKE_PASSWORD  = os.environ.get("SNOWFLAKE_PASSWORD", "")
SNOWFLAKE_DATABASE  = os.environ.get("SNOWFLAKE_DATABASE", "NRFI_DB")
SNOWFLAKE_SCHEMA    = os.environ.get("SNOWFLAKE_SCHEMA", "CORE")
SNOWFLAKE_WAREHOUSE = os.environ.get("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH")
SNOWFLAKE_ROLE      = os.environ.get("SNOWFLAKE_ROLE", "SYSADMIN")

# -- SportsDataIO ---------------------------------------------------------
SDIO_API_KEY: str = os.environ.get("SDIO_API_KEY", os.environ.get("SPORTSDATA_API_KEY", ""))
SDIO_BASE_URL = "https://api.sportsdata.io/v3/mlb"
SDIO_ENDPOINTS = {
    "games_by_date":      "{base}/scores/json/GamesByDate/{date}",
    "box_scores_by_date": "{base}/stats/json/BoxScores/{date}",
    "player_game_stats":  "{base}/stats/json/PlayerGameStatsByDate/{date}",
    "team_game_stats":    "{base}/stats/json/TeamGameStatsByDate/{date}",
    "schedules":          "{base}/scores/json/Games/{season}",
    "players":            "{base}/scores/json/Players",
    "teams":              "{base}/scores/json/Teams",
    "stadiums":           "{base}/scores/json/Stadiums",
    "standings":          "{base}/scores/json/Standings/{season}",
    "injuries":           "{base}/scores/json/Injuries",
    "projections":        "{base}/projections/json/PlayerGameProjectionStatsByDate/{date}",
    "starting_lineups":   "{base}/stats/json/StartingLineupsByDate/{date}",
    "news":               "{base}/scores/json/NewsByDate/{date}",
    "game_odds":          "{base}/odds/json/GameOddsByDate/{date}",
    "in_game_odds":       "{base}/odds/json/InGameOddsByDate/{date}",
    "historical_odds":    "{base}/odds/json/GameOddsLineMovement/{game_id}",
    "umpires":            "{base}/scores/json/Umpires",
}

# -- OpticOdds ------------------------------------------------------------
OPTIC_API_KEY: str = os.environ.get("OPTIC_API_KEY", os.environ.get("OPTICODDS_API_KEY", ""))
OPTIC_BASE_URL = os.environ.get("OPTIC_BASE_URL", "https://api.opticodds.com/api/v3")
# HUMAN ACTION REQUIRED: pin the exact OpticOdds market id for the MLB
# 1st-inning total (0.5) market. Substring matching is forbidden (it matched
# "First 5 Innings" markets). Empty value => odds ingest fails closed.
OPTIC_FI_TOTAL_MARKET_ID: str = os.environ.get("OPTIC_FI_TOTAL_MARKET_ID", "")
NRFI_SPORTSBOOKS = [
    b.strip() for b in os.environ.get(
        "NRFI_SPORTSBOOKS", "DraftKings,FanDuel,BetMGM,Caesars,Pinnacle"
    ).split(",") if b.strip()
]

# -- Fail-closed thresholds -------------------------------------------------
ODDS_MAX_AGE_SECONDS   = int(os.environ.get("ODDS_MAX_AGE_SECONDS", "600"))   # 10 min
FEATURE_COVERAGE_MIN   = float(os.environ.get("FEATURE_COVERAGE_MIN", "0.85"))
HIGH_TIER_COVERAGE_MIN = 0.95
MIN_BOOKS_FOR_MARKET   = int(os.environ.get("MIN_BOOKS_FOR_MARKET", "2"))

# -- pybaseball / MLB Stats API ---------------------------------------------
STATCAST_START_YEAR = 2015
RETROSHEET_START_YEAR = 2000
MLB_STATS_API_BASE = "https://statsapi.mlb.com/api/v1"

# -- Weather ----------------------------------------------------------------
OWM_API_KEY: str = os.environ.get("OWM_API_KEY", "")

# -- Model ------------------------------------------------------------------
MODEL_NAME = "nrfi_lgbm"
TRAIN_SEASONS = list(range(2015, 2024))   # walk-forward pool
VAL_SEASONS = [2024]
TEST_SEASONS = [2025]                     # LOCKED holdout - touch once at release
CALIBRATION_METHOD = "isotonic_oof"       # fit on out-of-fold predictions only
CV_PURGE_DAYS = 7                         # purge gap between train and validation

PITCHER_WINDOW_STARTS = [7, 14, 30, 90]
BATTER_WINDOW_STARTS = [7, 14, 30]
TEAM_WINDOW_STARTS = [7, 14, 30]

# -- API server ---------------------------------------------------------------
API_HOST = os.environ.get("API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("API_PORT", "8000"))
API_BEARER_TOKEN: str = os.environ.get("API_BEARER_TOKEN", "")  # empty => POST routes disabled
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()
]

# -- Automation (documented; scheduling lives in Render cron) -----------------
DAILY_PREDICTION_CRON = "0 6 * * *"    # 06:00 ET
NIGHTLY_GRADING_CRON = "5 0 * * *"     # 00:05 ET
WEEKLY_RETRAIN_CRON = "0 2 * * 1"      # Mon 02:00 ET


class Config:
    """Object-style access for modules that take a config instance."""

    MODEL_DIR = str(MODEL_DIR)
    DATA_DIR = str(DATA_DIR)
    LOGS_DIR = str(LOGS_DIR)
    MODEL_NAME = MODEL_NAME
    CV_PURGE_DAYS = CV_PURGE_DAYS
    FEATURE_COVERAGE_MIN = FEATURE_COVERAGE_MIN
    ODDS_MAX_AGE_SECONDS = ODDS_MAX_AGE_SECONDS
