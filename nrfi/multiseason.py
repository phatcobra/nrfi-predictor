"""Deterministic multi-season MLB development probability engine.

Official StatsAPI responses remain in memory. The local resumable cache and
committed outputs contain normalized derived records only. The locked 2025
holdout and quarantined assets are never opened.
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import random
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss

from nrfi.real_vertical_slice import (
    FEATURE_NAMES,
    VerticalSliceError,
    build_features,
    canonical_json_bytes,
    retrieve_normalized_games,
)

DEFAULT_SEASONS = (2021, 2022, 2023, 2024)
LOCKED_HOLDOUT_SEASON = 2025
FEATURE_VERSION = "team-league-strict-prior-v2"
CALIBRATOR_VERSION = "none-v1"
MODEL_C = 0.25
MODEL_MAX_ITER = 1000
MODEL_SOLVER = "lbfgs"
MODEL_RANDOM_STATE = 0
MODEL_PARAMETERS: dict[str, object] = {
    "C": MODEL_C,
    "max_iter": MODEL_MAX_ITER,
    "solver": MODEL_SOLVER,
    "random_state": MODEL_RANDOM_STATE,
}
DEFAULT_BOOTSTRAP_REPLICATES = 2000
NUMERICAL_TOLERANCE = 1e-12
NORMALIZATION_VERSION = "statsapi-normalized-v2"


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _identity(value: object) -> str:
    return _sha256(canonical_json_bytes(value))


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


def _verify_entries(directory: Path, entries: Sequence[Mapping[str, Any]]) -> None:
    for entry in entries:
        path = directory / str(entry["path"])
        if not path.is_file():
            raise VerticalSliceError(f"cached partition file is missing: {path}")
        content = path.read_bytes()
        if len(content) != int(entry["bytes"]):
            raise VerticalSliceError(f"cached partition byte count changed: {path}")
        if _sha256(content) != entry["sha256"]:
            raise VerticalSliceError(f"cached partition checksum changed: {path}")


def analytical_game_record(game: Mapping[str, Any]) -> dict[str, Any]:
    """Exclude execution timestamps and observation IDs from analytical identity."""
    times = game["time_semantics"]
    return {
        "schema_version": game.get("schema_version", "normalized_game.v1"),
        "game_pk": game["game_pk"],
        "official_date": game["official_date"],
        "scheduled_start_at": game["scheduled_start_at"],
        "game_type": game["game_type"],
        "status": game["status"],
        "doubleheader": game["doubleheader"],
        "doubleheader_code": game["doubleheader_code"],
        "game_number": game["game_number"],
        "away_team": game["away_team"],
        "home_team": game["home_team"],
        "venue": game["venue"],
        "actual_starters": game["actual_starters"],
        "first_inning": game["first_inning"],
        "time_semantics": {
            "event_time": times["event_time"],
            "source_update_time": times["source_update_time"],
            "correction_time": times["correction_time"],
            "finalized_at": times["finalized_at"],
            "finalized_at_gap": times["finalized_at_gap"],
            "label_available_at": times["label_available_at"],
            "label_availability_basis": times["label_availability_basis"],
        },
        "source": game["provenance"]["source"],
    }


def _source_record(provenance: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kind": provenance["kind"],
        "endpoint": provenance["endpoint"],
        "request_parameters": provenance["request_parameters"],
        "response_bytes": provenance["response_bytes"],
        "response_sha256": provenance["response_sha256"],
        "source_update_time": provenance["source_update_time"],
    }


def _month_bounds(season: int, month: int) -> tuple[date, date]:
    return (
        date(season, month, 1),
        date(season, month, calendar.monthrange(season, month)[1]),
    )


def _partition_directory(cache_dir: Path, season: int, month: int) -> Path:
    return (
        cache_dir
        / f"normalization={NORMALIZATION_VERSION}"
        / f"season={season}"
        / f"month={month:02d}"
    )


def _load_cached_partition(
    directory: Path, season: int, month: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]] | None:
    manifest_path = directory / "partition_manifest.json"
    if not manifest_path.exists():
        return None
    manifest = _read_json(manifest_path)
    if manifest.get("season") != season or manifest.get("month") != month:
        raise VerticalSliceError(f"cached partition identity changed: {directory}")
    if manifest.get("normalization_version") != NORMALIZATION_VERSION:
        raise VerticalSliceError(f"cached normalization version changed: {directory}")
    _verify_entries(directory, manifest["entries"])
    return (
        _read_jsonl(directory / "normalized_games.jsonl"),
        _read_jsonl(directory / "rejections.jsonl"),
        _read_jsonl(directory / "provenance.jsonl"),
    )


def acquire_month_partition(
    cache_dir: Path,
    season: int,
    month: int,
    max_workers: int,
    allow_network: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if season >= LOCKED_HOLDOUT_SEASON:
        raise VerticalSliceError("the locked 2025 holdout is outside development")
    directory = _partition_directory(cache_dir, season, month)
    cached = _load_cached_partition(directory, season, month)
    if cached is not None:
        return cached
    if not allow_network:
        raise VerticalSliceError(f"required cached partition is missing: {directory}")

    start, end = _month_bounds(season, month)
    games, rejections, provenance = retrieve_normalized_games(
        start,
        end,
        max_workers=max_workers,
    )
    games.sort(key=lambda row: (row["scheduled_start_at"], int(row["game_pk"])))
    rejections.sort(key=lambda row: (str(row.get("game_pk")), str(row["reason"])))
    provenance.sort(
        key=lambda row: (
            str(row["kind"]),
            str(row["endpoint"]),
            str(row["provenance_id"]),
        )
    )
    row_counts = {
        "normalized_games.jsonl": _write_jsonl(
            directory / "normalized_games.jsonl", games
        ),
        "rejections.jsonl": _write_jsonl(directory / "rejections.jsonl", rejections),
        "provenance.jsonl": _write_jsonl(directory / "provenance.jsonl", provenance),
    }
    entries = [
        _artifact_entry(directory / name, row_counts[name])
        for name in sorted(row_counts)
    ]
    manifest = {
        "schema_version": "1.0",
        "normalization_version": NORMALIZATION_VERSION,
        "season": season,
        "month": month,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "generated_at": _now_utc(),
        "raw_payloads_persisted": False,
        "analytical_games_sha256": _identity(
            [analytical_game_record(row) for row in games]
        ),
        "source_manifest_sha256": _identity(
            sorted(
                (_source_record(row) for row in provenance),
                key=lambda row: (
                    str(row["kind"]),
                    str(row["endpoint"]),
                    str(row["response_sha256"]),
                ),
            )
        ),
        "entries": entries,
    }
    _write_json(directory / "partition_manifest.json", manifest)
    return games, rejections, provenance


def acquire_development_games(
    cache_dir: Path,
    seasons: Sequence[int],
    max_workers: int,
    allow_network: bool,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    requested = tuple(sorted(set(seasons)))
    if len(requested) < 2:
        raise VerticalSliceError(
            "multi-season development requires at least two seasons"
        )
    if any(season >= LOCKED_HOLDOUT_SEASON for season in requested):
        raise VerticalSliceError("the locked 2025 holdout is outside development")

    games_by_pk: dict[int, dict[str, Any]] = {}
    rejection_keys: set[tuple[object, object]] = set()
    rejections: list[dict[str, Any]] = []
    provenance_by_id: dict[str, dict[str, Any]] = {}
    source_partitions_by_pk: dict[int, list[str]] = defaultdict(list)
    for season in requested:
        for month in range(3, 12):
            games, month_rejections, provenance = acquire_month_partition(
                cache_dir,
                season,
                month,
                max_workers,
                allow_network,
            )
            for game in games:
                game_pk = int(game["game_pk"])
                source_partitions_by_pk[game_pk].append(f"{season}-{month:02d}")
                existing = games_by_pk.get(game_pk)
                if existing is not None and analytical_game_record(existing) != (
                    analytical_game_record(game)
                ):
                    raise VerticalSliceError(
                        f"conflicting normalized records for gamePk {game_pk}"
                    )
                games_by_pk[game_pk] = game
            for rejection in month_rejections:
                key = (rejection.get("game_pk"), rejection.get("reason"))
                if key not in rejection_keys:
                    rejection_keys.add(key)
                    rejections.append(rejection)
            for record in provenance:
                provenance_by_id[str(record["provenance_id"])] = record

    games = sorted(
        games_by_pk.values(),
        key=lambda row: (row["scheduled_start_at"], int(row["game_pk"])),
    )
    rejections.sort(key=lambda row: (str(row.get("game_pk")), str(row["reason"])))
    provenance = sorted(
        provenance_by_id.values(),
        key=lambda row: (
            str(row["kind"]),
            str(row["endpoint"]),
            str(row["provenance_id"]),
        ),
    )
    reconciliations = [
        {
            "schema_version": "reconciliation.v1",
            "game_pk": game_pk,
            "reason": "cross_partition_duplicate_reconciled",
            "source_partitions": partitions,
            "duplicate_rows_removed": len(partitions) - 1,
            "analytical_game_identity": _identity(
                analytical_game_record(games_by_pk[game_pk])
            ),
        }
        for game_pk, partitions in sorted(source_partitions_by_pk.items())
        if len(partitions) > 1
    ]
    return games, rejections, provenance, reconciliations


def _feature_identity(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "game_pk": row["game_pk"],
        "official_date": row["official_date"],
        "prediction_cutoff": row["prediction_cutoff"],
        "home_team_id": row["home_team_id"],
        "away_team_id": row["away_team_id"],
        "venue_id": row["venue_id"],
        "home_prior_games": row["home_prior_games"],
        "away_prior_games": row["away_prior_games"],
        "league_prior_games": row["league_prior_games"],
        "feature_values": row["feature_values"],
        "feature_eligible": row["feature_eligible"],
        "evaluation_eligible": row["evaluation_eligible"],
        "evaluation_ineligibility_reason": row["evaluation_ineligibility_reason"],
        "pitcher_features_used": row["pitcher_features_used"],
        "schema_version": row["schema_version"],
        "feature_version": FEATURE_VERSION,
    }


def materialize_features(games: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    features = build_features(games)
    materialized: list[dict[str, Any]] = []
    for raw in features:
        row = dict(raw)
        row["schema_version"] = "feature.v1"
        row["feature_version"] = FEATURE_VERSION
        if not row["feature_eligible"]:
            ineligibility_reason = "insufficient_prior_history"
        elif not isinstance(row.get("label_available_at"), str):
            ineligibility_reason = "missing_label_availability"
        elif str(row["label_available_at"]) <= str(row["prediction_cutoff"]):
            ineligibility_reason = "label_availability_not_after_cutoff"
        else:
            ineligibility_reason = None
        row["evaluation_ineligibility_reason"] = ineligibility_reason
        row["evaluation_eligible"] = ineligibility_reason is None
        row["feature_hash"] = _identity(_feature_identity(row))
        materialized.append(row)
    return materialized


def _matrix(rows: Sequence[Mapping[str, Any]]) -> np.ndarray:
    return np.asarray(
        [
            [float(row["feature_values"][name]) for name in FEATURE_NAMES]
            for row in rows
        ],
        dtype=float,
    )


def _clip(probabilities: np.ndarray) -> np.ndarray:
    return np.clip(probabilities, 1e-6, 1.0 - 1e-6)


def _calibration_slope_intercept(
    y_true: np.ndarray, probabilities: np.ndarray
) -> tuple[float, float]:
    logits = np.log(_clip(probabilities) / (1.0 - _clip(probabilities)))
    design = np.column_stack((np.ones(len(logits)), logits))
    coefficients = np.asarray([0.0, 1.0], dtype=float)
    for _ in range(100):
        linear = design @ coefficients
        fitted = 1.0 / (1.0 + np.exp(-np.clip(linear, -35.0, 35.0)))
        weights = np.maximum(fitted * (1.0 - fitted), 1e-9)
        information = design.T @ (weights[:, None] * design)
        gradient = design.T @ (y_true - fitted)
        step = np.linalg.pinv(information, rcond=1e-12) @ gradient
        coefficients += step
        if float(np.max(np.abs(step))) < 1e-10:
            break
    return float(coefficients[0]), float(coefficients[1])


def probability_metrics(
    y_true: np.ndarray, probabilities: np.ndarray
) -> dict[str, Any]:
    probabilities = _clip(probabilities)
    bins: list[dict[str, Any]] = []
    weighted_gap = 0.0
    for index in range(10):
        lower = index / 10
        upper = (index + 1) / 10
        mask = (probabilities >= lower) & (
            probabilities <= upper if index == 9 else probabilities < upper
        )
        count = int(mask.sum())
        if count == 0:
            continue
        mean_probability = float(probabilities[mask].mean())
        observed_rate = float(y_true[mask].mean())
        gap = observed_rate - mean_probability
        weighted_gap += count * abs(gap)
        bins.append(
            {
                "lower": lower,
                "upper": upper,
                "count": count,
                "mean_probability": mean_probability,
                "observed_yrfi_rate": observed_rate,
                "calibration_gap": gap,
            }
        )
    intercept, slope = _calibration_slope_intercept(y_true, probabilities)
    return {
        "count": len(y_true),
        "yrfi_rate": float(y_true.mean()),
        "mean_probability": float(probabilities.mean()),
        "log_loss": float(log_loss(y_true, probabilities, labels=[0, 1])),
        "brier_score": float(brier_score_loss(y_true, probabilities)),
        "expected_calibration_error": weighted_gap / len(y_true),
        "calibration_intercept": intercept,
        "calibration_slope": slope,
        "probability_min": float(probabilities.min()),
        "probability_max": float(probabilities.max()),
        "probability_std": float(probabilities.std()),
        "reliability_bins": bins,
    }


def _mean_ci(
    values: np.ndarray,
    dates: Sequence[str],
    replicates: int,
    seed_identity: str,
) -> dict[str, Any]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for value, date_value in zip(values.tolist(), dates, strict=True):
        grouped[date_value].append(float(value))
    keys = sorted(grouped)
    sums = np.asarray([sum(grouped[key]) for key in keys], dtype=float)
    counts = np.asarray([len(grouped[key]) for key in keys], dtype=float)
    seed = int(_sha256(seed_identity.encode("utf-8"))[:16], 16)
    rng = random.Random(seed)
    estimates = np.empty(replicates, dtype=float)
    for index in range(replicates):
        sampled = np.fromiter(
            (rng.randrange(len(keys)) for _ in keys),
            dtype=int,
            count=len(keys),
        )
        estimates[index] = float(sums[sampled].sum() / counts[sampled].sum())
    lower, upper = np.quantile(estimates, [0.025, 0.975])
    return {
        "estimate": float(values.mean()),
        "lower_95": float(lower),
        "upper_95": float(upper),
        "method": "official-date-cluster-bootstrap",
        "replicates": replicates,
    }


def _score_contributions(
    y_true: np.ndarray, probabilities: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    probabilities = _clip(probabilities)
    log_losses = -(
        y_true * np.log(probabilities) + (1.0 - y_true) * np.log(1.0 - probabilities)
    )
    brier = (probabilities - y_true) ** 2
    return log_losses, brier


def _paired_evidence(
    y_true: np.ndarray,
    candidate: np.ndarray,
    baselines: Mapping[str, np.ndarray],
    dates: Sequence[str],
    replicates: int,
    fold_id: str,
) -> dict[str, Any]:
    candidate_log, candidate_brier = _score_contributions(y_true, candidate)
    evidence: dict[str, Any] = {}
    for name, baseline in baselines.items():
        baseline_log, baseline_brier = _score_contributions(y_true, baseline)
        log_improvement = baseline_log - candidate_log
        brier_improvement = baseline_brier - candidate_brier
        evidence[name] = {
            "log_loss_improvement": _mean_ci(
                log_improvement,
                dates,
                replicates,
                f"{fold_id}:{name}:log_loss",
            ),
            "brier_improvement": _mean_ci(
                brier_improvement,
                dates,
                replicates,
                f"{fold_id}:{name}:brier",
            ),
        }
    return evidence


def _prediction_uncertainty(
    model: LogisticRegression, x_train: np.ndarray, x_test: np.ndarray
) -> list[dict[str, float | str]]:
    train_design = np.column_stack((np.ones(len(x_train)), x_train))
    train_probability = _clip(model.predict_proba(x_train)[:, 1])
    weights = train_probability * (1.0 - train_probability)
    information = train_design.T @ (weights[:, None] * train_design)
    regularization = np.zeros_like(information)
    regularization[1:, 1:] = np.eye(x_train.shape[1]) / MODEL_C
    covariance = np.linalg.pinv(information + regularization, rcond=1e-12)
    test_design = np.column_stack((np.ones(len(x_test)), x_test))
    logit_variance = np.einsum("ij,jk,ik->i", test_design, covariance, test_design)
    logit_error = np.sqrt(np.maximum(logit_variance, 0.0))
    probability = _clip(model.predict_proba(x_test)[:, 1])
    standard_error = probability * (1.0 - probability) * logit_error
    logits = np.log(probability / (1.0 - probability))
    lower = 1.0 / (1.0 + np.exp(-np.clip(logits - 1.96 * logit_error, -35, 35)))
    upper = 1.0 / (1.0 + np.exp(-np.clip(logits + 1.96 * logit_error, -35, 35)))
    return [
        {
            "method": "regularized-observed-information-delta-v1",
            "standard_error": float(error),
            "lower_95": float(low),
            "upper_95": float(high),
        }
        for error, low, high in zip(
            standard_error.tolist(), lower.tolist(), upper.tolist(), strict=True
        )
    ]


def _season(value: object) -> int:
    return int(str(value)[:4])


def _subgroup_report(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    def grouped_metrics(
        keys: Callable[[Mapping[str, Any]], Iterable[str]], minimum: int = 30
    ) -> dict[str, Any]:
        grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in rows:
            for key in keys(row):
                grouped[key].append(row)
        report: dict[str, Any] = {}
        for key in sorted(grouped):
            values = grouped[key]
            if len(values) < minimum:
                continue
            actual = np.asarray([int(row["yrfi_actual"]) for row in values])
            probability = np.asarray([float(row["p_yrfi"]) for row in values])
            report[key] = probability_metrics(actual, probability)
        return report

    def probability_range(row: Mapping[str, Any]) -> Iterable[str]:
        probability = float(row["p_yrfi"])
        lower = max(0, min(9, int(probability * 10))) / 10
        yield f"{lower:.1f}-{lower + 0.1:.1f}"

    return {
        "season": grouped_metrics(lambda row: [str(row["official_date"])[:4]]),
        "month": grouped_metrics(lambda row: [str(row["official_date"])[:7]]),
        "team": grouped_metrics(
            lambda row: [str(row["home_team_id"]), str(row["away_team_id"])]
        ),
        "venue": grouped_metrics(lambda row: [str(row["venue_id"])]),
        "probability_range": grouped_metrics(probability_range),
        "pitcher_coverage": {
            "NO_PREGAME_PITCHER_FEATURES": probability_metrics(
                np.asarray([int(row["yrfi_actual"]) for row in rows]),
                np.asarray([float(row["p_yrfi"]) for row in rows]),
            )
        },
        "lineup_status": {"UNAVAILABLE_NOT_AUTHORIZED": {"count": len(rows)}},
    }


def _flatten_entities(
    games: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    teams: dict[int, dict[str, Any]] = {}
    venues: dict[int, dict[str, Any]] = {}
    starters: list[dict[str, Any]] = []
    for game in games:
        for side in ("away", "home"):
            team = {"schema_version": "team_identity.v1", **game[f"{side}_team"]}
            teams[int(team["team_id"])] = team
            starter = game["actual_starters"][side]
            if starter:
                starters.append(
                    {
                        "schema_version": "actual_starter.v1",
                        "game_pk": game["game_pk"],
                        "side": side,
                        **starter,
                        "actual_starter_confirmation_time": game["time_semantics"][
                            "source_update_time"
                        ],
                        "pregame_feature_eligible": False,
                    }
                )
        venue = {"schema_version": "venue_identity.v1", **game["venue"]}
        venues[int(venue["venue_id"])] = venue
    return (
        [teams[key] for key in sorted(teams)],
        [venues[key] for key in sorted(venues)],
        sorted(starters, key=lambda row: (int(row["game_pk"]), str(row["side"]))),
    )


def derive_multiseason_evidence(
    games: Sequence[Mapping[str, Any]],
    rejections: Sequence[Mapping[str, Any]],
    reconciliations: Sequence[Mapping[str, Any]],
    provenance: Sequence[Mapping[str, Any]],
    seasons: Sequence[int],
    code_commit: str,
    dependency_lock_sha256: str,
    generated_at: str,
    bootstrap_replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    requested = tuple(sorted(set(seasons)))
    if any(season >= LOCKED_HOLDOUT_SEASON for season in requested):
        raise VerticalSliceError("the locked 2025 holdout is outside development")
    configuration = {
        "schema_version": "configuration.v1",
        "seasons": list(requested),
        "fold_policy": "expanding-window-test-next-complete-season-v1",
        "feature_names": list(FEATURE_NAMES),
        "feature_version": FEATURE_VERSION,
        "model": {"type": "regularized_logistic_regression", **MODEL_PARAMETERS},
        "calibrator_version": CALIBRATOR_VERSION,
        "bootstrap": {
            "method": "official-date-cluster-bootstrap",
            "replicates": bootstrap_replicates,
        },
        "numerical_tolerance": NUMERICAL_TOLERANCE,
    }
    configuration_identity = _identity(configuration)
    source_manifest_identity = _identity(
        sorted(
            (_source_record(row) for row in provenance),
            key=lambda row: (
                str(row["kind"]),
                str(row["endpoint"]),
                str(row["response_sha256"]),
            ),
        )
    )
    normalized_identity = _identity([analytical_game_record(row) for row in games])
    features = materialize_features(games)
    feature_partition_identity = _identity(
        [
            _feature_identity(row) | {"feature_hash": row["feature_hash"]}
            for row in features
        ]
    )
    game_by_pk = {int(game["game_pk"]): game for game in games}

    predictions: list[dict[str, Any]] = []
    grades: list[dict[str, Any]] = []
    fold_reports: list[dict[str, Any]] = []
    scored_rows: list[dict[str, Any]] = []
    pooled_actual: list[int] = []
    pooled_candidate: list[float] = []
    pooled_dates: list[str] = []
    pooled_baselines: dict[str, list[float]] = defaultdict(list)

    eligible = [row for row in features if row["evaluation_eligible"]]
    for test_season in requested[1:]:
        test_rows = [
            row for row in eligible if _season(row["official_date"]) == test_season
        ]
        if not test_rows:
            raise VerticalSliceError(f"season {test_season} has no eligible test rows")
        first_test_cutoff = min(str(row["prediction_cutoff"]) for row in test_rows)
        train_rows = [
            row
            for row in eligible
            if _season(row["official_date"]) < test_season
            and isinstance(row.get("label_available_at"), str)
            and str(row["label_available_at"]) < first_test_cutoff
        ]
        if len(train_rows) < 500 or len(test_rows) < 500:
            raise VerticalSliceError(
                f"insufficient fold rows for {test_season}: "
                f"train={len(train_rows)} test={len(test_rows)}"
            )
        x_train = _matrix(train_rows)
        x_test = _matrix(test_rows)
        y_train = np.asarray([int(row["yrfi_actual"]) for row in train_rows])
        y_test = np.asarray([int(row["yrfi_actual"]) for row in test_rows])
        model = LogisticRegression(
            C=MODEL_C,
            max_iter=MODEL_MAX_ITER,
            solver=MODEL_SOLVER,
            random_state=MODEL_RANDOM_STATE,
        )
        model.fit(x_train, y_train)
        candidate = _clip(model.predict_proba(x_test)[:, 1])
        prior_season = max(_season(row["official_date"]) for row in train_rows)
        prior_rows = [
            row for row in train_rows if _season(row["official_date"]) == prior_season
        ]
        overall_rate = float(y_train.mean())
        prior_rate = float(np.mean([int(row["yrfi_actual"]) for row in prior_rows]))
        baselines = {
            "overall_climatology": np.full(len(test_rows), overall_rate),
            "prior_season_climatology": np.full(len(test_rows), prior_rate),
            "rolling_league_200": _clip(
                np.asarray(
                    [
                        float(row["feature_values"]["league_yrfi_rate_200"])
                        for row in test_rows
                    ]
                )
            ),
        }
        fold_definition = {
            "train_seasons": sorted(
                {_season(row["official_date"]) for row in train_rows}
            ),
            "test_season": test_season,
            "first_test_cutoff": first_test_cutoff,
            "train_game_pks": [row["game_pk"] for row in train_rows],
            "test_game_pks": [row["game_pk"] for row in test_rows],
        }
        fold_id = _identity(fold_definition)
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
        model_artifact = {
            "schema_version": "model_artifact.v1",
            "feature_names": list(FEATURE_NAMES),
            "intercept": float(np.asarray(model.intercept_).reshape(-1)[0]),
            "coefficients": [
                float(value) for value in np.asarray(model.coef_).reshape(-1)
            ],
            "parameters": MODEL_PARAMETERS,
            "training_identity": training_identity,
            "fold_id": fold_id,
        }
        model_identity = _identity(model_artifact)
        uncertainty = _prediction_uncertainty(model, x_train, x_test)
        dates = [str(row["official_date"]) for row in test_rows]

        candidate_metrics = probability_metrics(y_test, candidate)
        baseline_metrics = {
            name: probability_metrics(y_test, values)
            for name, values in baselines.items()
        }
        candidate_metrics["brier_skill_score_vs_overall_climatology"] = 1.0 - (
            candidate_metrics["brier_score"]
            / baseline_metrics["overall_climatology"]["brier_score"]
        )
        paired = _paired_evidence(
            y_test,
            candidate,
            baselines,
            dates,
            bootstrap_replicates,
            fold_id,
        )
        fold_reports.append(
            {
                "schema_version": "fold_evaluation.v1",
                "fold_id": fold_id,
                "train_seasons": fold_definition["train_seasons"],
                "test_season": test_season,
                "train_count": len(train_rows),
                "test_count": len(test_rows),
                "model_identity": model_identity,
                "calibrator_identity": CALIBRATOR_VERSION,
                "model_artifact": model_artifact,
                "candidate": candidate_metrics,
                "baselines": baseline_metrics,
                "paired_improvement": paired,
            }
        )

        for row, probability, uncertainty_row, actual, row_index in zip(
            test_rows,
            candidate.tolist(),
            uncertainty,
            y_test.tolist(),
            range(len(test_rows)),
            strict=True,
        ):
            prediction_record = {
                "schema_version": "prediction.v1",
                "event_id": int(row["game_pk"]),
                "prediction_timestamp": row["prediction_cutoff"],
                "prediction_cutoff": row["prediction_cutoff"],
                "historical_replay": True,
                "source_manifest_identity": source_manifest_identity,
                "normalized_partition_identity": normalized_identity,
                "feature_version": FEATURE_VERSION,
                "feature_hash": row["feature_hash"],
                "model_identity": model_identity,
                "calibrator_identity": CALIBRATOR_VERSION,
                "fold_id": fold_id,
                "p_nrfi": float(1.0 - probability),
                "p_yrfi": float(probability),
                "uncertainty": uncertainty_row,
                "coverage_state": "TEAM_LEAGUE_FEATURES_COMPLETE",
                "degradation_state": "PREGAME_PITCHER_FEATURES_UNAVAILABLE",
                "market_snapshot_id": None,
                "code_commit": code_commit,
                "dependency_lock_sha256": dependency_lock_sha256,
                "configuration_identity": configuration_identity,
            }
            prediction_id = _identity(prediction_record)
            prediction = {"prediction_id": prediction_id, **prediction_record}
            predictions.append(prediction)
            game = game_by_pk[int(row["game_pk"])]
            candidate_log, candidate_brier = _score_contributions(
                np.asarray([actual]), np.asarray([probability])
            )
            baseline_contributions: dict[str, dict[str, float]] = {}
            for name, baseline_values in baselines.items():
                base_log, base_brier = _score_contributions(
                    np.asarray([actual]), np.asarray([baseline_values[row_index]])
                )
                baseline_contributions[name] = {
                    "log_loss": float(base_log[0]),
                    "brier_score": float(base_brier[0]),
                }
            grade_identity_record = {
                "schema_version": "grade.v1",
                "prediction_id": prediction_id,
                "finalized_outcome": {"yrfi": actual, "nrfi": 1 - actual},
                "outcome_availability_time": row["label_available_at"],
                "correction_version": game["time_semantics"]["source_update_time"],
                "brier_contribution": float(candidate_brier[0]),
                "log_loss_contribution": float(candidate_log[0]),
                "baseline_contributions": baseline_contributions,
            }
            grade = {
                "grade_id": _identity(grade_identity_record),
                **grade_identity_record,
                "grade_time": generated_at,
            }
            grades.append(grade)
            scored = {
                "game_pk": row["game_pk"],
                "official_date": row["official_date"],
                "home_team_id": row["home_team_id"],
                "away_team_id": row["away_team_id"],
                "venue_id": row["venue_id"],
                "yrfi_actual": actual,
                "p_yrfi": probability,
            }
            scored_rows.append(scored)
            pooled_actual.append(actual)
            pooled_candidate.append(probability)
            pooled_dates.append(str(row["official_date"]))
            for name, baseline_values in baselines.items():
                pooled_baselines[name].append(float(baseline_values[row_index]))

    actual_array = np.asarray(pooled_actual)
    candidate_array = np.asarray(pooled_candidate)
    baseline_arrays = {
        name: np.asarray(values) for name, values in pooled_baselines.items()
    }
    pooled_candidate_metrics = probability_metrics(actual_array, candidate_array)
    pooled_baseline_metrics = {
        name: probability_metrics(actual_array, values)
        for name, values in baseline_arrays.items()
    }
    pooled_candidate_metrics["brier_skill_score_vs_overall_climatology"] = 1.0 - (
        pooled_candidate_metrics["brier_score"]
        / pooled_baseline_metrics["overall_climatology"]["brier_score"]
    )
    pooled_paired = _paired_evidence(
        actual_array,
        candidate_array,
        baseline_arrays,
        pooled_dates,
        bootstrap_replicates,
        "pooled",
    )
    all_fold_point_improvements = all(
        all(
            comparison["log_loss_improvement"]["estimate"] > 0
            and comparison["brier_improvement"]["estimate"] > 0
            for comparison in fold["paired_improvement"].values()
        )
        for fold in fold_reports
    )
    pooled_intervals_positive = all(
        comparison["log_loss_improvement"]["lower_95"] > 0
        and comparison["brier_improvement"]["lower_95"] > 0
        for comparison in pooled_paired.values()
    )
    decision = (
        "PREDICTIVE SKILL ESTABLISHED"
        if all_fold_point_improvements and pooled_intervals_positive
        else "PREDICTIVE SKILL NOT ESTABLISHED"
    )

    season_coverage: list[dict[str, Any]] = []
    for season in requested:
        season_games = [
            game for game in games if _season(game["official_date"]) == season
        ]
        season_features = [
            row for row in features if _season(row["official_date"]) == season
        ]
        eligible_count = sum(bool(row["feature_eligible"]) for row in season_features)
        evaluation_eligible_count = sum(
            bool(row["evaluation_eligible"]) for row in season_features
        )
        predicted_count = sum(
            1 for row in predictions if _season(row["prediction_cutoff"]) == season
        )
        season_coverage.append(
            {
                "season": season,
                "accepted_games": len(season_games),
                "feature_eligible_games": eligible_count,
                "feature_coverage": eligible_count / len(season_features),
                "evaluation_eligible_games": evaluation_eligible_count,
                "evaluation_coverage": evaluation_eligible_count / len(season_features),
                "chronological_predictions": predicted_count,
            }
        )
    complete_starters = sum(
        game["actual_starters"]["away"] is not None
        and game["actual_starters"]["home"] is not None
        for game in games
    )
    evaluation_ineligibility_reasons: dict[str, int] = defaultdict(int)
    for row in features:
        reason = row["evaluation_ineligibility_reason"]
        if reason is not None:
            evaluation_ineligibility_reasons[str(reason)] += 1
    duplicate_rows_removed = sum(
        int(row["duplicate_rows_removed"]) for row in reconciliations
    )
    coverage = {
        "schema_version": "coverage.v1",
        "seasons": list(requested),
        "scheduled_regular_season_games": len(games) + len(rejections),
        "accepted_finalized_games": len(games),
        "rejected_games": len(rejections),
        "label_coverage": len(games) / (len(games) + len(rejections)),
        "complete_actual_starter_games": complete_starters,
        "actual_starter_coverage": complete_starters / len(games),
        "feature_eligible_games": sum(
            bool(row["feature_eligible"]) for row in features
        ),
        "feature_coverage": sum(bool(row["feature_eligible"]) for row in features)
        / len(features),
        "evaluation_eligible_games": sum(
            bool(row["evaluation_eligible"]) for row in features
        ),
        "evaluation_coverage": sum(bool(row["evaluation_eligible"]) for row in features)
        / len(features),
        "evaluation_ineligibility_reasons": dict(
            sorted(evaluation_ineligibility_reasons.items())
        ),
        "chronological_predictions": len(predictions),
        "cross_partition_duplicate_game_pks": len(reconciliations),
        "cross_partition_duplicate_rows_removed": duplicate_rows_removed,
        "normalized_partition_observations": len(games) + duplicate_rows_removed,
        "pitcher_feature_coverage": 0.0,
        "lineup_feature_coverage": 0.0,
        "raw_payloads_persisted": False,
        "locked_holdout_used": False,
        "by_season": season_coverage,
    }
    evaluation = {
        "schema_version": "evaluation.v1",
        "decision": decision,
        "fold_count": len(fold_reports),
        "folds": fold_reports,
        "pooled": {
            "candidate": pooled_candidate_metrics,
            "baselines": pooled_baseline_metrics,
            "paired_improvement": pooled_paired,
        },
        "subgroups": _subgroup_report(scored_rows),
        "calibrator_identity": CALIBRATOR_VERSION,
        "locked_holdout_used": False,
        "market_data_used": False,
    }
    teams, venues, actual_starters = _flatten_entities(games)
    outcomes = [
        {
            "schema_version": "first_inning_outcome.v1",
            "game_pk": game["game_pk"],
            "official_date": game["official_date"],
            **game["first_inning"],
            "source_update_time": game["time_semantics"]["source_update_time"],
            "retrieval_time": game["time_semantics"]["retrieval_time"],
            "correction_time": game["time_semantics"]["correction_time"],
        }
        for game in games
    ]
    normalized_games = [
        {
            **game,
            "schema_version": "normalized_game.v1",
            "time_semantics": {
                **game["time_semantics"],
                "ingestion_time": generated_at,
            },
        }
        for game in games
    ]
    provenance_output = [
        {"schema_version": "provenance.v1", **row} for row in provenance
    ]
    rejection_output = [{"schema_version": "rejection.v1", **row} for row in rejections]
    deterministic_manifest = {
        "schema_version": "1.0",
        "code_commit": code_commit,
        "dependency_lock_sha256": dependency_lock_sha256,
        "configuration_identity": configuration_identity,
        "source_manifest_identity": source_manifest_identity,
        "normalization_version": NORMALIZATION_VERSION,
        "normalized_partition_identity": normalized_identity,
        "feature_partition_identity": feature_partition_identity,
        "fold_membership_identity": _identity(
            [
                {
                    "fold_id": fold["fold_id"],
                    "train_seasons": fold["train_seasons"],
                    "test_season": fold["test_season"],
                }
                for fold in fold_reports
            ]
        ),
        "model_identities": [fold["model_identity"] for fold in fold_reports],
        "calibrator_identity": CALIBRATOR_VERSION,
        "prediction_partition_identity": _identity(predictions),
        "grade_partition_identity": _identity(
            [
                {key: value for key, value in row.items() if key != "grade_time"}
                for row in grades
            ]
        ),
        "evaluation_identity": _identity(evaluation),
        "accepted_game_pks_identity": _identity(
            [int(game["game_pk"]) for game in games]
        ),
        "rejected_records_identity": _identity(rejection_output),
        "reconciliation_identity": _identity(list(reconciliations)),
        "numerical_tolerance": NUMERICAL_TOLERANCE,
        "execution_timestamps_excluded_from_analytical_identities": True,
        "locked_holdout_used": False,
    }
    return {
        "normalized_games": normalized_games,
        "teams": teams,
        "venues": venues,
        "actual_starters": actual_starters,
        "first_inning_outcomes": outcomes,
        "provenance": provenance_output,
        "rejections": rejection_output,
        "reconciliations": list(reconciliations),
        "features": features,
        "predictions": predictions,
        "grades": grades,
        "fold_evaluation": fold_reports,
        "coverage": coverage,
        "evaluation": evaluation,
        "deterministic_manifest": deterministic_manifest,
        "configuration": configuration,
    }


def build_multiseason_package(
    output_dir: Path,
    cache_dir: Path,
    seasons: Sequence[int],
    code_commit: str,
    dependency_lock_path: Path,
    max_workers: int = 8,
    bootstrap_replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
    allow_network: bool = True,
) -> dict[str, Any]:
    if not dependency_lock_path.is_file():
        raise VerticalSliceError(f"dependency lock is missing: {dependency_lock_path}")
    dependency_lock_sha256 = _sha256(dependency_lock_path.read_bytes())
    games, rejections, provenance, reconciliations = acquire_development_games(
        cache_dir,
        seasons,
        max_workers,
        allow_network,
    )
    generated_at = _now_utc()
    first = derive_multiseason_evidence(
        games,
        rejections,
        reconciliations,
        provenance,
        seasons,
        code_commit,
        dependency_lock_sha256,
        generated_at,
        bootstrap_replicates,
    )
    replay = derive_multiseason_evidence(
        games,
        rejections,
        reconciliations,
        provenance,
        seasons,
        code_commit,
        dependency_lock_sha256,
        "2099-01-01T00:00:00Z",
        bootstrap_replicates,
    )
    if first["deterministic_manifest"] != replay["deterministic_manifest"]:
        raise VerticalSliceError("deterministic replay analytical identities differ")

    jsonl_names = (
        "normalized_games",
        "teams",
        "venues",
        "actual_starters",
        "first_inning_outcomes",
        "provenance",
        "rejections",
        "reconciliations",
        "features",
        "predictions",
        "grades",
        "fold_evaluation",
    )
    json_names = (
        "coverage",
        "evaluation",
        "deterministic_manifest",
        "configuration",
    )
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
        "dependency_lock_sha256": dependency_lock_sha256,
        "raw_payloads_persisted": False,
        "deterministic_replay": "PASS",
        "entries": entries,
    }
    _write_json(output_dir / "artifact_manifest.json", artifact_manifest)
    return {
        "coverage": first["coverage"],
        "evaluation": first["evaluation"],
        "deterministic_manifest": first["deterministic_manifest"],
        "artifact_manifest": artifact_manifest,
    }


def _parse_seasons(value: str) -> tuple[int, ...]:
    try:
        seasons = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "seasons must be comma-separated years"
        ) from exc
    if len(set(seasons)) < 2:
        raise argparse.ArgumentTypeError("at least two seasons are required")
    if any(season >= LOCKED_HOLDOUT_SEASON for season in seasons):
        raise argparse.ArgumentTypeError("the locked 2025 holdout is prohibited")
    return tuple(sorted(set(seasons)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("docs/multiseason"))
    parser.add_argument("--cache", type=Path, default=Path(".cache/nrfi_multiseason"))
    parser.add_argument(
        "--seasons",
        type=_parse_seasons,
        default=DEFAULT_SEASONS,
    )
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--dependency-lock", type=Path, default=Path("uv.lock"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--bootstrap-replicates",
        type=int,
        default=DEFAULT_BOOTSTRAP_REPLICATES,
    )
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    result = build_multiseason_package(
        args.output,
        args.cache,
        args.seasons,
        args.code_commit,
        args.dependency_lock,
        max_workers=max(1, min(args.workers, 8)),
        bootstrap_replicates=max(200, args.bootstrap_replicates),
        allow_network=not args.offline,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
