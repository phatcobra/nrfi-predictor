"""LOCKED 2025 holdout evaluation - runs ONCE per released model.

Refuses to run if the model already has holdout metrics (the holdout is
burned by iteration). --acknowledge-burn is required to override, and the
override itself is recorded in the gate report.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from sklearn.metrics import brier_score_loss, log_loss

from nrfi._obs import logger
from nrfi.snowflake_loader import SnowflakeLoader
from nrfi.train import NFRIModelTrainer


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--acknowledge-burn", action="store_true")
    args = ap.parse_args()

    sf = SnowflakeLoader()
    existing = sf.execute_query(
        "SELECT holdout_logloss FROM NRFI_DB.ML.MODEL_STATUS WHERE model_version = %s",
        [args.version])
    if existing and existing[0].get("holdout_logloss") is not None \
            and not args.acknowledge_burn:
        raise SystemExit(
            "holdout already evaluated for this model. Re-running means the "
            "2025 holdout is burned; pass --acknowledge-burn to record that.")

    trainer = NFRIModelTrainer()
    trainer.load_model(trainer.config.MODEL_DIR, args.version)
    games = trainer.load_training_data("2025-03-01", "2025-11-30")
    X, y, _, kept = trainer.prepare_features(games)
    p = np.clip(trainer.predict_proba(X), 1e-6, 1 - 1e-6)
    metrics = {
        "holdout_logloss": float(log_loss(y, p)),
        "holdout_brier": float(brier_score_loss(y, p)),
        "holdout_n": int(len(y)),
        "burned_rerun": bool(args.acknowledge_burn and existing
                             and existing[0].get("holdout_logloss") is not None),
    }
    sf.merge_upsert("NRFI_DB.ML.MODEL_STATUS", [{
        "model_version": args.version,
        "holdout_logloss": metrics["holdout_logloss"],
        "holdout_brier": metrics["holdout_brier"],
    }], key_cols=["model_version"])
    logger.info(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
