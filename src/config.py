"""Central configuration for nrfi-predictor.
All secrets are loaded from environment variables (never hardcoded).
"""
from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT_DIR   = Path(__file__).resolve().parents[1]
DATA_DIR   = ROOT_DIR / "data"
MODEL_DIR  = ROOT_DIR / "models"
LOGS_DIR   = ROOT_DIR / "logs"

for _d in (DATA_DIR, MODEL_DIR, LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ── Database ─────────────────────────────────────────────────────────────────
DATABASE_URL: str = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{DATA_DIR / 'nrfi.db'}"
)

# ── SportsDataIO ─────────────────────────────────────────────────────────────
SDIO_API_KEY: str  = os.environ.get("SDIO_API_KEY", "")
SDIO_BASE_URL      = "https://api.sportsdata.io/v3/mlb"

# SportsDataIO endpoint templates
SDIO_ENDPOINTS = {
    "games_by_date":       "{base}/scores/json/GamesByDate/{date}",
    "box_scores_by_date":  "{base}/stats/json/BoxScores/{date}",
    "player_game_stats":   "{base}/stats/json/PlayerGameStatsByDate/{date}",
    "team_game_stats":     "{base}/stats/json/TeamGameStatsByDate/{date}",
    "schedules":           "{base}/scores/json/Games/{season}",
    "players":             "{base}/scores/json/Players",
    "teams":               "{base}/scores/json/Teams",
    "stadiums":            "{base}/scores/json/Stadiums",
    "standings":           "{base}/scores/json/Standings/{season}",
    "injuries":            "{base}/scores/json/Injuries",
    "projections":         "{base}/projections/json/PlayerGameProjectionStatsByDate/{date}",
    "starting_lineups":    "{base}/stats/json/StartingLineupsByDate/{date}",
    "news":                "{base}/scores/json/NewsByDate/{date}",
    "game_odds":           "{base}/odds/json/GameOddsByDate/{date}",
    "in_game_odds":        "{base}/odds/json/InGameOddsByDate/{date}",
    "historical_odds":     "{base}/odds/json/GameOddsLineMovement/{game_id}",
    "umpires":             "{base}/scores/json/Umpires",
}

# ── pybaseball / MLB Stats API ────────────────────────────────────────────────
STATCAST_START_YEAR   = 2015   # Statcast data reliable from 2015
RETROSHEET_START_YEAR = 2000   # we ingest from 2000; Retrosheet has ~1900+
MLB_STATS_API_BASE    = "https://statsapi.mlb.com/api/v1"

# ── Weather ───────────────────────────────────────────────────────────────────
# Meteostat is used for historical weather; OpenWeatherMap for forecasts
OWM_API_KEY: str = os.environ.get("OWM_API_KEY", "")

# ── Model ─────────────────────────────────────────────────────────────────────
MODEL_NAME            = "nrfi_lgbm"
TRAIN_SEASONS         = list(range(RETROSHEET_START_YEAR, 2023))
VAL_SEASONS           = [2023]
TEST_SEASONS          = [2024, 2025]
CALIBRATION_METHOD    = "isotonic"   # 'sigmoid' or 'isotonic'

# Feature windows (days)
PITCHER_WINDOW_STARTS   = [7, 14, 30, 90]
BATTER_WINDOW_STARTS    = [7, 14, 30]
TEAM_WINDOW_STARTS      = [7, 14, 30]

# ── API server ────────────────────────────────────────────────────────────────
API_HOST  = os.environ.get("API_HOST", "0.0.0.0")
API_PORT  = int(os.environ.get("API_PORT", "8000"))

# ── Automation ────────────────────────────────────────────────────────────────
# Cron schedule (ET): run prediction pipeline at 10 AM every day
DAILY_PREDICTION_CRON = "0 10 * * *"
# Weekly retrain on Monday at 3 AM
WEEKLY_RETRAIN_CRON   = "0 3 * * 1"
