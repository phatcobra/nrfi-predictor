"""Deterministic real-data candidate and temporal-calibration comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from nrfi.multiseason import (
    CALIBRATOR_VERSION,
    FEATURE_NAMES,
    MODEL_C,
    MODEL_MAX_ITER,
    MODEL_RANDOM_STATE,
    MODEL_SOLVER,
    NUMERICAL_TOLERANCE,
    _calibration_slope_intercept,
    _clip,
    _identity,
    _matrix,
    _paired_evidence,
    _score_contributions,
    probability_metrics,
)
from nrfi.real_vertical_slice import VerticalSliceError, canonical_json_bytes

VARIANTS = (
    "logistic_raw",
    "logistic_temporal_sigmoid",
    "lightgbm_raw",
    "lightgbm_temporal_sigmoid",
)
LIGHTGBM_PARAMETERS: dict[str, Any] = {
    "objective": "binary",
    "n_estimators": 160,
    "learning_rate": 0.03,
    "num_leaves": 7,
    "max_depth": 3,
    "min_child_samples": 60,
    "reg_lambda": 1.0,
    "subsample": 1.0,
    "colsample_bytree": 1.0,
    "random_state": 0,
    "n_jobs": 1,
    "deterministic": True,
    "force_col_wise": True,
    "verbosity": -1,
}
DEFAULT_UNCERTAINTY_REPLICATES = 32
DEFAULT_BOOTSTRAP_REPLICATES = 2000


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def _write_jsonl(path: Path, values: Iterable[Mapping[str, Any]]) -> int:
    rows = list(values)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        for row in rows:
            handle.write(canonical_json_bytes(row))
    return len(rows)


def _artifact_entry(path: Path, row_count: int) -> dict[str, object]:
    content = path.read_bytes()
    return {
        "path": path.name,
        "bytes": len(content),
        "row_count": row_count,
        "sha256": _sha256(content),
    }


def _fit_logistic(x_train: np.ndarray, y_train: np.ndarray) -> LogisticRegression:
    model = LogisticRegression(
        C=MODEL_C,
        max_iter=MODEL_MAX_ITER,
        solver=MODEL_SOLVER,
        random_state=MODEL_RANDOM_STATE,
    )
    model.fit(x_train, y_train)
    return model


def _fit_lightgbm(
    x_train: np.ndarray, y_train: np.ndarray, random_state: int = 0
) -> lgb.LGBMClassifier:
    parameters = {**LIGHTGBM_PARAMETERS, "random_state": random_state}
    model = lgb.LGBMClassifier(**parameters)
    model.fit(pd.DataFrame(x_train, columns=FEATURE_NAMES), y_train)
    return model


def _predict_lightgbm(model: lgb.LGBMClassifier, values: np.ndarray) -> np.ndarray:
    return _clip(
        np.asarray(
            model.predict_proba(pd.DataFrame(values, columns=FEATURE_NAMES)),
            dtype=float,
        )[:, 1]
    )


def _lightgbm_uncertainty(
    x_train: np.ndarray,
    y_train: np.ndarray,
    train_dates: Sequence[str],
    x_test: np.ndarray,
    replicates: int,
    seed_identity: str,
) -> tuple[list[dict[str, Any]], str]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for index, date_value in enumerate(train_dates):
        grouped[date_value].append(index)
    dates = sorted(grouped)
    seed = int(_sha256(seed_identity.encode("utf-8"))[:16], 16)
    rng = random.Random(seed)
    predictions = np.empty((replicates, len(x_test)), dtype=float)
    member_identities: list[str] = []
    for replicate in range(replicates):
        sampled_dates = [dates[rng.randrange(len(dates))] for _ in dates]
        sampled_indices = [index for day in sampled_dates for index in grouped[day]]
        member = _fit_lightgbm(
            x_train[sampled_indices],
            y_train[sampled_indices],
            random_state=replicate,
        )
        predictions[replicate] = _predict_lightgbm(member, x_test)
        member_identities.append(
            _sha256(member.booster_.model_to_string().encode("utf-8"))
        )
    standard_error = predictions.std(axis=0, ddof=1 if replicates > 1 else 0)
    lower = np.quantile(predictions, 0.025, axis=0)
    upper = np.quantile(predictions, 0.975, axis=0)
    uncertainty = [
        {
            "method": "official-date-cluster-model-bootstrap-v1",
            "replicates": replicates,
            "standard_error": float(error),
            "lower_95": float(low),
            "upper_95": float(high),
        }
        for error, low, high in zip(
            standard_error.tolist(), lower.tolist(), upper.tolist(), strict=True
        )
    ]
    return uncertainty, _identity(member_identities)


def _fit_temporal_sigmoid(
    probabilities: Sequence[float],
    actuals: Sequence[int],
    prediction_ids: Sequence[str],
    target_fold_id: str,
    model_family: str,
) -> dict[str, Any]:
    common = {
        "schema_version": "calibrator.v1",
        "target_fold_id": target_fold_id,
        "model_family": model_family,
        "training_count": len(probabilities),
        "training_prediction_identity": _identity(list(prediction_ids)),
    }
    if len(probabilities) < 1000:
        artifact = {
            **common,
            "method": "none_insufficient_prior_oof",
            "intercept": 0.0,
            "slope": 1.0,
        }
        return {"calibrator_identity": _identity(artifact), **artifact}
    intercept, slope = _calibration_slope_intercept(
        np.asarray(actuals, dtype=float),
        np.asarray(probabilities, dtype=float),
    )
    artifact = {
        **common,
        "method": "prior-fold-sigmoid-v1",
        "intercept": intercept,
        "slope": slope,
    }
    return {"calibrator_identity": _identity(artifact), **artifact}


def _apply_sigmoid(
    probabilities: np.ndarray, calibrator: Mapping[str, Any]
) -> np.ndarray:
    if calibrator["method"] == "none_insufficient_prior_oof":
        return probabilities.copy()
    probabilities = _clip(probabilities)
    logits = np.log(probabilities / (1.0 - probabilities))
    calibrated_logits = (
        float(calibrator["intercept"]) + float(calibrator["slope"]) * logits
    )
    return _clip(1.0 / (1.0 + np.exp(-np.clip(calibrated_logits, -35, 35))))


def _calibrate_uncertainty(
    raw: Sequence[Mapping[str, Any]],
    probabilities: np.ndarray,
    calibrator: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if calibrator["method"] == "none_insufficient_prior_oof":
        return [dict(row) for row in raw]
    raw_probabilities = _clip(np.asarray(probabilities, dtype=float))
    calibrated_probabilities = _apply_sigmoid(raw_probabilities, calibrator)
    raw_standard_errors = np.asarray(
        [float(row["standard_error"]) for row in raw], dtype=float
    )
    delta_scale = (
        abs(float(calibrator["slope"]))
        * calibrated_probabilities
        * (1.0 - calibrated_probabilities)
        / (raw_probabilities * (1.0 - raw_probabilities))
    )
    calibrated_standard_errors = raw_standard_errors * delta_scale
    lower_raw = np.asarray([float(row["lower_95"]) for row in raw])
    upper_raw = np.asarray([float(row["upper_95"]) for row in raw])
    lower_mapped = _apply_sigmoid(lower_raw, calibrator)
    upper_mapped = _apply_sigmoid(upper_raw, calibrator)
    return [
        {
            "method": f"{row['method']}+prior-fold-sigmoid-v1",
            "replicates": row.get("replicates"),
            "standard_error": float(error),
            "lower_95": float(min(low, high)),
            "upper_95": float(max(low, high)),
        }
        for row, error, low, high in zip(
            raw,
            calibrated_standard_errors.tolist(),
            lower_mapped.tolist(),
            upper_mapped.tolist(),
            strict=True,
        )
    ]


def _model_artifacts(
    fold_id: str,
    training_identity: str,
    logistic: LogisticRegression,
    tree: lgb.LGBMClassifier,
) -> tuple[dict[str, Any], dict[str, Any]]:
    logistic_artifact = {
        "schema_version": "model_artifact.v1",
        "model_family": "regularized_logistic_regression",
        "fold_id": fold_id,
        "training_identity": training_identity,
        "feature_names": list(FEATURE_NAMES),
        "parameters": {
            "C": MODEL_C,
            "max_iter": MODEL_MAX_ITER,
            "solver": MODEL_SOLVER,
            "random_state": MODEL_RANDOM_STATE,
        },
        "intercept": float(np.asarray(logistic.intercept_).reshape(-1)[0]),
        "coefficients": [
            float(value) for value in np.asarray(logistic.coef_).reshape(-1)
        ],
    }
    logistic_artifact["model_identity"] = _identity(logistic_artifact)
    model_text = tree.booster_.model_to_string()
    tree_artifact = {
        "schema_version": "model_artifact.v1",
        "model_family": "lightgbm_gradient_boosted_trees",
        "fold_id": fold_id,
        "training_identity": training_identity,
        "feature_names": list(FEATURE_NAMES),
        "parameters": LIGHTGBM_PARAMETERS,
        "model_text_sha256": _sha256(model_text.encode("utf-8")),
        "model_text": model_text,
    }
    tree_artifact["model_identity"] = _identity(tree_artifact)
    return logistic_artifact, tree_artifact


def _skill_decision(
    fold_reports: Sequence[Mapping[str, Any]],
    pooled: Mapping[str, Any],
    variant: str,
) -> str:
    fold_points_positive = all(
        all(
            comparison["log_loss_improvement"]["estimate"] > 0
            and comparison["brier_improvement"]["estimate"] > 0
            for comparison in fold["variants"][variant]["paired_improvement"].values()
        )
        for fold in fold_reports
    )
    pooled_intervals_positive = all(
        comparison["log_loss_improvement"]["lower_95"] > 0
        and comparison["brier_improvement"]["lower_95"] > 0
        for comparison in pooled["variants"][variant]["paired_improvement"].values()
    )
    return (
        "PREDICTIVE SKILL ESTABLISHED"
        if fold_points_positive and pooled_intervals_positive
        else "PREDICTIVE SKILL NOT ESTABLISHED"
    )


def derive_model_comparison(
    evidence_dir: Path,
    code_commit: str,
    generated_at: str,
    uncertainty_replicates: int = DEFAULT_UNCERTAINTY_REPLICATES,
    bootstrap_replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    base_manifest = _read_json(evidence_dir / "deterministic_manifest.json")
    base_coverage = _read_json(evidence_dir / "coverage.json")
    if base_coverage["seasons"] != [2021, 2022, 2023, 2024]:
        raise VerticalSliceError("model comparison requires the admitted 2021-2024 set")
    if base_manifest["locked_holdout_used"] is not False:
        raise VerticalSliceError("locked holdout evidence is prohibited")
    features = _read_jsonl(evidence_dir / "features.jsonl")
    base_predictions = _read_jsonl(evidence_dir / "predictions.jsonl")
    base_folds = {
        int(row["test_season"]): row
        for row in _read_jsonl(evidence_dir / "fold_evaluation.jsonl")
    }
    base_by_game = {int(row["event_id"]): row for row in base_predictions}
    eligible = [row for row in features if row["evaluation_eligible"]]

    configuration = {
        "schema_version": "model_comparison_configuration.v1",
        "base_normalized_partition_identity": base_manifest[
            "normalized_partition_identity"
        ],
        "base_feature_partition_identity": base_manifest["feature_partition_identity"],
        "base_fold_membership_identity": base_manifest["fold_membership_identity"],
        "variants": list(VARIANTS),
        "logistic_parameters": {
            "C": MODEL_C,
            "max_iter": MODEL_MAX_ITER,
            "solver": MODEL_SOLVER,
            "random_state": MODEL_RANDOM_STATE,
        },
        "lightgbm_parameters": LIGHTGBM_PARAMETERS,
        "calibration_policy": "prior-completed-fold-oof-sigmoid-v1",
        "uncertainty": {
            "method": "official-date-cluster-model-bootstrap-v1",
            "replicates": uncertainty_replicates,
        },
        "score_bootstrap": {
            "method": "official-date-cluster-bootstrap",
            "replicates": bootstrap_replicates,
        },
        "numerical_tolerance": NUMERICAL_TOLERANCE,
    }
    configuration_identity = _identity(configuration)
    prior_probabilities: dict[str, list[float]] = {
        "logistic": [],
        "lightgbm": [],
    }
    prior_actuals: dict[str, list[int]] = {"logistic": [], "lightgbm": []}
    prior_prediction_ids: dict[str, list[str]] = {
        "logistic": [],
        "lightgbm": [],
    }
    predictions: list[dict[str, Any]] = []
    grades: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    fold_reports: list[dict[str, Any]] = []
    pooled: dict[str, dict[str, list[Any]]] = {
        variant: {"actual": [], "probability": [], "date": [], "baselines": []}
        for variant in VARIANTS
    }
    max_logistic_replay_delta = 0.0

    for test_season in (2022, 2023, 2024):
        fold_base = base_folds[test_season]
        test_rows = [
            row for row in eligible if int(str(row["official_date"])[:4]) == test_season
        ]
        first_test_cutoff = min(str(row["prediction_cutoff"]) for row in test_rows)
        train_rows = [
            row
            for row in eligible
            if int(str(row["official_date"])[:4]) < test_season
            and str(row["label_available_at"]) < first_test_cutoff
        ]
        if len(train_rows) != int(fold_base["train_count"]) or len(test_rows) != int(
            fold_base["test_count"]
        ):
            raise VerticalSliceError(
                f"immutable fold membership changed: {test_season}"
            )
        fold_id = str(fold_base["fold_id"])
        x_train = _matrix(train_rows)
        x_test = _matrix(test_rows)
        y_train = np.asarray([int(row["yrfi_actual"]) for row in train_rows])
        y_test = np.asarray([int(row["yrfi_actual"]) for row in test_rows])
        dates = [str(row["official_date"]) for row in test_rows]
        train_dates = [str(row["official_date"]) for row in train_rows]
        training_identity = _identity(
            [
                {
                    "game_pk": row["game_pk"],
                    "feature_hash": row["feature_hash"],
                    "yrfi": row["yrfi_actual"],
                }
                for row in train_rows
            ]
        )
        logistic = _fit_logistic(x_train, y_train)
        tree = _fit_lightgbm(x_train, y_train)
        logistic_probability = _clip(logistic.predict_proba(x_test)[:, 1])
        tree_probability = _predict_lightgbm(tree, x_test)
        expected_logistic = np.asarray(
            [float(base_by_game[int(row["game_pk"])]["p_yrfi"]) for row in test_rows]
        )
        replay_delta = float(np.max(np.abs(logistic_probability - expected_logistic)))
        max_logistic_replay_delta = max(max_logistic_replay_delta, replay_delta)
        if replay_delta > NUMERICAL_TOLERANCE:
            raise VerticalSliceError(
                f"logistic replay differs by {replay_delta} in {test_season}"
            )
        logistic_artifact, tree_artifact = _model_artifacts(
            fold_id, training_identity, logistic, tree
        )
        artifacts.extend((logistic_artifact, tree_artifact))
        logistic_calibrator = _fit_temporal_sigmoid(
            prior_probabilities["logistic"],
            prior_actuals["logistic"],
            prior_prediction_ids["logistic"],
            fold_id,
            "regularized_logistic_regression",
        )
        tree_calibrator = _fit_temporal_sigmoid(
            prior_probabilities["lightgbm"],
            prior_actuals["lightgbm"],
            prior_prediction_ids["lightgbm"],
            fold_id,
            "lightgbm_gradient_boosted_trees",
        )
        artifacts.extend((logistic_calibrator, tree_calibrator))
        calibrated_logistic = _apply_sigmoid(logistic_probability, logistic_calibrator)
        calibrated_tree = _apply_sigmoid(tree_probability, tree_calibrator)
        raw_logistic_uncertainty = [
            dict(base_by_game[int(row["game_pk"])]["uncertainty"]) for row in test_rows
        ]
        raw_tree_uncertainty, uncertainty_identity = _lightgbm_uncertainty(
            x_train,
            y_train,
            train_dates,
            x_test,
            uncertainty_replicates,
            f"{fold_id}:lightgbm",
        )
        tree_artifact["uncertainty_ensemble_identity"] = uncertainty_identity
        variant_probabilities = {
            "logistic_raw": logistic_probability,
            "logistic_temporal_sigmoid": calibrated_logistic,
            "lightgbm_raw": tree_probability,
            "lightgbm_temporal_sigmoid": calibrated_tree,
        }
        variant_models = {
            "logistic_raw": logistic_artifact,
            "logistic_temporal_sigmoid": logistic_artifact,
            "lightgbm_raw": tree_artifact,
            "lightgbm_temporal_sigmoid": tree_artifact,
        }
        variant_calibrators = {
            "logistic_raw": {"calibrator_identity": CALIBRATOR_VERSION},
            "logistic_temporal_sigmoid": logistic_calibrator,
            "lightgbm_raw": {"calibrator_identity": CALIBRATOR_VERSION},
            "lightgbm_temporal_sigmoid": tree_calibrator,
        }
        variant_uncertainty = {
            "logistic_raw": raw_logistic_uncertainty,
            "logistic_temporal_sigmoid": _calibrate_uncertainty(
                raw_logistic_uncertainty, logistic_probability, logistic_calibrator
            ),
            "lightgbm_raw": raw_tree_uncertainty,
            "lightgbm_temporal_sigmoid": _calibrate_uncertainty(
                raw_tree_uncertainty, tree_probability, tree_calibrator
            ),
        }
        prior_season = test_season - 1
        prior_rows = [
            row
            for row in train_rows
            if int(str(row["official_date"])[:4]) == prior_season
        ]
        baselines = {
            "overall_climatology": np.full(len(test_rows), float(y_train.mean())),
            "prior_season_climatology": np.full(
                len(test_rows),
                float(np.mean([int(row["yrfi_actual"]) for row in prior_rows])),
            ),
            "rolling_league_200": _clip(
                np.asarray(
                    [
                        float(row["feature_values"]["league_yrfi_rate_200"])
                        for row in test_rows
                    ]
                )
            ),
        }
        fold_variants: dict[str, Any] = {}
        for variant, values in variant_probabilities.items():
            fold_variants[variant] = {
                "metrics": probability_metrics(y_test, values),
                "paired_improvement": _paired_evidence(
                    y_test,
                    values,
                    baselines,
                    dates,
                    bootstrap_replicates,
                    f"{fold_id}:{variant}",
                ),
            }
            pooled[variant]["actual"].extend(y_test.tolist())
            pooled[variant]["probability"].extend(values.tolist())
            pooled[variant]["date"].extend(dates)
            pooled[variant]["baselines"].extend(
                [
                    {
                        name: float(probability[index])
                        for name, probability in baselines.items()
                    }
                    for index in range(len(test_rows))
                ]
            )
        fold_reports.append(
            {
                "schema_version": "candidate_fold_evaluation.v1",
                "fold_id": fold_id,
                "test_season": test_season,
                "train_count": len(train_rows),
                "test_count": len(test_rows),
                "variants": fold_variants,
            }
        )

        raw_ids: dict[str, list[str]] = {"logistic": [], "lightgbm": []}
        for row_index, (row, actual) in enumerate(
            zip(test_rows, y_test.tolist(), strict=True)
        ):
            for variant in VARIANTS:
                probability = float(variant_probabilities[variant][row_index])
                model_artifact = variant_models[variant]
                calibrator = variant_calibrators[variant]
                record = {
                    "schema_version": "candidate_prediction.v1",
                    "event_id": int(row["game_pk"]),
                    "prediction_timestamp": row["prediction_cutoff"],
                    "prediction_cutoff": row["prediction_cutoff"],
                    "historical_replay": True,
                    "variant": variant,
                    "base_source_manifest_identity": base_manifest[
                        "source_manifest_identity"
                    ],
                    "normalized_partition_identity": base_manifest[
                        "normalized_partition_identity"
                    ],
                    "feature_version": row["feature_version"],
                    "feature_hash": row["feature_hash"],
                    "fold_id": fold_id,
                    "model_identity": model_artifact["model_identity"],
                    "calibrator_identity": calibrator["calibrator_identity"],
                    "p_nrfi": 1.0 - probability,
                    "p_yrfi": probability,
                    "uncertainty": variant_uncertainty[variant][row_index],
                    "coverage_state": "TEAM_LEAGUE_FEATURES_COMPLETE",
                    "degradation_state": "PREGAME_PITCHER_FEATURES_UNAVAILABLE",
                    "market_snapshot_id": None,
                    "code_commit": code_commit,
                    "dependency_lock_sha256": base_manifest["dependency_lock_sha256"],
                    "configuration_identity": configuration_identity,
                }
                prediction_id = _identity(record)
                prediction = {"prediction_id": prediction_id, **record}
                predictions.append(prediction)
                log_contribution, brier_contribution = _score_contributions(
                    np.asarray([actual]), np.asarray([probability])
                )
                grade_identity = {
                    "schema_version": "candidate_grade.v1",
                    "prediction_id": prediction_id,
                    "finalized_outcome": {"yrfi": actual, "nrfi": 1 - actual},
                    "outcome_availability_time": row["label_available_at"],
                    "brier_contribution": float(brier_contribution[0]),
                    "log_loss_contribution": float(log_contribution[0]),
                }
                grades.append(
                    {
                        "grade_id": _identity(grade_identity),
                        **grade_identity,
                        "grade_time": generated_at,
                    }
                )
                if variant == "logistic_raw":
                    raw_ids["logistic"].append(prediction_id)
                elif variant == "lightgbm_raw":
                    raw_ids["lightgbm"].append(prediction_id)
        prior_probabilities["logistic"].extend(logistic_probability.tolist())
        prior_actuals["logistic"].extend(y_test.tolist())
        prior_prediction_ids["logistic"].extend(raw_ids["logistic"])
        prior_probabilities["lightgbm"].extend(tree_probability.tolist())
        prior_actuals["lightgbm"].extend(y_test.tolist())
        prior_prediction_ids["lightgbm"].extend(raw_ids["lightgbm"])

    pooled_report: dict[str, Any] = {"variants": {}}
    for variant in VARIANTS:
        actual = np.asarray(pooled[variant]["actual"])
        probability = np.asarray(pooled[variant]["probability"])
        dates = [str(value) for value in pooled[variant]["date"]]
        baseline_rows = pooled[variant]["baselines"]
        baselines = {
            name: np.asarray([float(row[name]) for row in baseline_rows])
            for name in (
                "overall_climatology",
                "prior_season_climatology",
                "rolling_league_200",
            )
        }
        pooled_report["variants"][variant] = {
            "metrics": probability_metrics(actual, probability),
            "paired_improvement": _paired_evidence(
                actual,
                probability,
                baselines,
                dates,
                bootstrap_replicates,
                f"pooled:{variant}",
            ),
        }
    decisions = {
        variant: _skill_decision(fold_reports, pooled_report, variant)
        for variant in VARIANTS
    }
    primary_decision = (
        "PREDICTIVE SKILL ESTABLISHED"
        if any(value == "PREDICTIVE SKILL ESTABLISHED" for value in decisions.values())
        else "PREDICTIVE SKILL NOT ESTABLISHED"
    )
    calibration_decisions: dict[str, str] = {}
    for family in ("logistic", "lightgbm"):
        raw = pooled_report["variants"][f"{family}_raw"]["metrics"]
        calibrated = pooled_report["variants"][f"{family}_temporal_sigmoid"]["metrics"]
        later_fold_safe = all(
            fold["variants"][f"{family}_temporal_sigmoid"]["metrics"]["log_loss"]
            <= fold["variants"][f"{family}_raw"]["metrics"]["log_loss"]
            and fold["variants"][f"{family}_temporal_sigmoid"]["metrics"]["brier_score"]
            <= fold["variants"][f"{family}_raw"]["metrics"]["brier_score"]
            for fold in fold_reports[1:]
        )
        accepted = (
            calibrated["expected_calibration_error"] < raw["expected_calibration_error"]
            and calibrated["log_loss"] <= raw["log_loss"]
            and calibrated["brier_score"] <= raw["brier_score"]
            and later_fold_safe
        )
        calibration_decisions[family] = (
            "CALIBRATION ACCEPTED" if accepted else "CALIBRATION REJECTED"
        )
    evaluation = {
        "schema_version": "model_comparison_evaluation.v1",
        "primary_decision": primary_decision,
        "variant_decisions": decisions,
        "calibration_decisions": calibration_decisions,
        "fold_count": len(fold_reports),
        "folds": fold_reports,
        "pooled": pooled_report,
        "max_logistic_replay_delta": max_logistic_replay_delta,
        "locked_holdout_used": False,
        "market_data_used": False,
    }
    deterministic_manifest = {
        "schema_version": "model_comparison_manifest.v1",
        "code_commit": code_commit,
        "dependency_lock_sha256": base_manifest["dependency_lock_sha256"],
        "base_normalized_partition_identity": base_manifest[
            "normalized_partition_identity"
        ],
        "base_feature_partition_identity": base_manifest["feature_partition_identity"],
        "base_fold_membership_identity": base_manifest["fold_membership_identity"],
        "configuration_identity": configuration_identity,
        "model_artifact_identity": _identity(artifacts),
        "prediction_partition_identity": _identity(predictions),
        "grade_partition_identity": _identity(
            [
                {key: value for key, value in grade.items() if key != "grade_time"}
                for grade in grades
            ]
        ),
        "evaluation_identity": _identity(evaluation),
        "numerical_tolerance": NUMERICAL_TOLERANCE,
        "locked_holdout_used": False,
    }
    return {
        "predictions": predictions,
        "grades": grades,
        "model_artifacts": artifacts,
        "fold_evaluation": fold_reports,
        "configuration": configuration,
        "evaluation": evaluation,
        "deterministic_manifest": deterministic_manifest,
    }


def build_model_comparison(
    evidence_dir: Path,
    output_dir: Path,
    code_commit: str,
    uncertainty_replicates: int = DEFAULT_UNCERTAINTY_REPLICATES,
    bootstrap_replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    generated_at = _now_utc()
    first = derive_model_comparison(
        evidence_dir,
        code_commit,
        generated_at,
        uncertainty_replicates,
        bootstrap_replicates,
    )
    replay = derive_model_comparison(
        evidence_dir,
        code_commit,
        "2099-01-01T00:00:00Z",
        uncertainty_replicates,
        bootstrap_replicates,
    )
    if first["deterministic_manifest"] != replay["deterministic_manifest"]:
        raise VerticalSliceError("candidate comparison deterministic replay differs")
    jsonl_names = ("predictions", "grades", "model_artifacts", "fold_evaluation")
    json_names = ("configuration", "evaluation", "deterministic_manifest")
    row_counts: dict[str, int] = {}
    for name in jsonl_names:
        filename = f"{name}.jsonl"
        row_counts[filename] = _write_jsonl(output_dir / filename, first[name])
    for name in json_names:
        filename = f"{name}.json"
        _write_json(output_dir / filename, first[name])
        row_counts[filename] = 1
    entries = [
        _artifact_entry(output_dir / name, row_counts[name])
        for name in sorted(row_counts)
    ]
    artifact_manifest = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "code_commit": code_commit,
        "deterministic_replay": "PASS",
        "entries": entries,
    }
    _write_json(output_dir / "artifact_manifest.json", artifact_manifest)
    return {
        "evaluation": first["evaluation"],
        "deterministic_manifest": first["deterministic_manifest"],
        "artifact_manifest": artifact_manifest,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, default=Path("docs/multiseason"))
    parser.add_argument("--output", type=Path, default=Path("docs/model_comparison"))
    parser.add_argument("--code-commit", required=True)
    parser.add_argument(
        "--uncertainty-replicates",
        type=int,
        default=DEFAULT_UNCERTAINTY_REPLICATES,
    )
    parser.add_argument(
        "--bootstrap-replicates",
        type=int,
        default=DEFAULT_BOOTSTRAP_REPLICATES,
    )
    args = parser.parse_args()
    result = build_model_comparison(
        args.evidence,
        args.output,
        args.code_commit,
        uncertainty_replicates=max(8, args.uncertainty_replicates),
        bootstrap_replicates=max(200, args.bootstrap_replicates),
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
