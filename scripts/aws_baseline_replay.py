"""Reproduce and verify the frozen 2021-2024 baseline entirely offline."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from nrfi.model_comparison import build_model_comparison


ROOT = Path(__file__).resolve().parents[1]
SOURCE_EVIDENCE = ROOT / "docs" / "multiseason"
EXPECTED_EVIDENCE = ROOT / "docs" / "model_comparison"
PRODUCING_CODE_COMMIT = "a3e86f52e62bd8fcfbd47c579822ab5303a29082"
EXPECTED_SEASONS = [2021, 2022, 2023, 2024]
EXPECTED_PREDICTIONS_PER_VARIANT = 7_287
UNCERTAINTY_REPLICATES = 32
BOOTSTRAP_REPLICATES = 2_000


class ReplayVerificationError(RuntimeError):
    """Raised when frozen evidence or the AWS replay differs from expectation."""


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ReplayVerificationError(f"expected a JSON object: {path.name}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _row_count(path: Path) -> int:
    if path.suffix == ".jsonl":
        with path.open("rb") as handle:
            return sum(1 for line in handle if line.strip())
    _read_json(path)
    return 1


def _verify_artifact_manifest(root: Path) -> dict[str, int]:
    manifest = _read_json(root / "artifact_manifest.json")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ReplayVerificationError(f"invalid artifact manifest: {root.name}")

    rows: dict[str, int] = {}
    for entry in entries:
        relative = Path(str(entry["path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ReplayVerificationError("artifact manifest contains an unsafe path")
        path = root / relative
        if not path.is_file():
            raise ReplayVerificationError(f"artifact is missing: {relative.as_posix()}")
        if path.stat().st_size != int(entry["bytes"]):
            raise ReplayVerificationError(f"artifact byte count differs: {relative}")
        if _sha256(path) != str(entry["sha256"]):
            raise ReplayVerificationError(f"artifact hash differs: {relative}")
        actual_rows = _row_count(path)
        if actual_rows != int(entry["row_count"]):
            raise ReplayVerificationError(f"artifact row count differs: {relative}")
        rows[relative.as_posix()] = actual_rows
    return rows


def _verify_source_boundary() -> None:
    coverage = _read_json(SOURCE_EVIDENCE / "coverage.json")
    manifest = _read_json(SOURCE_EVIDENCE / "deterministic_manifest.json")
    if coverage.get("seasons") != EXPECTED_SEASONS:
        raise ReplayVerificationError("source evidence is not exactly 2021-2024")
    if coverage.get("locked_holdout_used") is not False:
        raise ReplayVerificationError("source coverage reports locked holdout access")
    if manifest.get("locked_holdout_used") is not False:
        raise ReplayVerificationError("source manifest reports locked holdout access")

    for filename in ("features.jsonl", "predictions.jsonl", "fold_evaluation.jsonl"):
        with (SOURCE_EVIDENCE / filename).open("rb") as handle:
            content = handle.read()
            if b'"official_date":"2025' in content or b'"test_season":2025' in content:
                raise ReplayVerificationError(f"2025 record found in {filename}")


def _variant_metrics(evaluation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    variants = evaluation["pooled"]["variants"]
    return {
        name: {
            "count": int(value["metrics"]["count"]),
            "log_loss": float(value["metrics"]["log_loss"]),
            "brier_score": float(value["metrics"]["brier_score"]),
            "expected_calibration_error": float(
                value["metrics"]["expected_calibration_error"]
            ),
        }
        for name, value in variants.items()
    }


def main() -> None:
    source_rows = _verify_artifact_manifest(SOURCE_EVIDENCE)
    expected_rows = _verify_artifact_manifest(EXPECTED_EVIDENCE)
    _verify_source_boundary()

    expected_manifest = _read_json(EXPECTED_EVIDENCE / "deterministic_manifest.json")
    expected_evaluation = _read_json(EXPECTED_EVIDENCE / "evaluation.json")
    if expected_manifest.get("code_commit") != PRODUCING_CODE_COMMIT:
        raise ReplayVerificationError("frozen producing commit differs")
    if expected_manifest.get("locked_holdout_used") is not False:
        raise ReplayVerificationError("expected evidence reports locked holdout access")

    with tempfile.TemporaryDirectory(prefix="nrfi-aws-baseline-") as directory:
        output = Path(directory)
        result = build_model_comparison(
            SOURCE_EVIDENCE,
            output,
            PRODUCING_CODE_COMMIT,
            uncertainty_replicates=UNCERTAINTY_REPLICATES,
            bootstrap_replicates=BOOTSTRAP_REPLICATES,
        )
        generated_rows = _verify_artifact_manifest(output)
        generated_manifest = _read_json(output / "deterministic_manifest.json")
        generated_evaluation = _read_json(output / "evaluation.json")

    numerical_tolerance = float(expected_manifest["numerical_tolerance"])
    expected_delta = float(expected_evaluation["max_logistic_replay_delta"])
    generated_delta = float(generated_evaluation["max_logistic_replay_delta"])
    if max(expected_delta, generated_delta) > numerical_tolerance:
        raise ReplayVerificationError("logistic replay exceeds numerical tolerance")

    comparable_expected_evaluation = dict(expected_evaluation)
    comparable_generated_evaluation = dict(generated_evaluation)
    comparable_expected_evaluation["max_logistic_replay_delta"] = 0.0
    comparable_generated_evaluation["max_logistic_replay_delta"] = 0.0
    if comparable_generated_evaluation != comparable_expected_evaluation:
        raise ReplayVerificationError("AWS evaluation differs from frozen evidence")

    comparable_expected_manifest = dict(expected_manifest)
    comparable_generated_manifest = dict(generated_manifest)
    comparable_generated_manifest["evaluation_identity"] = comparable_expected_manifest[
        "evaluation_identity"
    ]
    if comparable_generated_manifest != comparable_expected_manifest:
        raise ReplayVerificationError(
            "AWS analytical manifest differs from frozen evidence"
        )
    if result["deterministic_manifest"] != generated_manifest:
        raise ReplayVerificationError(
            "returned analytical manifest differs from output"
        )
    if generated_rows != expected_rows:
        raise ReplayVerificationError("AWS evidence row counts differ")

    metrics = _variant_metrics(generated_evaluation)
    if any(
        value["count"] != EXPECTED_PREDICTIONS_PER_VARIANT for value in metrics.values()
    ):
        raise ReplayVerificationError("candidate prediction count differs")
    if generated_evaluation.get("locked_holdout_used") is not False:
        raise ReplayVerificationError("AWS evaluation reports locked holdout access")
    if generated_evaluation.get("market_data_used") is not False:
        raise ReplayVerificationError("AWS evaluation reports market-data access")

    report = {
        "schema_version": "aws_baseline_replay.v1",
        "status": "PASS",
        "producing_code_commit": PRODUCING_CODE_COMMIT,
        "source_seasons": EXPECTED_SEASONS,
        "source_artifact_rows": sum(source_rows.values()),
        "generated_artifact_rows": sum(generated_rows.values()),
        "predictions_per_variant": EXPECTED_PREDICTIONS_PER_VARIANT,
        "candidate_count": len(metrics),
        "metrics": metrics,
        "primary_decision": generated_evaluation["primary_decision"],
        "deterministic_replay": result["artifact_manifest"]["deterministic_replay"],
        "numerical_tolerance": numerical_tolerance,
        "max_logistic_replay_delta": generated_delta,
        "analytical_match_within_tolerance": True,
        "configuration_identity": generated_manifest["configuration_identity"],
        "model_artifact_identity": generated_manifest["model_artifact_identity"],
        "prediction_partition_identity": generated_manifest[
            "prediction_partition_identity"
        ],
        "grade_partition_identity": generated_manifest["grade_partition_identity"],
        "evaluation_identity": generated_manifest["evaluation_identity"],
        "frozen_evaluation_identity": expected_manifest["evaluation_identity"],
        "locked_holdout_used": False,
        "market_data_used": False,
    }
    print("NRFI_AWS_BASELINE_RESULT=" + json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
