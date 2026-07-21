"""Fail-closed lineup + batter eligibility decision for one game side.

Pure decision core for Phase 6 staged eligibility.  Given the selected pre-cutoff
lineup snapshot for a side (or its absence), the compact terminal batter
profiles, and the opposing probable starter's hand, it returns
``lineup_feature_eligible`` / ``batter_feature_eligible`` and an explicit ordered
reason list.  It never treats a postgame or after-cutoff lineup as eligible and
never fabricates missing history.  The unified feature set stays false regardless
-- team/park/weather/umpire/schedule domains remain unimplemented -- so this
module can only ever gate the two batter-domain stages, never a probability.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from nrfi.batter_top_of_order import build_top_of_order_features, top_of_order_reason

# Lineup reason codes.
LINEUP_NOT_AVAILABLE = "LINEUP_NOT_AVAILABLE"
LINEUP_AFTER_CUTOFF = "LINEUP_AFTER_CUTOFF"
LINEUP_STALE = "LINEUP_STALE"
LINEUP_PROJECTED_ONLY = "LINEUP_PROJECTED_ONLY"
LINEUP_WITHDRAWN = "LINEUP_WITHDRAWN"
HISTORICAL_LINEUP_TIMING_UNAVAILABLE = "HISTORICAL_LINEUP_TIMING_UNAVAILABLE"
# Batter reason codes (BATTER_IDENTITY_MISSING / BATTER_PROFILE_MISSING /
# BATTER_HISTORY_INSUFFICIENT come from top_of_order_reason; plus:)
BATTER_FEATURE_ERROR = "BATTER_FEATURE_ERROR"

STATUS_CONFIRMED = "CONFIRMED"
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"
STATUS_PROJECTED = "PROJECTED"
STATUS_UPDATED = "UPDATED"
STATUS_WITHDRAWN = "WITHDRAWN"

DEFAULT_LINEUP_FRESHNESS_SECONDS = 43_200  # 12h: lineups post a few hours pre-game


def _parse_utc(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def evaluate_side_eligibility(
    selection: Mapping[str, Any] | None,
    terminal_profiles: Mapping[int, Mapping[str, Any]],
    *,
    pitcher_throws: str | None,
    as_of: datetime,
    historical: bool = False,
    freshness_limit_seconds: int = DEFAULT_LINEUP_FRESHNESS_SECONDS,
) -> dict[str, Any]:
    """Decide lineup + batter eligibility for one side with explicit reasons."""
    reasons: list[str] = []
    result: dict[str, Any] = {
        "lineup_feature_eligible": False,
        "batter_feature_eligible": False,
        "lineup_status": None,
        "lineup_observed_at": None,
        "lineup_age_at_cutoff_seconds": None,
        "lineup_revision_count": None,
        "confirmed_indicator": False,
        "top_of_order": None,
        "reasons": reasons,
    }

    if historical:
        reasons.append(HISTORICAL_LINEUP_TIMING_UNAVAILABLE)
        return result
    if selection is None:
        reasons.append(LINEUP_NOT_AVAILABLE)
        return result

    status = str(selection.get("lineup_status") or STATUS_NOT_AVAILABLE)
    result["lineup_status"] = status
    result["lineup_observed_at"] = selection.get("lineup_observed_at")
    result["lineup_revision_count"] = selection.get("revision_count")

    cutoff = _parse_utc(selection["prediction_cutoff"])
    observed_at = selection.get("lineup_observed_at")
    observed = _parse_utc(observed_at) if observed_at else None
    if observed is not None:
        result["lineup_age_at_cutoff_seconds"] = int(
            (cutoff - observed).total_seconds()
        )

    if status == STATUS_WITHDRAWN:
        reasons.append(LINEUP_WITHDRAWN)
        return result
    if status == STATUS_PROJECTED:
        reasons.append(LINEUP_PROJECTED_ONLY)
        return result
    if status not in (STATUS_CONFIRMED, STATUS_UPDATED):
        reasons.append(LINEUP_NOT_AVAILABLE)
        return result
    result["confirmed_indicator"] = True

    if (
        observed is None
        or observed >= cutoff
        or not selection.get("observed_before_cutoff", False)
    ):
        reasons.append(LINEUP_AFTER_CUTOFF)
        return result
    freshness = (as_of - observed).total_seconds()
    if freshness < 0 or freshness > freshness_limit_seconds:
        reasons.append(LINEUP_STALE)
        return result

    # Lineup stage passes.
    result["lineup_feature_eligible"] = True

    batting_order = [int(b) for b in selection.get("batting_order_ids", [])]
    try:
        features = build_top_of_order_features(
            batting_order, terminal_profiles, pitcher_throws=pitcher_throws
        )
    except Exception:  # pragma: no cover - defensive; feature build must not crash
        reasons.append(BATTER_FEATURE_ERROR)
        return result
    result["top_of_order"] = features
    reason = top_of_order_reason(features)
    if reason is not None:
        reasons.append(reason)
        return result
    result["batter_feature_eligible"] = True
    return result
