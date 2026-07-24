"""Tests for the read-only per-side assembly audit."""

from __future__ import annotations

from typing import Any

from nrfi import assembly_audit as aa


def _toe(size: int, eligible: int, missing: int) -> dict[str, Any]:
    return {
        "top_of_order_size": size,
        "profile_eligible_count": eligible,
        "missing_profile_count": missing,
        "profile_coverage": round(eligible / size, 6) if size else 0.0,
        "first_three_batter_ids": [1, 2, 3],
        "first_four_batter_ids": [1, 2, 3, 4],
    }


def _side(
    *,
    lineup_status: str,
    lineup_ok: bool,
    batter_ok: bool,
    team_ok: bool,
    toe: dict[str, Any] | None,
    batter_reasons: list[str],
    team_reasons: list[str],
    feature_status: str = "NOT_READY",
    feature_reason: str | None = "PREDICTION_CUTOFF_PASSED",
    age: int | None = 7200,
) -> dict[str, Any]:
    return {
        "selection_status": "SELECTED",
        "feature_status": feature_status,
        "feature_status_reason": feature_reason,
        "lineup_status": lineup_status,
        "lineup_feature_eligible": lineup_ok,
        "lineup_snapshot_id": "snap" if lineup_ok else None,
        "lineup_observed_at": "2026-07-21T21:00:00Z",
        "lineup_age_at_cutoff_seconds": age,
        "batter_feature_eligible": batter_ok,
        "batter_stage_reasons": batter_reasons,
        "top_of_order": toe,
        "team_context_eligible": team_ok,
        "team_context_reasons": team_reasons,
        "team_id": 100,
    }


def _game(
    pk: int, away: dict[str, Any], home: dict[str, Any], **elig: Any
) -> dict[str, Any]:
    eligibility = {
        "probable_starter_eligible": False,
        "pitcher_profile_eligible": False,
        "lineup_feature_eligible": False,
        "batter_feature_eligible": False,
        "team_context_eligible": False,
        "unified_feature_set_eligible": False,
    }
    eligibility.update(elig)
    reasons = []
    if not eligibility["probable_starter_eligible"]:
        reasons.append("game:PREDICTION_CUTOFF_PASSED")
    return {
        "game_pk": pk,
        "sides": {"away": away, "home": home},
        "eligibility": eligibility,
        "before_prediction_cutoff": False,
        "snapshot_fresh": True,
        "rejection_reasons": reasons,
    }


def _package() -> dict[str, Any]:
    # game 1: fully batter-eligible
    g1_side = _side(
        lineup_status="CONFIRMED",
        lineup_ok=True,
        batter_ok=True,
        team_ok=True,
        toe=_toe(4, 4, 0),
        batter_reasons=[],
        team_reasons=[],
    )
    g1 = _game(
        1,
        g1_side,
        dict(g1_side),
        lineup_feature_eligible=True,
        batter_feature_eligible=True,
        team_context_eligible=True,
    )
    # game 2: lineup ok, batter fails on missing profile
    g2_side = _side(
        lineup_status="CONFIRMED",
        lineup_ok=True,
        batter_ok=False,
        team_ok=True,
        toe=_toe(4, 3, 1),
        batter_reasons=["BATTER_PROFILE_MISSING"],
        team_reasons=[],
    )
    g2 = _game(
        2,
        g2_side,
        dict(g2_side),
        lineup_feature_eligible=True,
        team_context_eligible=True,
    )
    # game 3: lineup ok, batter fails on history insufficient
    g3_side = _side(
        lineup_status="UPDATED",
        lineup_ok=True,
        batter_ok=False,
        team_ok=True,
        toe=_toe(4, 2, 0),
        batter_reasons=["BATTER_HISTORY_INSUFFICIENT"],
        team_reasons=[],
    )
    g3 = _game(
        3,
        g3_side,
        dict(g3_side),
        lineup_feature_eligible=True,
        team_context_eligible=True,
    )
    # game 4: no lineup
    g4_side = _side(
        lineup_status="NOT_AVAILABLE",
        lineup_ok=False,
        batter_ok=False,
        team_ok=True,
        toe=None,
        batter_reasons=["LINEUP_NOT_AVAILABLE"],
        team_reasons=[],
    )
    g4 = _game(4, g4_side, dict(g4_side), team_context_eligible=True)
    return {
        "official_date": "2026-07-21",
        "package_id": "pkg1",
        "generated_at": "2026-07-21T23:38:00Z",
        "batter_profiles_status": "BATTER_PROFILES_LOADED",
        "batter_profile_identity": "7e7fc570",
        "team_profiles_status": "TEAM_PROFILES_LOADED",
        "team_profile_identity": "c99563f7",
        "games": [g1, g2, g3, g4],
        "wager_decision": "NO QUALIFIED WAGER",
    }


def test_game_level_counters() -> None:
    c = aa.audit_package(_package())
    gl = c["game_level"]
    assert gl["games"] == 4
    assert gl["pitcher_profile_eligible_games"] == 0
    assert gl["lineup_feature_eligible_games"] == 3
    assert gl["batter_feature_eligible_games"] == 1
    assert gl["team_context_eligible_games"] == 4
    assert gl["unified_feature_set_eligible_games"] == 0


def test_side_level_lineup_and_team() -> None:
    c = aa.audit_package(_package())["side_level"]
    assert c["total_sides"] == 8
    assert c["lineup_status"]["CONFIRMED"] == 4  # games 1,2 both sides
    assert c["lineup_status"]["UPDATED"] == 2  # game 3
    assert c["lineup_status"]["NOT_AVAILABLE"] == 2  # game 4
    assert c["lineup_reason"]["LINEUP_NOT_AVAILABLE"] == 2
    assert c["team_side_eligible"]["True"] == 8


def test_batter_missing_vs_history_split() -> None:
    c = aa.audit_package(_package())["side_level"]
    # game 2 both sides -> missing; game 3 both sides -> history
    assert c["batter_missing_profile_sides"] == 2
    assert c["batter_history_insufficient_sides"] == 2
    assert c["batter_reason"]["BATTER_PROFILE_MISSING"] == 2
    assert c["batter_reason"]["BATTER_HISTORY_INSUFFICIENT"] == 2


def test_pitcher_zero_explained() -> None:
    c = aa.audit_package(_package())["pitcher_zero_explanation"]
    assert c["pitcher_profile_eligible_games"] == 0
    assert c["games_before_prediction_cutoff"] == 0
    assert c["prediction_cutoff_passed_games"] == 4


def test_batter_eligible_games_verified() -> None:
    c = aa.audit_package(_package())
    beg = c["batter_eligible_games"]
    assert len(beg) == 1
    assert beg[0]["game_pk"] == 1
    assert beg[0]["fully_verified"] is True
    assert beg[0]["sides"]["away"]["profile_coverage"] == 1.0
    assert beg[0]["sides"]["away"]["lineup_status"] == "CONFIRMED"
