"""Real-data deterministic candidate-comparison tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from nrfi.model_comparison import VARIANTS, build_model_comparison

EVIDENCE = Path(__file__).resolve().parents[1] / "docs" / "multiseason"


def _jsonl(path: Path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


@pytest.fixture(scope="module")
def comparison(tmp_path_factory: pytest.TempPathFactory):
    output = tmp_path_factory.mktemp("real-model-comparison")
    result = build_model_comparison(
        EVIDENCE,
        output,
        "test-code-commit",
        uncertainty_replicates=2,
        bootstrap_replicates=20,
    )
    return output, result


def test_real_candidates_use_identical_folds_and_preserve_negative_decision(
    comparison,
):
    _, result = comparison
    evaluation = result["evaluation"]
    assert evaluation["fold_count"] == 3
    assert evaluation["primary_decision"] == "PREDICTIVE SKILL NOT ESTABLISHED"
    assert set(evaluation["variant_decisions"]) == set(VARIANTS)
    assert set(evaluation["variant_decisions"].values()) == {
        "PREDICTIVE SKILL NOT ESTABLISHED"
    }
    assert evaluation["max_logistic_replay_delta"] == 0.0
    assert evaluation["locked_holdout_used"] is False
    assert evaluation["market_data_used"] is False


def test_prior_fold_calibration_never_uses_current_test_labels(comparison):
    output, _ = comparison
    artifacts = _jsonl(output / "model_artifacts.jsonl")
    calibrators = [
        row for row in artifacts if row.get("schema_version") == "calibrator.v1"
    ]
    assert len(calibrators) == 6
    assert [row["training_count"] for row in calibrators] == [
        0,
        0,
        2429,
        2429,
        4858,
        4858,
    ]
    assert all(
        row["method"] == "none_insufficient_prior_oof" for row in calibrators[:2]
    )
    assert all(row["method"] == "prior-fold-sigmoid-v1" for row in calibrators[2:])


def test_candidate_predictions_are_outcome_free_and_grades_are_separate(comparison):
    output, _ = comparison
    predictions = _jsonl(output / "predictions.jsonl")
    grades = _jsonl(output / "grades.jsonl")
    assert len(predictions) == len(grades) == 7287 * len(VARIANTS)
    assert {row["variant"] for row in predictions} == set(VARIANTS)
    assert all("finalized_outcome" not in row for row in predictions)
    assert all("yrfi_actual" not in row for row in predictions)
    assert all(row["market_snapshot_id"] is None for row in predictions)
    assert {row["prediction_id"] for row in predictions} == {
        row["prediction_id"] for row in grades
    }
    by_variant = {
        variant: [row for row in predictions if row["variant"] == variant]
        for variant in VARIANTS
    }
    for family in ("logistic", "lightgbm"):
        raw = by_variant[f"{family}_raw"]
        calibrated = by_variant[f"{family}_temporal_sigmoid"]
        assert any(
            first["uncertainty"]["standard_error"]
            != second["uncertainty"]["standard_error"]
            for first, second in zip(raw, calibrated, strict=True)
        )


def test_candidate_artifact_manifest_and_replay_are_exact(comparison):
    output, result = comparison
    manifest = result["artifact_manifest"]
    assert manifest["deterministic_replay"] == "PASS"
    assert len(manifest["entries"]) == 7
    for entry in manifest["entries"]:
        content = (output / entry["path"]).read_bytes()
        assert len(content) == entry["bytes"]
        assert hashlib.sha256(content).hexdigest() == entry["sha256"]
