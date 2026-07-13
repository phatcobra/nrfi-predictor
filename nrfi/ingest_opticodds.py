"""OpticOdds NRFI/YRFI odds ingestion (fail-closed).

Rules:
  - The market is matched by EXACT market id (OPTIC_FI_TOTAL_MARKET_ID) and a
    numeric line == 0.5 check. Substring matching is forbidden: "first" also
    matched "First 5 Innings" markets and "0.5" matched 10.5.
  - No-vig probabilities are computed per book at ingest time:
        p_yrfi_novig = p_yrfi_raw / (p_yrfi_raw + p_nrfi_raw)
  - Snapshots are immutable and deduped on snapshot_id (MERGE upsert).
  - Timestamps are timezone-aware UTC from the API payload when present.
  - Missing market id or API key => the job raises. Nothing is guessed.
"""
from __future__ import annotations

import hashlib
import time
from datetime import date, datetime, timezone

from nrfi._obs import logger, sentry_sdk

from nrfi.config import (
    NRFI_SPORTSBOOKS,
    OPTIC_API_KEY,
    OPTIC_BASE_URL,
    OPTIC_FI_TOTAL_MARKET_ID,
)
from nrfi.snowflake_loader import SnowflakeLoader

ODDS_TABLE = "NRFI_DB.CORE.ODDS_SNAPSHOTS"


# ------------------------------------------------------------------ helpers

def american_to_prob(american: float) -> float:
    if american >= 0:
        return 100.0 / (american + 100.0)
    return abs(american) / (abs(american) + 100.0)


def novig_pair(p_a_raw: float, p_b_raw: float) -> tuple[float, float]:
    s = p_a_raw + p_b_raw
    return (p_a_raw / s, p_b_raw / s)


def _require_config() -> None:
    if not OPTIC_API_KEY:
        raise RuntimeError("OPTIC_API_KEY not set - odds ingest fails closed")
    if not OPTIC_FI_TOTAL_MARKET_ID:
        raise RuntimeError(
            "OPTIC_FI_TOTAL_MARKET_ID not set. A human must pin the exact "
            "OpticOdds market id for the MLB 1st-inning total; see config.py."
        )


def _get(endpoint: str, params: list[tuple[str, str]]) -> dict:
    import requests
    from tenacity import retry, stop_after_attempt, wait_exponential

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(min=2, max=20))
    def _go():
        return _do_get(endpoint, params)
    return _go()


def _do_get(endpoint: str, params: list[tuple[str, str]]) -> dict:
    import requests
    url = f"{OPTIC_BASE_URL}/{endpoint}"
    with sentry_sdk.start_span(op="http", description=f"OpticOdds {endpoint}"):
        resp = requests.get(url, headers={"x-api-key": OPTIC_API_KEY},
                            params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()


# ------------------------------------------------------------------ fetch

def fetch_mlb_fixtures(target_date: date | None = None) -> list[dict]:
    target_date = target_date or datetime.now(timezone.utc).date()
    data = _get("fixtures", [("sport", "baseball_mlb"),
                             ("date", target_date.isoformat()),
                             ("status", "scheduled")])
    fixtures = data.get("data", [])
    logger.info(f"{len(fixtures)} MLB fixtures on {target_date}")
    return fixtures


def fetch_fi_total_odds(fixture_id: str) -> list[dict]:
    """Return one row per sportsbook for the exact 1st-inning-total market."""
    params = [("fixture_id", fixture_id), ("market", OPTIC_FI_TOTAL_MARKET_ID)]
    params += [("sportsbook", b) for b in NRFI_SPORTSBOOKS]
    data = _get("fixtures/odds", params)

    rows: list[dict] = []
    for book_data in data.get("data", []):
        book = book_data.get("sportsbook")
        for market in book_data.get("markets", []):
            if str(market.get("id", market.get("market_id", ""))) != OPTIC_FI_TOTAL_MARKET_ID:
                continue
            try:
                line = float(market.get("line"))
            except (TypeError, ValueError):
                continue
            if line != 0.5:
                continue
            yrfi_price = nrfi_price = None
            for outcome in market.get("outcomes", []):
                name = str(outcome.get("name", "")).strip().lower()
                if name == "over":
                    yrfi_price = outcome.get("price")
                elif name == "under":
                    nrfi_price = outcome.get("price")
            if yrfi_price is None or nrfi_price is None:
                continue
            captured = market.get("timestamp") or book_data.get("timestamp")
            captured_at = (
                datetime.fromisoformat(captured.replace("Z", "+00:00"))
                if isinstance(captured, str)
                else datetime.now(timezone.utc)
            )
            p_yrfi_raw = american_to_prob(float(yrfi_price))
            p_nrfi_raw = american_to_prob(float(nrfi_price))
            p_yrfi_nv, p_nrfi_nv = novig_pair(p_yrfi_raw, p_nrfi_raw)
            snapshot_id = hashlib.sha1(
                f"{fixture_id}|{book}|{captured_at.isoformat()}".encode()
            ).hexdigest()
            rows.append({
                "snapshot_id": snapshot_id,
                "fixture_id": fixture_id,
                "sportsbook": book,
                "market_id": OPTIC_FI_TOTAL_MARKET_ID,
                "line": 0.5,
                "yrfi_american": float(yrfi_price),
                "nrfi_american": float(nrfi_price),
                "yrfi_prob_raw": p_yrfi_raw,
                "nrfi_prob_raw": p_nrfi_raw,
                "yrfi_prob_novig": p_yrfi_nv,
                "nrfi_prob_novig": p_nrfi_nv,
                "captured_at": captured_at.isoformat(),
            })
            break  # exactly one matching market per book
    return rows


# ------------------------------------------------------------------ store

def ingest_date(target_date: date | None = None) -> int:
    """Fetch + upsert all snapshots for a date. Returns row count."""
    _require_config()
    sf = SnowflakeLoader()
    fixtures = fetch_mlb_fixtures(target_date)
    total = 0
    with sentry_sdk.start_transaction(op="task", name="ingest_opticodds_nrfi"):
        for fx in fixtures:
            fixture_id = str(fx.get("id"))
            rows = fetch_fi_total_odds(fixture_id)
            for r in rows:
                r.update({
                    "game_date": fx.get("start_date"),
                    "home_team": fx.get("home_team"),
                    "away_team": fx.get("away_team"),
                    "start_time": fx.get("start_time"),
                })
            if rows:
                sf.merge_upsert(ODDS_TABLE, rows, key_cols=["snapshot_id"])
                total += len(rows)
            time.sleep(0.25)
    logger.info(f"ingested {total} odds snapshots for {len(fixtures)} fixtures")
    return total


class OpticOddsIngester:
    """Interface used by predict_daily: latest per-book odds keyed by matchup."""

    def __init__(self) -> None:
        self.sf = SnowflakeLoader()

    def refresh(self, target_date: date | None = None) -> int:
        return ingest_date(target_date)

    def get_nrfi_odds(self, target_date: str) -> dict:
        """{(home_team, away_team): {books: {book: row}, newest_captured_at}}
        using only each book's LATEST snapshot for the date."""
        query = """
        SELECT home_team, away_team, sportsbook,
               yrfi_prob_novig, nrfi_prob_novig,
               yrfi_american, nrfi_american, captured_at
        FROM NRFI_DB.CORE.ODDS_SNAPSHOTS
        WHERE game_date = %s
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY home_team, away_team, sportsbook
            ORDER BY captured_at DESC) = 1
        """
        out: dict = {}
        for row in self.sf.execute_query(query, [target_date]):
            key = (row["home_team"], row["away_team"])
            entry = out.setdefault(key, {"books": {}, "newest_captured_at": None})
            entry["books"][row["sportsbook"]] = row
            ts = row["captured_at"]
            if entry["newest_captured_at"] is None or str(ts) > str(entry["newest_captured_at"]):
                entry["newest_captured_at"] = ts
        return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (default today UTC)")
    args = ap.parse_args()
    d = date.fromisoformat(args.date) if args.date else None
    ingest_date(d)
