import json

import numpy as np
import pandas as pd
from test_features import _game_row
from test_model import synthetic_feature_frame

from nrfi.config import MISSING_PROBABLE_NOTE
from nrfi.model import fit_model
from nrfi.predict import (
    PREDICTION_COLUMNS,
    predict_slate,
    predictions_to_records,
    render_predictions_json,
    render_predictions_markdown,
    write_prediction_outputs,
)


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


def test_predictions_to_records_are_json_safe_and_complementary():
    model = _fitted_model()
    history = pd.DataFrame([_game_row(1, "2021-05-01")])
    slate = pd.DataFrame(
        [
            _game_row(10, "2021-06-01", status="Preview", innings=0),
            _game_row(11, "2021-06-01", status="Preview", innings=0, away_pid=None),
        ]
    )
    out = predict_slate(history, slate, model)
    records = predictions_to_records(out)
    assert len(records) == 2
    # Round-trips through JSON with no NaN/numpy types leaking out.
    reloaded = json.loads(json.dumps(records))
    predicted = [r for r in reloaded if r["p_yrfi"] is not None]
    assert len(predicted) == 1
    row = predicted[0]
    assert abs(row["p_yrfi"] + row["p_nrfi"] - 1.0) < 1e-6
    missing = [r for r in reloaded if r["p_yrfi"] is None][0]
    assert missing["note"] == MISSING_PROBABLE_NOTE
    assert missing["p_nrfi"] is None


def test_render_predictions_json_shape():
    model = _fitted_model()
    history = pd.DataFrame([_game_row(1, "2021-05-01")])
    slate = pd.DataFrame([_game_row(10, "2021-06-01", status="Preview", innings=0)])
    out = predict_slate(history, slate, model)
    payload = render_predictions_json(out, "2021-06-01", model)
    assert payload["date"] == "2021-06-01"
    assert payload["n_games"] == 1
    assert payload["n_predicted"] == 1
    assert payload["games"][0]["away_team_name"] == "Mockington Betas"


def test_write_prediction_outputs_creates_manifest(tmp_path):
    model = _fitted_model()
    history = pd.DataFrame([_game_row(1, "2021-05-01")])
    slate = pd.DataFrame([_game_row(10, "2021-06-01", status="Preview", innings=0)])
    out = predict_slate(history, slate, model)

    predictions_dir = tmp_path / "predictions"
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    pd.DataFrame(
        [
            {"season": "ALL", "n_games": 100, "yrfi_base_rate": 0.5, "log_loss_model": 0.69,
             "log_loss_baseline": 0.693, "brier_model": 0.25, "brier_baseline": 0.2501,
             "brier_skill_score": -0.004, "roc_auc": 0.504},
        ]
    ).to_csv(reports_dir / "backtest_metrics.csv", index=False)
    pd.DataFrame(
        [
            {"bin": "(0.4, 0.5]", "n_games": 60, "mean_predicted": 0.47,
             "observed_yrfi_rate": 0.49, "calibration_gap": 0.02},
        ]
    ).to_csv(reports_dir / "calibration_table.csv", index=False)

    write_prediction_outputs(out, "2021-06-01", model, predictions_dir, reports_dir)

    manifest = json.loads((predictions_dir / "index.json").read_text())
    assert manifest["latest_date"] == "2021-06-01"
    assert manifest["dates"] == ["2021-06-01"]
    assert manifest["backtest"]["roc_auc"] == 0.504
    assert len(manifest["calibration"]) == 1
    assert (predictions_dir / "2021-06-01.json").exists()
    assert (predictions_dir / "latest.json").exists()
