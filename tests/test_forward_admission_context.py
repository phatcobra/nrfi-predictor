"""Tests for the park/schedule/workload context stages in the assembly."""

from __future__ import annotations

from pathlib import Path

from nrfi import context_features as cf
from nrfi import forward_admission as fa

REFERENCE = cf.load_venue_reference(
    Path("docs/context_foundation_v1/venue_reference.json")
)

_PARK_PROFILES = {
    3: {
        "park_context_feature_eligible": True,
        "park_factor": 1.14,
        "first_inning_runs_per_game": 1.23,
    },
    17: {
        "park_context_feature_eligible": False,
        "park_factor": None,
        "first_inning_runs_per_game": 0.9,
    },
}


def test_park_context_eligible_when_venue_and_profile_present() -> None:
    result = fa._park_context(3, _PARK_PROFILES, fa.CONTEXT_PROFILES_LOADED, REFERENCE)
    assert result["park_context_eligible"] is True
    assert result["park_factor"] == 1.14
    assert result["altitude_ft"] == REFERENCE[3]["altitude_ft"]
    assert result["park_context_reasons"] == []


def test_park_context_history_insufficient() -> None:
    result = fa._park_context(17, _PARK_PROFILES, fa.CONTEXT_PROFILES_LOADED, REFERENCE)
    assert result["park_context_eligible"] is False
    assert fa.PARK_HISTORY_INSUFFICIENT in result["park_context_reasons"]


def test_park_context_profile_missing() -> None:
    result = fa._park_context(2, _PARK_PROFILES, fa.CONTEXT_PROFILES_LOADED, REFERENCE)
    assert result["park_context_eligible"] is False
    assert fa.PARK_PROFILE_MISSING in result["park_context_reasons"]


def test_park_context_venue_unknown() -> None:
    result = fa._park_context(
        999999, _PARK_PROFILES, fa.CONTEXT_PROFILES_LOADED, REFERENCE
    )
    assert result["park_context_eligible"] is False
    assert fa.PARK_VENUE_UNKNOWN in result["park_context_reasons"]


def test_schedule_travel_window_unavailable_fails_closed() -> None:
    result = fa._schedule_travel_game(1, None, REFERENCE)
    assert result["schedule_travel_eligible"] is False
    assert result["schedule_travel_reasons"] == [fa.SCHEDULE_WINDOW_UNAVAILABLE]


def test_schedule_travel_eligible_with_both_windows() -> None:
    def window(side: str) -> dict[str, object]:
        return {
            "prior_side_games": [
                {
                    "is_home": False,
                    "official_date": "2026-07-19",
                    "scheduled_start_at": "2026-07-19T23:05:00Z",
                    "venue_id": 3,
                }
            ],
            "target": {
                "team_id": 100 if side == "away" else 200,
                "is_home": side == "home",
                "official_date": "2026-07-21",
                "scheduled_start_at": "2026-07-21T23:05:00Z",
                "venue_id": 22,
                "doubleheader_code": "N",
                "game_number": 1,
            },
        }

    windows = {(1, "away"): window("away"), (1, "home"): window("home")}
    result = fa._schedule_travel_game(1, windows, REFERENCE)
    assert result["schedule_travel_eligible"] is True
    assert result["schedule_travel_sides"]["away"]["features"]["rest_days"] == 2


def test_workload_window_unavailable_fails_closed() -> None:
    result = fa._workload_game(1, None)
    assert result["workload_eligible"] is False
    assert result["workload_reasons"] == [fa.WORKLOAD_WINDOW_UNAVAILABLE]


def test_workload_eligible_with_both_windows() -> None:
    def window() -> dict[str, object]:
        return {
            "prior_starts": [{"official_date": "2026-07-16", "starter_id": 5}],
            "target": {"official_date": "2026-07-21", "starter_id": 5},
        }

    windows = {(1, "away"): window(), (1, "home"): window()}
    result = fa._workload_game(1, windows)
    assert result["workload_eligible"] is True
    assert result["workload_sides"]["away"]["workload"]["starter_rest_days"] == 5


def test_build_package_reports_context_counts() -> None:
    assembly = {
        "eligibility": {
            "pitcher_profile_eligible": False,
            "lineup_feature_eligible": False,
            "batter_feature_eligible": False,
            "team_context_eligible": False,
            "park_context_eligible": True,
            "schedule_travel_eligible": False,
            "workload_eligible": False,
            "unified_feature_set_eligible": False,
        }
    }
    from datetime import datetime, timezone

    package = fa.build_assembly_package(
        "2026-07-21",
        [],
        [assembly],
        generated_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
        profiles_status="PROFILES_LOADED",
        context_profiles_status=fa.CONTEXT_PROFILES_LOADED,
        context_profile_identity="abc",
    )
    assert package["park_context_eligible_games"] == 1
    assert package["schedule_travel_eligible_games"] == 0
    assert package["workload_eligible_games"] == 0
    assert package["context_profiles_status"] == fa.CONTEXT_PROFILES_LOADED
    assert package["unified_feature_set_eligible_games"] == 0
