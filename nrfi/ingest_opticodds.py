"""OpticOdds NRFI/YRFI odds ingestion (fail-closed).

Rules:
  - The market is matched by EXACT market id (OPTIC_FI_TOTAL_MARKET_ID) and a
    numeric line == 0.5 check.
  - No-vig probabilities are computed per book at ingest time.
  - Snapshots are immutable and deduped on snapshot_id (MERGE upsert).
  - Provider timestamps are normalized to timezone-aware UTC.
  - Missing market id or API key => the job raises. Nothing is guessed.
"""
from __future__ import annotations

import hashlib
import math
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


def _as_utc(value: object) -> datetime:
    """Normalize a provider/Snowflake timestamp to aware UTC."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    else:
        raise ValueError("timestamp must be datetime or ISO-8601 text")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def american_to_prob(american: float) -> float:
    american = float(american)
    if not math.isfinite(american) or american == 0:
        raise ValueError("American odds must be finite and non-zero")
    if american > 0:
        return 100.0 / (american + 100.0)
    return abs(american) / (abs(american) + 100.0)


def novig_pair(p_a_raw: float, p_b_raw: float) -> tuple[float, float]:
    if not all(math.isfinite(float(p)) and float(p) > 0 for p in (p_a_raw, p_b_raw)):
        raise ValueError("raw probabilities must be finite and positive")
    total = float(p_a_raw) + float(p_b_raw)
    return (float(p_a_raw) / total, float(p_b_raw) / total)


def _require_config() -> None:
    if not OPTIC_API_KEY:
        raise RuntimeError("OPTIC_API_KEY not set - odds ingest fails closed")
    if not OPTIC_FI_TOTAL_MARKET_ID:
        raise RuntimeError(
            "OPTIC_FI_TOTAL_MARKET_ID not set. A human must pin the exact "
            "OpticOdds market id for the MLB 1st-inning total; see config.py."
        )


def _get(endpoint: str, params: list[tuple[str, str]]) -> dict:
    from tenacity import retry, stop_after_attempt, wait_exponential

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(min=2, max=20),
           reraise=True)
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
        payload = resp.json()
        if not isinstance(payload, dict):
            raise ValueError(f"OpticOdds {endpoint} returned non-object JSON")
        return payload


def fetch_mlb_fixtures(target_date: date | None = None) -> list[dict]:
    target_date = target_date or datetime.now(timezone.utc).date()
    data = _get("fixtures", [("sport", "baseball_mlb"),
                             ("date", target_date.isoformat()),
                             ("status", "scheduled")])
    fixtures = data.get("data", [])
    if not isinstance(fixtures, list):
        raise ValueError("OpticOdds fixtures payload missing list data")
    logger.info(f"{len(fixtures)} MLB fixtures on {target_date}")
    return fixtures


def fetch_fi_total_odds(fixture_id: str) -> list[dict]:
    """Return one validated row per sportsbook for the exact FI total market."""
    params = [("fixture_id", fixture_id), ("market", OPTIC_FI_TOTAL_MARKET_ID)]
    params += [("sportsbook", b) for b in NRFI_SPORTSBOOKS]
    data = _get("fixtures/odds", params)

    rows: list[dict] = []
    for book_data in data.get("data", []):
        book = book_data.get("sportsbook")
        if not book:
            continue
        for market in book_data.get("markets", []):
            if str(market.get("id", market.get("market_id", ""))) != OPTIC_FI_TOTAL_MARKET_ID:
                continue
            try:
                line = float(market.get("line"))
            except (TypeError, ValueError):
                continue
            if not math.isclose(line, 0.5, rel_tol=0.0, abs_tol=1e-9):
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
            if captured is None:
                logger.warning(f"skipping {fixture_id}/{book}: provider timestamp missing")
                continue
            try:
                captured_at = _as_utc(captured)
                yrfi_price_f = float(yrfi_price)
                nrfi_price_f = float(nrfi_price)
                p_yrfi_raw = american_to_prob(yrfi_price_f)
                p_nrfi_raw = american_to_prob(nrfi_price_f)
                p_yrfi_nv, p_nrfi_nv = novig_pair(p_yrfi_raw, p_nrfi_raw)
            except (TypeError, ValueError, OverflowError) as exc:
                logger.warning(f"skipping invalid odds row {fixture_id}/{book}: {exc}")
                continue

            snapshot_id = hashlib.sha1(
                f"{fixture_id}|{book}|{captured_at.isoformat()}".encode()
            ).hexdigest()
            rows.append({
                "snapshot_id": snapshot_id,
                "fixture_id": fixture_id,
                "sportsbook": str(book),
                "market_id": OPTIC_FI_TOTAL_MARKET_ID,
                "line": 0.5,
                "yrfi_american": yrfi_price_f,
                "nrfi_american": nrfi_price_f,
                "yrfi_prob_raw": p_yrfi_raw,
                "nrfi_prob_raw": p_nrfi_raw,
                "yrfi_prob_novig": p_yrfi_nv,
                "nrfi_prob_novig": p_nrfi_nv,
                "captured_at": captured_at.isoformat(),
            })
            break
    return rows


def ingest_date(target_date: date | None = None) -> int:
    """Fetch and upsert all valid snapshots for a date."""
    _require_config()
    sf = SnowflakeLoader()
    fixtures = fetch_mlb_fixtures(target_date)
    total = 0
    with sentry_sdk.start_transaction(op="task", name="ingest_opticodds_nrfi"):
        for fixture in fixtures:
            fixture_id = str(fixture.get("id") or "")
            if not fixture_id:
                logger.warning("skipping fixture without id")
                continue
            rows = fetch_fi_total_odds(fixture_id)
            for row in rows:
                row.update({
                    "game_date": fixture.get("start_date"),
                    "home_team": fixture.get("home_team"),
                    "away_team": fixture.get("away_team"),
                    "start_time": fixture.get("start_time"),
                })
            if rows:
                sf.merge_upsert(ODDS_TABLE, rows, key_cols=["snapshot_id"])
                total += len(rows)
            time.sleep(0.25)
    logger.info(f"ingested {total} odds snapshots for {len(fixtures)} fixtures")
    return total


class OpticOddsIngester:
    """Latest per-book odds keyed by exact home/away matchup."""

    def __init__(self) -> None:
        self.sf = SnowflakeLoader()

    def refresh(self, target_date: date | None = None) -> int:
        return ingest_date(target_date)

    def get_nrfi_odds(self, target_date: str) -> dict:
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
            try:
                captured_at = _as_utc(row.get("captured_at"))
            except (TypeError, ValueError, OverflowError):
                logger.warning(f"invalid stored captured_at for {key}/{row.get('sportsbook')}")
                continue
            newest = entry["newest_captured_at"]
            if newest is None or captured_at > newest:
                entry["newest_captured_at"] = captured_at
        return out


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="YYYY-MM-DD (default today UTC)")
    args = parser.parse_args()
    requested_date = date.fromisoformat(args.date) if args.date else None
    ingest_date(requested_date)
