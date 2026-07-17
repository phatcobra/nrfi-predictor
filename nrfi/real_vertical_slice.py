"""Bounded real-data MLB vertical slice using official StatsAPI.

Raw responses remain in memory. Only normalized derived records, request
references, retrieval timestamps, checksums, features, predictions, and reports
are written. The locked 2025 holdout and quarantined local assets are out of
scope.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import requests
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss

STATSAPI_ROOT = "https://statsapi.mlb.com"
DEFAULT_START = date(2024, 4, 1)
DEFAULT_END = date(2024, 5, 31)
DEFAULT_SPLIT = date(2024, 5, 16)
DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parents[1] / "docs" / "vertical_slice"
FINAL_ABSTRACT_STATE = "Final"
FEATURE_NAMES = (
    "league_yrfi_rate_200",
    "home_team_yrfi_rate_20",
    "away_team_yrfi_rate_20",
    "home_team_scored_rate_20",
    "away_team_scored_rate_20",
    "home_team_allowed_rate_20",
    "away_team_allowed_rate_20",
)
GAME_FEED_FIELDS = ",".join(
    (
        "metaData",
        "timeStamp",
        "gameData",
        "datetime",
        "dateTime",
        "officialDate",
        "status",
        "abstractGameState",
        "detailedState",
        "teams",
        "away",
        "home",
        "id",
        "name",
        "abbreviation",
        "venue",
        "liveData",
        "linescore",
        "innings",
        "num",
        "runs",
        "boxscore",
        "players",
        "person",
        "fullName",
        "stats",
        "pitching",
        "gamesStarted",
    )
)


class VerticalSliceError(RuntimeError):
    """The bounded slice cannot produce trustworthy derived evidence."""


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _source_timestamp(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.strptime(value, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return parsed.isoformat().replace("+00:00", "Z")


def _as_int(value: object) -> int | None:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed


def _request_json(path: str, parameters: Mapping[str, str | int] | None = None):
    endpoint = f"{STATSAPI_ROOT}{path}"
    params = dict(parameters or {})
    headers = {"User-Agent": "nrfi-predictor-development-vertical-slice/1.0"}
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(
                endpoint,
                params=params or None,
                headers=headers,
                timeout=(10, 45),
            )
            if response.status_code == 429 or response.status_code >= 500:
                raise requests.HTTPError(
                    f"StatsAPI transient status {response.status_code}",
                    response=response,
                )
            response.raise_for_status()
            payload_bytes = response.content
            payload = response.json()
            retrieved_at = _now_utc()
            return payload, {
                "endpoint": endpoint,
                "request_parameters": params,
                "retrieved_at": retrieved_at,
                "response_bytes": len(payload_bytes),
                "response_sha256": _sha256(payload_bytes),
            }
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.5 * (2**attempt))
    raise VerticalSliceError(f"StatsAPI GET failed for {path}: {last_error}")


def _actual_starter(feed: Mapping[str, Any], side: str) -> dict[str, Any] | None:
    players = (
        feed.get("liveData", {})
        .get("boxscore", {})
        .get("teams", {})
        .get(side, {})
        .get("players", {})
    )
    candidates: dict[int, str | None] = {}
    for player in (players or {}).values():
        pitching = (player.get("stats") or {}).get("pitching") or {}
        if _as_int(pitching.get("gamesStarted")) != 1:
            continue
        person = player.get("person") or {}
        person_id = _as_int(person.get("id"))
        if person_id is not None:
            name = person.get("fullName")
            candidates[person_id] = str(name) if name else None
    if len(candidates) != 1:
        return None
    person_id, name = next(iter(candidates.items()))
    return {"player_id": person_id, "player_name": name}


def normalize_game(
    scheduled: Mapping[str, Any],
    feed: Mapping[str, Any],
    schedule_provenance_id: str,
    feed_provenance_id: str,
    retrieved_at: str,
    normalized_at: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Normalize one finalized official game or return an explicit rejection."""
    game_pk = _as_int(scheduled.get("gamePk"))
    if game_pk is None:
        return None, "missing_game_pk"
    if scheduled.get("gameType") != "R":
        return None, "not_regular_season"

    game_data = feed.get("gameData", {})
    status = game_data.get("status", {}) or scheduled.get("status", {}) or {}
    if status.get("abstractGameState") != FINAL_ABSTRACT_STATE:
        return None, "not_finalized"

    innings = feed.get("liveData", {}).get("linescore", {}).get("innings", [])
    first = next((inning for inning in innings if inning.get("num") == 1), None)
    if not first:
        return None, "missing_first_inning_linescore"
    away_runs = _as_int((first.get("away") or {}).get("runs"))
    home_runs = _as_int((first.get("home") or {}).get("runs"))
    if away_runs is None or home_runs is None or away_runs < 0 or home_runs < 0:
        return None, "incomplete_first_inning_linescore"

    teams = game_data.get("teams", {})
    away_team = teams.get("away", {}) or {}
    home_team = teams.get("home", {}) or {}
    away_team_id = _as_int(away_team.get("id"))
    home_team_id = _as_int(home_team.get("id"))
    venue = game_data.get("venue", {}) or {}
    venue_id = _as_int(venue.get("id"))
    if away_team_id is None or home_team_id is None or venue_id is None:
        return None, "missing_team_or_venue_identity"

    scheduled_start = (game_data.get("datetime", {}) or {}).get("dateTime")
    if not isinstance(scheduled_start, str) or not scheduled_start:
        scheduled_start = scheduled.get("gameDate")
    if not isinstance(scheduled_start, str) or not scheduled_start:
        return None, "missing_scheduled_start"

    source_update_time = _source_timestamp(
        (feed.get("metaData", {}) or {}).get("timeStamp")
    )
    away_starter = _actual_starter(feed, "away")
    home_starter = _actual_starter(feed, "home")
    official_date = game_data.get("datetime", {}).get("officialDate")
    if not isinstance(official_date, str) or not official_date:
        official_date = scheduled.get("officialDate")

    record: dict[str, Any] = {
        "game_pk": game_pk,
        "official_date": official_date,
        "scheduled_start_at": scheduled_start,
        "game_type": "R",
        "status": status.get("detailedState"),
        "doubleheader": scheduled.get("doubleHeader", "N") != "N",
        "doubleheader_code": scheduled.get("doubleHeader", "N"),
        "game_number": _as_int(scheduled.get("gameNumber")) or 1,
        "away_team": {
            "team_id": away_team_id,
            "name": away_team.get("name"),
            "abbreviation": away_team.get("abbreviation"),
        },
        "home_team": {
            "team_id": home_team_id,
            "name": home_team.get("name"),
            "abbreviation": home_team.get("abbreviation"),
        },
        "venue": {"venue_id": venue_id, "name": venue.get("name")},
        "actual_starters": {"away": away_starter, "home": home_starter},
        "first_inning": {
            "away_runs": away_runs,
            "home_runs": home_runs,
            "completed": True,
            "yrfi": int(away_runs + home_runs > 0),
            "nrfi": int(away_runs + home_runs == 0),
        },
        "time_semantics": {
            "event_time": scheduled_start,
            "source_update_time": source_update_time,
            "retrieval_time": retrieved_at,
            "normalization_time": normalized_at,
            "correction_time": None,
            "finalized_at": None,
            "finalized_at_gap": "SOURCE_DOES_NOT_SUPPLY_DISTINCT_FINALIZATION_TIME",
            "label_available_at": source_update_time,
            "label_availability_basis": (
                "STATSAPI_FEED_UPDATE_TIMESTAMP_WITH_FINAL_STATUS"
                if source_update_time
                else "UNKNOWN_SOURCE_UPDATE_TIME"
            ),
        },
        "provenance": {
            "source": "official_mlb_statsapi",
            "schedule_provenance_id": schedule_provenance_id,
            "feed_provenance_id": feed_provenance_id,
        },
    }
    return record, None


def _provenance_record(
    kind: str, values: Mapping[str, object], source_update_time: str | None = None
) -> dict[str, Any]:
    payload = dict(values)
    payload["source_update_time"] = source_update_time
    record_id = _sha256(canonical_json_bytes(payload))
    return {"provenance_id": record_id, "kind": kind, **payload}


def retrieve_normalized_games(
    start: date,
    end: date,
    max_workers: int = 4,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if start > end:
        raise ValueError("start must be on or before end")
    if end.year >= 2025:
        raise VerticalSliceError("the locked 2025 holdout is outside this slice")

    schedule_params = {
        "sportId": 1,
        "gameType": "R",
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "hydrate": "team,venue",
    }
    schedule_payload, schedule_request = _request_json(
        "/api/v1/schedule", schedule_params
    )
    schedule_provenance = _provenance_record("schedule", schedule_request)
    scheduled_games = sorted(
        (
            game
            for day in schedule_payload.get("dates", [])
            for game in day.get("games", [])
            if game.get("gameType") == "R"
        ),
        key=lambda item: (str(item.get("gameDate")), int(item.get("gamePk", 0))),
    )

    feeds: dict[int, tuple[dict[str, Any], dict[str, Any]]] = {}

    def fetch(game_pk: int):
        payload, request = _request_json(
            f"/api/v1.1/game/{game_pk}/feed/live",
            {"fields": GAME_FEED_FIELDS},
        )
        source_update = _source_timestamp(
            (payload.get("metaData", {}) or {}).get("timeStamp")
        )
        return game_pk, payload, _provenance_record("game_feed", request, source_update)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(fetch, int(game["gamePk"])): int(game["gamePk"])
            for game in scheduled_games
            if game.get("gamePk") is not None
        }
        for future in as_completed(futures):
            game_pk, payload, provenance = future.result()
            feeds[game_pk] = (payload, provenance)

    normalized_at = _now_utc()
    games: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    provenance_records = [schedule_provenance]
    for scheduled in scheduled_games:
        game_pk = _as_int(scheduled.get("gamePk"))
        if game_pk is None or game_pk not in feeds:
            rejections.append({"game_pk": game_pk, "reason": "feed_unavailable"})
            continue
        feed, feed_provenance = feeds[game_pk]
        provenance_records.append(feed_provenance)
        game, reason = normalize_game(
            scheduled,
            feed,
            str(schedule_provenance["provenance_id"]),
            str(feed_provenance["provenance_id"]),
            str(feed_provenance["retrieved_at"]),
            normalized_at,
        )
        if game is None:
            rejections.append({"game_pk": game_pk, "reason": reason})
        else:
            games.append(game)
    return games, rejections, provenance_records


def _rate(values: Sequence[int]) -> float | None:
    if not values:
        return None
    return float(sum(values) / len(values))


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def build_features(games: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Build deterministic features using only labels available before cutoff."""
    ordered = sorted(games, key=lambda row: (row["scheduled_start_at"], row["game_pk"]))
    features: list[dict[str, Any]] = []
    for target_index, target in enumerate(ordered):
        cutoff = _parse_time(target.get("scheduled_start_at"))
        if cutoff is None:
            continue
        home_id = int(target["home_team"]["team_id"])
        away_id = int(target["away_team"]["team_id"])
        home_history: list[Mapping[str, Any]] = []
        away_history: list[Mapping[str, Any]] = []
        league_history: list[Mapping[str, Any]] = []
        for candidate in reversed(ordered[:target_index]):
            event_time = _parse_time(candidate.get("scheduled_start_at"))
            available_at = _parse_time(
                (candidate.get("time_semantics") or {}).get("label_available_at")
            )
            if (
                event_time is None
                or available_at is None
                or event_time >= cutoff
                or available_at >= cutoff
            ):
                continue
            if len(league_history) < 200:
                league_history.append(candidate)
            candidate_teams = {
                int(candidate["home_team"]["team_id"]),
                int(candidate["away_team"]["team_id"]),
            }
            if home_id in candidate_teams and len(home_history) < 20:
                home_history.append(candidate)
            if away_id in candidate_teams and len(away_history) < 20:
                away_history.append(candidate)
            if (
                len(league_history) == 200
                and len(home_history) == 20
                and len(away_history) == 20
            ):
                break

        def scored_allowed(row: Mapping[str, Any], team_id: int) -> tuple[int, int]:
            outcome = row["first_inning"]
            if int(row["home_team"]["team_id"]) == team_id:
                return int(outcome["home_runs"] > 0), int(outcome["away_runs"] > 0)
            return int(outcome["away_runs"] > 0), int(outcome["home_runs"] > 0)

        home_scored_allowed = [scored_allowed(row, home_id) for row in home_history]
        away_scored_allowed = [scored_allowed(row, away_id) for row in away_history]
        values = {
            "league_yrfi_rate_200": _rate(
                [int(row["first_inning"]["yrfi"]) for row in league_history]
            ),
            "home_team_yrfi_rate_20": _rate(
                [int(row["first_inning"]["yrfi"]) for row in home_history]
            ),
            "away_team_yrfi_rate_20": _rate(
                [int(row["first_inning"]["yrfi"]) for row in away_history]
            ),
            "home_team_scored_rate_20": _rate(
                [value[0] for value in home_scored_allowed]
            ),
            "away_team_scored_rate_20": _rate(
                [value[0] for value in away_scored_allowed]
            ),
            "home_team_allowed_rate_20": _rate(
                [value[1] for value in home_scored_allowed]
            ),
            "away_team_allowed_rate_20": _rate(
                [value[1] for value in away_scored_allowed]
            ),
        }
        eligible = (
            len(home_history) >= 10
            and len(away_history) >= 10
            and len(league_history) >= 100
            and all(values[name] is not None for name in FEATURE_NAMES)
        )
        features.append(
            {
                "game_pk": target["game_pk"],
                "official_date": target["official_date"],
                "prediction_cutoff": target["scheduled_start_at"],
                "home_team_id": home_id,
                "away_team_id": away_id,
                "venue_id": target["venue"]["venue_id"],
                "home_prior_games": len(home_history),
                "away_prior_games": len(away_history),
                "league_prior_games": len(league_history),
                "feature_values": values,
                "feature_eligible": eligible,
                "pitcher_features_used": False,
                "pitcher_feature_coverage": 0.0,
                "yrfi_actual": target["first_inning"]["yrfi"],
                "label_available_at": target["time_semantics"]["label_available_at"],
            }
        )
    return features


def _calibration(y_true: np.ndarray, probabilities: np.ndarray) -> dict[str, object]:
    bins: list[dict[str, object]] = []
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
    return {
        "expected_calibration_error": weighted_gap / len(y_true),
        "bins": bins,
    }


def train_and_evaluate(
    features: Sequence[Mapping[str, Any]], split_date: date
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    train_rows: list[Mapping[str, Any]] = []
    eligible_rows = [row for row in features if row.get("feature_eligible")]
    test_rows = [
        row
        for row in eligible_rows
        if str(row.get("official_date")) >= split_date.isoformat()
    ]
    test_cutoffs = [
        cutoff
        for row in test_rows
        if (cutoff := _parse_time(row.get("prediction_cutoff"))) is not None
    ]
    if not test_cutoffs:
        raise VerticalSliceError("chronological test period has no valid cutoffs")
    first_test_cutoff = min(test_cutoffs)
    for row in eligible_rows:
        if str(row.get("official_date")) >= split_date.isoformat():
            continue
        label_available_at = _parse_time(row.get("label_available_at"))
        if label_available_at is not None and label_available_at < first_test_cutoff:
            train_rows.append(row)
    if len(train_rows) < 100 or len(test_rows) < 50:
        raise VerticalSliceError(
            f"insufficient chronological rows: train={len(train_rows)} test={len(test_rows)}"
        )

    def matrix(rows: Sequence[Mapping[str, Any]]) -> np.ndarray:
        return np.asarray(
            [
                [float(row["feature_values"][name]) for name in FEATURE_NAMES]
                for row in rows
            ],
            dtype=float,
        )

    x_train = matrix(train_rows)
    x_test = matrix(test_rows)
    y_train = np.asarray([int(row["yrfi_actual"]) for row in train_rows], dtype=int)
    y_test = np.asarray([int(row["yrfi_actual"]) for row in test_rows], dtype=int)
    if len(set(y_train.tolist())) != 2 or len(set(y_test.tolist())) != 2:
        raise VerticalSliceError("chronological train/test split lacks both labels")

    model = LogisticRegression(C=0.25, max_iter=1000, solver="lbfgs")
    model.fit(x_train, y_train)
    probabilities = np.clip(model.predict_proba(x_test)[:, 1], 1e-6, 1 - 1e-6)
    baseline_probability = float(y_train.mean())
    baseline = np.full(len(y_test), baseline_probability, dtype=float)
    training_identity = _sha256(
        canonical_json_bytes(
            [
                {
                    "game_pk": row["game_pk"],
                    "features": row["feature_values"],
                    "yrfi": row["yrfi_actual"],
                }
                for row in train_rows
            ]
        )
    )
    model_version = f"real-team-baseline-v1-{training_identity[:12]}"
    predictions = [
        {
            "game_pk": row["game_pk"],
            "official_date": row["official_date"],
            "prediction_cutoff": row["prediction_cutoff"],
            "model_version": model_version,
            "p_yrfi": float(probability),
            "p_nrfi": float(1.0 - probability),
            "yrfi_actual": int(actual),
            "feature_values": row["feature_values"],
            "pitcher_features_used": False,
            "out_of_sample": True,
        }
        for row, probability, actual in zip(
            test_rows, probabilities.tolist(), y_test.tolist(), strict=True
        )
    ]
    model_log_loss = float(log_loss(y_test, probabilities, labels=[0, 1]))
    baseline_log_loss = float(log_loss(y_test, baseline, labels=[0, 1]))
    model_brier = float(brier_score_loss(y_test, probabilities))
    baseline_brier = float(brier_score_loss(y_test, baseline))
    evaluation = {
        "model_version": model_version,
        "split_date": split_date.isoformat(),
        "feature_names": list(FEATURE_NAMES),
        "train_count": len(train_rows),
        "test_count": len(test_rows),
        "train_yrfi_rate": baseline_probability,
        "test_yrfi_rate": float(y_test.mean()),
        "model": {
            "log_loss": model_log_loss,
            "brier_score": model_brier,
            **_calibration(y_test, probabilities),
        },
        "climatology_baseline": {
            "probability": baseline_probability,
            "log_loss": baseline_log_loss,
            "brier_score": baseline_brier,
        },
        "comparison": {
            "log_loss_improvement": baseline_log_loss - model_log_loss,
            "brier_improvement": baseline_brier - model_brier,
        },
        "locked_holdout_used": False,
    }
    return predictions, evaluation


def _flatten_records(
    games: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    teams: dict[int, dict[str, Any]] = {}
    venues: dict[int, dict[str, Any]] = {}
    starters: list[dict[str, Any]] = []
    for game in games:
        for side in ("away", "home"):
            team = dict(game[f"{side}_team"])
            teams[int(team["team_id"])] = team
            starter = game["actual_starters"][side]
            if starter:
                starters.append(
                    {
                        "game_pk": game["game_pk"],
                        "side": side,
                        **starter,
                        "actual_starter_confirmation_time": game["time_semantics"][
                            "source_update_time"
                        ],
                        "pregame_feature_eligible": False,
                    }
                )
        venue = dict(game["venue"])
        venues[int(venue["venue_id"])] = venue
    return (
        [teams[key] for key in sorted(teams)],
        [venues[key] for key in sorted(venues)],
        sorted(starters, key=lambda row: (int(row["game_pk"]), str(row["side"]))),
    )


def _write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> int:
    rows = list(records)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        for row in rows:
            handle.write(canonical_json_bytes(row))
    return len(rows)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def historical_prediction_payload(
    game_pk: int | None = None,
    artifact_dir: Path = DEFAULT_ARTIFACT_DIR,
) -> dict[str, Any]:
    """Return one committed real historical prediction without warehouse access."""
    predictions = _read_jsonl(artifact_dir / "predictions.jsonl")
    if not predictions:
        raise VerticalSliceError("no committed real historical prediction exists")
    prediction = (
        next((row for row in predictions if int(row["game_pk"]) == game_pk), None)
        if game_pk is not None
        else predictions[0]
    )
    if prediction is None:
        raise VerticalSliceError(f"no vertical-slice prediction for game {game_pk}")
    games = {
        int(row["game_pk"]): row
        for row in _read_jsonl(artifact_dir / "normalized_games.jsonl")
    }
    game = games.get(int(prediction["game_pk"]))
    if game is None:
        raise VerticalSliceError("prediction has no normalized game record")
    coverage = json.loads((artifact_dir / "coverage.json").read_text(encoding="utf-8"))
    evaluation = json.loads(
        (artifact_dir / "evaluation.json").read_text(encoding="utf-8")
    )
    return {
        "slice_id": coverage["slice_id"],
        "development_only": True,
        "game": {
            "game_pk": game["game_pk"],
            "official_date": game["official_date"],
            "scheduled_start_at": game["scheduled_start_at"],
            "away_team": game["away_team"],
            "home_team": game["home_team"],
            "venue": game["venue"],
            "actual_starters": game["actual_starters"],
        },
        "prediction": {
            "model_version": prediction["model_version"],
            "prediction_cutoff": prediction["prediction_cutoff"],
            "p_nrfi": prediction["p_nrfi"],
            "p_yrfi": prediction["p_yrfi"],
            "out_of_sample": prediction["out_of_sample"],
            "pitcher_features_used": prediction["pitcher_features_used"],
            "feature_values": prediction["feature_values"],
        },
        "outcome": game["first_inning"],
        "evidence": {
            "source": "official_mlb_statsapi",
            "split_date": evaluation["split_date"],
            "test_count": evaluation["test_count"],
            "feature_coverage": coverage["feature_coverage"],
            "model_log_loss": evaluation["model"]["log_loss"],
            "model_brier_score": evaluation["model"]["brier_score"],
            "expected_calibration_error": evaluation["model"][
                "expected_calibration_error"
            ],
            "locked_holdout_used": False,
            "market_data_used": False,
        },
        "disclaimer": "Historical development evidence; not a production or wagering signal.",
    }


def build_vertical_slice(
    output_dir: Path,
    start: date = DEFAULT_START,
    end: date = DEFAULT_END,
    split_date: date = DEFAULT_SPLIT,
    max_workers: int = 4,
) -> dict[str, Any]:
    games, rejections, provenance = retrieve_normalized_games(
        start, end, max_workers=max_workers
    )
    features = build_features(games)
    predictions, evaluation = train_and_evaluate(features, split_date)
    teams, venues, starters = _flatten_records(games)
    outcomes = [
        {
            "game_pk": game["game_pk"],
            "official_date": game["official_date"],
            **game["first_inning"],
            "source_update_time": game["time_semantics"]["source_update_time"],
            "retrieval_time": game["time_semantics"]["retrieval_time"],
            "correction_time": game["time_semantics"]["correction_time"],
        }
        for game in games
    ]
    feature_eligible = sum(bool(row["feature_eligible"]) for row in features)
    complete_starters = sum(
        game["actual_starters"]["away"] is not None
        and game["actual_starters"]["home"] is not None
        for game in games
    )
    coverage = {
        "slice_id": "nrfi.real_vertical_slice.2024-04-01_2024-05-31.v1",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "scheduled_regular_season_games": len(games) + len(rejections),
        "accepted_finalized_games": len(games),
        "rejected_games": len(rejections),
        "label_coverage": len(games) / (len(games) + len(rejections)),
        "complete_actual_starter_games": complete_starters,
        "actual_starter_coverage": complete_starters / len(games),
        "feature_eligible_games": feature_eligible,
        "feature_coverage": feature_eligible / len(features),
        "pitcher_feature_coverage": 0.0,
        "pitcher_features_used": False,
        "raw_payloads_persisted": False,
        "locked_holdout_used": False,
    }

    files: dict[str, tuple[object, bool]] = {
        "normalized_games.jsonl": (games, True),
        "teams.jsonl": (teams, True),
        "venues.jsonl": (venues, True),
        "actual_starters.jsonl": (starters, True),
        "first_inning_outcomes.jsonl": (outcomes, True),
        "provenance.jsonl": (provenance, True),
        "rejections.jsonl": (rejections, True),
        "features.jsonl": (features, True),
        "predictions.jsonl": (predictions, True),
        "coverage.json": (coverage, False),
        "evaluation.json": (evaluation, False),
    }
    row_counts: dict[str, int] = {}
    for name, (payload, is_jsonl) in files.items():
        path = output_dir / name
        if is_jsonl:
            row_counts[name] = _write_jsonl(path, payload)  # type: ignore[arg-type]
        else:
            _write_json(path, payload)
            row_counts[name] = 1

    manifest_entries = []
    for name in sorted(files):
        path = output_dir / name
        content = path.read_bytes()
        manifest_entries.append(
            {
                "path": name,
                "bytes": len(content),
                "sha256": _sha256(content),
                "row_count": row_counts[name],
            }
        )
    manifest = {
        "slice_id": coverage["slice_id"],
        "generated_at": _now_utc(),
        "entries": manifest_entries,
    }
    _write_json(output_dir / "artifact_manifest.json", manifest)
    return {"coverage": coverage, "evaluation": evaluation, "manifest": manifest}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("docs/vertical_slice"))
    parser.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    parser.add_argument("--end", type=date.fromisoformat, default=DEFAULT_END)
    parser.add_argument("--split", type=date.fromisoformat, default=DEFAULT_SPLIT)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    result = build_vertical_slice(
        args.output,
        start=args.start,
        end=args.end,
        split_date=args.split,
        max_workers=max(1, min(args.workers, 8)),
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
