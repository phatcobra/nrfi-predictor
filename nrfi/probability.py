"""Canonical probability contract and leakage-safe calibration evidence."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss

from nrfi.ensemble import GATE_BRIER_MIN, GATE_LOGLOSS_MIN
from nrfi.venn_abers import VennAbersCalibrator

FINAL_PROBABILITY_PIPELINE_VERSION = "yrfi-meta-venn-abers-clip-v1"
OOF_EVIDENCE_CONTRACT_VERSION = "yrfi-temporal-oof-v1"
HOLDOUT_EVIDENCE_CONTRACT_VERSION = "yrfi-locked-holdout-v1"
PROBABILITY_EPSILON = 1e-6
MIN_CALIBRATION_ROWS = 50


def canonical_probability(values: np.ndarray) -> np.ndarray:
    """Validate and clip the sole deployable P(YRFI) representation."""
    probabilities = np.asarray(values, dtype=float)
    if np.any(~np.isfinite(probabilities)):
        raise ValueError("model emitted non-finite calibrated probabilities")
    if np.any((probabilities < 0.0) | (probabilities > 1.0)):
        raise ValueError("model emitted probabilities outside [0, 1]")
    return np.clip(probabilities, PROBABILITY_EPSILON, 1.0 - PROBABILITY_EPSILON)


def _metrics(labels: np.ndarray, probabilities: np.ndarray) -> dict[str, Any]:
    return {
        "logloss": float(log_loss(labels, probabilities)),
        "brier": float(brier_score_loss(labels, probabilities)),
        "n": int(len(labels)),
    }


def temporal_calibration_evidence(
    raw_scores: np.ndarray,
    baseline_scores: np.ndarray,
    labels: np.ndarray,
    dates: pd.Series,
    *,
    n_folds: int,
    purge_days: int,
) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    """Cross-fit calibration using only chronologically prior OOF evidence."""
    raw = np.asarray(raw_scores, dtype=float)
    baseline = np.asarray(baseline_scores, dtype=float)
    y = np.asarray(labels, dtype=int)
    when = pd.Series(pd.to_datetime(dates, errors="raise")).reset_index(drop=True)
    if not (len(raw) == len(baseline) == len(y) == len(when)):
        raise ValueError("OOF scores, baselines, labels, and dates must align")
    if not when.is_monotonic_increasing:
        raise ValueError("calibration evidence dates must be chronological")

    valid = np.flatnonzero(np.isfinite(raw) & np.isfinite(baseline))
    if len(valid) < 2 * MIN_CALIBRATION_ROWS:
        raise ValueError("insufficient raw OOF rows for temporal calibration")
    blocks = [block for block in np.array_split(valid, max(2, n_folds)) if len(block)]
    calibrated = np.full(len(raw), np.nan, dtype=float)
    audits: list[dict[str, Any]] = []
    for fold_number, validation_idx in enumerate(blocks[1:], start=1):
        cutoff = when.iloc[validation_idx[0]] - pd.Timedelta(days=purge_days)
        training_idx = valid[
            (valid < validation_idx[0])
            & (when.iloc[valid].to_numpy() <= np.datetime64(cutoff))
        ]
        if len(training_idx) < MIN_CALIBRATION_ROWS:
            continue
        calibrator = VennAbersCalibrator().fit(raw[training_idx], y[training_idx])
        calibrated[validation_idx] = canonical_probability(
            calibrator.predict(raw[validation_idx])
        )
        audits.append(
            {
                "fold": fold_number,
                "train_n": int(len(training_idx)),
                "validation_n": int(len(validation_idx)),
                "train_end": when.iloc[training_idx[-1]].isoformat(),
                "validation_start": when.iloc[validation_idx[0]].isoformat(),
                "purge_cutoff": cutoff.isoformat(),
            }
        )

    mask = np.isfinite(calibrated)
    if mask.sum() < MIN_CALIBRATION_ROWS or not audits:
        raise ValueError("no sufficient temporal calibration evidence was produced")
    final_metrics = _metrics(y[mask], calibrated[mask])
    baseline_probabilities = canonical_probability(baseline[mask])
    baseline_metrics = _metrics(y[mask], baseline_probabilities)
    logloss_improvement = baseline_metrics["logloss"] - final_metrics["logloss"]
    brier_improvement = baseline_metrics["brier"] - final_metrics["brier"]
    gates_passed = (
        logloss_improvement >= GATE_LOGLOSS_MIN and brier_improvement >= GATE_BRIER_MIN
    )
    report = {
        "probability_pipeline_version": FINAL_PROBABILITY_PIPELINE_VERSION,
        "oof_evidence_contract_version": OOF_EVIDENCE_CONTRACT_VERSION,
        "calibration": "temporally_cross_fitted_prior_only",
        "baseline": {**baseline_metrics, "kind": "prior_only_fold_climatology"},
        "final_probability": final_metrics,
        "gate_improvements": {
            "logloss": float(logloss_improvement),
            "brier": float(brier_improvement),
            "minimum_logloss": GATE_LOGLOSS_MIN,
            "minimum_brier": GATE_BRIER_MIN,
        },
        "folds": audits,
        "gates_passed": bool(gates_passed),
    }
    return report, calibrated, mask
