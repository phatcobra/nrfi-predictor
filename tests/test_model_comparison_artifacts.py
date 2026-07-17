"""Integrity checks for committed real-data candidate-comparison evidence."""

from __future__ import annotations

import ast
import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from nrfi.model_comparison import VARIANTS
from nrfi.multiseason import _identity

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "model_comparison"
BASE = ROOT / "docs" / "multiseason"
CODE_COMMIT = "a3e86f52e62bd8fcfbd47c579822ab5303a29082"
MACHINE_FILES = {
    "configuration.json",
    "deterministic_manifest.json",
    "evaluation.json",
    "fold_evaluation.jsonl",
    "grades.jsonl",
    "model_artifacts.jsonl",
    "predictions.jsonl",
}


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


@pytest.fixture(scope="module")
def artifacts():
    return {
        "artifact_manifest": _json(EVIDENCE / "artifact_manifest.json"),
        "configuration": _json(EVIDENCE / "configuration.json"),
        "deterministic_manifest": _json(EVIDENCE / "deterministic_manifest.json"),
        "evaluation": _json(EVIDENCE / "evaluation.json"),
        "folds": _jsonl(EVIDENCE / "fold_evaluation.jsonl"),
        "grades": _jsonl(EVIDENCE / "grades.jsonl"),
        "models": _jsonl(EVIDENCE / "model_artifacts.jsonl"),
        "predictions": _jsonl(EVIDENCE / "predictions.jsonl"),
    }


def test_manifest_bytes_rows_and_privacy_are_exact(artifacts):
    manifest = artifacts["artifact_manifest"]
    assert manifest["deterministic_replay"] == "PASS"
    assert manifest["code_commit"] == CODE_COMMIT
    assert {entry["path"] for entry in manifest["entries"]} == MACHINE_FILES
    assert sum(entry["bytes"] for entry in manifest["entries"]) == 55_154_142
    assert (
        sum(
            entry["row_count"]
            for entry in manifest["entries"]
            if entry["path"].endswith(".jsonl")
        )
        == 58_311
    )
    forbidden = (b"C:\\Users\\", b"/Users/", b"/home/")
    for entry in manifest["entries"]:
        content = (EVIDENCE / entry["path"]).read_bytes()
        assert len(content) == entry["bytes"]
        assert hashlib.sha256(content).hexdigest() == entry["sha256"]
        assert all(value not in content for value in forbidden)
        if entry["path"].endswith(".jsonl"):
            assert len(content.splitlines()) == entry["row_count"]


def test_prediction_and_grade_ledgers_are_separate_and_complete(artifacts):
    predictions = artifacts["predictions"]
    grades = artifacts["grades"]
    assert len(predictions) == len(grades) == 29_148
    assert Counter(row["variant"] for row in predictions) == {
        variant: 7_287 for variant in VARIANTS
    }
    prediction_ids = [row["prediction_id"] for row in predictions]
    grade_prediction_ids = [row["prediction_id"] for row in grades]
    assert len(set(prediction_ids)) == len(prediction_ids)
    assert Counter(prediction_ids) == Counter(grade_prediction_ids)
    assert {str(row["prediction_timestamp"])[:4] for row in predictions} == {
        "2022",
        "2023",
        "2024",
    }
    forbidden_prediction_fields = {"finalized_outcome", "yrfi_actual", "grade_id"}
    assert all(not forbidden_prediction_fields.intersection(row) for row in predictions)
    assert all(row["market_snapshot_id"] is None for row in predictions)
    assert all(row["code_commit"] == CODE_COMMIT for row in predictions)
    assert all(
        row["p_nrfi"] + row["p_yrfi"] == pytest.approx(1.0) for row in predictions
    )
    assert all(
        row["prediction_id"]
        == _identity(
            {key: value for key, value in row.items() if key != "prediction_id"}
        )
        for row in predictions
    )
    assert all(
        row["grade_id"]
        == _identity(
            {
                key: value
                for key, value in row.items()
                if key not in {"grade_id", "grade_time"}
            }
        )
        for row in grades
    )
    base_events = {int(row["event_id"]) for row in _jsonl(BASE / "predictions.jsonl")}
    for variant in VARIANTS:
        assert {
            int(row["event_id"]) for row in predictions if row["variant"] == variant
        } == base_events


def test_folds_models_and_calibrators_retain_provenance(artifacts):
    folds = artifacts["folds"]
    base_folds = _jsonl(BASE / "fold_evaluation.jsonl")
    assert [row["fold_id"] for row in folds] == [row["fold_id"] for row in base_folds]
    assert [row["test_season"] for row in folds] == [2022, 2023, 2024]
    assert [(row["train_count"], row["test_count"]) for row in folds] == [
        (2_271, 2_429),
        (4_700, 2_429),
        (7_129, 2_429),
    ]
    assert [(row["train_count"], row["test_count"]) for row in folds] == [
        (row["train_count"], row["test_count"]) for row in base_folds
    ]
    models = artifacts["models"]
    fitted = [row for row in models if row["schema_version"] == "model_artifact.v1"]
    calibrators = [row for row in models if row["schema_version"] == "calibrator.v1"]
    assert len(fitted) == len(calibrators) == 6
    assert [row["training_count"] for row in calibrators] == [
        0,
        0,
        2_429,
        2_429,
        4_858,
        4_858,
    ]
    assert [row["target_fold_id"] for row in calibrators] == [
        fold_id for row in folds for fold_id in (row["fold_id"], row["fold_id"])
    ]
    assert [row["model_family"] for row in calibrators] == [
        "regularized_logistic_regression",
        "lightgbm_gradient_boosted_trees",
    ] * 3
    assert all(
        row["model_text_sha256"]
        == hashlib.sha256(row["model_text"].encode("utf-8")).hexdigest()
        for row in fitted
        if row["model_family"] == "lightgbm_gradient_boosted_trees"
    )
    for row in fitted:
        identity_fields = {
            key: value
            for key, value in row.items()
            if key not in {"model_identity", "uncertainty_ensemble_identity"}
        }
        assert row["model_identity"] == _identity(identity_fields)
    for row in calibrators:
        assert row["calibrator_identity"] == _identity(
            {key: value for key, value in row.items() if key != "calibrator_identity"}
        )


def test_evaluation_and_analytical_identities_are_reproducible(artifacts):
    configuration = artifacts["configuration"]
    evaluation = artifacts["evaluation"]
    manifest = artifacts["deterministic_manifest"]
    predictions = artifacts["predictions"]
    grades = artifacts["grades"]
    models = artifacts["models"]
    assert configuration["uncertainty"]["replicates"] == 32
    assert configuration["score_bootstrap"]["replicates"] == 2_000
    assert manifest["code_commit"] == CODE_COMMIT
    assert manifest["configuration_identity"] == _identity(configuration)
    assert manifest["model_artifact_identity"] == _identity(models)
    assert manifest["prediction_partition_identity"] == _identity(predictions)
    assert manifest["grade_partition_identity"] == _identity(
        [
            {key: value for key, value in row.items() if key != "grade_time"}
            for row in grades
        ]
    )
    assert manifest["evaluation_identity"] == _identity(evaluation)
    assert manifest["locked_holdout_used"] is False
    assert evaluation["locked_holdout_used"] is False
    assert evaluation["market_data_used"] is False
    assert evaluation["max_logistic_replay_delta"] == 0.0
    assert evaluation["primary_decision"] == "PREDICTIVE SKILL NOT ESTABLISHED"
    assert set(evaluation["variant_decisions"].values()) == {
        "PREDICTIVE SKILL NOT ESTABLISHED"
    }
    assert evaluation["calibration_decisions"] == {
        "lightgbm": "CALIBRATION ACCEPTED",
        "logistic": "CALIBRATION REJECTED",
    }
    expected_log_loss = {
        "logistic_raw": 0.6932044873356864,
        "logistic_temporal_sigmoid": 0.6938467638875778,
        "lightgbm_raw": 0.6976539593031028,
        "lightgbm_temporal_sigmoid": 0.6959987307163928,
    }
    for variant, expected in expected_log_loss.items():
        assert evaluation["pooled"]["variants"][variant]["metrics"][
            "log_loss"
        ] == pytest.approx(expected, abs=1e-15)


def test_reconciliation_exclusions_and_offline_boundary_are_explicit():
    reconciliations = _jsonl(BASE / "reconciliations.jsonl")
    rejections = _jsonl(BASE / "rejections.jsonl")
    coverage = _json(BASE / "coverage.json")
    assert len(reconciliations) == 62
    assert {row["reason"] for row in reconciliations} == {
        "cross_partition_duplicate_reconciled"
    }
    assert all(row["duplicate_rows_removed"] == 1 for row in reconciliations)
    assert Counter(row["reason"] for row in rejections) == {
        "missing_first_inning_linescore": 2,
        "missing_team_or_venue_identity": 2,
    }
    assert coverage["evaluation_ineligibility_reasons"] == {
        "insufficient_prior_history": 157,
        "label_availability_not_after_cutoff": 1,
    }
    assert coverage["seasons"] == [2021, 2022, 2023, 2024]
    assert coverage["locked_holdout_used"] is False
    assert coverage["raw_payloads_persisted"] is False
    tree = ast.parse((ROOT / "nrfi" / "model_comparison.py").read_text())
    imported_roots = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imported_roots.isdisjoint({"aiohttp", "httpx", "requests", "urllib"})
