"""Gated ensemble: LightGBM + ElasticNet-logistic OOF stack -> Venn-ABERS.

Evidence discipline:
  - Expanding walk-forward folds with a configurable purge gap.
  - Members, meta-learner, and calibrator use out-of-fold evidence only.
  - Optional members ship only after a pooled OOF log-loss ablation gate.
  - The final gate report is recomputed after member selection and therefore
    describes the exact ensemble that is fitted and persisted.
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

GATE_LOGLOSS_MIN = 0.005
GATE_BRIER_MIN = 0.002
SHRINKAGE_K = 20.0
RANDOM_SEED = 42

LGB_PARAMS = {
    "objective": "binary",
    "metric": "binary_logloss",
    "boosting_type": "gbdt",
    "num_leaves": 31,
    "learning_rate": 0.05,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "max_depth": 6,
    "min_child_samples": 20,
    "verbose": -1,
    "seed": RANDOM_SEED,
    "feature_fraction_seed": RANDOM_SEED,
    "bagging_seed": RANDOM_SEED,
    "data_random_seed": RANDOM_SEED,
    "deterministic": True,
    "force_col_wise": True,
    "num_threads": 1,
}


def purged_walk_forward_folds(dates: pd.Series, n_folds: int, purge_days: int,
                              min_train: int = 200):
    """Yield expanding train/validation indexes with a temporal purge gap."""
    if n_folds < 2:
        raise ValueError("n_folds must be at least 2")
    if purge_days < 0:
        raise ValueError("purge_days cannot be negative")
    dates = pd.Series(pd.to_datetime(dates, errors="raise")).reset_index(drop=True)
    if not dates.is_monotonic_increasing:
        raise ValueError("dates must be sorted ascending before walk-forward CV")
    n = len(dates)
    edges = np.linspace(0, n, n_folds + 2, dtype=int)[1:]
    for fold_index in range(n_folds):
        train_end, validation_end = edges[fold_index], edges[fold_index + 1]
        validation_idx = np.arange(train_end, validation_end)
        if len(validation_idx) == 0:
            continue
        cutoff = dates.iloc[validation_idx[0]] - pd.Timedelta(days=purge_days)
        train_idx = np.arange(0, train_end)
        train_idx = train_idx[dates.iloc[train_idx].values <= np.datetime64(cutoff)]
        if len(train_idx) < min_train:
            continue
        yield train_idx, validation_idx


def _fit_lgbm(X_train, y_train, X_validation=None, y_validation=None,
              feature_names=None):
    import lightgbm as lgb

    train_data = lgb.Dataset(
        X_train, label=y_train, feature_name=list(feature_names or []) or "auto")
    if X_validation is not None:
        validation_data = lgb.Dataset(
            X_validation, label=y_validation, reference=train_data)
        return lgb.train(
            LGB_PARAMS,
            train_data,
            num_boost_round=1000,
            valid_sets=[validation_data],
            callbacks=[lgb.early_stopping(50, verbose=False)],
        )
    return lgb.train(LGB_PARAMS, train_data, num_boost_round=200)


def _meta_model() -> LogisticRegression:
    return LogisticRegression(max_iter=1000, random_state=RANDOM_SEED)


def _enet_pipeline() -> Pipeline:
    return Pipeline([
        ("impute", SimpleImputer(strategy="median", add_indicator=True)),
        ("scale", StandardScaler()),
        ("clf", LogisticRegression(
            penalty="elasticnet",
            solver="saga",
            l1_ratio=0.5,
            C=1.0,
            max_iter=4000,
            random_state=RANDOM_SEED,
            n_jobs=1,
        )),
    ])


class Member:
    """A gated ensemble member."""

    def __init__(self, name: str):
        self.name = name
        self.model = None
        self.best_iters: list[int] = []

    def fit_fold(self, X_train, y_train, X_validation, y_validation,
                 feature_names):
        raise NotImplementedError

    def fit_full(self, X, y, feature_names):
        raise NotImplementedError

    def predict(self, X) -> np.ndarray:
        raise NotImplementedError


class LGBMMember(Member):
    def __init__(self):
        super().__init__("lgbm")

    def fit_fold(self, X_train, y_train, X_validation, y_validation,
                 feature_names):
        model = _fit_lgbm(
            X_train, y_train, X_validation, y_validation, feature_names)
        self.best_iters.append(model.best_iteration or 200)
        return model.predict(X_validation, num_iteration=model.best_iteration)

    def fit_full(self, X, y, feature_names):
        import lightgbm as lgb

        rounds = int(np.median(self.best_iters)) if self.best_iters else 200
        self.model = lgb.train(
            LGB_PARAMS,
            lgb.Dataset(X, label=y, feature_name=list(feature_names)),
            num_boost_round=rounds,
        )

    def predict(self, X):
        if self.model is None:
            raise RuntimeError("LightGBM member has not been fitted")
        return np.asarray(self.model.predict(X), dtype=float)


class ENetMember(Member):
    def __init__(self):
        super().__init__("enet")

    def fit_fold(self, X_train, y_train, X_validation, y_validation,
                 feature_names):
        pipeline = _enet_pipeline()
        pipeline.fit(X_train, y_train)
        return pipeline.predict_proba(X_validation)[:, 1]

    def fit_full(self, X, y, feature_names):
        self.model = _enet_pipeline().fit(X, y)

    def predict(self, X):
        if self.model is None:
            raise RuntimeError("ElasticNet member has not been fitted")
        return self.model.predict_proba(X)[:, 1]


def optional_members() -> list[Member]:
    """Return optional candidates only when their dependency is installed."""
    candidates: list[Member] = []
    try:
        import xgboost as xgb

        class XGBMember(Member):
            def __init__(self):
                super().__init__("xgb")

            def fit_fold(self, X_train, y_train, X_validation, y_validation,
                         feature_names):
                model = xgb.XGBClassifier(
                    n_estimators=400,
                    max_depth=5,
                    learning_rate=0.05,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    eval_metric="logloss",
                    early_stopping_rounds=50,
                    random_state=RANDOM_SEED,
                    n_jobs=1,
                )
                model.fit(X_train, y_train,
                          eval_set=[(X_validation, y_validation)], verbose=False)
                self.best_iters.append(model.best_iteration or 200)
                return model.predict_proba(X_validation)[:, 1]

            def fit_full(self, X, y, feature_names):
                rounds = int(np.median(self.best_iters)) if self.best_iters else 200
                self.model = xgb.XGBClassifier(
                    n_estimators=rounds,
                    max_depth=5,
                    learning_rate=0.05,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    eval_metric="logloss",
                    random_state=RANDOM_SEED,
                    n_jobs=1,
                ).fit(X, y)

            def predict(self, X):
                if self.model is None:
                    raise RuntimeError("XGBoost member has not been fitted")
                return self.model.predict_proba(X)[:, 1]

        candidates.append(XGBMember())
    except ImportError:
        pass
    return candidates


class StackedEnsemble:
    """Core LightGBM/ElasticNet stack with gated optional additions."""

    def __init__(self, purge_days: int = 7, n_folds: int = 5):
        self.purge_days = purge_days
        self.n_folds = n_folds
        self.members: list[Member] = [LGBMMember(), ENetMember()]
        self.meta: LogisticRegression | None = None
        self.feature_names: list[str] = []
        self._oof_scores = np.array([], dtype=float)
        self._oof_mask = np.array([], dtype=bool)

    def _oof_matrix(self, members, X, y, dates) -> np.ndarray:
        oof = np.full((len(X), len(members)), np.nan)
        fold_count = 0
        for train_idx, validation_idx in purged_walk_forward_folds(
                dates, self.n_folds, self.purge_days):
            fold_count += 1
            if len(np.unique(y[train_idx])) < 2:
                raise ValueError("walk-forward training fold contains one class")
            if len(np.unique(y[validation_idx])) < 2:
                raise ValueError("walk-forward validation fold contains one class")
            for column, member in enumerate(members):
                oof[validation_idx, column] = member.fit_fold(
                    X[train_idx], y[train_idx],
                    X[validation_idx], y[validation_idx],
                    self.feature_names,
                )
        if fold_count == 0:
            raise ValueError("no valid walk-forward folds were produced")
        return oof

    @staticmethod
    def _pooled(oof_col, y):
        mask = ~np.isnan(oof_col)
        if mask.sum() == 0:
            raise ValueError("no out-of-fold predictions available")
        probabilities = np.clip(oof_col[mask], 1e-6, 1 - 1e-6)
        return {
            "logloss": float(log_loss(y[mask], probabilities)),
            "brier": float(brier_score_loss(y[mask], probabilities)),
            "n": int(mask.sum()),
        }

    @staticmethod
    def _baseline(y, mask) -> dict:
        observed = y[mask]
        if len(observed) == 0 or len(np.unique(observed)) < 2:
            raise ValueError("OOF baseline requires both target classes")
        rate = float(np.clip(observed.mean(), 1e-6, 1 - 1e-6))
        constant = np.full(mask.sum(), rate)
        return {
            "rate": rate,
            "logloss": float(log_loss(observed, constant)),
            "brier": float(brier_score_loss(observed, constant)),
            "n": int(mask.sum()),
        }

    def fit(self, X: np.ndarray, y: np.ndarray, dates: pd.Series,
            feature_names: list[str]) -> dict:
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=int)
        dates = pd.Series(pd.to_datetime(dates, errors="raise")).reset_index(drop=True)
        if X.ndim != 2 or len(X) != len(y) or len(y) != len(dates):
            raise ValueError("X, y, and dates must have matching row counts")
        if X.shape[1] != len(feature_names):
            raise ValueError("feature_names length does not match X columns")
        if len(np.unique(y)) < 2:
            raise ValueError("training target must contain both classes")
        if not dates.is_monotonic_increasing:
            raise ValueError("training rows must be sorted chronologically")
        self.feature_names = list(feature_names)

        oof = self._oof_matrix(self.members, X, y, dates)
        mask = ~np.isnan(oof).any(axis=1)
        if mask.sum() < 50:
            raise ValueError("insufficient pooled OOF rows for stack training")

        self.meta = _meta_model().fit(oof[mask], y[mask])
        stack_oof = np.full(len(X), np.nan)
        stack_oof[mask] = self.meta.predict_proba(oof[mask])[:, 1]

        report = {"ablation": {}}
        base_logloss = self._pooled(stack_oof, y)["logloss"]

        for candidate in optional_members():
            trial_members = [LGBMMember(), ENetMember(), candidate]
            trial_oof = self._oof_matrix(trial_members, X, y, dates)
            trial_mask = ~np.isnan(trial_oof).any(axis=1)
            trial_meta = _meta_model().fit(trial_oof[trial_mask], y[trial_mask])
            trial_stack = trial_meta.predict_proba(trial_oof[trial_mask])[:, 1]
            trial_logloss = float(log_loss(
                y[trial_mask], np.clip(trial_stack, 1e-6, 1 - 1e-6)))
            improvement = base_logloss - trial_logloss
            passed = improvement >= GATE_LOGLOSS_MIN
            report["ablation"][candidate.name] = {
                "logloss_with": trial_logloss,
                "logloss_without": base_logloss,
                "delta": improvement,
                "passes_gate": bool(passed),
            }
            if not passed:
                logger.info(
                    f"member {candidate.name} FAILED gate "
                    f"(delta {improvement:.4f}) - not shipped")
                continue

            logger.info(
                f"member {candidate.name} PASSED gate "
                f"(delta {improvement:.4f}) - adding")
            self.members.append(candidate)
            oof = np.column_stack([oof, trial_oof[:, -1]])
            mask = ~np.isnan(oof).any(axis=1)
            self.meta = _meta_model().fit(oof[mask], y[mask])
            stack_oof = np.full(len(X), np.nan)
            stack_oof[mask] = self.meta.predict_proba(oof[mask])[:, 1]
            base_logloss = self._pooled(stack_oof, y)["logloss"]

        # Recompute every report field from the final selected OOF matrix.
        report["members"] = {
            member.name: self._pooled(oof[:, column], y)
            for column, member in enumerate(self.members)
        }
        report["stack"] = self._pooled(stack_oof, y)
        report["baseline_constant"] = self._baseline(y, mask)
        report["shipped_members"] = [member.name for member in self.members]
        report["gates_passed"] = bool(
            report["stack"]["logloss"] < report["baseline_constant"]["logloss"])

        self._oof_scores = stack_oof
        self._oof_mask = mask

        for member in self.members:
            member.fit_full(X, y, self.feature_names)
        return report

    def raw_scores(self, X: np.ndarray) -> np.ndarray:
        if self.meta is None:
            raise RuntimeError("ensemble has not been fitted")
        columns = [member.predict(X) for member in self.members]
        return self.meta.predict_proba(np.column_stack(columns))[:, 1]


def shrink_to_venue(p_cal: float, venue_yrfi_rate: float | None,
                    n_eff: float, k: float = SHRINKAGE_K) -> float:
    """Bayesian pull toward venue YRFI base rate for cold matchups."""
    if venue_yrfi_rate is None or np.isnan(p_cal):
        return p_cal
    n_eff = max(0.0, float(n_eff))
    return (n_eff * p_cal + k * float(venue_yrfi_rate)) / (n_eff + k)


def n_eff_for_game(features: dict, coverage_val: float) -> float:
    """Coverage-scaled minimum first-inning sample size, capped at 60."""
    first_inning_games = [
        features.get("away_p_fi_games"),
        features.get("home_p_fi_games"),
    ]
    first_inning_games = [
        value for value in first_inning_games
        if value is not None
        and not (isinstance(value, float) and np.isnan(value))
    ]
    base = min(first_inning_games) if first_inning_games else 0.0
    return float(min(base, 60.0)) * float(coverage_val)
