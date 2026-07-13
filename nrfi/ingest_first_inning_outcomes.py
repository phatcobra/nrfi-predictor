"""Backfill and nightly append of authoritative first-inning outcomes.

Labels come from finalized MLB Stats API linescores. Starting-pitcher IDs come
from finalized box-score pitching stats, never scheduled probable pitchers.
When the feed cannot prove the actual starter, the ID remains NULL and feature
coverage gates decide whether the game is usable.
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import date, datetime, timedelta
from typing import Any

from nrfi.config import TZ_ET
from nrfi.snowflake_loader import SnowflakeLoader

logger = logging.getLogger(__name__)

OUTCOMES_TABLE = "NRFI_DB.CORE.FIRST_INNING_OUTCOMES"
FINAL_STATUSES = {"Final", "Game Over", "Completed Early"}


def actual_starter_id(game_feed: dict[str, Any], side: str) -> int | None:
    """Return the unique finalized starter for ``away`` or ``home``.

    MLB box-score player rows mark the starter with pitching.gamesStarted == 1.
    Multiple or absent matches are treated as ambiguous and return None.
    """
    if side not in {"away", "home"}:
        raise ValueError("side must be 'away' or 'home'")
    team = (
        game_feed.get("liveData", {})
        .get("boxscore", {})
        .get("teams", {})
        .get(side, {})
    )
    candidates: list[int] = []
    for player in (team.get("players") or {}).values():
        pitching = (player.get("stats") or {}).get("pitching") or {}
        try:
            games_started = int(pitching.get("gamesStarted", 0) or 0)
        except (TypeError, ValueError):
            games_started = 0
        if games_started != 1:
            continue
        person_id = (player.get("person") or {}).get("id")
        try:
            candidates.append(int(person_id))
        except (TypeError, ValueError):
            continue
    unique = sorted(set(candidates))
    return unique[0] if len(unique) == 1 else None


def _team_metadata(game_feed: dict[str, Any], side: str) -> tuple[str | None, int | None]:
    team = (game_feed.get("gameData", {}).get("teams", {}).get(side, {}) or {})
    name = team.get("name")
    identifier = team.get("id")
    try:
        identifier = int(identifier) if identifier is not None else None
    except (TypeError, ValueError):
        identifier = None
    return (str(name) if name else None, identifier)


def _venue_id(game_feed: dict[str, Any]) -> int | None:
    value = (game_feed.get("gameData", {}).get("venue", {}) or {}).get("id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def fetch_day(day: date) -> list[dict]:
    """Return one observed row per final game with a complete first inning."""
    import statsapi

    rows: list[dict] = []
    schedule = statsapi.schedule(date=day.isoformat())
    for scheduled_game in schedule:
        if scheduled_game.get("status") not in FINAL_STATUSES:
            continue
        game_pk = scheduled_game.get("game_id")
        if game_pk is None:
            continue
        try:
            game_feed = statsapi.get("game", {"gamePk": game_pk})
        except Exception as exc:
            logger.error(
                f"final game feed failed for {game_pk}: {exc}; skipping")
            continue

        innings = (
            game_feed.get("liveData", {})
            .get("linescore", {})
            .get("innings", [])
        )
        first = next(
            (inning for inning in innings if inning.get("num") == 1), None)
        if not first:
            logger.warning(f"game {game_pk} has no explicit first-inning linescore")
            continue
        top = (first.get("away") or {}).get("runs")
        bottom = (first.get("home") or {}).get("runs")
        try:
            top_runs = int(top)
            bottom_runs = int(bottom)
        except (TypeError, ValueError):
            logger.warning(f"game {game_pk} has incomplete first-inning runs")
            continue
        if top_runs < 0 or bottom_runs < 0:
            logger.warning(f"game {game_pk} has negative first-inning runs")
            continue

        away_name, _ = _team_metadata(game_feed, "away")
        home_name, _ = _team_metadata(game_feed, "home")
        away_name = away_name or scheduled_game.get("away_name")
        home_name = home_name or scheduled_game.get("home_name")

        rows.append({
            "game_id": str(game_pk),
            "game_date": day.isoformat(),
            "season": day.year,
            "home_team": home_name,
            "away_team": away_name,
            "home_sp_id": actual_starter_id(game_feed, "home"),
            "away_sp_id": actual_starter_id(game_feed, "away"),
            "venue_id": _venue_id(game_feed),
            "fi_runs_top": top_runs,
            "fi_runs_bottom": bottom_runs,
            "yrfi": bool(top_runs + bottom_runs > 0),
            "is_doubleheader": scheduled_game.get("doubleheader", "N") != "N",
            "game_number": int(scheduled_game.get("game_num", 1) or 1),
            "source": "mlb_statsapi_final",
            "ingested_at": datetime.now(TZ_ET).isoformat(),
        })
    return rows


def backfill(start: date, end: date, sleep_s: float = 0.3) -> int:
    if start > end:
        raise ValueError("start must be on or before end")
    warehouse = SnowflakeLoader()
    total = 0
    current = start
    while current <= end:
        rows = fetch_day(current)
        if rows:
            warehouse.merge_upsert(OUTCOMES_TABLE, rows, key_cols=["game_id"])
            total += len(rows)
        if current.day == 1 or rows:
            logger.info(f"{current}: {len(rows)} games (running total {total})")
        current += timedelta(days=1)
        time.sleep(max(0.0, sleep_s))
    logger.info(f"backfill complete: {total} games {start}..{end}")
    return total


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="start", help="YYYY-MM-DD")
    parser.add_argument("--to", dest="end", help="YYYY-MM-DD")
    parser.add_argument("--yesterday", action="store_true")
    args = parser.parse_args()
    if args.yesterday:
        yesterday = (datetime.now(TZ_ET) - timedelta(days=1)).date()
        backfill(yesterday, yesterday, sleep_s=0.1)
    elif args.start and args.end:
        backfill(date.fromisoformat(args.start), date.fromisoformat(args.end))
    else:
        parser.error("--yesterday or (--from and --to) required")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    main()
