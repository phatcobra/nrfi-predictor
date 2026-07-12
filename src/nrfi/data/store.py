"""Processed-data store: one compact CSV per season plus venue metadata.

CSVs are committed to the repository by the training workflow so every
retrain is reproducible and past seasons never need refetching.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from nrfi.data.statsapi import GAME_COLUMNS

log = logging.getLogger(__name__)

VENUES_FILE = "venues.csv"
WEATHER_FILE = "weather.csv"


def season_path(data_dir: Path, season: int) -> Path:
    return data_dir / f"games_{season}.csv"


def write_season(data_dir: Path, season: int, rows: list[dict]) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows, columns=GAME_COLUMNS)
    path = season_path(data_dir, season)
    frame.to_csv(path, index=False)
    log.info("wrote %d rows -> %s", len(frame), path)
    return path


def load_games(data_dir: Path) -> pd.DataFrame:
    """Load every stored season, chronologically sorted."""
    paths = sorted(data_dir.glob("games_*.csv"))
    if not paths:
        raise FileNotFoundError(f"no games_*.csv files under {data_dir}; run `nrfi ingest` first")
    frames = [pd.read_csv(p) for p in paths]
    games = pd.concat(frames, ignore_index=True)
    games = games.sort_values(["game_date", "game_datetime_utc", "game_pk"], kind="stable")
    return games.reset_index(drop=True)


def stored_seasons(data_dir: Path) -> list[int]:
    return sorted(int(p.stem.split("_")[1]) for p in data_dir.glob("games_*.csv"))


def write_venues(data_dir: Path, rows: list[dict]) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / VENUES_FILE
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def load_venues(data_dir: Path) -> pd.DataFrame | None:
    path = data_dir / VENUES_FILE
    if not path.exists():
        return None
    return pd.read_csv(path)


def write_weather(data_dir: Path, frame: pd.DataFrame) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / WEATHER_FILE
    frame.to_csv(path, index=False)
    return path


def load_weather(data_dir: Path) -> pd.DataFrame | None:
    path = data_dir / WEATHER_FILE
    if not path.exists():
        return None
    return pd.read_csv(path)
