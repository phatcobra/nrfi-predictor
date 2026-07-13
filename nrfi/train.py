"""Model training for NRFI/YRFI prediction (Phase 1 corrected).

Fixes vs the prior version:
  - Missing features stay NaN (LightGBM handles them natively). No zero-fill.
  - Feature names are the union across all games, sorted (stable schema).
  - Walk-forward CV with a purge gap (CV_PURGE_DAYS): train rows within the
    gap before each validation fold are dropped.
  - Calibration is fit on POOLED OUT-OF-FOLD predictions (isotonic). The old
    CalibratedClassifierCV(cv='prefit') fit on training data was invalid.
  - Final boosting rounds = median of early-stopped fold iterations.
  - Metadata (metrics, feature list, calibrator) saved with the model and
    registered in ML.MODEL_STATUS.

Phase 2 adds: ElasticNet-logistic OOF stack, Venn-ABERS, ablation gates,
2025 locked-holdout release evaluation, venue-YRFI Bayesian shrinkage.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Tuple

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import sentry_sdk
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from nrfi.config import Config, CV_PURGE_DAYS
from nrfi.features import NFRIFeatureEngineer
from nrfi.snowflake_loader import SnowflakeLoader

logger = logging.getLogger(__name__)

if os.getenv("SENTRY_DSN"):
    sentry_sdk.init(dsn=os.getenv("SENTRY_DSN"),
                    environment=os.getenv("ENV", "development"),
                    traces_sample_rate=0.1)

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
}


class NFRIModelTrainer:
    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        self.sf = SnowflakeLoader()
        self.feature_engineer = NFRIFeatureEngineer(self.sf)
        self.model: lgb.Booster | None = None
        self.calibrator: IsotonicRegression | None = None
        self.feature_names: List[str] = []

    # ------------------------------------------------------------- data

    def load_training_data(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Games + labels. Label yrfi = any run in top+bottom of the 1st."""
        query = """
        SELECT game_id, game_date, away_team, home_team,
               away_sp_id AS away_pitcher_id, home_sp_id AS home_pitcher_id,
               venue_id, is_doubleheader,
               fi_runs_top, fi_runs_bottom,
               CASE WHEN (fi_runs_top + fi_runs_bottom) > 0 THEN 1 ELSE 0 END AS yrfi
        FROM NRFI_DB.CORE.FIRST_INNING_OUTCOMES
        WHERE game_date >= %s AND game_date <= %s
          AND fi_runs_top IS NOT NULL AND fi_runs_bottom IS NOT NULL
        ORDER BY game_date
        """
        rows = self.sf.execute_query(query, [start_date, end_date])
        df = pd.DataFrame(rows)
        logger.info(f"Loaded {len(df)} labeled games {start_date}..{end_date}")
        return df

    def prepare_features(self, games_df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, pd.Series]:
        """Two passes: collect the feature-name union, then build the matrix.

        Games below the coverage floor are EXCLUDED from training (they would
        be BLOCKED at serve time; training on them teaches the model nothing
        real). NaN is the missing value; no zero-fill.
        """
        feats: List[Dict] = []
        labels: List[int] = []
        dates: List = []
        dropped = 0
        for _, game in games_df.iterrows():
            try:
                f = self.feature_engineer.generate_game_features(game.to_dict())
            except Exception as e:
                sentry_sdk.capture_exception(e)
                logger.warning(f"feature build failed for {game['game_id']}: {e}")
                dropped += 1
                continue
            if NFRIFeatureEngineer.coverage(f) < self.config.FEATURE_COVERAGE_MIN:
                dropped += 1
                continue
            feats.append(f)
            labels.append(int(game["yrfi"]))
            dates.append(pd.to_datetime(game["game_date"]))

        self.feature_names = sorted({k for f in feats for k in f})
        X = np.array([[f.get(name, np.nan) for name in self.feature_names] for f in feats],
                     dtype=float)
        y = np.array(labels, dtype=int)
        d = pd.Series(dates)
        logger.info(f"{X.shape[0]} games x {X.shape[1]} features "
                    f"(dropped {dropped} below coverage floor); YRFI rate {y.mean():.3f}")
        return X, y, d

    # ------------------------------------------------------------ training

    def train_model(self, X: np.ndarray, y: np.ndarray, dates: pd.Series,
                    cv_splits: int = 5) -> Dict:
        """Walk-forward CV with a purge gap; OOF isotonic calibration."""
        n = len(X)
        fold_edges = np.linspace(0, n, cv_splits + 2, dtype=int)[1:]  # expanding
        oof_pred = np.full(n, np.nan)
        best_iters: List[int] = []
        scores = {"brier": [], "auc": [], "log_loss": []}

        for k in range(cv_splits):
            tr_end, va_end = fold_edges[k], fold_edges[k + 1]
            va_idx = np.arange(tr_end, va_end)
            if len(va_idx) == 0:
                continue
            # purge: drop train rows within CV_PURGE_DAYS of the first val date
            cutoff = dates.iloc[va_idx[0]] - pd.Timedelta(days=CV_PURGE_DAYS)
            tr_idx = np.arange(0, tr_end)
            tr_idx = tr_idx[dates.iloc[tr_idx].values <= np.datetime64(cutoff)]
            if len(tr_idx) < 200:
                continue

            dtr = lgb.Dataset(X[tr_idx], label=y[tr_idx], feature_name=self.feature_names)
            dva = lgb.Dataset(X[va_idx], label=y[va_idx], reference=dtr)
            model = lgb.train(LGB_PARAMS, dtr, num_boost_round=1000,
                              valid_sets=[dva], valid_names=["val"],
                              callbacks=[lgb.early_stopping(50, verbose=False)])
            best_iters.append(model.best_iteration)
            p = model.predict(X[va_idx], num_iteration=model.best_iteration)
            oof_pred[va_idx] = p
            scores["brier"].append(brier_score_loss(y[va_idx], p))
            scores["auc"].append(roc_auc_score(y[va_idx], p))
            scores["log_loss"].append(log_loss(y[va_idx], p))
            logger.info(f"fold {k+1}: n_tr={len(tr_idx)} n_va={len(va_idx)} "
                        f"logloss={scores['log_loss'][-1]:.4f}")

        mask = ~np.isnan(oof_pred)
        metrics = {
            "cv_brier_mean": float(np.mean(scores["brier"])),
            "cv_auc_mean": float(np.mean(scores["auc"])),
            "cv_logloss_mean": float(np.mean(scores["log_loss"])),
            "oof_n": int(mask.sum()),
            "oof_brier": float(brier_score_loss(y[mask], oof_pred[mask])),
            "oof_logloss": float(log_loss(y[mask], oof_pred[mask])),
            "baseline_logloss_constant": float(
                log_loss(y[mask], np.full(mask.sum(), y.mean()))
            ),
        }
        logger.info(f"CV metrics: {metrics}")

        # calibration on OOF only
        self.calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        self.calibrator.fit(oof_pred[mask], y[mask])

        # final model on all data with median early-stopped rounds
        rounds = int(np.median(best_iters)) if best_iters else 200
        self.model = lgb.train(LGB_PARAMS,
                               lgb.Dataset(X, label=y, feature_name=self.feature_names),
                               num_boost_round=rounds)
        metrics["final_num_rounds"] = rounds
        return metrics

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Calibrated P(YRFI)."""
        if self.model is None or self.calibrator is None:
            raise RuntimeError("model/calibrator not loaded - refusing to guess")
        raw = self.model.predict(X)
        return self.calibrator.predict(raw)

    # ------------------------------------------------------------ persist

    def save_model(self, model_dir: str, version: str | None = None,
                   metrics: Dict | None = None) -> str:
        version = version or datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs(model_dir, exist_ok=True)
        self.model.save_model(os.path.join(model_dir, f"nrfi_model_{version}.txt"))
        joblib.dump(self.calibrator, os.path.join(model_dir, f"nrfi_calibrator_{version}.pkl"))
        with open(os.path.join(model_dir, f"nrfi_meta_{version}.json"), "w") as fh:
            json.dump({"version": version,
                       "feature_names": self.feature_names,
                       "metrics": metrics or {},
                       "created_at": datetime.now().isoformat()}, fh, indent=2)
        logger.info(f"saved model version {version}")
        return version

    def load_model(self, model_dir: str, version: str) -> None:
        self.model = lgb.Booster(model_file=os.path.join(model_dir, f"nrfi_model_{version}.txt"))
        self.calibrator = joblib.load(os.path.join(model_dir, f"nrfi_calibrator_{version}.pkl"))
        with open(os.path.join(model_dir, f"nrfi_meta_{version}.json")) as fh:
            self.feature_names = json.load(fh)["feature_names"]
        logger.info(f"loaded model version {version}")

    def register_model(self, version: str, metrics: Dict, status: str = "candidate") -> None:
        self.sf.merge_upsert(
            "NRFI_DB.ML.MODEL_STATUS",
            [{
                "model_version": version,
                "trained_at": datetime.now().isoformat(),
                "cv_logloss": metrics.get("oof_logloss"),
                "cv_brier": metrics.get("oof_brier"),
                "gate_report": json.dumps(metrics),
                "status": status,
            }],
            key_cols=["model_version"],
        )


def main() -> None:
    trainer = NFRIModelTrainer()
    games = trainer.load_training_data("2015-04-01", "2024-11-30")
    X, y, dates = trainer.prepare_features(games)
    metrics = trainer.train_model(X, y, dates)
    version = trainer.save_model(trainer.config.MODEL_DIR, metrics=metrics)
    trainer.register_model(version, metrics, status="candidate")
    logger.info(f"training complete: {version} {json.dumps(metrics, indent=2)}")
    # NOTE: 2025 is the LOCKED holdout. It is evaluated once, at release,
    # by scripts/evaluate_holdout.py (Phase 2) - never inside routine training.


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    main()
