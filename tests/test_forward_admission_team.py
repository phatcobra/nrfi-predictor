"""Integration: team_context stage wired into the shared assembly."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from nrfi import forward_admission as fa

CUTOFF = "2026-07-20T23:05:00Z"
OBSERVED = "2026-07-20T21:00:00Z"
AS_OF = datetime(2026, 7, 20, 21, 30, tzinfo=timezone.utc)


def _tp(team_id: int, *, eligible: bool = True) -> dict[str, Any]:
    return {
        "schema_version": "team_terminal_profile.v1",
        "team_id": team_id,
        "career_games": 300 if eligible else 5,
        "team_context_feature_eligible": eligible,
        "feature_values": {
            "first_inning_scored_rate_career": 0.55,
            "first_inning_allowed_rate_career": 0.5,
        },
    }


def _lineup(side: str) -> dict[str, Any]:
    return {
        "lineup_status": "NOT_AVAILABLE",
        "lineup_observed_at": OBSERVED,
        "prediction_cutoff": CUTOFF,
        "observed_before_cutoff": True,
        "revision_count": 0,
        "batting_order_ids": [],
        "snapshot_id": None,
        "team_id": 100 if side == "away" else 200,
    }


def _lineups() -> dict[tuple[int, str], dict[str, Any]]:
    return {(1, "away"): _lineup("away"), (1, "home"): _lineup("home")}


def _assemble(team_ids: Any, team_profiles: Any, status: str) -> dict[str, Any]:
    return fa.assemble_games(
        {},
        {},
        as_of=AS_OF,
        lineup_selections=_lineups(),
        team_profiles=team_profiles,
        team_profiles_status=status,
        team_ids=team_ids,
    )[0]


def test_team_context_eligible_unified_false() -> None:
    team_ids = {(1, "away"): 100, (1, "home"): 200}
    profiles = {100: _tp(100), 200: _tp(200)}
    a = _assemble(team_ids, profiles, fa.TEAM_PROFILES_LOADED)
    e = a["eligibility"]
    assert e["team_context_eligible"] is True
    # unified stays false: park/weather/umpire/schedule remain unimplemented
    assert e["unified_feature_set_eligible"] is False
    assert e["model_probability_eligible"] is False
    away = a["sides"]["away"]
    assert away["team_id"] == 100
    assert away["team_feature_values"]["first_inning_scored_rate_career"] == 0.55
    assert a["wager_decision"] == "NO QUALIFIED WAGER"


def test_missing_team_identity() -> None:
    a = _assemble(None, {100: _tp(100), 200: _tp(200)}, fa.TEAM_PROFILES_LOADED)
    assert a["eligibility"]["team_context_eligible"] is False
    assert any("TEAM_IDENTITY_MISSING" in r for r in a["rejection_reasons"])


def test_missing_team_profile() -> None:
    team_ids = {(1, "away"): 100, (1, "home"): 200}
    a = _assemble(team_ids, {100: _tp(100)}, fa.TEAM_PROFILES_LOADED)  # 200 absent
    assert a["eligibility"]["team_context_eligible"] is False
    assert any("TEAM_PROFILE_MISSING" in r for r in a["rejection_reasons"])


def test_team_history_insufficient() -> None:
    team_ids = {(1, "away"): 100, (1, "home"): 200}
    profiles = {100: _tp(100), 200: _tp(200, eligible=False)}
    a = _assemble(team_ids, profiles, fa.TEAM_PROFILES_LOADED)
    assert a["eligibility"]["team_context_eligible"] is False
    assert any("TEAM_HISTORY_INSUFFICIENT" in r for r in a["rejection_reasons"])


def test_team_profile_load_failed_reason() -> None:
    team_ids = {(1, "away"): 100, (1, "home"): 200}
    a = _assemble(team_ids, {}, "TEAM_PROFILE_LOAD_FAILED")
    assert a["eligibility"]["team_context_eligible"] is False
    assert any("TEAM_PROFILE_LOAD_FAILED" in r for r in a["rejection_reasons"])
