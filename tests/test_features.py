"""Leakage guards and attribution correctness for the feature builder."""

import numpy as np
import pandas as pd

from nrfi.config import FeatureConfig
from nrfi.features import (
    FEATURE_COLUMNS,
    WEATHER_FEATURES,
    FeatureBuilder,
    build_slate_features,
    build_training_frame,
)


def _game_row(
    game_pk: int,
    date: str,
    fi_away=0,
    fi_home=0,
    home_pid=500001,
    away_pid=500002,
    home_tid=9001,
    away_tid=9002,
    venue_id=7001,
    status="Final",
    innings=9,
):
    return {
        "game_pk": game_pk,
        "season": int(date[:4]),
        "game_date": date,
        "game_datetime_utc": f"{date}T23:05:00Z",
        "game_type": "R",
        "status": status,
        "day_night": "night",
        "double_header": "N",
        "venue_id": venue_id,
        "venue_name": "Fixture Park",
        "home_team_id": home_tid,
        "home_team_name": "Testville Alphas",
        "away_team_id": away_tid,
        "away_team_name": "Mockington Betas",
        "home_probable_pitcher_id": home_pid,
        "home_probable_pitcher_name": "Test Pitcher Alpha",
        "away_probable_pitcher_id": away_pid,
        "away_probable_pitcher_name": "Test Pitcher Beta",
        "innings_recorded": innings,
        "first_inning_runs_away": fi_away,
        "first_inning_runs_home": fi_home,
    }


def test_home_pitcher_charged_with_away_first_inning_runs():
    builder = FeatureBuilder()
    row = _game_row(1, "2021-05-01", fi_away=3, fi_home=0)
    builder.update(row)
    state = builder.pitchers[500001]  # home pitcher
    assert state.runs.total == 3.0
    assert state.yrfi.total == 1.0
    away_state = builder.pitchers[500002]
    assert away_state.runs.total == 0.0
    assert away_state.yrfi.total == 0.0


def test_features_use_only_prior_days_never_same_day():
    games = pd.DataFrame(
        [
            _game_row(1, "2021-05-01", fi_away=5, fi_home=5),
            # Two games on 05-02: neither may see the other's result.
            _game_row(2, "2021-05-02", fi_away=4, fi_home=4),
            _game_row(3, "2021-05-02", fi_away=0, fi_home=0, home_pid=500009, away_pid=500010),
            _game_row(4, "2021-05-03", fi_away=0, fi_home=0),
        ]
    )
    frame = build_training_frame(games)
    frame = frame.set_index("game_pk")

    prior = frame.loc[1, "hp_fi_runs_allowed_shrunk"]
    # Day-1 game: no history at all -> pure prior.
    assert frame.loc[1, "hp_starts_tracked"] == 0.0
    # Day-2 game for the same pitcher sees exactly one prior start (day 1).
    assert frame.loc[2, "hp_starts_tracked"] == 1.0
    # Day-2 second game (different pitchers) must NOT see game 2's result:
    # its pitchers still have zero tracked starts.
    assert frame.loc[3, "hp_starts_tracked"] == 0.0
    # Day-3 game sees both day-1 and day-2 starts for pitcher 500001.
    assert frame.loc[4, "hp_starts_tracked"] == 2.0
    # Shrinkage: after one 5-run start, the estimate moves up from prior.
    assert frame.loc[2, "hp_fi_runs_allowed_shrunk"] > prior


def test_shrinkage_formula_matches_definition():
    cfg = FeatureConfig()
    builder = FeatureBuilder(cfg)
    builder.update(_game_row(1, "2021-05-01", fi_away=5, fi_home=0))
    feats = builder.features_for(_game_row(2, "2021-05-02"))
    half_runs_prior = builder.league_half_runs.shrunk(0.54, 500.0)
    expected = (5.0 + cfg.shrinkage_strength_pitcher * half_runs_prior) / (1.0 + cfg.shrinkage_strength_pitcher)
    assert abs(feats["hp_fi_runs_allowed_shrunk"] - expected) < 1e-9


def test_unlabelled_games_do_not_pollute_pitcher_rates_but_track_rest():
    builder = FeatureBuilder()
    row = _game_row(1, "2021-05-01", fi_away=None, fi_home=None, status="Final", innings=0)
    builder.update(row)
    state = builder.pitchers[500001]
    assert state.runs.n == 0
    assert state.last_start is not None


def test_days_rest_computed_and_capped():
    cfg = FeatureConfig()
    builder = FeatureBuilder(cfg)
    builder.update(_game_row(1, "2021-05-01"))
    feats = builder.features_for(_game_row(2, "2021-05-06"))
    assert feats["hp_days_rest"] == 5.0
    feats_late = builder.features_for(_game_row(3, "2021-09-01"))
    assert feats_late["hp_days_rest"] == cfg.max_days_rest


def test_training_frame_has_all_feature_columns():
    games = pd.DataFrame([_game_row(1, "2021-05-01"), _game_row(2, "2021-05-02")])
    frame = build_training_frame(games)
    for col in FEATURE_COLUMNS + WEATHER_FEATURES + ["yrfi", "label_valid", "game_pk"]:
        assert col in frame.columns, col


def test_slate_features_exclude_same_day_history():
    history = pd.DataFrame(
        [
            _game_row(1, "2021-05-01", fi_away=2, fi_home=1),
            # Same-day "finished" game must be ignored when featurising the slate.
            _game_row(2, "2021-05-02", fi_away=9, fi_home=9),
        ]
    )
    slate = pd.DataFrame([_game_row(3, "2021-05-02", fi_away=None, fi_home=None, status="Preview", innings=0)])
    feats = build_slate_features(history, slate)
    assert len(feats) == 1
    # Pitcher 500001 started game 1 (charged 2 runs) and game 2 (9 runs);
    # only game 1 may be visible.
    assert feats.loc[0, "hp_starts_tracked"] == 1.0


def test_missing_pitcher_yields_nan_pitcher_features():
    games = pd.DataFrame([_game_row(1, "2021-05-01", home_pid=None)])
    frame = build_training_frame(games)
    assert np.isnan(frame.loc[0, "hp_fi_runs_allowed_shrunk"])
    assert not np.isnan(frame.loc[0, "ap_fi_runs_allowed_shrunk"])
