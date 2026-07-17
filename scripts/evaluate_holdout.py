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
from nrfi.probability import (
    FINAL_PROBABILITY_PIPELINE_VERSION,
    HOLDOUT_EVIDENCE_CONTRACT_VERSION,
    OOF_EVIDENCE_CONTRACT_VERSION,
)
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


def _preflight_candidate(
    trainer: NFRIModelTrainer, existing: dict, version: str
) -> tuple[dict, str]:
    """Verify all non-holdout evidence before any locked rows are opened."""
    if (
        existing.get("probability_pipeline_version")
        != FINAL_PROBABILITY_PIPELINE_VERSION
    ):
        raise SystemExit("candidate probability pipeline contract mismatch")
    if existing.get("oof_evidence_contract_version") != OOF_EVIDENCE_CONTRACT_VERSION:
        raise SystemExit("candidate OOF evidence contract mismatch")
    if (
        existing.get("holdout_evidence_contract_version")
        != HOLDOUT_EVIDENCE_CONTRACT_VERSION
    ):
        raise SystemExit("candidate holdout evidence contract mismatch")
    registry_digest = str(existing.get("artifact_sha256") or "")
    if len(registry_digest) != 64 or any(
        character not in "0123456789abcdef" for character in registry_digest
    ):
        raise SystemExit("candidate registry lacks a valid artifact SHA-256")

    metadata = _read_metadata(trainer.config.MODEL_DIR, version)
    if (
        metadata.get("probability_pipeline_version")
        != FINAL_PROBABILITY_PIPELINE_VERSION
    ):
        raise SystemExit("model metadata probability pipeline contract mismatch")
    if metadata.get("oof_evidence_contract_version") != OOF_EVIDENCE_CONTRACT_VERSION:
        raise SystemExit("model metadata OOF evidence contract mismatch")
    if (
        metadata.get("holdout_evidence_contract_version")
        != HOLDOUT_EVIDENCE_CONTRACT_VERSION
    ):
        raise SystemExit("model metadata holdout evidence contract mismatch")
    metadata_digest = str(metadata.get("artifact_sha256") or "")
    bundle_path = os.path.join(
        trainer.config.MODEL_DIR, f"nrfi_bundle_{version}.joblib"
    )
    if not os.path.exists(bundle_path):
        raise SystemExit("candidate model bundle is missing")
    actual_digest = trainer._sha256(bundle_path)
    if not (registry_digest == metadata_digest == actual_digest):
        raise SystemExit("candidate artifact SHA-256 evidence mismatch")
    metrics = metadata.get("metrics") or {}
    final_oof = metrics.get("final_probability_oof") or {}
    if (
        metrics.get("probability_pipeline_version")
        != FINAL_PROBABILITY_PIPELINE_VERSION
        or metrics.get("oof_evidence_contract_version") != OOF_EVIDENCE_CONTRACT_VERSION
        or metrics.get("holdout_evidence_contract_version")
        != HOLDOUT_EVIDENCE_CONTRACT_VERSION
        or not bool(metrics.get("gates_passed"))
        or final_oof.get("oof_evidence_contract_version")
        != OOF_EVIDENCE_CONTRACT_VERSION
        or not bool(final_oof.get("gates_passed"))
    ):
        raise SystemExit("candidate metadata lacks passing final OOF evidence")
    return metadata, actual_digest


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
               holdout_logloss, holdout_brier, holdout_evaluated_at,
               probability_pipeline_version, oof_evidence_contract_version,
               holdout_evidence_contract_version,
               artifact_sha256
        FROM NRFI_DB.ML.MODEL_STATUS
        WHERE model_version = %s
        """,
        [args.version],
    )
    if not existing_rows:
        raise SystemExit("candidate is not registered; holdout evaluation refused")
    existing = existing_rows[0]
    if existing.get("status") != "candidate":
        raise SystemExit("holdout evaluation requires candidate status")
    if not bool(existing.get("gates_passed")):
        raise SystemExit("candidate failed OOF gates; holdout must not be opened")
    previously_evaluated = existing.get("holdout_evaluated_at") is not None
    if previously_evaluated and not args.acknowledge_burn:
        raise SystemExit(
            "holdout already evaluated for this model. Re-running burns the "
            "locked evidence; pass --acknowledge-burn to record the override."
        )

    metadata, artifact_sha256 = _preflight_candidate(trainer, existing, args.version)
    training_metrics = metadata.get("metrics") or {}
    recorded_training_end = training_metrics.get("training_end")
    if not recorded_training_end:
        raise SystemExit("model metadata lacks a recorded training_end")
    if pd.Timestamp(recorded_training_end) >= pd.Timestamp(
        trainer.config.HOLDOUT_START_DATE
    ):
        raise SystemExit(
            f"candidate training end {recorded_training_end} overlaps locked "
            f"holdout beginning {trainer.config.HOLDOUT_START_DATE}"
        )

    baseline_rate = training_metrics.get("baseline_constant", {}).get("deployment_rate")
    try:
        baseline_rate = float(baseline_rate)
    except (TypeError, ValueError):
        raise SystemExit("model metadata lacks a valid pre-holdout baseline rate")
    if not 0.0 < baseline_rate < 1.0:
        raise SystemExit("pre-holdout baseline rate must be strictly between 0 and 1")

    # Burn the evaluation slot before opening locked rows. Any later failure
    # remains recorded and prevents an unacknowledged rerun.
    evaluation_started_at = datetime.now(timezone.utc).isoformat()
    burned_rerun = bool(previously_evaluated)
    warehouse.merge_upsert(
        "NRFI_DB.ML.MODEL_STATUS",
        [
            {
                "model_version": args.version,
                "holdout_evaluated_at": evaluation_started_at,
                "holdout_burned_rerun": burned_rerun,
            }
        ],
        key_cols=["model_version"],
    )

    trainer.load_model(
        trainer.config.MODEL_DIR,
        args.version,
        expected_artifact_sha256=artifact_sha256,
    )
    games = trainer.load_training_data(
        trainer.config.HOLDOUT_START_DATE,
        trainer.config.HOLDOUT_END_DATE,
        allow_holdout=True,
    )
    X, y, _, _ = trainer.prepare_features(games)
    probabilities = trainer.predict_proba(X)
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
        "probability_pipeline_version": FINAL_PROBABILITY_PIPELINE_VERSION,
        "oof_evidence_contract_version": OOF_EVIDENCE_CONTRACT_VERSION,
        "holdout_evidence_contract_version": HOLDOUT_EVIDENCE_CONTRACT_VERSION,
        "artifact_sha256": artifact_sha256,
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
        "burned_rerun": burned_rerun,
        "evaluated_at": evaluation_started_at,
    }
    gate_report = _existing_gate_report(existing.get("gate_report"))
    gate_report["locked_holdout"] = holdout_report

    warehouse.merge_upsert(
        "NRFI_DB.ML.MODEL_STATUS",
        [
            {
                "model_version": args.version,
                "holdout_logloss": model_logloss,
                "holdout_brier": model_brier,
                "holdout_baseline_logloss": baseline_logloss,
                "holdout_baseline_brier": baseline_brier,
                "holdout_n": int(len(y)),
                "holdout_passed": bool(passed),
                "holdout_evaluated_at": holdout_report["evaluated_at"],
                "holdout_burned_rerun": holdout_report["burned_rerun"],
                "holdout_evidence_contract_version": (
                    HOLDOUT_EVIDENCE_CONTRACT_VERSION
                ),
                "gate_report": json.dumps(gate_report, default=float),
                "status": "candidate" if passed else "rejected",
            }
        ],
        key_cols=["model_version"],
    )

    logger.info(json.dumps(holdout_report, indent=2))
    if not passed:
        raise SystemExit("locked holdout gate failed; candidate marked rejected")


if __name__ == "__main__":
    main()
