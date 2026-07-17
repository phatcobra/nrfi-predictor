"""Offline tests: purged folds, OOF stack, Venn-ABERS, shrinkage, save/load."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from nrfi.ensemble import (
    GATE_BRIER_MIN,
    GATE_LOGLOSS_MIN,
    LGB_NUM_BOOST_ROUND,
    LGBMMember,
    StackedEnsemble,
    _probability_gate,
    n_eff_for_game,
    purged_walk_forward_folds,
    shrink_to_venue,
)
from nrfi.venn_abers import VennAbersCalibrator

RNG = np.random.default_rng(7)


def _synthetic(n=1200, seed=7):
    rng = np.random.default_rng(seed)
    dates = pd.Series(pd.date_range("2023-04-01", periods=n, freq="6h"))
    x1 = rng.normal(size=n)
    x2 = rng.normal(size=n)
    noise = rng.normal(scale=0.5, size=n)
    logit = 0.9 * x1 - 0.7 * x2 + noise
    y = (rng.uniform(size=n) < 1 / (1 + np.exp(-logit))).astype(int)
    X = np.column_stack([x1, x2, rng.normal(size=n), rng.normal(size=n)])
    # inject some NaNs (missing features must be handled, not filled with 0)
    X[rng.uniform(size=X.shape) < 0.03] = np.nan
    return X, y, dates


@pytest.fixture(scope="module")
def fitted_stack():
    X, y, dates = _synthetic()
    ensemble = StackedEnsemble(purge_days=7, n_folds=4)
    report = ensemble.fit(X, y, dates, [f"f{i}" for i in range(X.shape[1])])
    return X, y, dates, ensemble, report


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


def test_stack_reports_temporal_gate_on_common_rows(fitted_stack):
    _, _, _, ens, report = fitted_stack
    assert set(report["members"]) == {"lgbm", "enet"}
    assert report["shipped_members"] == ["lgbm", "enet"]
    assert report["ablation"] == {}
    assert report["stack"]["n"] == report["baseline_constant"]["n"]
    assert report["stack"]["n"] == int(ens._oof_mask.sum())
    improvements = report["gate_improvements"]
    assert improvements["logloss"] == pytest.approx(
        report["baseline_constant"]["logloss"] - report["stack"]["logloss"]
    )
    assert improvements["brier"] == pytest.approx(
        report["baseline_constant"]["brier"] - report["stack"]["brier"]
    )
    expected_gate = (
        improvements["logloss"] >= GATE_LOGLOSS_MIN
        and improvements["brier"] >= GATE_BRIER_MIN
    )
    assert report["gates_passed"] is expected_gate
    assert np.isfinite(ens._oof_scores[ens._oof_mask]).all()


def test_probability_gate_fails_when_only_brier_threshold_misses():
    improvements, passed = _probability_gate(
        {"logloss": 0.49, "brier": 0.199},
        {"logloss": 0.50, "brier": 0.200},
    )
    assert improvements["logloss"] > GATE_LOGLOSS_MIN
    assert improvements["brier"] < GATE_BRIER_MIN
    assert passed is False


def test_meta_crossfit_audit_is_disjoint_chronological_and_purged(fitted_stack):
    _, _, dates, ens, _ = fitted_stack
    assert ens._meta_fold_audit
    evaluated = []
    for audit in ens._meta_fold_audit:
        train_idx = audit["train_idx"]
        validation_idx = audit["validation_idx"]
        validation_fold = audit["validation_fold"]
        evaluated.extend(validation_idx.tolist())

        assert set(train_idx).isdisjoint(validation_idx)
        assert (ens._first_level_fold_ids[train_idx] < validation_fold).all()
        assert (ens._first_level_fold_ids[validation_idx] == validation_fold).all()
        assert dates.iloc[train_idx].max() <= audit["purge_cutoff"]
        assert dates.iloc[validation_idx].min() - dates.iloc[train_idx].max() >= (
            pd.Timedelta(days=ens.purge_days)
        )

    assert np.array_equal(
        np.sort(np.asarray(evaluated, dtype=int)), np.flatnonzero(ens._oof_mask)
    )


def test_first_member_oof_fold_is_excluded_from_meta_evidence(fitted_stack):
    _, _, _, ens, _ = fitted_stack
    available = ens._first_level_fold_ids[ens._first_level_fold_ids >= 0]
    first_fold = int(available.min())
    assert not ens._oof_mask[ens._first_level_fold_ids == first_fold].any()
    assert ens._oof_mask[ens._first_level_fold_ids > first_fold].any()


def test_prior_baseline_uses_only_each_meta_folds_training_labels(fitted_stack):
    _, y, _, ens, report = fitted_stack
    assert np.array_equal(~np.isnan(ens._baseline_oof_scores), ens._oof_mask)
    for audit in ens._meta_fold_audit:
        expected_rate = float(y[audit["train_idx"]].mean())
        assert audit["baseline_rate"] == pytest.approx(expected_rate)
        assert np.allclose(
            ens._baseline_oof_scores[audit["validation_idx"]], expected_rate
        )
    assert report["baseline_constant"]["method"] == "prior_fold_climatology"
    assert report["baseline_constant"]["deployment_rate"] == pytest.approx(
        float(y.mean())
    )


def test_member_set_does_not_depend_on_ambient_xgboost(monkeypatch):
    monkeypatch.setitem(sys.modules, "xgboost", SimpleNamespace())
    assert [member.name for member in StackedEnsemble().members] == ["lgbm", "enet"]


def test_lightgbm_uses_fixed_rounds_without_outer_validation(monkeypatch):
    calls = []

    class FakeDataset:
        def __init__(self, X, **kwargs):
            self.X = X
            self.kwargs = kwargs

    class FakeBooster:
        @staticmethod
        def predict(X):
            return np.full(len(X), 0.5)

    def fake_train(params, dataset, **kwargs):
        calls.append({"params": params, "dataset": dataset, **kwargs})
        return FakeBooster()

    monkeypatch.setitem(
        sys.modules,
        "lightgbm",
        SimpleNamespace(Dataset=FakeDataset, train=fake_train),
    )
    member = LGBMMember()
    X = np.arange(24, dtype=float).reshape(12, 2)
    y = np.array([0, 1] * 6)
    fold_scores = member.fit_fold(X[:8], y[:8], X[8:], y[8:], ["a", "b"])
    member.fit_full(X, y, ["a", "b"])

    assert np.asarray(fold_scores).shape == (4,)
    assert [call["num_boost_round"] for call in calls] == [
        LGB_NUM_BOOST_ROUND,
        LGB_NUM_BOOST_ROUND,
    ]
    assert all("valid_sets" not in call and "callbacks" not in call for call in calls)


def test_full_fit_members_and_meta_score_new_rows(fitted_stack):
    X, _, _, ens, _ = fitted_stack
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
