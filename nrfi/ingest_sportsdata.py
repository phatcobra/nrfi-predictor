"""SportsDataIO MLB ingestion module.

Fetches and persists:
  - Daily schedules / game scores
  - Box scores (team + player, by date)
  - Player game stats
  - Starting lineups
  - Game-level odds (NRFI/YRFI lines where available)
  - Injuries
  - Umpires
  - Projections

All data is stored in the SQLite / Postgres database defined in config.py.
"""
from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any

import pandas as pd
import requests
from nrfi._obs import logger
from sqlalchemy import create_engine, text
from tenacity import retry, stop_after_attempt, wait_exponential

from nrfi.config import (
    DATABASE_URL,
    SDIO_API_KEY,
    SDIO_BASE_URL,
    SDIO_ENDPOINTS,
)

_ENGINE = create_engine(DATABASE_URL, echo=False)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

@retry(stop=stop_after_attempt(5), wait=wait_exponential(min=2, max=30))
def _get(url: str) -> Any:
    """GET with automatic retry + rate-limit handling."""
    resp = requests.get(
        url,
        headers={"Ocp-Apim-Subscription-Key": SDIO_API_KEY},
        timeout=30,
    )
    if resp.status_code == 429:
        logger.warning("Rate-limited; sleeping 60 s")
        time.sleep(60)
        resp.raise_for_status()
    resp.raise_for_status()
    return resp.json()


def _url(endpoint_key: str, **kwargs) -> str:
    tpl = SDIO_ENDPOINTS[endpoint_key]
    return tpl.format(base=SDIO_BASE_URL, **kwargs)


# ---------------------------------------------------------------------------
# Per-endpoint fetchers
# ---------------------------------------------------------------------------

def fetch_games_by_date(game_date: date) -> pd.DataFrame:
    data = _get(_url("games_by_date", date=game_date.strftime("%Y-%b-%d")))
    if not data:
        return pd.DataFrame()
    df = pd.json_normalize(data)
    df["fetch_date"] = game_date
    return df


def fetch_box_scores(game_date: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (team_box_df, player_box_df)."""
    data = _get(_url("box_scores_by_date", date=game_date.strftime("%Y-%b-%d")))
    if not data:
        return pd.DataFrame(), pd.DataFrame()

    team_rows, player_rows = [], []
    for game in data:
        game_id = game.get("Game", {}).get("GameID")
        inning_data = game.get("Innings", [])
        # ---- first-inning runs for label construction ----
        home_1st = 0
        away_1st = 0
        for inn in inning_data:
            if inn.get("InningNumber") == 1:
                home_1st += inn.get("HomeTeamRuns", 0) or 0
                away_1st += inn.get("AwayTeamRuns", 0) or 0
        total_1st = home_1st + away_1st
        label_nrfi = int(total_1st == 0)  # 1 = NRFI, 0 = YRFI

        # Team stats
        for side in ("HomeTeam", "AwayTeam"):
            ts = game.get(side + "Stats") or {}
            ts["GameID"]      = game_id
            ts["Side"]        = side
            ts["FirstInningRuns"] = home_1st if side == "HomeTeam" else away_1st
            ts["TotalFirstInningRuns"] = total_1st
            ts["NRFI"]        = label_nrfi
            ts["GameDate"]    = game_date
            team_rows.append(ts)

        # Player batting/pitching rows
        for pstat in game.get("PlayerStats", []):
            pstat["GameID"]   = game_id
            pstat["GameDate"] = game_date
            pstat["NRFI"]     = label_nrfi
            player_rows.append(pstat)

    return pd.DataFrame(team_rows), pd.DataFrame(player_rows)


def fetch_starting_lineups(game_date: date) -> pd.DataFrame:
    data = _get(_url("starting_lineups", date=game_date.strftime("%Y-%b-%d")))
    if not data:
        return pd.DataFrame()
    rows = []
    for lineup in data:
        game_id = lineup.get("GameID")
        for player in lineup.get("Lineups", []):
            player["GameID"]   = game_id
            player["GameDate"] = game_date
            rows.append(player)
    return pd.DataFrame(rows)


def fetch_injuries() -> pd.DataFrame:
    data = _get(_url("injuries"))
    if not data:
        return pd.DataFrame()
    return pd.json_normalize(data)


def fetch_game_odds(game_date: date) -> pd.DataFrame:
    data = _get(_url("game_odds", date=game_date.strftime("%Y-%b-%d")))
    if not data:
        return pd.DataFrame()
    rows = []
    for game_odds in data:
        game_id = game_odds.get("GameID")
        for line in game_odds.get("PregameOdds", []) or []:
            line["GameID"]   = game_id
            line["GameDate"] = game_date
            rows.append(line)
    return pd.DataFrame(rows)


def fetch_projections(game_date: date) -> pd.DataFrame:
    data = _get(_url("projections", date=game_date.strftime("%Y-%b-%d")))
    if not data:
        return pd.DataFrame()
    df = pd.json_normalize(data)
    df["GameDate"] = game_date
    return df


def fetch_umpires() -> pd.DataFrame:
    data = _get(_url("umpires"))
    if not data:
        return pd.DataFrame()
    return pd.json_normalize(data)


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _upsert(df: pd.DataFrame, table: str, if_exists: str = "append") -> None:
    if df.empty:
        return
    # Flatten any remaining nested dicts
    df = df.applymap(lambda x: str(x) if isinstance(x, (dict, list)) else x)
    df.to_sql(table, _ENGINE, if_exists=if_exists, index=False, chunksize=500)
    logger.info(f"Persisted {len(df)} rows -> {table}")


# ---------------------------------------------------------------------------
# Main daily ingestion entry-point
# ---------------------------------------------------------------------------

def ingest_date(game_date: date) -> None:
    """Ingest all SportsDataIO data for a single date."""
    logger.info(f"=== Ingesting SDIO data for {game_date} ===")

    # Games
    games_df = fetch_games_by_date(game_date)
    _upsert(games_df, "sdio_games")

    # Box scores
    team_box, player_box = fetch_box_scores(game_date)
    _upsert(team_box, "sdio_team_box")
    _upsert(player_box, "sdio_player_box")

    # Lineups
    lineups = fetch_starting_lineups(game_date)
    _upsert(lineups, "sdio_lineups")

    # Odds
    odds = fetch_game_odds(game_date)
    _upsert(odds, "sdio_odds")

    # Projections
    proj = fetch_projections(game_date)
    _upsert(proj, "sdio_projections")

    logger.info(f"=== SDIO ingestion complete for {game_date} ===")


def ingest_date_range(start: date, end: date) -> None:
    """Backfill ingestion across a range of dates."""
    d = start
    while d <= end:
        try:
            ingest_date(d)
        except Exception as exc:
            logger.error(f"Failed ingesting {d}: {exc}")
        d += timedelta(days=1)
        time.sleep(0.5)   # be kind to the API


def ingest_season(season: int) -> None:
    """Ingest an entire MLB season (April-October)."""
    start = date(season, 3, 20)
    end   = date(season, 11, 5)
    ingest_date_range(start, end)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--date",   help="YYYY-MM-DD")
    ap.add_argument("--season", type=int, help="Full season year")
    ap.add_argument("--start",  help="YYYY-MM-DD start of range")
    ap.add_argument("--end",    help="YYYY-MM-DD end of range")
    args = ap.parse_args()

    if args.date:
        ingest_date(date.fromisoformat(args.date))
    elif args.season:
        ingest_season(args.season)
    elif args.start and args.end:
        ingest_date_range(
            date.fromisoformat(args.start),
            date.fromisoformat(args.end),
        )
    else:
        # Default: ingest yesterday
        ingest_date(date.today() - timedelta(days=1))
