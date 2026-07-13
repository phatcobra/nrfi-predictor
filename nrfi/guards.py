"""Central fail-closed status and display rules."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from nrfi.config import (
    FEATURE_COVERAGE_MIN,
    HIGH_TIER_COVERAGE_MIN,
    MIN_BOOKS_FOR_MARKET,
    ODDS_MAX_AGE_SECONDS,
)

OK, DEGRADED, BLOCKED = "OK", "DEGRADED", "BLOCKED"
GREEN, AMBER, RED = "green", "amber", "red"
PREDICTION_STALE_AFTER_S = 6 * 3600


def odds_fresh(odds_age_sec: Optional[int]) -> bool:
    return (
        odds_age_sec is not None
        and 0 <= odds_age_sec <= ODDS_MAX_AGE_SECONDS
    )


def market_usable(p_market: Optional[float], books_n: int,
                  odds_age_sec: Optional[int]) -> tuple[bool, Optional[str]]:
    """Return market usability and one stable machine-readable reason."""
    if odds_age_sec is None:
        return False, "odds_age_unknown"
    if odds_age_sec < 0:
        return False, "odds_timestamp_in_future"
    if not odds_fresh(odds_age_sec):
        return False, f"odds_stale_{odds_age_sec}s"
    if p_market is None or books_n < MIN_BOOKS_FOR_MARKET:
        return False, "no_market_consensus"
    return True, None


def coverage_blocks(coverage_value: float) -> Optional[str]:
    if coverage_value < FEATURE_COVERAGE_MIN:
        return (
            f"coverage_{coverage_value:.2f}_below_{FEATURE_COVERAGE_MIN}")
    return None


def tier_for(status: str, lineup_confirmed: bool, coverage_value: float,
             books_n: int) -> str:
    """Unconfirmed lineups cap the tier at medium."""
    if status != OK:
        return "LOW"
    if (
        lineup_confirmed
        and coverage_value >= HIGH_TIER_COVERAGE_MIN
        and books_n >= MIN_BOOKS_FOR_MARKET
    ):
        return "HIGH"
    return "MEDIUM"


def data_health(rows: list[dict], now_utc: Optional[datetime] = None) -> str:
    """Return red for stale/absent output, amber for degraded rows, else green."""
    now_utc = now_utc or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    else:
        now_utc = now_utc.astimezone(timezone.utc)
    if not rows:
        return RED

    newest = None
    for row in rows:
        timestamp = row.get("predicted_at")
        if timestamp is None:
            continue
        try:
            parsed = (
                timestamp if isinstance(timestamp, datetime)
                else datetime.fromisoformat(
                    str(timestamp).replace("Z", "+00:00"))
            )
        except (TypeError, ValueError):
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            parsed = parsed.astimezone(timezone.utc)
        newest = parsed if newest is None or parsed > newest else newest

    if (
        newest is None
        or (now_utc - newest).total_seconds() > PREDICTION_STALE_AFTER_S
    ):
        return RED
    if any(row.get("status") != OK for row in rows):
        return AMBER
    return GREEN


def display_fields(row: dict) -> dict:
    """Orient stored YRFI probabilities as NRFI percentages for display."""
    model_probability = row.get("p_yrfi")
    market_probability = row.get("p_yrfi_market")
    output = {
        "nrfi_pct": (
            None if model_probability is None
            else round(100 * (1 - model_probability), 1)
        ),
        "market_nrfi_pct": (
            None if market_probability is None
            else round(100 * (1 - market_probability), 1)
        ),
        "edge_pct": None,
    }
    if row.get("edge") is not None:
        output["edge_pct"] = round(-100 * row["edge"], 1)
    return output
