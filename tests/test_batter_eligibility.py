"""Tests for the fail-closed lineup + batter eligibility evaluator."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from nrfi import batter_eligibility as el

CUTOFF = "2026-07-20T23:05:00Z"
OBSERVED_OK = "2026-07-20T21:00:00Z"
AS_OF = datetime(2026, 7, 20, 21, 30, tzinfo=timezone.utc)


def _profile(batter_id: int, *, eligible: bool = True) -> dict[str, Any]:
    fv = {
        "on_base_rate_career": 0.32,
        "strikeout_avoidance_rate_career": 0.8,
        "walk_rate_career": 0.09,
        "contact_rate_career": 0.75,
        "whiff_rate_career": 0.25,
        "hard_hit_rate_career": 0.4,
        "barrel_rate_career": 0.08,
        "vs_lhp_on_base_rate_career": 0.34,
        "vs_lhp_strikeout_rate_career": 0.2,
        "vs_rhp_on_base_rate_career": 0.31,
        "vs_rhp_strikeout_rate_career": 0.24,
    }
    return {
        "batter_id": batter_id,
        "profile_feature_eligible": eligible,
        "batter_stand_latest": "R",
        "feature_values": fv,
    }


def _profiles(*ids: int) -> dict[int, dict[str, Any]]:
    return {i: _profile(i) for i in ids}


def _selection(**over: Any) -> dict[str, Any]:
    base = {
        "lineup_status": "CONFIRMED",
        "lineup_observed_at": OBSERVED_OK,
        "prediction_cutoff": CUTOFF,
        "observed_before_cutoff": True,
        "revision_count": 1,
        "batting_order_ids": [1, 2, 3, 4],
    }
    base.update(over)
    return base


def test_historical_is_unavailable() -> None:
    r = el.evaluate_side_eligibility(
        _selection(),
        _profiles(1, 2, 3, 4),
        pitcher_throws="R",
        as_of=AS_OF,
        historical=True,
    )
    assert r["lineup_feature_eligible"] is False
    assert r["batter_feature_eligible"] is False
    assert el.HISTORICAL_LINEUP_TIMING_UNAVAILABLE in r["reasons"]


def test_no_selection_not_available() -> None:
    r = el.evaluate_side_eligibility(None, {}, pitcher_throws="R", as_of=AS_OF)
    assert r["reasons"] == [el.LINEUP_NOT_AVAILABLE]


def test_confirmed_fresh_full_coverage_eligible() -> None:
    r = el.evaluate_side_eligibility(
        _selection(), _profiles(1, 2, 3, 4), pitcher_throws="R", as_of=AS_OF
    )
    assert r["lineup_feature_eligible"] is True
    assert r["batter_feature_eligible"] is True
    assert r["reasons"] == []
    assert r["confirmed_indicator"] is True
    assert r["top_of_order"]["first_four_batter_ids"] == [1, 2, 3, 4]


def test_after_cutoff_blocks_lineup() -> None:
    r = el.evaluate_side_eligibility(
        _selection(
            lineup_observed_at="2026-07-20T23:30:00Z", observed_before_cutoff=False
        ),
        _profiles(1, 2, 3, 4),
        pitcher_throws="R",
        as_of=datetime(2026, 7, 20, 23, 40, tzinfo=timezone.utc),
    )
    assert r["lineup_feature_eligible"] is False
    assert el.LINEUP_AFTER_CUTOFF in r["reasons"]


def test_stale_lineup_blocked() -> None:
    r = el.evaluate_side_eligibility(
        _selection(lineup_observed_at="2026-07-19T00:00:00Z"),
        _profiles(1, 2, 3, 4),
        pitcher_throws="R",
        as_of=AS_OF,
    )
    assert r["lineup_feature_eligible"] is False
    assert el.LINEUP_STALE in r["reasons"]


def test_withdrawn_and_projected() -> None:
    w = el.evaluate_side_eligibility(
        _selection(lineup_status="WITHDRAWN"), {}, pitcher_throws="R", as_of=AS_OF
    )
    assert el.LINEUP_WITHDRAWN in w["reasons"]
    p = el.evaluate_side_eligibility(
        _selection(lineup_status="PROJECTED"), {}, pitcher_throws="R", as_of=AS_OF
    )
    assert el.LINEUP_PROJECTED_ONLY in p["reasons"]


def test_lineup_ok_but_batter_profile_missing() -> None:
    r = el.evaluate_side_eligibility(
        _selection(), _profiles(1, 2, 3), pitcher_throws="R", as_of=AS_OF
    )  # id 4 has no profile
    assert r["lineup_feature_eligible"] is True
    assert r["batter_feature_eligible"] is False
    assert "BATTER_PROFILE_MISSING" in r["reasons"]
