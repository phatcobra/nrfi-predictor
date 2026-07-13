"""Evaluate the locked holdout exactly once for a gated candidate model.

The evaluator verifies that the model's recorded training end predates the
holdout, compares against the predeclared training climatology baseline, and
records an explicit pass/fail decision. Re-evaluation requires a burn override.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from nrfi._obs import logger
from nrfi.snowflake_loader import SnowflakeLoader
from nrfi.train import NFRIModelTrainer

MIN_LOGLOSS_IMPROVEMENT = 0.001
MIN_BRIER_IMPROVEMENT = 0.0005


def _read_metadata(model_dir: str, version: str) -> dict:
    path = os.path.join(model_dir, f"nrfi_meta_{version}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"model metadata not found: {path}")
    with open(path, encoding="utf-8") as file_handle:
        metadata = json.load(file_handle)
    if metadata.get("version") != version:
        raise ValueError("metadata version does not match requested model")
    return metadata


def _existing_gate_report(value: object) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--acknowledge-burn", action="store_true")
    args = parser.parse_args()

    trainer = NFRIModelTrainer()
    warehouse = SnowflakeLoader()
    existing_rows = warehouse.execute_query(
        """
        SELECT model_version, status, gates_passed, gate_report,
               holdout_logloss, holdout_brier, holdout_evaluated_at
        FROM NRFI_DB.ML.MODEL_STATUS
        WHERE model_version = %s
        """,
        [args.version],
    )
    if not existing_rows:
        raise SystemExit("candidate is not registered; holdout evaluation refused")
    existing = existing_rows[0]
    if not bool(existing.get("gates_passed")):
        raise SystemExit("candidate failed OOF gates; holdout must not be opened")
    previously_evaluated = existing.get("holdout_evaluated_at") is not None
    if previously_evaluated and not args.acknowledge_burn:
        raise SystemExit(
            "holdout already evaluated for this model. Re-running burns the "
            "locked evidence; pass --acknowledge-burn to record the override.")

    metadata = _read_metadata(trainer.config.MODEL_DIR, args.version)
    training_metrics = metadata.get("metrics") or {}
    recorded_training_end = training_metrics.get("training_end")
    if not recorded_training_end:
        raise SystemExit("model metadata lacks a recorded training_end")
    if pd.Timestamp(recorded_training_end) >= pd.Timestamp(
            trainer.config.HOLDOUT_START_DATE):
        raise SystemExit(
            f"candidate training end {recorded_training_end} overlaps locked "
            f"holdout beginning {trainer.config.HOLDOUT_START_DATE}")

    baseline_rate = training_metrics.get("baseline_constant", {}).get("rate")
    try:
        baseline_rate = float(baseline_rate)
    except (TypeError, ValueError):
        raise SystemExit("model metadata lacks a valid pre-holdout baseline rate")
    if not 0.0 < baseline_rate < 1.0:
        raise SystemExit("pre-holdout baseline rate must be strictly between 0 and 1")

    trainer.load_model(trainer.config.MODEL_DIR, args.version)
    games = trainer.load_training_data(
        trainer.config.HOLDOUT_START_DATE,
        trainer.config.HOLDOUT_END_DATE,
        allow_holdout=True,
    )
    X, y, _, _ = trainer.prepare_features(games)
    probabilities = np.clip(trainer.predict_proba(X), 1e-6, 1 - 1e-6)
    baseline_probabilities = np.full(len(y), baseline_rate, dtype=float)

    model_logloss = float(log_loss(y, probabilities))
    model_brier = float(brier_score_loss(y, probabilities))
    baseline_logloss = float(log_loss(y, baseline_probabilities))
    baseline_brier = float(brier_score_loss(y, baseline_probabilities))
    logloss_improvement = baseline_logloss - model_logloss
    brier_improvement = baseline_brier - model_brier
    passed = (
        logloss_improvement >= MIN_LOGLOSS_IMPROVEMENT
        and brier_improvement >= MIN_BRIER_IMPROVEMENT
    )

    holdout_report = {
        "model_version": args.version,
        "holdout_start": trainer.config.HOLDOUT_START_DATE,
        "holdout_end": trainer.config.HOLDOUT_END_DATE,
        "holdout_n": int(len(y)),
        "holdout_yrfi_rate": float(np.mean(y)),
        "holdout_logloss": model_logloss,
        "holdout_brier": model_brier,
        "holdout_roc_auc": float(roc_auc_score(y, probabilities)),
        "holdout_baseline_rate": baseline_rate,
        "holdout_baseline_logloss": baseline_logloss,
        "holdout_baseline_brier": baseline_brier,
        "holdout_logloss_improvement": logloss_improvement,
        "holdout_brier_improvement": brier_improvement,
        "minimum_logloss_improvement": MIN_LOGLOSS_IMPROVEMENT,
        "minimum_brier_improvement": MIN_BRIER_IMPROVEMENT,
        "holdout_passed": bool(passed),
        "burned_rerun": bool(previously_evaluated and args.acknowledge_burn),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }
    gate_report = _existing_gate_report(existing.get("gate_report"))
    gate_report["locked_holdout"] = holdout_report

    warehouse.merge_upsert("NRFI_DB.ML.MODEL_STATUS", [{
        "model_version": args.version,
        "holdout_logloss": model_logloss,
        "holdout_brier": model_brier,
        "holdout_baseline_logloss": baseline_logloss,
        "holdout_baseline_brier": baseline_brier,
        "holdout_n": int(len(y)),
        "holdout_passed": bool(passed),
        "holdout_evaluated_at": holdout_report["evaluated_at"],
        "holdout_burned_rerun": holdout_report["burned_rerun"],
        "gate_report": json.dumps(gate_report, default=float),
        "status": "candidate" if passed else "rejected",
    }], key_cols=["model_version"])

    logger.info(json.dumps(holdout_report, indent=2))
    if not passed:
        raise SystemExit("locked holdout gate failed; candidate marked rejected")


if __name__ == "__main__":
    main()
