"""Deterministic top-of-order batter features for one game side.

Given the ordered pregame batting order (from a pre-cutoff CONFIRMED lineup
snapshot) and the compact terminal per-batter profiles, produce the aggregate
top-of-order features the first-inning model will consume: identities, profile
coverage, aggregate rate profile, handedness sequence, and platoon interaction
against the opposing probable starter's throwing hand.

This module is pure and shared by historical replay and live assembly.  It never
fabricates a profile: a batter with no eligible terminal profile is counted as
missing, aggregates are computed only over eligible top-of-order batters, and a
minimum-history indicator is raised whenever any top-of-order slot lacks an
eligible profile.  It never consumes a postgame batting order -- callers must
pass only pre-cutoff CONFIRMED lineup batters.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

TOP_OF_ORDER_SCHEMA = "batter_top_of_order.v1"
DEFAULT_TOP_N = 4

# Career-window metrics aggregated across the top-of-order batters.
_AGGREGATE_METRICS = (
    "on_base_rate",
    "strikeout_avoidance_rate",
    "walk_rate",
    "contact_rate",
    "whiff_rate",
    "hard_hit_rate",
    "barrel_rate",
)


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def _eligible_metric(profiles: list[Mapping[str, Any]], metric: str) -> float | None:
    vals = [
        float(p["feature_values"][f"{metric}_career"])
        for p in profiles
        if p["feature_values"].get(f"{metric}_career") is not None
    ]
    return _mean(vals)


def build_top_of_order_features(
    batter_ids: list[int],
    terminal_profiles: Mapping[int, Mapping[str, Any]],
    *,
    pitcher_throws: str | None,
    top_n: int = DEFAULT_TOP_N,
) -> dict[str, Any]:
    """Aggregate top-of-order features for one side; aggregates skip missing."""
    top_ids = [int(b) for b in batter_ids[:top_n]]
    present = [terminal_profiles[b] for b in top_ids if b in terminal_profiles]
    eligible = [p for p in present if p.get("profile_feature_eligible") is True]

    handedness = [
        (
            terminal_profiles[b].get("batter_stand_latest")
            if b in terminal_profiles
            else None
        )
        for b in top_ids
    ]

    platoon_obp = platoon_k = None
    if pitcher_throws in ("L", "R") and eligible:
        prefix = "vs_lhp" if pitcher_throws == "L" else "vs_rhp"
        obp = [
            float(p["feature_values"][f"{prefix}_on_base_rate_career"])
            for p in eligible
            if p["feature_values"].get(f"{prefix}_on_base_rate_career") is not None
        ]
        kk = [
            float(p["feature_values"][f"{prefix}_strikeout_rate_career"])
            for p in eligible
            if p["feature_values"].get(f"{prefix}_strikeout_rate_career") is not None
        ]
        platoon_obp = _mean(obp)
        platoon_k = _mean(kk)

    aggregates = {
        f"top_of_order_{metric}": _eligible_metric(eligible, metric)
        for metric in _AGGREGATE_METRICS
    }

    return {
        "schema_version": TOP_OF_ORDER_SCHEMA,
        "top_of_order_size": len(top_ids),
        "first_three_batter_ids": top_ids[:3],
        "first_four_batter_ids": top_ids[:4],
        "profile_present_count": len(present),
        "profile_eligible_count": len(eligible),
        "missing_profile_count": len(top_ids) - len(present),
        "profile_coverage": (
            round(len(eligible) / len(top_ids), 6) if top_ids else 0.0
        ),
        "handedness_sequence": handedness,
        "platoon_pitcher_throws": pitcher_throws,
        "platoon_on_base_rate": platoon_obp,
        "platoon_strikeout_rate": platoon_k,
        "top_of_order_minimum_history_indicator": len(eligible) < len(top_ids),
        **aggregates,
    }


def top_of_order_reason(features: Mapping[str, Any]) -> str | None:
    """Explicit reason when the top-of-order profile coverage is insufficient."""
    if features["top_of_order_size"] == 0:
        return "BATTER_IDENTITY_MISSING"
    if features["missing_profile_count"] > 0:
        return "BATTER_PROFILE_MISSING"
    if features["profile_eligible_count"] < features["top_of_order_size"]:
        return "BATTER_HISTORY_INSUFFICIENT"
    return None
