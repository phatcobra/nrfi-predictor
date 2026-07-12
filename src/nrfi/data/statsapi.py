"""MLB StatsAPI ingestion.

Fetches regular-season schedules hydrated with linescores and probable
pitchers, month by month, and flattens them into one row per game. This is
the only historical data source the pipeline needs: first-inning runs for
both teams come from the linescore, and the starter is attributed via the
probable pitcher, which matches the pre-game information set used at
prediction time.

No function here is called from tests with a live URL; tests exercise the
parsers against recorded-style fixtures.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from collections.abc import Iterable
from typing import Any

import requests

from nrfi.config import (
    GAME_TYPE,
    REQUEST_BACKOFF_SECONDS,
    REQUEST_RETRIES,
    REQUEST_TIMEOUT,
    SPORT_ID,
    STATSAPI_BASE,
)

log = logging.getLogger(__name__)

USER_AGENT = "nrfi-predictor/1.0 (research pipeline)"

# Regular season spans March-November in every modern season (2020 started
# in July, but querying empty months just returns zero games).
SEASON_MONTHS = [(3, 1), (4, 1), (5, 1), (6, 1), (7, 1), (8, 1), (9, 1), (10, 1), (11, 1), (12, 1)]

GAME_COLUMNS = [
    "game_pk",
    "season",
    "game_date",
    "game_datetime_utc",
    "game_type",
    "status",
    "day_night",
    "double_header",
    "venue_id",
    "venue_name",
    "home_team_id",
    "home_team_name",
    "away_team_id",
    "away_team_name",
    "home_probable_pitcher_id",
    "home_probable_pitcher_name",
    "away_probable_pitcher_id",
    "away_probable_pitcher_name",
    "innings_recorded",
    "first_inning_runs_away",
    "first_inning_runs_home",
]


def _get_json(session: requests.Session, url: str, params: dict[str, Any]) -> dict[str, Any]:
    last_err: Exception | None = None
    for attempt in range(REQUEST_RETRIES + 1):
        try:
            resp = session.get(url, params=params, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as err:  # ValueError: bad JSON
            last_err = err
            wait = REQUEST_BACKOFF_SECONDS * (2**attempt)
            log.warning(
                "StatsAPI request failed (attempt %d/%d): %s; retrying in %.0fs",
                attempt + 1,
                REQUEST_RETRIES + 1,
                err,
                wait,
            )
            time.sleep(wait)
    raise RuntimeError(f"StatsAPI request failed after {REQUEST_RETRIES + 1} attempts: {url}") from last_err


def _month_ranges(season: int) -> Iterable[tuple[str, str]]:
    for month, day in SEASON_MONTHS[:-1]:
        start = dt.date(season, month, day)
        next_month, _ = SEASON_MONTHS[SEASON_MONTHS.index((month, day)) + 1]
        end = dt.date(season, next_month, 1) - dt.timedelta(days=1)
        yield start.isoformat(), end.isoformat()


def fetch_season_games(season: int, session: requests.Session | None = None) -> list[dict[str, Any]]:
    """Fetch and parse all regular-season games for one season."""
    sess = session or requests.Session()
    rows: list[dict[str, Any]] = []
    for start, end in _month_ranges(season):
        payload = _get_json(
            sess,
            f"{STATSAPI_BASE}/schedule",
            params={
                "sportId": SPORT_ID,
                "gameType": GAME_TYPE,
                "startDate": start,
                "endDate": end,
                "hydrate": "linescore,probablePitcher",
            },
        )
        rows.extend(parse_schedule_payload(payload))
    # Doubleheader/suspended games can appear in two monthly windows; the
    # official date decides which copy we keep (last write wins on game_pk).
    dedup: dict[int, dict[str, Any]] = {row["game_pk"]: row for row in rows}
    out = sorted(dedup.values(), key=lambda r: (r["game_date"], r["game_pk"]))
    log.info("season %d: %d games parsed", season, len(out))
    return out


def parse_schedule_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a hydrated /schedule response into per-game rows.

    Defensive: any missing sub-object yields None fields rather than a crash,
    so one malformed game cannot sink an ingest run.
    """
    rows: list[dict[str, Any]] = []
    for date_block in payload.get("dates", []) or []:
        for game in date_block.get("games", []) or []:
            row = parse_game(game)
            if row is not None:
                rows.append(row)
    return rows


def parse_game(game: dict[str, Any]) -> dict[str, Any] | None:
    if game.get("gameType") != GAME_TYPE:
        return None
    game_pk = game.get("gamePk")
    if game_pk is None:
        return None

    teams = game.get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}
    venue = game.get("venue") or {}
    status = game.get("status") or {}
    linescore = game.get("linescore") or {}
    innings = linescore.get("innings") or []

    first = innings[0] if innings else {}
    fi_away = (first.get("away") or {}).get("runs")
    fi_home = (first.get("home") or {}).get("runs")

    def _pitcher(side: dict[str, Any]) -> tuple[Any, Any]:
        pp = side.get("probablePitcher") or {}
        return pp.get("id"), pp.get("fullName")

    home_pid, home_pname = _pitcher(home)
    away_pid, away_pname = _pitcher(away)

    season_raw = game.get("season")
    try:
        season = int(season_raw)
    except (TypeError, ValueError):
        season = None

    return {
        "game_pk": int(game_pk),
        "season": season,
        "game_date": game.get("officialDate") or game.get("gameDate", "")[:10],
        "game_datetime_utc": game.get("gameDate"),
        "game_type": game.get("gameType"),
        "status": (status.get("abstractGameState") or "").strip(),
        "day_night": game.get("dayNight"),
        "double_header": game.get("doubleHeader"),
        "venue_id": venue.get("id"),
        "venue_name": venue.get("name"),
        "home_team_id": (home.get("team") or {}).get("id"),
        "home_team_name": (home.get("team") or {}).get("name"),
        "away_team_id": (away.get("team") or {}).get("id"),
        "away_team_name": (away.get("team") or {}).get("name"),
        "home_probable_pitcher_id": home_pid,
        "home_probable_pitcher_name": home_pname,
        "away_probable_pitcher_id": away_pid,
        "away_probable_pitcher_name": away_pname,
        "innings_recorded": len(innings),
        "first_inning_runs_away": fi_away,
        "first_inning_runs_home": fi_home,
    }


def fetch_venues(session: requests.Session | None = None) -> list[dict[str, Any]]:
    """Fetch venue metadata (coordinates, roof type) for weather joins.

    Authoritative source; nothing is hardcoded so renamed/new parks resolve
    automatically.
    """
    sess = session or requests.Session()
    payload = _get_json(
        sess,
        f"{STATSAPI_BASE}/venues",
        params={"hydrate": "location,fieldInfo"},
    )
    return parse_venues_payload(payload)


def parse_venues_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for venue in payload.get("venues", []) or []:
        vid = venue.get("id")
        if vid is None:
            continue
        loc = venue.get("location") or {}
        coords = loc.get("defaultCoordinates") or {}
        field_info = venue.get("fieldInfo") or {}
        rows.append(
            {
                "venue_id": int(vid),
                "venue_name": venue.get("name"),
                "latitude": coords.get("latitude"),
                "longitude": coords.get("longitude"),
                "roof_type": field_info.get("roofType"),
            }
        )
    return rows
