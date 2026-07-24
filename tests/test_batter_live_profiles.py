"""Tests for compact terminal per-batter live profiles."""

from __future__ import annotations

from typing import Any

import pytest

from nrfi import batter_live_profiles as blp


def _game(batter: int, day: str, pa: int = 4, k: int = 1) -> dict[str, Any]:
    return {
        "schema_version": "batter_game.v1",
        "game_pk": int(day.replace("-", "")),
        "batter_id": batter,
        "official_date": day,
        "scheduled_start_at": f"{day}T23:05:00Z",
        "label_available_at": f"{day}T23:59:00Z",
        "prediction_cutoff": f"{day}T22:00:00Z",
        "batter_stand": "R",
        "plate_appearances": pa,
        "strikeouts": k,
        "walks": 1,
        "hit_by_pitch": 0,
        "hits": 1,
        "total_bases": 2,
        "on_base_events": 2,
        "swings": 12,
        "whiffs": 3,
        "contact": 9,
        "batted_balls": 3,
        "hard_hit_balls": 1,
        "barrels": 0,
        "exit_velocity_sum": 265.5,
        "ground_balls": 1,
        "fly_balls": 1,
        "line_drives": 1,
        "typed_batted_balls": 3,
        "vs_lhp_plate_appearances": 2,
        "vs_lhp_strikeouts": 1,
        "vs_lhp_on_base_events": 1,
        "vs_rhp_plate_appearances": 2,
        "vs_rhp_strikeouts": 0,
        "vs_rhp_on_base_events": 1,
    }


def _history(batter: int, n: int, start_month: int = 4) -> list[dict[str, Any]]:
    return [_game(batter, f"2024-{start_month:02d}-{i:02d}") for i in range(1, n + 1)]


def test_one_profile_per_batter_sorted() -> None:
    history = _history(500002, 10) + _history(500001, 10)
    profiles = blp.build_terminal_profiles(history)
    assert [p["batter_id"] for p in profiles] == [500001, 500002]


def test_terminal_is_deterministic() -> None:
    history = _history(500001, 30)
    a = blp.build_terminal_profiles(history)
    b = blp.build_terminal_profiles(history)
    assert a == b
    assert blp.terminal_projection_bytes(a) == blp.terminal_projection_bytes(b)


def test_career_and_window_counts() -> None:
    history = _history(500001, 25)
    (profile,) = blp.build_terminal_profiles(history)
    v = profile["feature_values"]
    assert profile["career_games"] == 25
    assert profile["career_plate_appearances"] == 100  # 25 games * 4 PA
    assert v["prior_games_career"] == 25
    assert v["prior_games_last_20"] == 20
    assert v["prior_plate_appearances_last_20"] == 80
    assert profile["profile_feature_eligible"] is True


def test_min_pa_makes_ineligible() -> None:
    history = _history(500001, 5)  # 20 PA < 50
    (profile,) = blp.build_terminal_profiles(history)
    assert profile["career_plate_appearances"] == 20
    assert profile["profile_feature_eligible"] is False


def test_refuses_locked_2025() -> None:
    history = _history(500001, 5)
    history.append(_game(500001, "2025-04-01"))
    with pytest.raises(blp.BatterLiveProfileError):
        blp.build_terminal_profiles(history)
