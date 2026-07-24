"""Reproduce and verify the frozen 2021-2024 baseline entirely offline."""

from __future__ import annotations

import hashlib
import json
import tempfile
from itertools import zip_longest
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


def _assert_json_close(
    expected: Any,
    generated: Any,
    tolerance: float,
    path: str = "$",
) -> float:
    if isinstance(expected, dict) and isinstance(generated, dict):
        if expected.keys() != generated.keys():
            raise ReplayVerificationError(f"JSON object keys differ at {path}")
        return max(
            (
                _assert_json_close(
                    expected[key], generated[key], tolerance, f"{path}.{key}"
                )
                for key in expected
            ),
            default=0.0,
        )
    if isinstance(expected, list) and isinstance(generated, list):
        if len(expected) != len(generated):
            raise ReplayVerificationError(f"JSON array length differs at {path}")
        return max(
            (
                _assert_json_close(left, right, tolerance, f"{path}[{index}]")
                for index, (left, right) in enumerate(
                    zip(expected, generated, strict=True)
                )
            ),
            default=0.0,
        )
    if (
        isinstance(expected, (int, float))
        and not isinstance(expected, bool)
        and isinstance(generated, (int, float))
        and not isinstance(generated, bool)
    ):
        delta = abs(float(expected) - float(generated))
        if delta > tolerance:
            raise ReplayVerificationError(
                f"numeric value differs at {path}: delta={delta:.17g}"
            )
        return delta
    if expected != generated:
        raise ReplayVerificationError(f"JSON value differs at {path}")
    return 0.0


def _jsonl_pairs(expected: Path, generated: Path):
    sentinel = object()
    with (
        expected.open(encoding="utf-8") as expected_handle,
        generated.open(encoding="utf-8") as generated_handle,
    ):
        for index, (left, right) in enumerate(
            zip_longest(expected_handle, generated_handle, fillvalue=sentinel)
        ):
            if left is sentinel or right is sentinel:
                raise ReplayVerificationError(f"JSONL length differs: {expected.name}")
            if not isinstance(left, str) or not isinstance(right, str):
                raise ReplayVerificationError("unexpected JSONL record type")
            yield index, json.loads(left), json.loads(right)


def _map_identity(
    forward: dict[str, str],
    reverse: dict[str, str],
    expected: str,
    generated: str,
    label: str,
) -> None:
    if expected in forward and forward[expected] != generated:
        raise ReplayVerificationError(f"inconsistent {label} mapping")
    if generated in reverse and reverse[generated] != expected:
        raise ReplayVerificationError(f"non-unique {label} mapping")
    forward[expected] = generated
    reverse[generated] = expected


def _verify_package_equivalence(
    expected_root: Path,
    generated_root: Path,
    tolerance: float,
) -> dict[str, Any]:
    max_delta = _assert_json_close(
        _read_json(expected_root / "configuration.json"),
        _read_json(generated_root / "configuration.json"),
        tolerance,
        "$.configuration",
    )

    model_map: dict[str, str] = {}
    reverse_model_map: dict[str, str] = {}
    calibrator_map = {"none-v1": "none-v1"}
    reverse_calibrator_map = {"none-v1": "none-v1"}
    for index, expected, generated in _jsonl_pairs(
        expected_root / "model_artifacts.jsonl",
        generated_root / "model_artifacts.jsonl",
    ):
        if expected["schema_version"] == "model_artifact.v1":
            _map_identity(
                model_map,
                reverse_model_map,
                expected["model_identity"],
                generated["model_identity"],
                "model identity",
            )
            ignored = {
                "model_identity",
                "model_text",
                "model_text_sha256",
                "uncertainty_ensemble_identity",
            }
        elif expected["schema_version"] == "calibrator.v1":
            _map_identity(
                calibrator_map,
                reverse_calibrator_map,
                expected["calibrator_identity"],
                generated["calibrator_identity"],
                "calibrator identity",
            )
            ignored = {"calibrator_identity", "training_prediction_identity"}
        else:
            raise ReplayVerificationError("unexpected model artifact schema")
        comparable_expected = {
            key: value for key, value in expected.items() if key not in ignored
        }
        comparable_generated = {
            key: value for key, value in generated.items() if key not in ignored
        }
        max_delta = max(
            max_delta,
            _assert_json_close(
                comparable_expected,
                comparable_generated,
                tolerance,
                f"$.model_artifacts[{index}]",
            ),
        )

    prediction_map: dict[str, str] = {}
    reverse_prediction_map: dict[str, str] = {}
    prediction_count = 0
    for index, expected, generated in _jsonl_pairs(
        expected_root / "predictions.jsonl",
        generated_root / "predictions.jsonl",
    ):
        expected_model = str(expected["model_identity"])
        expected_calibrator = str(expected["calibrator_identity"])
        if model_map.get(expected_model) != generated["model_identity"]:
            raise ReplayVerificationError("prediction-to-model link differs")
        if calibrator_map.get(expected_calibrator) != generated["calibrator_identity"]:
            raise ReplayVerificationError("prediction-to-calibrator link differs")
        _map_identity(
            prediction_map,
            reverse_prediction_map,
            str(expected["prediction_id"]),
            str(generated["prediction_id"]),
            "prediction identity",
        )
        if (
            abs(float(generated["p_nrfi"]) + float(generated["p_yrfi"]) - 1.0)
            > tolerance
        ):
            raise ReplayVerificationError("probability complement differs")
        ignored = {
            "prediction_id",
            "model_identity",
            "calibrator_identity",
        }
        max_delta = max(
            max_delta,
            _assert_json_close(
                {key: value for key, value in expected.items() if key not in ignored},
                {key: value for key, value in generated.items() if key not in ignored},
                tolerance,
                f"$.predictions[{index}]",
            ),
        )
        prediction_count += 1

    grade_map: dict[str, str] = {}
    reverse_grade_map: dict[str, str] = {}
    grade_count = 0
    for index, expected, generated in _jsonl_pairs(
        expected_root / "grades.jsonl",
        generated_root / "grades.jsonl",
    ):
        if (
            prediction_map.get(str(expected["prediction_id"]))
            != generated["prediction_id"]
        ):
            raise ReplayVerificationError("prediction-to-grade link differs")
        _map_identity(
            grade_map,
            reverse_grade_map,
            str(expected["grade_id"]),
            str(generated["grade_id"]),
            "grade identity",
        )
        ignored = {"grade_id", "prediction_id", "grade_time"}
        max_delta = max(
            max_delta,
            _assert_json_close(
                {key: value for key, value in expected.items() if key not in ignored},
                {key: value for key, value in generated.items() if key not in ignored},
                tolerance,
                f"$.grades[{index}]",
            ),
        )
        grade_count += 1

    fold_count = 0
    for index, expected, generated in _jsonl_pairs(
        expected_root / "fold_evaluation.jsonl",
        generated_root / "fold_evaluation.jsonl",
    ):
        max_delta = max(
            max_delta,
            _assert_json_close(
                expected,
                generated,
                tolerance,
                f"$.fold_evaluation[{index}]",
            ),
        )
        fold_count += 1

    return {
        "max_record_delta": max_delta,
        "prediction_count": prediction_count,
        "grade_count": grade_count,
        "fold_count": fold_count,
        "model_identity_count": len(model_map),
        "calibrator_identity_count": len(calibrator_map) - 1,
        "model_identities_exact": all(
            left == right for left, right in model_map.items()
        ),
        "calibrator_identities_exact": all(
            left == right for left, right in calibrator_map.items()
        ),
        "prediction_identities_exact": all(
            left == right for left, right in prediction_map.items()
        ),
        "grade_identities_exact": all(
            left == right for left, right in grade_map.items()
        ),
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
        package_equivalence = _verify_package_equivalence(
            EXPECTED_EVIDENCE,
            output,
            numerical_tolerance,
        )

    expected_delta = float(expected_evaluation["max_logistic_replay_delta"])
    generated_delta = float(generated_evaluation["max_logistic_replay_delta"])
    if max(expected_delta, generated_delta) > numerical_tolerance:
        raise ReplayVerificationError("logistic replay exceeds numerical tolerance")

    max_evaluation_delta = _assert_json_close(
        expected_evaluation,
        generated_evaluation,
        numerical_tolerance,
    )

    derived_identity_keys = {
        "model_artifact_identity",
        "prediction_partition_identity",
        "grade_partition_identity",
        "evaluation_identity",
    }
    comparable_expected_manifest = {
        key: value
        for key, value in expected_manifest.items()
        if key not in derived_identity_keys
    }
    comparable_generated_manifest = {
        key: value
        for key, value in generated_manifest.items()
        if key not in derived_identity_keys
    }
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
        "max_frozen_evaluation_delta": max_evaluation_delta,
        "max_frozen_record_delta": package_equivalence["max_record_delta"],
        "analytical_match_within_tolerance": True,
        "package_equivalence": package_equivalence,
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
