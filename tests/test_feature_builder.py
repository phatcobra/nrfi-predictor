"""Offline correctness and leakage tests for the set-based FeatureBuilder."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nrfi.build_features import FeatureBuilder, coverage

P1 = 100


def _frames(pitcher_rows):
    return {
        "pitcher_games": pd.DataFrame(pitcher_rows),
        "pitcher_fi": pd.DataFrame(
            {
                "pitcher_id": [P1] * 3,
                "game_date": ["2024-05-01", "2024-05-07", "2024-05-13"],
                "first_inning_runs": [0, 2, 0],
                "first_inning_hits": [1, 3, 0],
                "first_inning_walks": [0, 1, 0],
            }
        ),
        "statcast_pitcher": pd.DataFrame(),
        "team_games": pd.DataFrame(
            {
                "team": ["NYY"] * 4,
                "game_date": ["2024-05-01", "2024-05-05", "2024-05-09", "2024-05-13"],
                "runs": [4, 6, 2, 8],
                "hits": [8, 10, 5, 12],
                "at_bats": [33, 35, 30, 36],
                "total_bases": [14, 18, 7, 22],
                "times_on_base": [11, 13, 7, 15],
                "plate_appearances": [38, 40, 34, 41],
                "woba_num": [10.0, 12.0, 6.0, 14.0],
                "woba_den": [38, 40, 34, 41],
            }
        ),
        "team_fi": pd.DataFrame(
            {
                "team": ["NYY"] * 3,
                "game_date": ["2024-05-01", "2024-05-05", "2024-05-09"],
                "first_inning_runs": [1, 0, 0],
            }
        ),
        "batters": pd.DataFrame(),
        "parks": pd.DataFrame(
            {
                "venue_id": [7],
                "runs_factor": [1.10],
                "hr_factor": [1.05],
                "hits_factor": [1.02],
            }
        ),
    }


def _pitcher_rows():
    return {
        "pitcher_id": [P1] * 3,
        "game_date": ["2024-05-01", "2024-05-07", "2024-05-13"],
        "earned_runs": [2, 4, 1],
        "runs_allowed": [2, 5, 1],
        "hits": [5, 8, 3],
        "walks": [1, 3, 0],
        "strikeouts": [7, 4, 9],
        "innings_pitched": [6.0, 5.0, 7.0],
        "opponent_team": ["BOS", "TOR", "BAL"],
    }


def _game(date="2024-05-20"):
    return {
        "game_id": "g1",
        "game_date": date,
        "away_pitcher_id": P1,
        "home_pitcher_id": None,
        "away_team": "NYY",
        "home_team": "BOS",
        "venue_id": 7,
        "is_dome": False,
        "weather": None,
        "lineups": None,
    }


def _build(frames, game):
    builder = FeatureBuilder(sf=None, raw_frames=frames)
    builder.prepare(max_date=game["game_date"])
    return builder.build_game(game)


def test_ratio_of_sums_not_avg_of_ratios():
    features = _build(_frames(_pitcher_rows()), _game())
    assert features["away_p_career_era"] == pytest.approx(7 * 9 / 18.0)
    per_game_avg = np.mean([2 * 9 / 6, 4 * 9 / 5, 1 * 9 / 7])
    assert abs(features["away_p_career_era"] - per_game_avg) > 0.3
    assert features["away_p_fi_ra9"] == pytest.approx(6.0)
    assert features["away_p_fi_nrfi_rate"] == pytest.approx(2 / 3)


def test_leakage_strictly_before_as_of():
    rows = _pitcher_rows()
    rows = {
        key: values + [extra]
        for (key, values), extra in zip(
            rows.items(),
            [P1, "2024-05-20", 0, 0, 0, 0, 15, 9.0, "BOS"],
        )
    }
    with_same_day = _build(_frames(rows), _game("2024-05-20"))
    without_same_day = _build(_frames(_pitcher_rows()), _game("2024-05-20"))
    for name in without_same_day:
        left, right = with_same_day[name], without_same_day[name]
        assert (left == right) or (np.isnan(left) and np.isnan(right)), (
            f"leak via {name}"
        )


def test_missing_is_nan_and_flagged_never_default():
    features = _build(_frames(_pitcher_rows()), _game())
    assert features["home_p_missing"] == 1.0
    assert all(
        np.isnan(value)
        for name, value in features.items()
        if name.startswith("home_p_") and not name.endswith("_missing")
    )
    assert np.isnan(features["away_p_avg_exit_velo"])
    assert np.isnan(features["temp_f"]) and features["weather_missing"] == 1.0


def test_null_first_inning_outcomes_do_not_enter_rate_denominators():
    frames = _frames(_pitcher_rows())
    frames["pitcher_fi"] = frames["pitcher_fi"].copy()
    frames["pitcher_fi"]["first_inning_runs"] = [0, np.nan, 1]
    frames["team_fi"] = frames["team_fi"].copy()
    frames["team_fi"]["first_inning_runs"] = [1, np.nan, 0]

    features = _build(frames, _game())

    assert features["away_p_fi_games"] == pytest.approx(2.0)
    assert features["away_p_fi_runs_rate"] == pytest.approx(0.5)
    assert features["away_p_fi_nrfi_rate"] == pytest.approx(0.5)
    assert features["away_t_fi_rpg"] == pytest.approx(0.5)
    assert features["away_t_fi_scoring_pct"] == pytest.approx(0.5)


def test_rest_days_and_windows():
    features = _build(_frames(_pitcher_rows()), _game("2024-05-20"))
    assert features["away_p_rest_days"] == pytest.approx(7.0)
    assert features["away_p_7d_starts"] == pytest.approx(1.0)
    assert features["away_p_365d_starts"] == pytest.approx(3.0)


def test_coverage_math():
    features = {"a": 1.0, "b": float("nan"), "a_missing": 0.0}
    assert coverage(features) == pytest.approx(0.5)


def test_park_and_team_features():
    features = _build(_frames(_pitcher_rows()), _game())
    assert features["park_runs_factor"] == pytest.approx(1.10)
    assert features["away_t_season_avg"] == pytest.approx(35 / 134)
    assert features["away_t_fi_scoring_pct"] == pytest.approx(1 / 3)
