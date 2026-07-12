"""Statcast / pybaseball ingestion module.

Ingests:
  - Pitch-level Statcast data (2015+) via pybaseball
  - Batting / pitching season stats via FanGraphs (pybaseball)
  - Retrosheet play-by-play for historical labels (pre-Statcast)
  - Weather via Meteostat (historical) or OpenWeatherMap (future)
"""
from __future__ import annotations

import time
from datetime import date, timedelta

import pandas as pd
from loguru import logger
from sqlalchemy import create_engine
from tenacity import retry, stop_after_attempt, wait_exponential

try:
    import pybaseball as pb
    pb.cache.enable()
except ImportError:
    pb = None
    logger.warning("pybaseball not installed; Statcast ingestion disabled.")

from src.config import DATABASE_URL, STATCAST_START_YEAR

_ENGINE = create_engine(DATABASE_URL, echo=False)


# ---------------------------------------------------------------------------
# Statcast pitch-level
# ---------------------------------------------------------------------------

def ingest_statcast_range(start: date, end: date) -> None:
    """Ingest Statcast pitch-level data for a date range."""
    if pb is None:
        logger.error("pybaseball not available.")
        return
    logger.info(f"Fetching Statcast {start} -> {end}")
    df = pb.statcast(
        start_dt=start.strftime("%Y-%m-%d"),
        end_dt=end.strftime("%Y-%m-%d"),
        verbose=False,
    )
    if df is None or df.empty:
        logger.warning("No Statcast data returned.")
        return
    # Keep only cols relevant to first-inning analysis
    keep = [
        "game_pk", "game_date", "inning", "inning_topbot",
        "pitcher", "batter", "stand", "p_throws",
        "pitch_type", "release_speed", "release_spin_rate",
        "effective_speed", "pfx_x", "pfx_z",
        "plate_x", "plate_z", "zone",
        "type", "events", "description",
        "launch_speed", "launch_angle",
        "estimated_ba_using_speedangle", "estimated_woba_using_speedangle",
        "woba_value", "woba_denom",
        "babip_value", "iso_value",
        "at_bat_number", "pitch_number",
        "on_1b", "on_2b", "on_3b",
        "outs_when_up", "balls", "strikes",
        "home_team", "away_team",
        "home_score", "away_score",
    ]
    existing = [c for c in keep if c in df.columns]
    df = df[existing].copy()
    df["game_date"] = pd.to_datetime(df["game_date"])
    # Only first inning
    df_1st = df[df["inning"] == 1].copy()
    _save(df_1st, "statcast_pitches_1st")
    # Save all pitches for rolling window features
    _save(df, "statcast_pitches_all")
    logger.info(f"Statcast: {len(df_1st)} 1st-inning pitches, {len(df)} total")


def ingest_statcast_season(season: int) -> None:
    if season < STATCAST_START_YEAR:
        logger.warning(f"Statcast not available before {STATCAST_START_YEAR}")
        return
    start = date(season, 3, 20)
    end   = date(season, 11, 5)
    # Chunk by month to avoid huge downloads
    d = start
    while d < end:
        chunk_end = min(d + timedelta(days=30), end)
        try:
            ingest_statcast_range(d, chunk_end)
        except Exception as e:
            logger.error(f"Statcast chunk {d}-{chunk_end} failed: {e}")
        d = chunk_end + timedelta(days=1)
        time.sleep(2)


# ---------------------------------------------------------------------------
# FanGraphs season-level batting / pitching
# ---------------------------------------------------------------------------

def ingest_fg_batting(season: int) -> None:
    if pb is None:
        return
    logger.info(f"FG batting {season}")
    df = pb.batting_stats(season, qual=0)
    if df is not None and not df.empty:
        df["Season"] = season
        _save(df, "fg_batting")


def ingest_fg_pitching(season: int) -> None:
    if pb is None:
        return
    logger.info(f"FG pitching {season}")
    df = pb.pitching_stats(season, qual=0)
    if df is not None and not df.empty:
        df["Season"] = season
        _save(df, "fg_pitching")


# ---------------------------------------------------------------------------
# Retrosheet first-inning labels (historical, pre-Statcast)
# ---------------------------------------------------------------------------

def ingest_retrosheet_season(season: int, retrosheet_dir: str) -> None:
    """Parse Retrosheet event files for a season to extract first-inning labels.

    Retrosheet files (*.EVN / *.EVA) must be pre-downloaded to retrosheet_dir.
    Download from: https://www.retrosheet.org/game.htm
    """
    import os, re
    from pathlib import Path

    retro_path = Path(retrosheet_dir)
    event_files = list(retro_path.glob(f"{season}*.EV*"))
    if not event_files:
        logger.warning(f"No Retrosheet event files for {season} in {retrosheet_dir}")
        return

    rows = []
    for f in event_files:
        game_id = None
        inning   = None
        side     = None  # T=top, B=bottom
        first_inn_runs = {"home": 0, "away": 0}
        inning_closed  = {"top1": False, "bot1": False}

        with open(f, encoding="latin-1") as fh:
            for line in fh:
                parts = line.strip().split(",")
                rec_type = parts[0]

                if rec_type == "id":
                    if game_id is not None:
                        # save previous game
                        rows.append(_retrosheet_row(
                            game_id, season, first_inn_runs
                        ))
                    game_id = parts[1]
                    first_inn_runs = {"home": 0, "away": 0}
                    inning_closed  = {"top1": False, "bot1": False}

                elif rec_type == "play" and game_id:
                    # play,inning,side,batter,...,play_desc
                    try:
                        inn  = int(parts[1])
                        side = int(parts[2])  # 0=away(top), 1=home(bot)
                        play = parts[6] if len(parts) > 6 else ""
                        if inn == 1:
                            runs_scored = play.count("H") - play.count("HP")  # rough
                            # Better: count explicit run scoring
                            runs_scored = len(re.findall(r"(?<![B])R(?!H)", play))
                            if side == 0:   # top of 1st = away bats
                                first_inn_runs["away"] += runs_scored
                            else:           # bot of 1st = home bats
                                first_inn_runs["home"] += runs_scored
                    except (IndexError, ValueError):
                        pass

        if game_id is not None:
            rows.append(_retrosheet_row(game_id, season, first_inn_runs))

    if rows:
        df = pd.DataFrame(rows)
        _save(df, "retrosheet_labels")
        logger.info(f"Retrosheet {season}: {len(df)} games")


def _retrosheet_row(game_id, season, runs):
    total = runs["home"] + runs["away"]
    return {
        "game_id": game_id,
        "season":  season,
        "home_1st_runs": runs["home"],
        "away_1st_runs": runs["away"],
        "total_1st_runs": total,
        "nrfi": int(total == 0),
    }


# ---------------------------------------------------------------------------
# Park / stadium metadata from pybaseball
# ---------------------------------------------------------------------------

def ingest_park_factors(season: int) -> None:
    if pb is None:
        return
    logger.info(f"Park factors {season}")
    try:
        df = pb.park_factors(season)
        if df is not None and not df.empty:
            df["Season"] = season
            _save(df, "park_factors")
    except Exception as e:
        logger.warning(f"Park factor fetch failed: {e}")


# ---------------------------------------------------------------------------
# Weather via Meteostat
# ---------------------------------------------------------------------------

def fetch_weather_for_game(
    lat: float,
    lon: float,
    game_date: date,
) -> dict:
    """Return hourly weather row closest to first pitch (~7 PM local)."""
    try:
        from datetime import datetime
        from meteostat import Point, Hourly
        point   = Point(lat, lon)
        start_t = datetime(game_date.year, game_date.month, game_date.day, 18)
        end_t   = datetime(game_date.year, game_date.month, game_date.day, 22)
        df = Hourly(point, start_t, end_t).fetch()
        if df.empty:
            return {}
        row = df.iloc[0]
        return {
            "temp_c":     row.get("temp"),
            "wind_speed_kmh": row.get("wspd"),
            "wind_dir_deg":   row.get("wdir"),
            "humidity":       row.get("rhum"),
            "precip_mm":      row.get("prcp"),
            "condition_code": row.get("coco"),
        }
    except Exception as e:
        logger.warning(f"Weather fetch failed: {e}")
        return {}


# ---------------------------------------------------------------------------
# Shared DB helper
# ---------------------------------------------------------------------------

def _save(df: pd.DataFrame, table: str) -> None:
    if df is None or df.empty:
        return
    df = df.copy()
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].astype(str)
    df.to_sql(table, _ENGINE, if_exists="append", index=False, chunksize=500)
    logger.info(f"Saved {len(df)} rows -> {table}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--retrosheet-dir", default="data/retrosheet")
    args = ap.parse_args()

    ingest_fg_batting(args.season)
    ingest_fg_pitching(args.season)
    ingest_park_factors(args.season)
    ingest_statcast_season(args.season)
    ingest_retrosheet_season(args.season, args.retrosheet_dir)
