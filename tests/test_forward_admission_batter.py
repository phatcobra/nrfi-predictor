"""Integration: lineup + batter stages wired into the shared assembly."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from nrfi import forward_admission as fa

CUTOFF = "2026-07-20T23:05:00Z"
OBSERVED = "2026-07-20T21:00:00Z"
AS_OF = datetime(2026, 7, 20, 21, 30, tzinfo=timezone.utc)


def _tp(batter_id: int, *, eligible: bool = True) -> dict[str, Any]:
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


def _sel(
    side: str,
    order: list[int],
    *,
    observed: str = OBSERVED,
    before: bool = True,
    status: str = "CONFIRMED",
) -> dict[str, Any]:
    return {
        "schema_version": "lineup_selection.v1",
        "game_pk": 1,
        "side": side,
        "team_id": 100 if side == "away" else 200,
        "snapshot_id": f"snap-{side}",
        "capture_key": f"key-{side}",
        "capture_version_id": f"ver-{side}",
        "lineup_observed_at": observed,
        "source_publication_time": None,
        "prediction_cutoff": CUTOFF,
        "observed_before_cutoff": before,
        "lineup_status": status,
        "revision_count": 1,
        "previous_snapshot_ids": [],
        "batting_order_ids": order,
        "batting_order": [{"player_id": p} for p in order],
    }


def _lineups(order: list[int], **kw: Any) -> dict[tuple[int, str], dict[str, Any]]:
    return {
        (1, "away"): _sel("away", order, **kw),
        (1, "home"): _sel("home", order, **kw),
    }


def _assemble(lineups: Any, profiles: Any, status: str) -> dict[str, Any]:
    return fa.assemble_games(
        {},
        {},
        as_of=AS_OF,
        lineup_selections=lineups,
        terminal_profiles=profiles,
        batter_profiles_status=status,
    )[0]


def test_batter_stage_eligible_unified_false() -> None:
    order = [1, 2, 3, 4]
    profiles = {i: _tp(i) for i in order}
    a = _assemble(_lineups(order), profiles, fa.BATTER_PROFILES_LOADED)
    e = a["eligibility"]
    assert e["lineup_feature_eligible"] is True
    assert e["batter_feature_eligible"] is True
    # unified stays false: team/park/weather/umpire/schedule remain unimplemented
    assert e["unified_feature_set_eligible"] is False
    assert e["model_probability_eligible"] is False
    toe = a["sides"]["away"]["top_of_order"]
    assert toe["first_four_batter_ids"] == [1, 2, 3, 4]
    assert toe["profile_coverage"] == 1.0
    assert a["sides"]["away"]["lineup_snapshot_id"] == "snap-away"
    assert a["wager_decision"] == "NO QUALIFIED WAGER"


def test_missing_batter_profile_fails_closed() -> None:
    order = [1, 2, 3, 4]
    profiles = {1: _tp(1), 2: _tp(2), 3: _tp(3)}  # batter 4 absent
    a = _assemble(_lineups(order), profiles, fa.BATTER_PROFILES_LOADED)
    assert a["eligibility"]["lineup_feature_eligible"] is True
    assert a["eligibility"]["batter_feature_eligible"] is False
    assert any("BATTER_PROFILE_MISSING" in r for r in a["rejection_reasons"])
    assert a["eligibility"]["unified_feature_set_eligible"] is False


def test_profile_artifact_load_failed_reason() -> None:
    order = [1, 2, 3, 4]
    a = _assemble(_lineups(order), {}, "BATTER_PROFILE_LOAD_FAILED")
    assert a["eligibility"]["batter_feature_eligible"] is False
    assert any("BATTER_PROFILE_LOAD_FAILED" in r for r in a["rejection_reasons"])


def test_after_cutoff_lineup_blocks_stage() -> None:
    order = [1, 2, 3, 4]
    profiles = {i: _tp(i) for i in order}
    lineups = _lineups(order, observed="2026-07-20T23:30:00Z", before=False)
    a = fa.assemble_games(
        {},
        {},
        as_of=datetime(2026, 7, 20, 23, 40, tzinfo=timezone.utc),
        lineup_selections=lineups,
        terminal_profiles=profiles,
        batter_profiles_status=fa.BATTER_PROFILES_LOADED,
    )[0]
    assert a["eligibility"]["lineup_feature_eligible"] is False
    assert any("LINEUP_AFTER_CUTOFF" in r for r in a["rejection_reasons"])
