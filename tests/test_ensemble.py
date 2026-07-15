"""Offline tests: purged folds, OOF stack, Venn-ABERS, shrinkage, save/load."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nrfi.ensemble import (
    StackedEnsemble,
    n_eff_for_game,
    purged_walk_forward_folds,
    shrink_to_venue,
)
from nrfi.venn_abers import VennAbersCalibrator

RNG = np.random.default_rng(7)


def _synthetic(n=1200):
    dates = pd.Series(pd.date_range("2023-04-01", periods=n, freq="6h"))
    x1 = RNG.normal(size=n)
    x2 = RNG.normal(size=n)
    noise = RNG.normal(scale=0.5, size=n)
    logit = 0.9 * x1 - 0.7 * x2 + noise
    y = (RNG.uniform(size=n) < 1 / (1 + np.exp(-logit))).astype(int)
    X = np.column_stack([x1, x2, RNG.normal(size=n), RNG.normal(size=n)])
    # inject some NaNs (missing features must be handled, not filled with 0)
    X[RNG.uniform(size=X.shape) < 0.03] = np.nan
    return X, y, dates


def test_purged_folds_respect_gap_and_expansion():
    _, _, dates = _synthetic(600)
    folds = list(
        purged_walk_forward_folds(dates, n_folds=4, purge_days=7, min_train=50)
    )
    assert len(folds) >= 2
    prev_tr_max = -1
    for tr, va in folds:
        assert tr.max() < va.min()  # walk-forward
        gap = dates.iloc[va.min()] - dates.iloc[tr.max()]
        assert gap >= pd.Timedelta(days=7)  # purge gap
        assert tr.max() >= prev_tr_max  # expanding
        prev_tr_max = tr.max()


def test_stack_fits_beats_baseline_and_reports():
    X, y, dates = _synthetic()
    ens = StackedEnsemble(purge_days=7, n_folds=4)
    report = ens.fit(X, y, dates, [f"f{i}" for i in range(X.shape[1])])
    assert set(report["members"]) == {"lgbm", "enet"}
    assert report["stack"]["logloss"] < report["baseline_constant"]["logloss"]
    assert report["gates_passed"] is True
    # OOF scores exist only where folds validated
    assert np.isnan(ens._oof_scores[0])  # earliest rows: train-only
    assert np.isfinite(ens._oof_scores[ens._oof_mask]).all()
    # full-fit members can score new rows
    p = ens.raw_scores(X[:10])
    assert p.shape == (10,) and np.isfinite(p).all() and ((p >= 0) & (p <= 1)).all()


def test_venn_abers_calibrates_and_bounds():
    n = 800
    s = RNG.uniform(0.05, 0.95, size=n)
    y = (RNG.uniform(size=n) < s).astype(int)  # scores are true probabilities
    va = VennAbersCalibrator().fit(s, y)
    test_s = np.array([0.2, 0.5, 0.8])
    iv = va.predict_interval(test_s)
    p = va.predict(test_s)
    assert (iv[:, 0] <= iv[:, 1] + 1e-9).all()
    assert ((p >= 0) & (p <= 1)).all()
    assert np.all(np.diff(p) > 0)  # monotone in score
    assert np.abs(p - test_s).max() < 0.1  # near-identity when calibrated
    assert np.isnan(va.predict(np.array([np.nan]))[0])  # NaN passthrough


def test_venn_abers_refuses_tiny_calibration_set():
    with pytest.raises(ValueError):
        VennAbersCalibrator().fit(np.array([0.5] * 10), np.array([1] * 10))


def test_shrinkage_math_exact():
    # (n*p + k*v)/(n+k)
    assert shrink_to_venue(0.60, 0.50, n_eff=20.0, k=20.0) == pytest.approx(0.55)
    assert shrink_to_venue(0.60, 0.50, n_eff=0.0) == pytest.approx(0.50)  # cold: venue
    assert shrink_to_venue(0.60, None, n_eff=0.0) == pytest.approx(
        0.60
    )  # no venue: untouched


def test_n_eff_uses_min_fi_games_and_coverage():
    f = {"away_p_fi_games": 40.0, "home_p_fi_games": 10.0}
    assert n_eff_for_game(f, 0.9) == pytest.approx(9.0)
    assert n_eff_for_game({"away_p_fi_games": float("nan")}, 1.0) == 0.0


def test_trainer_save_load_roundtrip(tmp_path):
    from nrfi.train import NFRIModelTrainer

    X, y, dates = _synthetic(800)
    kept = pd.DataFrame({"venue_id": RNG.integers(1, 5, size=len(y))})
    tr = NFRIModelTrainer()
    tr.feature_names = [f"f{i}" for i in range(X.shape[1])]
    report = tr.train(X, y, dates, kept)
    p_before = tr.predict_proba(X[:5])
    v = tr.save_model(str(tmp_path), metrics=report)
    tr2 = NFRIModelTrainer()
    tr2.load_model(str(tmp_path), v)
    p_after = tr2.predict_proba(X[:5])
    assert np.allclose(p_before, p_after)
    assert tr2.venue_yrfi_rates == tr.venue_yrfi_rates
