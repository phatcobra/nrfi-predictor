"""Tests for Context Foundation V1 shared deterministic features."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nrfi import context_features as cf
from nrfi.pitcher_statcast import canonical_json_bytes

REFERENCE = Path("docs/context_foundation_v1/venue_reference.json")


def _game(
    pk: int,
    date: str,
    *,
    venue: int,
    away_id: int = 100,
    home_id: int = 200,
    away_runs: int = 1,
    home_runs: int = 0,
    away_starter: int | None = 500,
    home_starter: int | None = 600,
    dh_code: str = "N",
    game_number: int = 1,
    start_hour: str = "23:05:00",
) -> dict[str, Any]:
    return {
        "game_type": "R",
        "game_pk": pk,
        "official_date": date,
        "game_number": game_number,
        "doubleheader_code": dh_code,
        "scheduled_start_at": f"{date}T{start_hour}Z",
        "time_semantics": {"label_available_at": f"{date}T23:59:00Z"},
        "venue": {"venue_id": venue},
        "away_team": {"team_id": away_id},
        "home_team": {"team_id": home_id},
        "actual_starters": {
            "away": {"player_id": away_starter},
            "home": {"player_id": home_starter},
        },
        "first_inning": {
            "completed": True,
            "away_runs": away_runs,
            "home_runs": home_runs,
        },
    }


def _cut(pks: list[int], dates: list[str]) -> dict[int, str]:
    return {pk: f"{d}T22:00:00Z" for pk, d in zip(pks, dates, strict=True)}


def _reference() -> dict[int, dict[str, Any]]:
    return cf.load_venue_reference(REFERENCE)


# --------------------------------------------------------------------------- #
def test_venue_reference_complete_and_geometry() -> None:
    ref = _reference()
    assert len(ref) == 44
    fenway = ref[3]
    assert fenway["utc_offset_standard_hours"] == -5
    # Fenway (Boston) -> Dodger Stadium (LA): ~2600 statute miles.
    miles = cf.haversine_miles(
        fenway["latitude"],
        fenway["longitude"],
        ref[22]["latitude"],
        ref[22]["longitude"],
    )
    assert 2500 <= miles <= 2700
    # 1pm ET start = day; 8pm ET start = night (standard offset, no DST).
    assert cf.day_night("2024-04-01T17:05:00Z", -5) == "day"
    assert cf.day_night("2024-04-02T00:05:00Z", -5) == "night"


def test_two_side_schedule_rows_per_game() -> None:
    games = [_game(1, "2024-04-01", venue=3)]
    rows = cf.build_side_schedule_log(games, _cut([1], ["2024-04-01"]))
    assert len(rows) == 2
    away = next(r for r in rows if not r["is_home"])
    home = next(r for r in rows if r["is_home"])
    assert away["starter_id"] == 500 and home["starter_id"] == 600
    assert away["first_inning_runs_for"] == 1 and away["first_inning_runs_against"] == 0


def test_schedule_travel_rest_distance_tz() -> None:
    ref = _reference()
    # Team 100 plays away at Fenway (v3), then away at Dodger (v22) two days later.
    prior = cf.build_side_schedule_log(
        [_game(1, "2024-04-01", venue=3)], _cut([1], ["2024-04-01"])
    )
    prior_away = [r for r in prior if r["team_id"] == 100]
    target = {
        "team_id": 100,
        "is_home": False,
        "official_date": "2024-04-03",
        "scheduled_start_at": "2024-04-03T23:05:00Z",
        "venue_id": 22,
        "doubleheader_code": "N",
        "game_number": 1,
        "starter_id": 500,
    }
    feats = cf.compute_schedule_travel_features(prior_away, target, ref)
    assert feats["rest_days"] == 2
    assert 2500 <= feats["travel_miles"] <= 2700
    assert feats["tz_shift_hours"] == -3.0
    assert feats["trip_kind"] == "road_trip"
    assert feats["prior_venue_id"] == 3


def test_road_trip_streak_and_congestion() -> None:
    ref = _reference()
    # Three consecutive away games for team 100 (road trip of length 3).
    games = [
        _game(1, "2024-04-01", venue=3, away_id=100, home_id=200),
        _game(2, "2024-04-02", venue=3, away_id=100, home_id=200),
        _game(3, "2024-04-03", venue=3, away_id=100, home_id=200),
    ]
    rows = cf.build_side_schedule_log(games, _cut([1, 2, 3], ["2024-04-01"] * 3))
    away = [r for r in rows if r["team_id"] == 100]
    away.sort(key=lambda r: (r["official_date"], r["game_pk"]))
    feats = cf.compute_schedule_travel_features(away[:2], away[2], ref)
    assert feats["trip_game_index"] == 3
    assert feats["trip_is_first_game"] is False
    assert feats["games_prior_3d"] == 2


def test_doubleheader_same_day_zero_rest() -> None:
    ref = _reference()
    g1 = {
        "team_id": 100,
        "is_home": True,
        "official_date": "2024-04-01",
        "scheduled_start_at": "2024-04-01T17:05:00Z",
        "venue_id": 3,
        "doubleheader_code": "S",
        "game_number": 1,
        "starter_id": 600,
    }
    g2 = dict(g1)
    g2["game_number"] = 2
    g2["scheduled_start_at"] = "2024-04-01T23:05:00Z"
    feats = cf.compute_schedule_travel_features([g1], g2, ref)
    assert feats["rest_days"] == 0
    assert feats["doubleheader"] is True
    assert feats["travel_miles"] == 0.0


def test_starter_workload_rest_and_window() -> None:
    prior = [
        {"official_date": "2024-04-01", "starter_id": 500},
        {"official_date": "2024-04-06", "starter_id": 500},
    ]
    target = {"official_date": "2024-04-11", "starter_id": 500}
    wl = cf.compute_starter_workload(prior, target)
    assert wl["starter_rest_days"] == 5
    assert wl["starter_starts_prior_30d"] == 2
    assert wl["workload_feature_eligible"] is True
    # No prior starts -> ineligible, rest None.
    first = cf.compute_starter_workload([], target)
    assert first["workload_feature_eligible"] is False
    assert first["starter_rest_days"] is None


def _venue3_series(n: int) -> tuple[list[dict[str, Any]], dict[int, str]]:
    dates = [f"2024-04-{i:02d}" for i in range(1, n + 1)]
    games = [
        _game(i + 1, dates[i], venue=3, away_runs=1, home_runs=1) for i in range(n)
    ]
    return games, _cut([g["game_pk"] for g in games], dates)


def test_strict_prior_park_factor_threshold_and_value() -> None:
    games, cutoffs = _venue3_series(31)
    rows = cf.build_side_schedule_log(games, cutoffs)
    park = cf.strict_prior_park_factors(rows)
    # 30th game (index pk=30) has 29 strict-prior games -> below threshold.
    assert park[30]["park_prior_games_at_venue"] == 29
    assert park[30]["park_context_feature_eligible"] is False
    # 31st game has 30 strict-prior games -> eligible; all totals are 2 runs.
    assert park[31]["park_prior_games_at_venue"] == 30
    assert park[31]["park_context_feature_eligible"] is True
    assert park[31]["park_factor"] == pytest.approx(1.0)


def test_terminal_park_factor_and_2025_guard() -> None:
    games, cutoffs = _venue3_series(31)
    rows = cf.build_side_schedule_log(games, cutoffs)
    terminal = cf.build_terminal_park_factors(rows)
    assert len(terminal) == 1
    prof = terminal[0]
    assert prof["venue_id"] == 3
    assert prof["prior_games_at_venue"] == 31
    assert prof["park_context_feature_eligible"] is True
    # Defense-in-depth: a 2025 row reaching the terminal builder must hard-fail
    # (build_side_schedule_log already filters the locked season upstream).
    bad_row = {
        "game_pk": 999,
        "team_id": 100,
        "is_home": True,
        "official_date": "2025-04-01",
        "season": 2025,
        "scheduled_start_at": "2025-04-01T23:05:00Z",
        "label_available_at": "2025-04-01T23:59:00Z",
        "prediction_cutoff": "2025-04-01T22:00:00Z",
        "venue_id": 3,
        "doubleheader_code": "N",
        "game_number": 1,
        "starter_id": 600,
        "first_inning_runs_for": 1,
        "first_inning_runs_against": 1,
    }
    with pytest.raises(cf.ContextFeatureError):
        cf.build_terminal_park_factors([bad_row])


def test_context_feature_set_deterministic_and_nonnegative() -> None:
    ref = _reference()
    games, cutoffs = _venue3_series(10)
    rows = cf.build_side_schedule_log(games, cutoffs)
    first = cf.build_context_feature_set(rows, ref)
    second = cf.build_context_feature_set(rows, ref)
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    for snap in first:
        rest = snap["feature_values"]["rest_days"]
        assert rest is None or rest >= 0
        srest = snap["feature_values"]["starter_rest_days"]
        assert srest is None or srest >= 0


def test_load_games_refuses_2025(tmp_path: Path) -> None:
    games_dir = tmp_path
    (games_dir / "features.jsonl").write_text(
        '{"game_pk": 1, "prediction_cutoff": "2025-04-01T22:00:00Z"}\n',
        encoding="utf-8",
    )
    (games_dir / "normalized_games.jsonl").write_text(
        '{"game_pk": 1, "official_date": "2025-04-01"}\n', encoding="utf-8"
    )
    with pytest.raises(cf.ContextFeatureError):
        cf.load_games(games_dir)
