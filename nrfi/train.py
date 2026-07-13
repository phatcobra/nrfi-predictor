"""Training orchestration: builder -> gated stack -> Venn-ABERS -> registry.

Redlines: candidate models are registered as 'candidate' and shipped via
retrain_weekly's PR for HUMAN MERGE. Nothing here deploys itself. The 2025
holdout is evaluated only by scripts/evaluate_holdout.py, once, at release.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Tuple

import joblib
import numpy as np
import pandas as pd

from nrfi._obs import sentry_sdk
from nrfi.build_features import FeatureBuilder, coverage
from nrfi.config import CV_PURGE_DAYS, Config
from nrfi.ensemble import StackedEnsemble
from nrfi.snowflake_loader import SnowflakeLoader
from nrfi.venn_abers import VennAbersCalibrator

logger = logging.getLogger(__name__)

if os.getenv("SENTRY_DSN"):
    sentry_sdk.init(dsn=os.getenv("SENTRY_DSN"),
                    environment=os.getenv("ENV", "development"),
                    traces_sample_rate=0.1)


class NFRIModelTrainer:
    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        self.sf = SnowflakeLoader()
        self.ensemble: StackedEnsemble | None = None
        self.calibrator: VennAbersCalibrator | None = None
        self.venue_yrfi_rates: Dict[str, float] = {}
        self.feature_names: List[str] = []

    # ------------------------------------------------------------- data

    def load_training_data(self, start_date: str, end_date: str) -> pd.DataFrame:
        query = """
        SELECT game_id, game_date, away_team, home_team,
               away_sp_id AS away_pitcher_id, home_sp_id AS home_pitcher_id,
               venue_id, is_doubleheader,
               CASE WHEN (fi_runs_top + fi_runs_bottom) > 0 THEN 1 ELSE 0 END AS yrfi
        FROM NRFI_DB.CORE.FIRST_INNING_OUTCOMES
        WHERE game_date >= %s AND game_date <= %s
          AND fi_runs_top IS NOT NULL AND fi_runs_bottom IS NOT NULL
        ORDER BY game_date
        """
        df = pd.DataFrame(self.sf.execute_query(query, [start_date, end_date]))
        logger.info(f"loaded {len(df)} labeled games {start_date}..{end_date}")
        return df

    def prepare_features(self, games_df: pd.DataFrame,
                         builder: FeatureBuilder | None = None
                         ) -> Tuple[np.ndarray, np.ndarray, pd.Series, pd.DataFrame]:
        builder = builder or FeatureBuilder(self.sf)
        builder.prepare(max_date=str(games_df["game_date"].max()))
        feats, labels, dates, kept = [], [], [], []
        dropped = 0
        for _, game in games_df.iterrows():
            try:
                f = builder.build_game(game.to_dict())
            except Exception as e:
                sentry_sdk.capture_exception(e)
                dropped += 1
                continue
            if coverage(f) < self.config.FEATURE_COVERAGE_MIN:
                dropped += 1
                continue
            feats.append(f)
            labels.append(int(game["yrfi"]))
            dates.append(pd.to_datetime(game["game_date"]))
            kept.append(game)
        self.feature_names = sorted({k for f in feats for k in f})
        X = np.array([[f.get(n, np.nan) for n in self.feature_names] for f in feats],
                     dtype=float)
        y = np.array(labels, dtype=int)
        logger.info(f"{X.shape[0]}x{X.shape[1]} (dropped {dropped} low-coverage); "
                    f"YRFI rate {y.mean():.3f}")
        return X, y, pd.Series(dates), pd.DataFrame(kept)

    # ---------------------------------------------------------- training

    def train(self, X: np.ndarray, y: np.ndarray, dates: pd.Series,
              kept_games: pd.DataFrame) -> Dict:
        self.ensemble = StackedEnsemble(purge_days=CV_PURGE_DAYS)
        report = self.ensemble.fit(X, y, dates, self.feature_names)

        mask = self.ensemble._oof_mask
        self.calibrator = VennAbersCalibrator().fit(
            self.ensemble._oof_scores[mask], y[mask])

        # venue YRFI base rates (training rows only - no leakage)
        vr = (kept_games.assign(yrfi=y)
              .groupby("venue_id")["yrfi"].agg(["mean", "count"]))
        self.venue_yrfi_rates = {
            str(k): float(v["mean"]) for k, v in vr.iterrows() if v["count"] >= 50}
        report["n_venues_with_rates"] = len(self.venue_yrfi_rates)
        return report

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Calibrated P(YRFI). Venue shrinkage is applied by the caller,
        which knows venue + evidence (see ensemble.shrink_to_venue)."""
        if self.ensemble is None or self.calibrator is None:
            raise RuntimeError("model not loaded - refusing to guess")
        return self.calibrator.predict(self.ensemble.raw_scores(X))

    # ----------------------------------------------------------- persist

    def save_model(self, model_dir: str, version: str | None = None,
                   metrics: Dict | None = None) -> str:
        version = version or datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs(model_dir, exist_ok=True)
        joblib.dump({
            "ensemble": self.ensemble,
            "calibrator_arrays": self.calibrator.to_arrays(),
            "venue_yrfi_rates": self.venue_yrfi_rates,
            "feature_names": self.feature_names,
        }, os.path.join(model_dir, f"nrfi_bundle_{version}.joblib"))
        with open(os.path.join(model_dir, f"nrfi_meta_{version}.json"), "w") as fh:
            json.dump({"version": version, "feature_names": self.feature_names,
                       "metrics": metrics or {},
                       "created_at": datetime.now().isoformat()}, fh, indent=2,
                      default=float)
        logger.info(f"saved model bundle {version}")
        return version

    def load_model(self, model_dir: str, version: str) -> None:
        bundle = joblib.load(os.path.join(model_dir, f"nrfi_bundle_{version}.joblib"))
        self.ensemble = bundle["ensemble"]
        self.calibrator = VennAbersCalibrator.from_arrays(bundle["calibrator_arrays"])
        self.venue_yrfi_rates = bundle["venue_yrfi_rates"]
        self.feature_names = bundle["feature_names"]
        logger.info(f"loaded model bundle {version}")

    def register_model(self, version: str, metrics: Dict,
                       status: str = "candidate") -> None:
        self.sf.merge_upsert("NRFI_DB.ML.MODEL_STATUS", [{
            "model_version": version,
            "trained_at": datetime.now().isoformat(),
            "feature_version": "fv3.1",
            "cv_logloss": metrics.get("stack", {}).get("logloss"),
            "cv_brier": metrics.get("stack", {}).get("brier"),
            "gates_passed": metrics.get("gates_passed"),
            "gate_report": json.dumps(metrics, default=float),
            "status": status,
        }], key_cols=["model_version"])


def main() -> None:
    trainer = NFRIModelTrainer()
    games = trainer.load_training_data("2015-04-01", "2024-11-30")
    X, y, dates, kept = trainer.prepare_features(games)
    report = trainer.train(X, y, dates, kept)
    version = trainer.save_model(trainer.config.MODEL_DIR, metrics=report)
    trainer.register_model(version, report, status="candidate")
    logger.info(f"candidate {version}: gates_passed={report['gates_passed']}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    main()
