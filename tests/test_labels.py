import pandas as pd

from nrfi.labels import attach_labels, label_game


def test_yrfi_when_away_scores_even_if_home_half_missing():
    assert label_game("Final", 2, None, 1) == (1, True)


def test_yrfi_when_home_scores():
    assert label_game("Final", 0, 1, 9) == (1, True)


def test_nrfi_requires_both_zero_and_enough_innings():
    assert label_game("Final", 0, 0, 9) == (0, True)
    assert label_game("Final", 0, 0, 5) == (0, True)
    # A 4-inning "Final" linescore is too suspicious to trust a zero.
    assert label_game("Final", 0, 0, 4) == (None, False)


def test_non_final_games_are_never_labelled():
    assert label_game("Preview", 0, 0, 0) == (None, False)
    assert label_game("Live", 1, 0, 3) == (None, False)


def test_missing_linescore_is_invalid():
    assert label_game("Final", None, None, 0) == (None, False)
    assert label_game("Final", None, 0, 9) == (None, False)


def test_attach_labels_frame_roundtrip():
    frame = pd.DataFrame(
        [
            {"status": "Final", "first_inning_runs_away": 1, "first_inning_runs_home": 0, "innings_recorded": 9},
            {"status": "Final", "first_inning_runs_away": 0, "first_inning_runs_home": 0, "innings_recorded": 9},
            {
                "status": "Preview",
                "first_inning_runs_away": None,
                "first_inning_runs_home": None,
                "innings_recorded": 0,
            },
        ]
    )
    out = attach_labels(frame)
    assert out["yrfi"].tolist()[:2] == [1.0, 0.0]
    assert bool(out["label_valid"].iloc[2]) is False
    assert pd.isna(out["yrfi"].iloc[2])
