from test_model import synthetic_feature_frame

from nrfi.backtest import calibration_table, render_backtest_report, walk_forward_backtest
from nrfi.config import TrainConfig


def test_walk_forward_backtest_produces_out_of_time_metrics():
    frame = synthetic_feature_frame(n=6000, seasons=(2017, 2018, 2019, 2020, 2021, 2022))
    metrics, pooled, calibration = walk_forward_backtest(frame, TrainConfig())

    assert "ALL" in metrics["season"].tolist()
    test_seasons = [s for s in metrics["season"] if s != "ALL"]
    assert len(test_seasons) >= 2
    pooled_row = metrics[metrics["season"] == "ALL"].iloc[0]
    assert pooled_row["n_games"] == len(pooled)
    # With a genuine signal feature the model must beat climatology.
    assert pooled_row["brier_skill_score"] > 0
    assert pooled_row["roc_auc"] > 0.55
    # No test row may come from a season used to train its model:
    # walk-forward guarantees test season > every train season by protocol;
    # sanity-check the pooled predictions only contain test seasons.
    assert set(pooled["season"].unique()) == set(float(s) for s in test_seasons)

    assert not calibration.empty
    assert abs(calibration["calibration_gap"].mean()) < 0.15


def test_render_backtest_report_contains_key_sections():
    frame = synthetic_feature_frame(n=6000, seasons=(2017, 2018, 2019, 2020, 2021, 2022))
    metrics, _, calibration = walk_forward_backtest(frame, TrainConfig())
    report = render_backtest_report(metrics, calibration, {"trained_at_utc": "test", "base_rate_yrfi": 0.5})
    assert "Walk-Forward Backtest" in report
    assert "Per-season metrics" in report
    assert "Calibration" in report


def test_calibration_table_gap_definition():
    import numpy as np

    rng = np.random.default_rng(3)
    p = rng.uniform(0.2, 0.8, 2000)
    y = (rng.random(2000) < p).astype(float)
    table = calibration_table(y, p)
    assert table["n_games"].sum() == 2000
    assert (table["calibration_gap"].abs() < 0.12).all()
