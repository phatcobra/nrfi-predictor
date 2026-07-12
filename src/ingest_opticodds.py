"""OpticOdds MLB NRFI/YRFI odds ingestion.

Fetches real-time NRFI/YRFI lines from 200+ sportsbooks via OpticOdds API,
stores in Snowflake, compares vs model predictions for +EV detection.

Supports:
  - MLB fixture discovery (today's games)
  - Multi-sportsbook odds fetching (DraftKings, FanDuel, BetMGM, Caesars, Pinnacle)
  - 1st inning total (NRFI/YRFI) market extraction
  - Line movement tracking
  - Storage in Snowflake for historical analysis
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import requests
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

import sentry_sdk
from src.config import OPTIC_API_KEY, OPTIC_BASE_URL, NRFI_SPORTSBOOKS
from src.snowflake_loader import get_snowflake_engine


# ---------------------------------------------------------------------------
# OpticOdds API helpers
# ---------------------------------------------------------------------------

@retry(stop=stop_after_attempt(5), wait=wait_exponential(min=2, max=30))
def _optic_get(endpoint: str, params: dict) -> dict:
    """GET from OpticOdds API with retry logic."""
    url = f"{OPTIC_BASE_URL}/{endpoint}"
    headers = {"x-api-key": OPTIC_API_KEY}
    
    with sentry_sdk.start_span(op="http", description=f"OpticOdds {endpoint}"):
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        
        if resp.status_code == 429:
            logger.warning("OpticOdds rate limit; sleeping 60s")
            time.sleep(60)
        
        resp.raise_for_status()
        return resp.json()


def american_to_prob(american_odds: int | float) -> float:
    """Convert American odds to implied probability."""
    if american_odds >= 0:
        return 100 / (american_odds + 100)
    else:
        return abs(american_odds) / (abs(american_odds) + 100)


def american_to_decimal(american_odds: int | float) -> float:
    """Convert American odds to decimal."""
    if american_odds >= 0:
        return (american_odds / 100) + 1
    else:
        return (100 / abs(american_odds)) + 1


# ---------------------------------------------------------------------------
# Fixture discovery
# ---------------------------------------------------------------------------

def fetch_mlb_fixtures(target_date: date | None = None) -> list[dict]:
    """Get MLB fixtures for a specific date from OpticOdds.
    
    Args:
        target_date: Date to fetch fixtures for (defaults to today)
    
    Returns:
        List of fixture dicts with id, home_team, away_team, start_time
    """
    if target_date is None:
        target_date = date.today()
    
    params = {
        "sport": "baseball_mlb",
        "date": target_date.isoformat(),
        "status": "scheduled",  # Upcoming/live games
    }
    
    try:
        data = _optic_get("fixtures", params)
        fixtures = data.get("data", [])
        logger.info(f"Found {len(fixtures)} MLB fixtures on {target_date}")
        return fixtures
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.error(f"Failed to fetch fixtures: {e}")
        return []


# ---------------------------------------------------------------------------
# NRFI/YRFI odds fetching
# ---------------------------------------------------------------------------

def fetch_nrfi_odds(fixture_id: str, sportsbooks: list[str] | None = None) -> dict:
    """Fetch NRFI/YRFI odds for a specific game from multiple sportsbooks.
    
    Args:
        fixture_id: OpticOdds fixture ID
        sportsbooks: List of sportsbook names (defaults to config.NRFI_SPORTSBOOKS)
    
    Returns:
        Dict mapping sportsbook -> {nrfi_american, yrfi_american, nrfi_prob, yrfi_prob, ...}
    """
    if sportsbooks is None:
        sportsbooks = NRFI_SPORTSBOOKS
    
    # Build params for OpticOdds API
    # Note: Multiple sportsbooks must be passed as repeated params
    params = {
        "fixture_id": fixture_id,
        "market": "1st_inning_total",  # May need adjustment based on OpticOdds naming
    }
    
    # Add multiple sportsbooks (OpticOdds expects ?sportsbook=X&sportsbook=Y)
    url_params = "&".join([f"sportsbook={book}" for book in sportsbooks])
    params_str = f"fixture_id={fixture_id}&market=1st_inning_total&{url_params}"
    
    try:
        # Manual URL construction for multiple sportsbooks
        url = f"{OPTIC_BASE_URL}/fixtures/odds?{params_str}"
        headers = {"x-api-key": OPTIC_API_KEY}
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        odds_by_book = {}
        
        for book_data in data.get("data", []):
            book_name = book_data.get("sportsbook")
            markets = book_data.get("markets", [])
            
            # Find 1st inning 0.5 total market
            for market in markets:
                market_name = market.get("name", "").lower()
                line = market.get("line")
                
                # Check if this is the 0.5 line (NRFI/YRFI)
                if "0.5" in str(line) or "first" in market_name:
                    outcomes = market.get("outcomes", [])
                    
                    nrfi_price = None
                    yrfi_price = None
                    
                    for outcome in outcomes:
                        outcome_name = outcome.get("name", "").lower()
                        price = outcome.get("price")
                        
                        if "under" in outcome_name:  # NRFI = Under 0.5
                            nrfi_price = price
                        elif "over" in outcome_name:  # YRFI = Over 0.5
                            yrfi_price = price
                    
                    if nrfi_price is not None and yrfi_price is not None:
                        odds_by_book[book_name] = {
                            "nrfi_american": nrfi_price,
                            "yrfi_american": yrfi_price,
                            "nrfi_prob": american_to_prob(nrfi_price),
                            "yrfi_prob": american_to_prob(yrfi_price),
                            "nrfi_decimal": american_to_decimal(nrfi_price),
                            "yrfi_decimal": american_to_decimal(yrfi_price),
                            "timestamp": datetime.utcnow().isoformat(),
                        }
                        break  # Found the market, move to next book
        
        return odds_by_book
    
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.error(f"Failed to fetch NRFI odds for fixture {fixture_id}: {e}")
        return {}


# ---------------------------------------------------------------------------
# Storage to Snowflake
# ---------------------------------------------------------------------------

def store_nrfi_odds(fixture_data: dict, odds_data: dict) -> None:
    """Store NRFI/YRFI odds in Snowflake.
    
    Args:
        fixture_data: Dict with fixture metadata (id, home_team, away_team, start_time)
        odds_data: Dict from fetch_nrfi_odds() mapping sportsbook -> odds
    """
    engine = get_snowflake_engine()
    
    rows = []
    for sportsbook, odds in odds_data.items():
        row = {
            "fixture_id": fixture_data.get("id"),
            "game_date": fixture_data.get("start_date"),
            "start_time": fixture_data.get("start_time"),
            "home_team": fixture_data.get("home_team"),
            "away_team": fixture_data.get("away_team"),
            "sportsbook": sportsbook,
            **odds,
        }
        rows.append(row)
    
    if rows:
        df = pd.DataFrame(rows)
        df.to_sql(
            "optic_nrfi_odds",
            engine,
            if_exists="append",
            index=False,
            chunksize=100,
        )
        logger.info(f"Stored NRFI odds from {len(rows)} sportsbooks for {fixture_data.get('away_team')} @ {fixture_data.get('home_team')}")


# ---------------------------------------------------------------------------
# Main daily ingestion
# ---------------------------------------------------------------------------

def ingest_today_nrfi_odds() -> pd.DataFrame:
    """Fetch and store today's NRFI/YRFI odds from OpticOdds.
    
    Returns:
        DataFrame with all odds for analysis
    """
    with sentry_sdk.start_transaction(op="task", name="ingest_opticodds_nrfi"):
        fixtures = fetch_mlb_fixtures()
        
        if not fixtures:
            logger.warning("No MLB fixtures found for today")
            return pd.DataFrame()
        
        all_odds = []
        
        for fixture in fixtures:
            fixture_id = fixture.get("id")
            home_team = fixture.get("home_team")
            away_team = fixture.get("away_team")
            
            logger.info(f"Fetching NRFI odds: {away_team} @ {home_team}")
            
            odds = fetch_nrfi_odds(fixture_id)
            
            if odds:
                store_nrfi_odds(fixture, odds)
                
                # Collect for return DataFrame
                for book, book_odds in odds.items():
                    all_odds.append({
                        "fixture_id": fixture_id,
                        "home_team": home_team,
                        "away_team": away_team,
                        "sportsbook": book,
                        **book_odds,
                    })
            
            time.sleep(0.5)  # Rate limit courtesy
        
        logger.info(f"Ingested NRFI odds for {len(fixtures)} games from OpticOdds")
        return pd.DataFrame(all_odds)


def get_best_nrfi_odds(fixture_id: str) -> dict:
    """Find best available NRFI and YRFI odds across all sportsbooks.
    
    Args:
        fixture_id: OpticOdds fixture ID
    
    Returns:
        Dict with best_nrfi_book, best_nrfi_odds, best_yrfi_book, best_yrfi_odds
    """
    odds = fetch_nrfi_odds(fixture_id)
    
    if not odds:
        return {}
    
    best_nrfi = max(odds.items(), key=lambda x: x[1]["nrfi_decimal"])
    best_yrfi = max(odds.items(), key=lambda x: x[1]["yrfi_decimal"])
    
    return {
        "best_nrfi_book": best_nrfi[0],
        "best_nrfi_american": best_nrfi[1]["nrfi_american"],
        "best_nrfi_decimal": best_nrfi[1]["nrfi_decimal"],
        "best_yrfi_book": best_yrfi[0],
        "best_yrfi_american": best_yrfi[1]["yrfi_american"],
        "best_yrfi_decimal": best_yrfi[1]["yrfi_decimal"],
    }


if __name__ == "__main__":
    import argparse
    
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (defaults to today)")
    args = ap.parse_args()
    
    if args.date:
        target = date.fromisoformat(args.date)
        fixtures = fetch_mlb_fixtures(target)
    else:
        df = ingest_today_nrfi_odds()
        print(df)
