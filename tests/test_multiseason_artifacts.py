"""Integrity checks for committed real multi-season development evidence."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "docs" / "multiseason"
PRODUCING_COMMIT = "cd7c332d42d696794d56928ebfbcc4c6b04a8444"


def _json(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def _jsonl(name: str):
    return [
        json.loads(line)
        for line in (ROOT / name).read_text(encoding="utf-8").splitlines()
        if line
    ]


def test_artifact_manifest_hashes_and_row_counts_are_exact():
    manifest = _json("artifact_manifest.json")
    assert manifest["code_commit"] == PRODUCING_COMMIT
    assert manifest["deterministic_replay"] == "PASS"
    assert len(manifest["entries"]) == 16
    for entry in manifest["entries"]:
        path = ROOT / entry["path"]
        content = path.read_bytes()
        assert len(content) == entry["bytes"], entry["path"]
        assert hashlib.sha256(content).hexdigest() == entry["sha256"], entry["path"]
        if path.suffix == ".jsonl":
            assert (
                len([line for line in content.splitlines() if line])
                == entry["row_count"]
            )
        else:
            json.loads(content)
            assert entry["row_count"] == 1


def test_generated_evidence_bytes_are_not_line_ending_normalized():
    attributes = (ROOT.parents[1] / ".gitattributes").read_text(encoding="utf-8")
    assert "docs/vertical_slice/*.jsonl -text" in attributes
    assert "docs/multiseason/*.jsonl -text" in attributes


def test_real_coverage_rejections_and_reconciliations_are_complete():
    coverage = _json("coverage.json")
    rejections = _jsonl("rejections.jsonl")
    reconciliations = _jsonl("reconciliations.jsonl")
    assert coverage["seasons"] == [2021, 2022, 2023, 2024]
    assert coverage["scheduled_regular_season_games"] == 9720
    assert coverage["accepted_finalized_games"] == 9716
    assert coverage["feature_eligible_games"] == 9559
    assert coverage["evaluation_eligible_games"] == 9558
    assert coverage["chronological_predictions"] == 7287
    assert coverage["actual_starter_coverage"] == 1.0
    assert coverage["pitcher_feature_coverage"] == 0.0
    assert coverage["locked_holdout_used"] is False
    assert coverage["raw_payloads_persisted"] is False
    assert len(rejections) == coverage["rejected_games"] == 4
    assert len(reconciliations) == coverage["cross_partition_duplicate_game_pks"] == 62
    assert sum(row["duplicate_rows_removed"] for row in reconciliations) == 62
    assert coverage["normalized_partition_observations"] == 9778


def test_predictions_are_outcome_free_and_join_one_to_one_to_grades():
    predictions = _jsonl("predictions.jsonl")
    grades = _jsonl("grades.jsonl")
    assert len(predictions) == len(grades) == 7287
    assert len({row["prediction_id"] for row in predictions}) == len(predictions)
    assert {row["prediction_id"] for row in predictions} == {
        row["prediction_id"] for row in grades
    }
    for prediction in predictions:
        assert "yrfi_actual" not in prediction
        assert "finalized_outcome" not in prediction
        assert prediction["market_snapshot_id"] is None
        assert prediction["code_commit"] == PRODUCING_COMMIT
        assert prediction["historical_replay"] is True
        assert math.isclose(
            prediction["p_nrfi"] + prediction["p_yrfi"],
            1.0,
            abs_tol=1e-12,
        )


def test_negative_skill_decision_and_deterministic_identities_are_locked():
    evaluation = _json("evaluation.json")
    deterministic = _json("deterministic_manifest.json")
    assert evaluation["decision"] == "PREDICTIVE SKILL NOT ESTABLISHED"
    assert evaluation["locked_holdout_used"] is False
    assert evaluation["market_data_used"] is False
    assert deterministic["code_commit"] == PRODUCING_COMMIT
    assert deterministic["normalized_partition_identity"] == (
        "f7a3a6e1ad7b3fe0567ed1326f12007f98fa0488ed355f69f2aa679ba5d86d2c"
    )
    assert deterministic["fold_membership_identity"] == (
        "f3f6af1dfec1c6a3ddc260b0092359a5716a9960baf43ff838b0a3c6c0bd1dc6"
    )
    assert deterministic["prediction_partition_identity"] == (
        "334f1ff8fce0bdcdcedd2f20cc1e6f090dbf589f24b92bbaf0f93b6e439e2f24"
    )
    assert deterministic["grade_partition_identity"] == (
        "d9cfe3f01188d55b84cfc808e85ad102643b4df0252cc938716652bca03590c7"
    )
    assert deterministic["locked_holdout_used"] is False
