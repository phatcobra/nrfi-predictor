"""Backfill + nightly append of first-inning outcomes (labels).

Source: MLB Stats API linescores (free, authoritative). Idempotent MERGE on
game_id. Label yrfi = (top+bottom 1st-inning runs) > 0, NULL until final.

Usage:
    python -m nrfi.ingest_first_inning_outcomes --from 2015-04-01 --to 2015-11-15
    python -m nrfi.ingest_first_inning_outcomes --yesterday
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import date, datetime, timedelta

from nrfi.config import TZ_ET
from nrfi.snowflake_loader import SnowflakeLoader

logger = logging.getLogger(__name__)

OUTCOMES_TABLE = "NRFI_DB.CORE.FIRST_INNING_OUTCOMES"
FINAL_STATUSES = {"Final", "Game Over", "Completed Early"}


def fetch_day(d: date) -> list[dict]:
    """One row per FINAL game with a first-inning linescore."""
    import statsapi  # lazy
    rows: list[dict] = []
    sched = statsapi.schedule(date=d.isoformat())
    for g in sched:
        if g.get("status") not in FINAL_STATUSES:
            continue
        game_pk = g.get("game_id")
        try:
            data = statsapi.get("game", {"gamePk": game_pk})
            innings = (data.get("liveData", {}).get("linescore", {})
                       .get("innings", []))
        except Exception as e:
            logger.error(f"linescore fetch failed for {game_pk}: {e} - skipping (null, not guessed)")
            continue
        if not innings:
            continue
        first = innings[0]
        top = first.get("away", {}).get("runs")
        bottom = first.get("home", {}).get("runs")
        if top is None or bottom is None:
            # suspended/forfeit weirdness: leave unlabeled rather than guess
            continue
        rows.append({
            "game_id": str(game_pk),
            "game_date": d.isoformat(),
            "season": d.year,
            "home_team": g.get("home_name"),
            "away_team": g.get("away_name"),
            "home_sp_id": g.get("home_probable_pitcher_id") or None,
            "away_sp_id": g.get("away_probable_pitcher_id") or None,
            "venue_id": g.get("venue_id"),
            "fi_runs_top": int(top),
            "fi_runs_bottom": int(bottom),
            "yrfi": bool(int(top) + int(bottom) > 0),
            "is_doubleheader": g.get("doubleheader", "N") != "N",
            "game_number": int(g.get("game_num", 1)),
            "source": "statsapi",
            "ingested_at": datetime.now(TZ_ET).isoformat(),
        })
    return rows


def backfill(start: date, end: date, sleep_s: float = 0.3) -> int:
    sf = SnowflakeLoader()
    total = 0
    d = start
    while d <= end:
        rows = fetch_day(d)
        if rows:
            sf.merge_upsert(OUTCOMES_TABLE, rows, key_cols=["game_id"])
            total += len(rows)
        if d.day == 1 or rows:
            logger.info(f"{d}: {len(rows)} games (running total {total})")
        d += timedelta(days=1)
        time.sleep(sleep_s)
    logger.info(f"backfill complete: {total} games {start}..{end}")
    return total


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", help="YYYY-MM-DD")
    ap.add_argument("--to", dest="end", help="YYYY-MM-DD")
    ap.add_argument("--yesterday", action="store_true",
                    help="grade yesterday (ET) - the nightly job")
    args = ap.parse_args()
    if args.yesterday:
        y = (datetime.now(TZ_ET) - timedelta(days=1)).date()
        backfill(y, y, sleep_s=0.1)
    elif args.start and args.end:
        backfill(date.fromisoformat(args.start), date.fromisoformat(args.end))
    else:
        ap.error("--yesterday or (--from and --to) required")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    main()
