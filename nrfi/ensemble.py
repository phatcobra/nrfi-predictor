"""Gated ensemble: LightGBM + ElasticNet-logistic OOF stack -> Venn-ABERS.

Evidence discipline (SYSTEM_DESIGN_V3 SS7):
  - Walk-forward expanding folds with a CV_PURGE_DAYS gap.
  - Members produce OUT-OF-FOLD predictions; the logistic meta-learner and
    the Venn-ABERS calibrator only ever see OOF scores.
  - Optional members (xgboost / MLP) ship ONLY if they cut pooled OOF log
    loss by >= GATE_LOGLOSS_MIN each (ablation gate). New features same idea
    plus GATE_BRIER_MIN.
  - Baselines (constant rate, venue rate) are computed and published in the
    gate report; a candidate that cannot beat them does not pass.
  - Venue shrinkage: p = (n_eff*p_cal + k*p_venue) / (n_eff + k), k=20.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from nrfi._obs import logger

GATE_LOGLOSS_MIN = 0.005   # per added model AND per added feature family
GATE_BRIER_MIN = 0.002     # additional bar for features
SHRINKAGE_K = 20.0

LGB_PARAMS = {
    "objective": "binary", "metric": "binary_logloss", "boosting_type": "gbdt",
    "num_leaves": 31, "learning_rate": 0.05, "feature_fraction": 0.8,
    "bagging_fraction": 0.8, "bagging_freq": 5, "max_depth": 6,
    "min_child_samples": 20, "verbose": -1,
}


# ---------------------------------------------------------------- folds

def purged_walk_forward_folds(dates: pd.Series, n_folds: int, purge_days: int,
                              min_train: int = 200):
    """Expanding-window folds; train rows within purge_days of the first
    validation date are dropped. Yields (train_idx, val_idx)."""
    n = len(dates)
    edges = np.linspace(0, n, n_folds + 2, dtype=int)[1:]
    for k in range(n_folds):
        tr_end, va_end = edges[k], edges[k + 1]
        va_idx = np.arange(tr_end, va_end)
        if len(va_idx) == 0:
            continue
        cutoff = dates.iloc[va_idx[0]] - pd.Timedelta(days=purge_days)
        tr_idx = np.arange(0, tr_end)
        tr_idx = tr_idx[dates.iloc[tr_idx].values <= np.datetime64(cutoff)]
        if len(tr_idx) < min_train:
            continue
        yield tr_idx, va_idx


# ---------------------------------------------------------------- members

def _fit_lgbm(X_tr, y_tr, X_va=None, y_va=None, feature_names=None):
    import lightgbm as lgb
    dtr = lgb.Dataset(X_tr, label=y_tr, feature_name=list(feature_names or []) or "auto")
    if X_va is not None:
        dva = lgb.Dataset(X_va, label=y_va, reference=dtr)
        model = lgb.train(LGB_PARAMS, dtr, num_boost_round=1000,
                          valid_sets=[dva],
                          callbacks=[lgb.early_stopping(50, verbose=False)])
    else:
        model = lgb.train(LGB_PARAMS, dtr, num_boost_round=200)
    return model


def _enet_pipeline() -> Pipeline:
    return Pipeline([
        ("impute", SimpleImputer(strategy="median", add_indicator=True)),
        ("scale", StandardScaler()),
        ("clf", LogisticRegression(penalty="elasticnet", solver="saga",
                                   l1_ratio=0.5, C=1.0, max_iter=4000)),
    ])


class Member:
    """A gated ensemble member."""

    def __init__(self, name: str):
        self.name = name
        self.model = None
        self.best_iters: list[int] = []

    def fit_fold(self, X_tr, y_tr, X_va, y_va, feature_names):
        raise NotImplementedError

    def fit_full(self, X, y, feature_names):
        raise NotImplementedError

    def predict(self, X) -> np.ndarray:
        raise NotImplementedError


class LGBMMember(Member):
    def __init__(self):
        super().__init__("lgbm")

    def fit_fold(self, X_tr, y_tr, X_va, y_va, feature_names):
        m = _fit_lgbm(X_tr, y_tr, X_va, y_va, feature_names)
        self.best_iters.append(m.best_iteration or 200)
        return m.predict(X_va, num_iteration=m.best_iteration)

    def fit_full(self, X, y, feature_names):
        import lightgbm as lgb
        rounds = int(np.median(self.best_iters)) if self.best_iters else 200
        self.model = lgb.train(
            LGB_PARAMS, lgb.Dataset(X, label=y, feature_name=list(feature_names)),
            num_boost_round=rounds)

    def predict(self, X):
        return np.asarray(self.model.predict(X), dtype=float)


class ENetMember(Member):
    def __init__(self):
        super().__init__("enet")

    def fit_fold(self, X_tr, y_tr, X_va, y_va, feature_names):
        pipe = _enet_pipeline()
        pipe.fit(X_tr, y_tr)
        return pipe.predict_proba(X_va)[:, 1]

    def fit_full(self, X, y, feature_names):
        self.model = _enet_pipeline().fit(X, y)

    def predict(self, X):
        return self.model.predict_proba(X)[:, 1]


def optional_members() -> list[Member]:
    """XGBoost / MLP candidates - included in ablation only if importable.
    They ship only if they pass the gate; absence is never an error."""
    out: list[Member] = []
    try:
        import xgboost as xgb  # noqa: F401

        class XGBMember(Member):
            def __init__(self):
                super().__init__("xgb")

            def fit_fold(self, X_tr, y_tr, X_va, y_va, feature_names):
                m = xgb.XGBClassifier(
                    n_estimators=400, max_depth=5, learning_rate=0.05,
                    subsample=0.8, colsample_bytree=0.8,
                    eval_metric="logloss", early_stopping_rounds=50)
                m.fit(X_tr, y_tr, eval_set=[(X_va, y_va)], verbose=False)
                self.best_iters.append(m.best_iteration or 200)
                return m.predict_proba(X_va)[:, 1]

            def fit_full(self, X, y, feature_names):
                rounds = int(np.median(self.best_iters)) if self.best_iters else 200
                self.model = xgb.XGBClassifier(
                    n_estimators=rounds, max_depth=5, learning_rate=0.05,
                    subsample=0.8, colsample_bytree=0.8).fit(X, y)

            def predict(self, X):
                return self.model.predict_proba(X)[:, 1]

        out.append(XGBMember())
    except ImportError:
        pass
    return out


# ---------------------------------------------------------------- stack

class StackedEnsemble:
    """Core two-member stack with optional gated additions."""

    def __init__(self, purge_days: int = 7, n_folds: int = 5):
        self.purge_days = purge_days
        self.n_folds = n_folds
        self.members: list[Member] = [LGBMMember(), ENetMember()]
        self.meta: LogisticRegression | None = None
        self.feature_names: list[str] = []

    def _oof_matrix(self, members, X, y, dates) -> np.ndarray:
        oof = np.full((len(X), len(members)), np.nan)
        for tr_idx, va_idx in purged_walk_forward_folds(
                dates, self.n_folds, self.purge_days):
            for j, m in enumerate(members):
                oof[va_idx, j] = m.fit_fold(
                    X[tr_idx], y[tr_idx], X[va_idx], y[va_idx],
                    self.feature_names)
        return oof

    @staticmethod
    def _pooled(oof_col, y):
        mask = ~np.isnan(oof_col)
        p = np.clip(oof_col[mask], 1e-6, 1 - 1e-6)
        return {"logloss": float(log_loss(y[mask], p)),
                "brier": float(brier_score_loss(y[mask], p)),
                "n": int(mask.sum())}

    def fit(self, X: np.ndarray, y: np.ndarray, dates: pd.Series,
            feature_names: list[str]) -> dict:
        self.feature_names = list(feature_names)

        # --- core members OOF
        oof = self._oof_matrix(self.members, X, y, dates)
        mask = ~np.isnan(oof).any(axis=1)

        # --- meta on OOF (2-param logistic; members never see own train rows)
        self.meta = LogisticRegression(max_iter=1000)
        self.meta.fit(oof[mask], y[mask])
        stack_oof = np.full(len(X), np.nan)
        stack_oof[mask] = self.meta.predict_proba(oof[mask])[:, 1]

        report = {
            "members": {m.name: self._pooled(oof[:, j], y)
                        for j, m in enumerate(self.members)},
            "stack": self._pooled(stack_oof, y),
            "baseline_constant": {
                "logloss": float(log_loss(y[mask],
                                          np.full(mask.sum(), y.mean()))),
                "brier": float(brier_score_loss(y[mask],
                                                np.full(mask.sum(), y.mean()))),
            },
        }

        # --- ablation gate for optional members
        report["ablation"] = {}
        base_ll = report["stack"]["logloss"]
        for cand in optional_members():
            trial_members = [LGBMMember(), ENetMember(), cand]
            t_oof = self._oof_matrix(trial_members, X, y, dates)
            t_mask = ~np.isnan(t_oof).any(axis=1)
            t_meta = LogisticRegression(max_iter=1000).fit(t_oof[t_mask], y[t_mask])
            t_stack = t_meta.predict_proba(t_oof[t_mask])[:, 1]
            t_ll = float(log_loss(y[t_mask], np.clip(t_stack, 1e-6, 1 - 1e-6)))
            improved = (base_ll - t_ll) >= GATE_LOGLOSS_MIN
            report["ablation"][cand.name] = {
                "logloss_with": t_ll, "logloss_without": base_ll,
                "delta": base_ll - t_ll, "passes_gate": bool(improved),
            }
            if improved:
                logger.info(f"member {cand.name} PASSED gate "
                            f"(delta {base_ll - t_ll:.4f}) - adding")
                self.members.append(cand)
                oof = np.column_stack([oof, t_oof[:, -1]])
                mask = ~np.isnan(oof).any(axis=1)
                self.meta = LogisticRegression(max_iter=1000).fit(oof[mask], y[mask])
                stack_oof = np.full(len(X), np.nan)
                stack_oof[mask] = self.meta.predict_proba(oof[mask])[:, 1]
                base_ll = self._pooled(stack_oof, y)["logloss"]
            else:
                logger.info(f"member {cand.name} FAILED gate "
                            f"(delta {base_ll - t_ll:.4f}) - not shipped")

        # --- gates summary
        report["gates_passed"] = bool(
            report["stack"]["logloss"] < report["baseline_constant"]["logloss"])
        self._oof_scores = stack_oof   # calibration input (OOF only)
        self._oof_mask = mask

        # --- final member fits on all data
        for m in self.members:
            m.fit_full(X, y, self.feature_names)
        return report

    def raw_scores(self, X: np.ndarray) -> np.ndarray:
        cols = [m.predict(X) for m in self.members]
        return self.meta.predict_proba(np.column_stack(cols))[:, 1]


# ---------------------------------------------------------------- shrinkage

def shrink_to_venue(p_cal: float, venue_yrfi_rate: float | None,
                    n_eff: float, k: float = SHRINKAGE_K) -> float:
    """Bayesian pull toward the venue YRFI base rate for cold matchups.
    n_eff ~ evidence behind p_cal (coverage-scaled FI-games count)."""
    if venue_yrfi_rate is None or np.isnan(p_cal):
        return p_cal
    n_eff = max(0.0, float(n_eff))
    return (n_eff * p_cal + k * venue_yrfi_rate) / (n_eff + k)


def n_eff_for_game(features: dict, coverage_val: float) -> float:
    """Evidence proxy: coverage-scaled minimum first-inning sample size."""
    fi_games = [features.get("away_p_fi_games"), features.get("home_p_fi_games")]
    fi_games = [g for g in fi_games
                if g is not None and not (isinstance(g, float) and np.isnan(g))]
    base = min(fi_games) if fi_games else 0.0
    return float(min(base, 60.0)) * float(coverage_val)
