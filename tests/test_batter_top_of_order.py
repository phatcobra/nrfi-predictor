"""Tests for the deterministic top-of-order feature builder."""

from __future__ import annotations

from typing import Any

from nrfi import batter_top_of_order as toe


def _profile(
    batter_id: int, *, eligible: bool = True, stand: str = "R", base: float = 0.3
) -> dict[str, Any]:
    fv = {
        "on_base_rate_career": base,
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
        "batter_stand_latest": stand,
        "feature_values": fv,
    }


def _profiles(*profs: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {p["batter_id"]: p for p in profs}


def test_full_coverage_aggregates() -> None:
    profs = _profiles(
        _profile(1, base=0.30, stand="L"),
        _profile(2, base=0.40, stand="R"),
        _profile(3, base=0.20, stand="L"),
        _profile(4, base=0.10, stand="S"),
    )
    f = toe.build_top_of_order_features([1, 2, 3, 4], profs, pitcher_throws="R")
    assert f["missing_profile_count"] == 0
    assert f["profile_eligible_count"] == 4
    assert f["profile_coverage"] == 1.0
    assert f["top_of_order_minimum_history_indicator"] is False
    assert f["first_three_batter_ids"] == [1, 2, 3]
    assert f["first_four_batter_ids"] == [1, 2, 3, 4]
    assert f["handedness_sequence"] == ["L", "R", "L", "S"]
    assert f["top_of_order_on_base_rate"] == 0.25  # mean(0.3,0.4,0.2,0.1)
    # pitcher throws R -> vs_rhp platoon metrics
    assert f["platoon_on_base_rate"] == 0.31
    assert f["platoon_strikeout_rate"] == 0.24
    assert toe.top_of_order_reason(f) is None


def test_platoon_uses_lhp_when_pitcher_left() -> None:
    profs = _profiles(_profile(1), _profile(2), _profile(3), _profile(4))
    f = toe.build_top_of_order_features([1, 2, 3, 4], profs, pitcher_throws="L")
    assert f["platoon_on_base_rate"] == 0.34
    assert f["platoon_strikeout_rate"] == 0.2


def test_missing_profile_flagged() -> None:
    profs = _profiles(_profile(1), _profile(2), _profile(3))  # id 4 absent
    f = toe.build_top_of_order_features([1, 2, 3, 4], profs, pitcher_throws="R")
    assert f["missing_profile_count"] == 1
    assert f["profile_present_count"] == 3
    assert f["top_of_order_minimum_history_indicator"] is True
    assert toe.top_of_order_reason(f) == "BATTER_PROFILE_MISSING"


def test_ineligible_profile_flagged() -> None:
    profs = _profiles(
        _profile(1), _profile(2), _profile(3), _profile(4, eligible=False)
    )
    f = toe.build_top_of_order_features([1, 2, 3, 4], profs, pitcher_throws="R")
    assert f["missing_profile_count"] == 0
    assert f["profile_eligible_count"] == 3
    assert f["top_of_order_minimum_history_indicator"] is True
    assert toe.top_of_order_reason(f) == "BATTER_HISTORY_INSUFFICIENT"


def test_empty_lineup() -> None:
    f = toe.build_top_of_order_features([], {}, pitcher_throws="R")
    assert f["top_of_order_size"] == 0
    assert f["top_of_order_on_base_rate"] is None
    assert toe.top_of_order_reason(f) == "BATTER_IDENTITY_MISSING"


def test_deterministic() -> None:
    profs = _profiles(_profile(1), _profile(2), _profile(3), _profile(4))
    a = toe.build_top_of_order_features([1, 2, 3, 4], profs, pitcher_throws="L")
    b = toe.build_top_of_order_features([1, 2, 3, 4], profs, pitcher_throws="L")
    assert a == b
