"""Model training, calibration, persistence.

Primary model: HistGradientBoostingClassifier (native NaN handling, strong
regularisation for a low-signal binary target) with an isotonic calibration
layer fit on a chronologically-held-out tail of the training window, so
reported probabilities are honest out-of-time estimates rather than
overconfident resubstitution scores.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression

from nrfi import __version__
from nrfi.config import TrainConfig
from nrfi.features import FEATURE_COLUMNS, WEATHER_FEATURES

ALL_FEATURES = FEATURE_COLUMNS + WEATHER_FEATURES

MODEL_FILENAME = "nrfi_model.joblib"
METADATA_FILENAME = "nrfi_model_metadata.json"

PROB_FLOOR = 0.02
PROB_CEIL = 0.98


@dataclass
class NRFIModel:
    estimator: HistGradientBoostingClassifier
    calibrator: IsotonicRegression | None
    features: list[str]
    metadata: dict

    def predict_yrfi_proba(self, frame: pd.DataFrame) -> np.ndarray:
        matrix = frame.reindex(columns=self.features).to_numpy(dtype=float)
        raw = self.estimator.predict_proba(matrix)[:, 1]
        if self.calibrator is not None:
            raw = self.calibrator.predict(raw)
        return np.clip(raw, PROB_FLOOR, PROB_CEIL)

    def save(self, models_dir: Path) -> tuple[Path, Path]:
        models_dir.mkdir(parents=True, exist_ok=True)
        model_path = models_dir / MODEL_FILENAME
        meta_path = models_dir / METADATA_FILENAME
        joblib.dump(
            {"estimator": self.estimator, "calibrator": self.calibrator, "features": self.features},
            model_path,
            compress=3,
        )
        meta_path.write_text(json.dumps(self.metadata, indent=2, sort_keys=True))
        return model_path, meta_path

    @classmethod
    def load(cls, models_dir: Path) -> NRFIModel:
        payload = joblib.load(models_dir / MODEL_FILENAME)
        meta_path = models_dir / METADATA_FILENAME
        metadata = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        return cls(
            estimator=payload["estimator"],
            calibrator=payload.get("calibrator"),
            features=list(payload["features"]),
            metadata=metadata,
        )


def trainable_rows(features_frame: pd.DataFrame) -> pd.DataFrame:
    """Rows eligible for supervised training/evaluation.

    Requires a valid label and both probable pitchers known, so training
    rows carry the same information the live predictor requires.
    """
    mask = (
        features_frame["label_valid"].fillna(False).astype(bool)
        & features_frame["yrfi"].notna()
        & features_frame["home_probable_pitcher_id"].notna()
        & features_frame["away_probable_pitcher_id"].notna()
    )
    return features_frame.loc[mask]


def _make_estimator(cfg: TrainConfig) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        loss="log_loss",
        learning_rate=cfg.learning_rate,
        max_leaf_nodes=cfg.max_leaf_nodes,
        min_samples_leaf=cfg.min_samples_leaf,
        l2_regularization=cfg.l2_regularization,
        max_iter=cfg.max_iter,
        early_stopping=True,
        validation_fraction=cfg.early_stopping_fraction,
        n_iter_no_change=25,
        random_state=cfg.random_state,
    )


def fit_model(train_frame: pd.DataFrame, cfg: TrainConfig | None = None) -> NRFIModel:
    """Fit estimator + isotonic calibrator on a chronological split.

    The last ~15% of the window (by date) is held out for calibration only.
    """
    cfg = cfg or TrainConfig()
    rows = trainable_rows(train_frame).sort_values("game_date", kind="stable")
    if len(rows) < 500:
        raise ValueError(f"not enough trainable rows to fit a model: {len(rows)}")

    split = int(len(rows) * 0.85)
    fit_rows, cal_rows = rows.iloc[:split], rows.iloc[split:]

    x_fit = fit_rows.reindex(columns=ALL_FEATURES).to_numpy(dtype=float)
    # Columns with no observed values at all (e.g. weather disabled) break
    # HGB's binning; neutralize them to a constant so the tree ignores them.
    all_nan_cols = np.where(np.all(np.isnan(x_fit), axis=0))[0]
    x_fit[:, all_nan_cols] = 0.0
    y_fit = fit_rows["yrfi"].to_numpy(dtype=float)
    estimator = _make_estimator(cfg)
    estimator.fit(x_fit, y_fit)

    calibrator = None
    if len(cal_rows) >= 300:
        x_cal = cal_rows.reindex(columns=ALL_FEATURES).to_numpy(dtype=float)
        x_cal[:, all_nan_cols] = 0.0
        y_cal = cal_rows["yrfi"].to_numpy(dtype=float)
        raw = estimator.predict_proba(x_cal)[:, 1]
        calibrator = IsotonicRegression(y_min=PROB_FLOOR, y_max=PROB_CEIL, out_of_bounds="clip")
        calibrator.fit(raw, y_cal)

    metadata = {
        "package_version": __version__,
        "trained_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "n_trainable_rows": int(len(rows)),
        "n_fit_rows": int(len(fit_rows)),
        "n_calibration_rows": int(len(cal_rows)),
        "train_date_min": str(rows["game_date"].min()),
        "train_date_max": str(rows["game_date"].max()),
        "base_rate_yrfi": float(rows["yrfi"].mean()),
        "features": ALL_FEATURES,
        "unobserved_features": [ALL_FEATURES[i] for i in all_nan_cols],
        "calibrated": calibrator is not None,
    }
    return NRFIModel(estimator=estimator, calibrator=calibrator, features=list(ALL_FEATURES), metadata=metadata)
