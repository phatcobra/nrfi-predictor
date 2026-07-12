import numpy as np
import pandas as pd
from test_features import _game_row
from test_model import synthetic_feature_frame

from nrfi.config import MISSING_PROBABLE_NOTE
from nrfi.model import fit_model
from nrfi.predict import PREDICTION_COLUMNS, predict_slate, render_predictions_markdown


def _fitted_model():
    return fit_model(synthetic_feature_frame(), None)


def test_predict_slate_outputs_complementary_probabilities():
    model = _fitted_model()
    history = pd.DataFrame([_game_row(1, "2021-05-01", fi_away=1, fi_home=0)])
    slate = pd.DataFrame([_game_row(10, "2021-06-01", fi_away=None, fi_home=None, status="Preview", innings=0)])
    out = predict_slate(history, slate, model)
    assert list(out.columns) == PREDICTION_COLUMNS
    assert len(out) == 1
    row = out.iloc[0]
    assert 0.0 < row["p_yrfi"] < 1.0
    assert abs(row["p_yrfi"] + row["p_nrfi"] - 1.0) < 1e-6
    assert row["note"] == ""


def test_predict_slate_refuses_games_without_probable_pitchers():
    model = _fitted_model()
    history = pd.DataFrame([_game_row(1, "2021-05-01")])
    slate = pd.DataFrame(
        [
            _game_row(10, "2021-06-01", status="Preview", innings=0),
            _game_row(11, "2021-06-01", status="Preview", innings=0, away_pid=None),
        ]
    )
    out = predict_slate(history, slate, model)
    with_pitchers = out[out["game_pk"] == 10].iloc[0]
    without = out[out["game_pk"] == 11].iloc[0]
    assert not np.isnan(with_pitchers["p_yrfi"])
    assert np.isnan(without["p_yrfi"]) and np.isnan(without["p_nrfi"])
    assert without["note"] == MISSING_PROBABLE_NOTE


def test_predict_slate_empty_slate():
    model = _fitted_model()
    history = pd.DataFrame([_game_row(1, "2021-05-01")])
    out = predict_slate(history, pd.DataFrame(columns=history.columns), model)
    assert out.empty
    md = render_predictions_markdown(out, "2021-06-01")
    assert "No games" in md


def test_markdown_report_lists_games():
    model = _fitted_model()
    history = pd.DataFrame([_game_row(1, "2021-05-01")])
    slate = pd.DataFrame([_game_row(10, "2021-06-01", status="Preview", innings=0)])
    out = predict_slate(history, slate, model)
    md = render_predictions_markdown(out, "2021-06-01")
    assert "Testville Alphas" in md
    assert "p_nrfi" in md
