"""Fail-closed rules in ONE place (SYSTEM_DESIGN_V3 SS8.3).

Every consumer (scoring job, API, jobs) imports these instead of re-deriving
thresholds. Display contract: stale/missing => hidden/BLOCKED, never a
fabricated number.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from nrfi.config import (FEATURE_COVERAGE_MIN, HIGH_TIER_COVERAGE_MIN,
                         MIN_BOOKS_FOR_MARKET, ODDS_MAX_AGE_SECONDS)

OK, DEGRADED, BLOCKED = "OK", "DEGRADED", "BLOCKED"
GREEN, AMBER, RED = "green", "amber", "red"
PREDICTION_STALE_AFTER_S = 6 * 3600


def odds_fresh(odds_age_sec: Optional[int]) -> bool:
    return odds_age_sec is not None and 0 <= odds_age_sec <= ODDS_MAX_AGE_SECONDS


def market_usable(p_market: Optional[float], books_n: int,
                  odds_age_sec: Optional[int]) -> tuple[bool, Optional[str]]:
    """Return market usability and a stable, machine-readable reason."""
    if p_market is None or books_n < MIN_BOOKS_FOR_MARKET:
        return False, "no_market_consensus"
    if odds_age_sec is None:
        return False, "odds_age_unknown"
    if odds_age_sec < 0:
        return False, "odds_timestamp_in_future"
    if not odds_fresh(odds_age_sec):
        return False, f"odds_stale_{odds_age_sec}s"
    return True, None


def coverage_blocks(cov: float) -> Optional[str]:
    if cov < FEATURE_COVERAGE_MIN:
        return f"coverage_{cov:.2f}_below_{FEATURE_COVERAGE_MIN}"
    return None


def tier_for(status: str, lineup_confirmed: bool, cov: float,
             books_n: int) -> str:
    """Unconfirmed lineup caps at MEDIUM; only clean games reach HIGH."""
    if status != OK:
        return "LOW"
    if (lineup_confirmed and cov >= HIGH_TIER_COVERAGE_MIN
            and books_n >= MIN_BOOKS_FOR_MARKET):
        return "HIGH"
    return "MEDIUM"


def data_health(rows: list[dict], now_utc: Optional[datetime] = None) -> str:
    """Header dot. red: no scored rows or newest prediction stale >6h.
    amber: any DEGRADED/BLOCKED row. green: all rows OK and fresh."""
    now_utc = now_utc or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    else:
        now_utc = now_utc.astimezone(timezone.utc)
    if not rows:
        return RED
    newest = None
    for r in rows:
        ts = r.get("predicted_at")
        if ts is None:
            continue
        try:
            dt = ts if isinstance(ts, datetime) else datetime.fromisoformat(
                str(ts).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        newest = dt if newest is None or dt > newest else newest
    if newest is None or (now_utc - newest).total_seconds() > PREDICTION_STALE_AFTER_S:
        return RED
    if any(r.get("status") != OK for r in rows):
        return AMBER
    return GREEN


def display_fields(row: dict) -> dict:
    """FIRSTFRAME display contract: 'NRFI x% / Market y% / Edge +-z%'.
    Null model prob => BLOCKED; null market => UNAVAILABLE; edge only when
    both sides exist. 0.0 edge is a real value, not missing."""
    p, m = row.get("p_yrfi"), row.get("p_yrfi_market")
    out = {
        "nrfi_pct": None if p is None else round(100 * (1 - p), 1),
        "market_nrfi_pct": None if m is None else round(100 * (1 - m), 1),
        "edge_pct": None,
    }
    if row.get("edge") is not None:
        out["edge_pct"] = round(-100 * row["edge"], 1)  # NRFI orientation
    return out
