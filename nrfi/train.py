"""Train, calibrate, persist, and register a fail-closed NRFI candidate."""

from __future__ import annotations

import json
import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Tuple

import joblib
import numpy as np
import pandas as pd

from nrfi._obs import sentry_sdk
from nrfi.build_features import FeatureBuilder, coverage
from nrfi.config import CV_PURGE_DAYS, Config
from nrfi.data_readiness import require_warehouse_ready
from nrfi.ensemble import StackedEnsemble
from nrfi.probability import (
    FINAL_PROBABILITY_PIPELINE_VERSION,
    HOLDOUT_EVIDENCE_CONTRACT_VERSION,
    OOF_EVIDENCE_CONTRACT_VERSION,
    canonical_probability,
    temporal_calibration_evidence,
)
from nrfi.snowflake_loader import SnowflakeLoader
from nrfi.venn_abers import VennAbersCalibrator

logger = logging.getLogger(__name__)

if os.getenv("SENTRY_DSN"):
    sentry_sdk.init(
        dsn=os.getenv("SENTRY_DSN"),
        environment=os.getenv("ENV", "development"),
        traces_sample_rate=0.1,
    )


class NFRIModelTrainer:
    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        self.sf = SnowflakeLoader()
        self.ensemble: StackedEnsemble | None = None
        self.calibrator: VennAbersCalibrator | None = None
        self.venue_yrfi_rates: Dict[str, float] = {}
        self.feature_names: List[str] = []
        self._final_oof_scores = np.array([], dtype=float)
        self._final_oof_mask = np.array([], dtype=bool)

    def load_training_data(
        self, start_date: str, end_date: str, allow_holdout: bool = False
    ) -> pd.DataFrame:
        """Load labels while refusing holdout overlap unless explicitly evaluating it."""
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)
        if start > end:
            raise ValueError("start_date must be on or before end_date")
        if not allow_holdout and end > pd.Timestamp(self.config.TRAIN_END_DATE):
            raise ValueError(
                f"training end {end.date()} crosses locked cutoff "
                f"{self.config.TRAIN_END_DATE}"
            )

        query = """
        SELECT game_id, game_date, away_team, home_team,
               away_sp_id AS away_pitcher_id, home_sp_id AS home_pitcher_id,
               venue_id, is_doubleheader,
               CASE WHEN (fi_runs_top + fi_runs_bottom) > 0 THEN 1 ELSE 0 END AS yrfi
        FROM NRFI_DB.CORE.FIRST_INNING_OUTCOMES
        WHERE game_date >= %s AND game_date <= %s
          AND fi_runs_top IS NOT NULL AND fi_runs_bottom IS NOT NULL
        ORDER BY game_date, game_id
        """
        frame = pd.DataFrame(self.sf.execute_query(query, [start_date, end_date]))
        if frame.empty:
            raise ValueError(f"no labeled games found for {start_date}..{end_date}")
        required = {
            "game_id",
            "game_date",
            "away_team",
            "home_team",
            "away_pitcher_id",
            "home_pitcher_id",
            "venue_id",
            "yrfi",
        }
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"labeled-game query missing columns: {sorted(missing)}")
        frame["game_date"] = pd.to_datetime(frame["game_date"], errors="raise")
        duplicate_ids = frame["game_id"].astype(str).duplicated(keep=False)
        if duplicate_ids.any():
            examples = frame.loc[duplicate_ids, "game_id"].astype(str).head(5).tolist()
            raise ValueError(f"duplicate game_id rows in labels: {examples}")
        frame = frame.sort_values(["game_date", "game_id"]).reset_index(drop=True)
        logger.info(f"loaded {len(frame)} labeled games {start_date}..{end_date}")
        return frame

    def prepare_features(
        self,
        games_df: pd.DataFrame,
        builder: FeatureBuilder | None = None,
    ) -> Tuple[np.ndarray, np.ndarray, pd.Series, pd.DataFrame]:
        if games_df is None or games_df.empty:
            raise ValueError("cannot prepare features from an empty game set")
        games_df = games_df.copy()
        games_df["game_date"] = pd.to_datetime(games_df["game_date"], errors="raise")
        games_df = games_df.sort_values(["game_date", "game_id"]).reset_index(drop=True)

        builder = builder or FeatureBuilder(self.sf)
        builder.prepare(max_date=games_df["game_date"].max().date().isoformat())
        feature_dicts: list[dict] = []
        labels: list[int] = []
        dates: list[pd.Timestamp] = []
        kept_rows: list[pd.Series] = []
        dropped = 0

        for _, game in games_df.iterrows():
            try:
                features = builder.build_game(game.to_dict())
            except Exception as exc:
                sentry_sdk.capture_exception(exc)
                dropped += 1
                continue
            if coverage(features) < self.config.FEATURE_COVERAGE_MIN:
                dropped += 1
                continue
            label = int(game["yrfi"])
            if label not in (0, 1):
                raise ValueError(
                    f"invalid YRFI label {label} for game {game['game_id']}"
                )
            feature_dicts.append(features)
            labels.append(label)
            dates.append(pd.Timestamp(game["game_date"]))
            kept_rows.append(game)

        if not feature_dicts:
            raise ValueError(
                "all games were dropped by feature construction/coverage gates"
            )
        batch_feature_names = sorted(
            {name for values in feature_dicts for name in values}
        )
        if not batch_feature_names:
            raise ValueError("feature builder returned no feature columns")
        if self.feature_names and batch_feature_names != self.feature_names:
            missing = sorted(set(self.feature_names).difference(batch_feature_names))
            unexpected = sorted(set(batch_feature_names).difference(self.feature_names))
            raise ValueError(
                "evaluation feature contract differs from loaded model: "
                f"missing={missing}, unexpected={unexpected}"
            )
        if not self.feature_names:
            self.feature_names = batch_feature_names

        matrix = np.array(
            [
                [values.get(name, np.nan) for name in self.feature_names]
                for values in feature_dicts
            ],
            dtype=float,
        )
        targets = np.asarray(labels, dtype=int)
        date_series = pd.Series(dates).reset_index(drop=True)
        kept = pd.DataFrame(kept_rows).reset_index(drop=True)
        if len(np.unique(targets)) < 2:
            raise ValueError("prepared training set contains only one target class")
        if not date_series.is_monotonic_increasing:
            raise ValueError("prepared training dates are not chronological")
        logger.info(
            f"{matrix.shape[0]}x{matrix.shape[1]} "
            f"(dropped {dropped} low-coverage); YRFI rate {targets.mean():.3f}"
        )
        return matrix, targets, date_series, kept

    def train(
        self, X: np.ndarray, y: np.ndarray, dates: pd.Series, kept_games: pd.DataFrame
    ) -> Dict:
        dates = pd.Series(pd.to_datetime(dates, errors="raise")).reset_index(drop=True)
        if dates.empty:
            raise ValueError("training dates are empty")
        if dates.max() > pd.Timestamp(self.config.TRAIN_END_DATE):
            raise ValueError(
                f"training data reaches {dates.max().date()}, beyond locked cutoff "
                f"{self.config.TRAIN_END_DATE}"
            )
        if len(kept_games) != len(y):
            raise ValueError("kept_games and target row counts differ")

        self.ensemble = StackedEnsemble(purge_days=CV_PURGE_DAYS)
        self.calibrator = None
        report = self.ensemble.fit(X, y, dates, self.feature_names)
        mask = self.ensemble._oof_mask
        if mask.sum() < 50:
            raise ValueError("insufficient OOF rows for probability calibration")
        baseline_scores = getattr(self.ensemble, "_baseline_oof_scores", None)
        if baseline_scores is None:
            raise ValueError("ensemble omitted prior-only OOF baseline predictions")
        raw_stack_gates_passed = bool(report.get("gates_passed"))
        final_report, final_scores, final_mask = temporal_calibration_evidence(
            self.ensemble._oof_scores,
            baseline_scores,
            y,
            dates,
            n_folds=self.ensemble.n_folds,
            purge_days=self.ensemble.purge_days,
        )
        final_report["raw_stack_gates_passed"] = raw_stack_gates_passed
        final_report["gates_passed"] = bool(
            raw_stack_gates_passed and final_report["gates_passed"]
        )
        report["raw_stack_gates_passed"] = raw_stack_gates_passed
        report["final_probability_oof"] = final_report
        report["probability_pipeline_version"] = FINAL_PROBABILITY_PIPELINE_VERSION
        report["oof_evidence_contract_version"] = OOF_EVIDENCE_CONTRACT_VERSION
        report["holdout_evidence_contract_version"] = HOLDOUT_EVIDENCE_CONTRACT_VERSION
        report["gates_passed"] = final_report["gates_passed"]
        self._final_oof_scores = final_scores
        self._final_oof_mask = final_mask
        if report["gates_passed"]:
            self.calibrator = VennAbersCalibrator().fit(
                self.ensemble._oof_scores[mask], y[mask]
            )

        venue_frame = kept_games.assign(yrfi=np.asarray(y, dtype=int))
        venue_rates = venue_frame.groupby("venue_id", dropna=True)["yrfi"].agg(
            ["mean", "count"]
        )
        self.venue_yrfi_rates = {
            str(venue_id): float(values["mean"])
            for venue_id, values in venue_rates.iterrows()
            if int(values["count"]) >= 50
        }
        report.update(
            {
                "n_training_rows": int(len(y)),
                "training_start": dates.min().date().isoformat(),
                "training_end": dates.max().date().isoformat(),
                "locked_training_cutoff": self.config.TRAIN_END_DATE,
                "n_venues_with_rates": len(self.venue_yrfi_rates),
            }
        )
        return report

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if self.ensemble is None or self.calibrator is None:
            raise RuntimeError("model not loaded - refusing to guess")
        probabilities = canonical_probability(
            self.calibrator.predict(self.ensemble.raw_scores(X))
        )
        return probabilities

    @staticmethod
    def _sha256(path: str) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as file_handle:
            for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def save_model(
        self, model_dir: str, version: str | None = None, metrics: Dict | None = None
    ) -> str:
        if self.ensemble is None or self.calibrator is None:
            raise RuntimeError("cannot save an unfitted model")
        if metrics is not None and not metrics.get("gates_passed", False):
            raise ValueError("refusing to persist a model that failed evidence gates")
        version = version or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        os.makedirs(model_dir, exist_ok=True)
        bundle_path = os.path.join(model_dir, f"nrfi_bundle_{version}.joblib")
        metadata_path = os.path.join(model_dir, f"nrfi_meta_{version}.json")
        temporary_bundle = f"{bundle_path}.tmp"
        temporary_metadata = f"{metadata_path}.tmp"

        joblib.dump(
            {
                "ensemble": self.ensemble,
                "calibrator_arrays": self.calibrator.to_arrays(),
                "venue_yrfi_rates": self.venue_yrfi_rates,
                "feature_names": self.feature_names,
            },
            temporary_bundle,
        )
        artifact_sha256 = self._sha256(temporary_bundle)
        if metrics is not None:
            metrics["artifact_sha256"] = artifact_sha256
        with open(temporary_metadata, "w", encoding="utf-8") as file_handle:
            json.dump(
                {
                    "version": version,
                    "artifact_sha256": artifact_sha256,
                    "probability_pipeline_version": FINAL_PROBABILITY_PIPELINE_VERSION,
                    "oof_evidence_contract_version": OOF_EVIDENCE_CONTRACT_VERSION,
                    "holdout_evidence_contract_version": HOLDOUT_EVIDENCE_CONTRACT_VERSION,
                    "feature_names": self.feature_names,
                    "metrics": metrics or {},
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
                file_handle,
                indent=2,
                default=float,
            )
        os.replace(temporary_bundle, bundle_path)
        os.replace(temporary_metadata, metadata_path)
        logger.info(f"saved model bundle {version}")
        return version

    def load_model(
        self, model_dir: str, version: str, expected_artifact_sha256: str | None = None
    ) -> None:
        bundle_path = os.path.join(model_dir, f"nrfi_bundle_{version}.joblib")
        metadata_path = os.path.join(model_dir, f"nrfi_meta_{version}.json")
        if not os.path.exists(bundle_path) or not os.path.exists(metadata_path):
            raise FileNotFoundError(f"model version {version} is incomplete")
        with open(metadata_path, encoding="utf-8") as file_handle:
            metadata = json.load(file_handle)
        if metadata.get("version") != version:
            raise ValueError("model metadata version does not match requested version")
        if (
            metadata.get("probability_pipeline_version")
            != FINAL_PROBABILITY_PIPELINE_VERSION
        ):
            raise ValueError("model metadata probability pipeline is unsupported")
        if (
            metadata.get("oof_evidence_contract_version")
            != OOF_EVIDENCE_CONTRACT_VERSION
        ):
            raise ValueError("model metadata OOF evidence contract is unsupported")
        if (
            metadata.get("holdout_evidence_contract_version")
            != HOLDOUT_EVIDENCE_CONTRACT_VERSION
        ):
            raise ValueError("model metadata holdout evidence contract is unsupported")
        recorded_digest = str(metadata.get("artifact_sha256") or "")
        actual_digest = self._sha256(bundle_path)
        if recorded_digest != actual_digest:
            raise ValueError("model artifact SHA-256 does not match metadata")
        if (
            expected_artifact_sha256 is not None
            and actual_digest != expected_artifact_sha256
        ):
            raise ValueError("model artifact SHA-256 does not match registry")
        bundle = joblib.load(bundle_path)
        required = {
            "ensemble",
            "calibrator_arrays",
            "venue_yrfi_rates",
            "feature_names",
        }
        missing = required.difference(bundle)
        if missing:
            raise ValueError(f"model bundle missing keys: {sorted(missing)}")
        self.ensemble = bundle["ensemble"]
        self.calibrator = VennAbersCalibrator.from_arrays(bundle["calibrator_arrays"])
        self.venue_yrfi_rates = dict(bundle["venue_yrfi_rates"])
        self.feature_names = list(bundle["feature_names"])
        if self.feature_names != list(metadata.get("feature_names", [])):
            raise ValueError("bundle and metadata feature contracts differ")
        logger.info(f"loaded model bundle {version}")

    def register_model(
        self, version: str, metrics: Dict, status: str = "candidate"
    ) -> None:
        training_start = metrics.get("training_start")
        training_end = metrics.get("training_end")
        train_range = (
            f"{training_start}..{training_end}"
            if training_start and training_end
            else None
        )
        final_oof = metrics.get("final_probability_oof", {})
        artifact_sha256 = metrics.get("artifact_sha256")
        if status == "candidate":
            if (
                metrics.get("probability_pipeline_version")
                != FINAL_PROBABILITY_PIPELINE_VERSION
                or metrics.get("oof_evidence_contract_version")
                != OOF_EVIDENCE_CONTRACT_VERSION
                or metrics.get("holdout_evidence_contract_version")
                != HOLDOUT_EVIDENCE_CONTRACT_VERSION
                or not isinstance(artifact_sha256, str)
                or len(artifact_sha256) != 64
                or any(
                    character not in "0123456789abcdef" for character in artifact_sha256
                )
            ):
                raise ValueError(
                    "candidate lacks versioned probability artifact evidence"
                )
        self.sf.merge_upsert(
            "NRFI_DB.ML.MODEL_STATUS",
            [
                {
                    "model_version": version,
                    "trained_at": datetime.now(timezone.utc).isoformat(),
                    "feature_version": "fv3.1",
                    "probability_pipeline_version": metrics.get(
                        "probability_pipeline_version"
                    ),
                    "oof_evidence_contract_version": metrics.get(
                        "oof_evidence_contract_version"
                    ),
                    "holdout_evidence_contract_version": metrics.get(
                        "holdout_evidence_contract_version"
                    ),
                    "artifact_sha256": artifact_sha256,
                    "train_range": train_range,
                    "cv_logloss": final_oof.get("final_probability", {}).get("logloss"),
                    "cv_brier": final_oof.get("final_probability", {}).get("brier"),
                    "gates_passed": metrics.get("gates_passed"),
                    "gate_report": json.dumps(metrics, default=float),
                    "status": status,
                }
            ],
            key_cols=["model_version"],
        )


def main() -> None:
    trainer = NFRIModelTrainer()
    readiness = require_warehouse_ready(trainer.sf)
    logger.info(
        f"warehouse ready for {readiness['training_window']['start']}.."
        f"{readiness['training_window']['end']}"
    )
    games = trainer.load_training_data(
        trainer.config.TRAIN_START_DATE, trainer.config.TRAIN_END_DATE
    )
    X, y, dates, kept = trainer.prepare_features(games)
    report = trainer.train(X, y, dates, kept)
    report["warehouse_readiness"] = readiness
    version = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if not report.get("gates_passed"):
        trainer.register_model(version, report, status="rejected")
        raise SystemExit("training evidence gates failed; no model bundle written")
    trainer.save_model(trainer.config.MODEL_DIR, version=version, metrics=report)
    trainer.register_model(version, report, status="candidate")
    logger.info(f"candidate {version}: gates_passed=True")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    main()
