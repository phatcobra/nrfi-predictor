"""Gated ensemble: fixed LightGBM + ElasticNet temporal OOF stack.

Evidence discipline:
  - Expanding walk-forward folds with a configurable purge gap.
  - Base members use fixed, predeclared training behavior in every outer fold.
  - Each reported stack score comes from a fresh meta-learner fitted only on
    earlier first-level OOF folds outside the purge gap.
  - The shipped member architecture is fixed and cannot depend on ambient
    optional packages.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

GATE_LOGLOSS_MIN = 0.005
GATE_BRIER_MIN = 0.002
SHRINKAGE_K = 20.0
RANDOM_SEED = 42
LGB_NUM_BOOST_ROUND = 200
META_MIN_TRAIN = 50

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


def purged_walk_forward_folds(
    dates: pd.Series, n_folds: int, purge_days: int, min_train: int = 200
):
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


def _fit_lgbm(X_train, y_train, feature_names=None):
    import lightgbm as lgb

    return lgb.train(
        LGB_PARAMS,
        lgb.Dataset(
            X_train,
            label=y_train,
            feature_name=list(feature_names or []) or "auto",
        ),
        num_boost_round=LGB_NUM_BOOST_ROUND,
    )


def _meta_model() -> LogisticRegression:
    return LogisticRegression(max_iter=1000, random_state=RANDOM_SEED)


def _enet_pipeline() -> Pipeline:
    return Pipeline(
        [
            ("impute", SimpleImputer(strategy="median", add_indicator=True)),
            ("scale", StandardScaler()),
            (
                "clf",
                LogisticRegression(
                    penalty="elasticnet",
                    solver="saga",
                    l1_ratio=0.5,
                    C=1.0,
                    max_iter=4000,
                    random_state=RANDOM_SEED,
                    n_jobs=1,
                ),
            ),
        ]
    )


def _probability_gate(stack: dict, baseline: dict) -> tuple[dict, bool]:
    """Return exact baseline-minus-stack deltas and the predeclared decision."""
    logloss_improvement = baseline["logloss"] - stack["logloss"]
    brier_improvement = baseline["brier"] - stack["brier"]
    improvements = {
        "logloss": float(logloss_improvement),
        "brier": float(brier_improvement),
        "minimum_logloss": GATE_LOGLOSS_MIN,
        "minimum_brier": GATE_BRIER_MIN,
    }
    passed = (
        logloss_improvement >= GATE_LOGLOSS_MIN and brier_improvement >= GATE_BRIER_MIN
    )
    return improvements, bool(passed)


class Member:
    """A gated ensemble member."""

    def __init__(self, name: str):
        self.name = name
        self.model = None

    def fit_fold(self, X_train, y_train, X_validation, y_validation, feature_names):
        raise NotImplementedError

    def fit_full(self, X, y, feature_names):
        raise NotImplementedError

    def predict(self, X) -> np.ndarray:
        raise NotImplementedError


class LGBMMember(Member):
    def __init__(self):
        super().__init__("lgbm")

    def fit_fold(self, X_train, y_train, X_validation, y_validation, feature_names):
        model = _fit_lgbm(X_train, y_train, feature_names)
        return model.predict(X_validation)

    def fit_full(self, X, y, feature_names):
        self.model = _fit_lgbm(X, y, feature_names)

    def predict(self, X):
        if self.model is None:
            raise RuntimeError("LightGBM member has not been fitted")
        return np.asarray(self.model.predict(X), dtype=float)


class ENetMember(Member):
    def __init__(self):
        super().__init__("enet")

    def fit_fold(self, X_train, y_train, X_validation, y_validation, feature_names):
        pipeline = _enet_pipeline()
        pipeline.fit(X_train, y_train)
        return pipeline.predict_proba(X_validation)[:, 1]

    def fit_full(self, X, y, feature_names):
        self.model = _enet_pipeline().fit(X, y)

    def predict(self, X):
        if self.model is None:
            raise RuntimeError("ElasticNet member has not been fitted")
        return self.model.predict_proba(X)[:, 1]


class StackedEnsemble:
    """Fixed LightGBM/ElasticNet stack with temporal evidence separation."""

    def __init__(self, purge_days: int = 7, n_folds: int = 5):
        self.purge_days = purge_days
        self.n_folds = n_folds
        self.members: list[Member] = [LGBMMember(), ENetMember()]
        self.meta: LogisticRegression | None = None
        self.feature_names: list[str] = []
        self._oof_scores = np.array([], dtype=float)
        self._oof_mask = np.array([], dtype=bool)
        self._baseline_oof_scores = np.array([], dtype=float)
        self._first_level_fold_ids = np.array([], dtype=int)
        self._meta_fold_audit: list[dict] = []

    def _oof_matrix(self, members, X, y, dates) -> np.ndarray:
        oof = np.full((len(X), len(members)), np.nan)
        fold_ids = np.full(len(X), -1, dtype=int)
        fold_count = 0
        for train_idx, validation_idx in purged_walk_forward_folds(
            dates, self.n_folds, self.purge_days
        ):
            fold_count += 1
            if len(np.unique(y[train_idx])) < 2:
                raise ValueError("walk-forward training fold contains one class")
            if len(np.unique(y[validation_idx])) < 2:
                raise ValueError("walk-forward validation fold contains one class")
            for column, member in enumerate(members):
                oof[validation_idx, column] = member.fit_fold(
                    X[train_idx],
                    y[train_idx],
                    X[validation_idx],
                    y[validation_idx],
                    self.feature_names,
                )
            fold_ids[validation_idx] = fold_count - 1
        if fold_count == 0:
            raise ValueError("no valid walk-forward folds were produced")
        self._first_level_fold_ids = fold_ids
        return oof

    def _crossfit_meta(
        self,
        oof: np.ndarray,
        y: np.ndarray,
        dates: pd.Series,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Create temporal meta and prior-climatology scores on identical rows."""
        complete = ~np.isnan(oof).any(axis=1)
        stack_oof = np.full(len(y), np.nan)
        baseline_oof = np.full(len(y), np.nan)
        self._meta_fold_audit = []

        available_folds = np.unique(self._first_level_fold_ids[complete])
        available_folds = available_folds[available_folds >= 0]
        for validation_fold in available_folds[1:]:
            validation_idx = np.flatnonzero(
                complete & (self._first_level_fold_ids == validation_fold)
            )
            if len(validation_idx) == 0:
                continue
            cutoff = dates.iloc[validation_idx[0]] - pd.Timedelta(days=self.purge_days)
            earlier_complete = (
                complete
                & (self._first_level_fold_ids >= 0)
                & (self._first_level_fold_ids < validation_fold)
            )
            train_idx = np.flatnonzero(
                earlier_complete
                & (dates.to_numpy(dtype="datetime64[ns]") <= np.datetime64(cutoff))
            )
            if len(train_idx) < META_MIN_TRAIN:
                continue
            if len(np.unique(y[train_idx])) < 2:
                raise ValueError("meta training fold contains one class")
            if len(np.unique(y[validation_idx])) < 2:
                raise ValueError("meta validation fold contains one class")

            fold_meta = _meta_model().fit(oof[train_idx], y[train_idx])
            stack_oof[validation_idx] = fold_meta.predict_proba(oof[validation_idx])[
                :, 1
            ]
            baseline_rate = float(np.clip(y[train_idx].mean(), 1e-6, 1 - 1e-6))
            baseline_oof[validation_idx] = baseline_rate
            self._meta_fold_audit.append(
                {
                    "validation_fold": int(validation_fold),
                    "train_idx": train_idx.copy(),
                    "validation_idx": validation_idx.copy(),
                    "purge_cutoff": pd.Timestamp(cutoff),
                    "baseline_rate": baseline_rate,
                }
            )

        evidence_mask = ~np.isnan(stack_oof)
        if evidence_mask.sum() < META_MIN_TRAIN:
            raise ValueError("insufficient temporal meta OOF rows for stack evidence")
        if not np.array_equal(evidence_mask, ~np.isnan(baseline_oof)):
            raise RuntimeError("stack and baseline evidence rows differ")
        return stack_oof, baseline_oof

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
    def _baseline(y, baseline_oof, deployment_rate) -> dict:
        report = StackedEnsemble._pooled(baseline_oof, y)
        report.update(
            {
                "deployment_rate": float(np.clip(deployment_rate, 1e-6, 1 - 1e-6)),
                "method": "prior_fold_climatology",
            }
        )
        return report

    def fit(
        self, X: np.ndarray, y: np.ndarray, dates: pd.Series, feature_names: list[str]
    ) -> dict:
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
        member_mask = ~np.isnan(oof).any(axis=1)
        if member_mask.sum() < META_MIN_TRAIN:
            raise ValueError("insufficient pooled OOF rows for stack training")

        stack_oof, baseline_oof = self._crossfit_meta(oof, y, dates)
        evidence_mask = ~np.isnan(stack_oof)
        report = {"ablation": {}}
        report["members"] = {
            member.name: self._pooled(
                np.where(evidence_mask, oof[:, column], np.nan), y
            )
            for column, member in enumerate(self.members)
        }
        report["stack"] = self._pooled(stack_oof, y)
        report["baseline_constant"] = self._baseline(y, baseline_oof, y.mean())
        report["shipped_members"] = [member.name for member in self.members]
        report["gate_improvements"], report["gates_passed"] = _probability_gate(
            report["stack"], report["baseline_constant"]
        )

        self._oof_scores = stack_oof
        self._oof_mask = evidence_mask
        self._baseline_oof_scores = baseline_oof

        # Deployment fitting happens only after the temporal evidence is frozen.
        self.meta = _meta_model().fit(oof[member_mask], y[member_mask])
        for member in self.members:
            member.fit_full(X, y, self.feature_names)
        return report

    def raw_scores(self, X: np.ndarray) -> np.ndarray:
        if self.meta is None:
            raise RuntimeError("ensemble has not been fitted")
        columns = [member.predict(X) for member in self.members]
        return self.meta.predict_proba(np.column_stack(columns))[:, 1]


def shrink_to_venue(
    p_cal: float, venue_yrfi_rate: float | None, n_eff: float, k: float = SHRINKAGE_K
) -> float:
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
        value
        for value in first_inning_games
        if value is not None and not (isinstance(value, float) and np.isnan(value))
    ]
    base = min(first_inning_games) if first_inning_games else 0.0
    return float(min(base, 60.0)) * float(coverage_val)
