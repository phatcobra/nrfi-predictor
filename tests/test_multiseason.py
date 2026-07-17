"""Deterministic multi-season probability-engine tests."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nrfi.multiseason import (
    analytical_game_record,
    acquire_development_games,
    derive_multiseason_evidence,
)
from nrfi.real_vertical_slice import VerticalSliceError


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _game(season: int, index: int) -> dict:
    event = datetime(season, 1, 1, 17 + index % 4, tzinfo=timezone.utc) + timedelta(
        days=index // 4
    )
    available = event + timedelta(hours=3)
    home_id = index % 10 + 1
    away_id = (index + 1) % 10 + 1
    yrfi = int((index + season) % 5 in {0, 1})
    game_pk = season * 10000 + index
    return {
        "game_pk": game_pk,
        "official_date": event.date().isoformat(),
        "scheduled_start_at": _timestamp(event),
        "game_type": "R",
        "status": "Final",
        "doubleheader": False,
        "doubleheader_code": "N",
        "game_number": 1,
        "away_team": {
            "team_id": away_id,
            "name": f"Away {away_id}",
            "abbreviation": f"A{away_id}",
        },
        "home_team": {
            "team_id": home_id,
            "name": f"Home {home_id}",
            "abbreviation": f"H{home_id}",
        },
        "venue": {"venue_id": home_id, "name": f"Park {home_id}"},
        "actual_starters": {
            "away": {"player_id": game_pk * 2, "player_name": "Away Starter"},
            "home": {"player_id": game_pk * 2 + 1, "player_name": "Home Starter"},
        },
        "first_inning": {
            "away_runs": yrfi,
            "home_runs": 0,
            "completed": True,
            "yrfi": yrfi,
            "nrfi": 1 - yrfi,
        },
        "time_semantics": {
            "event_time": _timestamp(event),
            "source_update_time": _timestamp(available),
            "retrieval_time": "2026-07-16T00:00:00Z",
            "normalization_time": "2026-07-16T00:00:01Z",
            "correction_time": None,
            "finalized_at": None,
            "finalized_at_gap": "SOURCE_DOES_NOT_SUPPLY_DISTINCT_FINALIZATION_TIME",
            "label_available_at": _timestamp(available),
            "label_availability_basis": (
                "STATSAPI_FEED_UPDATE_TIMESTAMP_WITH_FINAL_STATUS"
            ),
        },
        "provenance": {
            "source": "official_mlb_statsapi",
            "schedule_provenance_id": "schedule-observation",
            "feed_provenance_id": f"feed-observation-{game_pk}",
        },
    }


def _development_inputs(seasons: tuple[int, ...]):
    games = [_game(season, index) for season in seasons for index in range(800)]
    provenance = [
        {
            "provenance_id": "observation-id",
            "kind": "schedule",
            "endpoint": "https://statsapi.mlb.com/api/v1/schedule",
            "request_parameters": {"gameType": "R"},
            "retrieved_at": "2026-07-16T00:00:00Z",
            "response_bytes": 100,
            "response_sha256": "a" * 64,
            "source_update_time": None,
        }
    ]
    return games, provenance


@pytest.fixture(scope="module")
def derived_evidence() -> dict:
    seasons = (2021, 2022, 2023, 2024)
    games, provenance = _development_inputs(seasons)
    return derive_multiseason_evidence(
        games,
        [],
        [],
        provenance,
        seasons,
        "code-commit",
        "b" * 64,
        "2026-07-16T01:00:00Z",
        bootstrap_replicates=20,
    )


def test_identical_frozen_inputs_replay_to_identical_analytical_manifest():
    seasons = (2021, 2022)
    games, provenance = _development_inputs(seasons)
    first = derive_multiseason_evidence(
        games,
        [],
        [],
        provenance,
        seasons,
        "code-commit",
        "b" * 64,
        "2026-07-16T01:00:00Z",
        bootstrap_replicates=5,
    )
    replay = derive_multiseason_evidence(
        games,
        [],
        [],
        provenance,
        seasons,
        "code-commit",
        "b" * 64,
        "2099-01-01T00:00:00Z",
        bootstrap_replicates=5,
    )
    assert first["deterministic_manifest"] == replay["deterministic_manifest"]
    assert first["predictions"] == replay["predictions"]


def test_expanding_folds_emit_predictions_and_separate_grades(
    derived_evidence: dict,
):
    evaluation = derived_evidence["evaluation"]
    predictions = derived_evidence["predictions"]
    grades = derived_evidence["grades"]
    assert evaluation["fold_count"] == 3
    assert evaluation["decision"] in {
        "PREDICTIVE SKILL ESTABLISHED",
        "PREDICTIVE SKILL NOT ESTABLISHED",
    }
    assert len(predictions) == len(grades) > 1500
    assert all("yrfi_actual" not in row for row in predictions)
    assert all("finalized_outcome" not in row for row in predictions)
    assert {row["prediction_id"] for row in predictions} == {
        row["prediction_id"] for row in grades
    }
    assert all(row["market_snapshot_id"] is None for row in predictions)
    assert all(row["historical_replay"] is True for row in predictions)


def test_execution_timestamps_do_not_change_analytical_game_identity():
    original = _game(2021, 1)
    observed_later = _game(2021, 1)
    observed_later["time_semantics"]["retrieval_time"] = "2099-01-01T00:00:00Z"
    observed_later["time_semantics"]["normalization_time"] = "2099-01-01T00:00:01Z"
    observed_later["provenance"]["schedule_provenance_id"] = "later-schedule"
    observed_later["provenance"]["feed_provenance_id"] = "later-feed"
    assert analytical_game_record(original) == analytical_game_record(observed_later)


def test_grade_time_is_excluded_from_deterministic_replay_identity(
    derived_evidence: dict,
):
    replay_grades = [
        dict(row, grade_time="2099-01-01T00:00:00Z")
        for row in derived_evidence["grades"]
    ]
    assert all(
        {key: value for key, value in original.items() if key != "grade_time"}
        == {key: value for key, value in replay.items() if key != "grade_time"}
        for original, replay in zip(
            derived_evidence["grades"], replay_grades, strict=True
        )
    )
    assert (
        derived_evidence["deterministic_manifest"][
            "execution_timestamps_excluded_from_analytical_identities"
        ]
        is True
    )


def test_locked_holdout_is_rejected_before_cache_or_network_access(tmp_path: Path):
    with pytest.raises(VerticalSliceError, match="locked 2025 holdout"):
        acquire_development_games(
            tmp_path,
            (2024, 2025),
            max_workers=1,
            allow_network=False,
        )


def test_identical_cross_partition_games_are_reconciled_and_counted(
    monkeypatch, tmp_path: Path
):
    original = _game(2021, 1)
    later_observation = copy.deepcopy(original)
    later_observation["time_semantics"]["retrieval_time"] = "2026-07-17T00:00:00Z"
    later_observation["time_semantics"]["normalization_time"] = "2026-07-17T00:00:01Z"

    def fake_partition(cache_dir, season, month, max_workers, allow_network):
        del cache_dir, max_workers, allow_network
        if (season, month) == (2021, 3):
            return [original], [], []
        if (season, month) == (2021, 4):
            return [later_observation], [], []
        return [], [], []

    monkeypatch.setattr("nrfi.multiseason.acquire_month_partition", fake_partition)
    games, rejections, provenance, reconciliations = acquire_development_games(
        tmp_path,
        (2021, 2022),
        max_workers=1,
        allow_network=False,
    )
    assert len(games) == 1
    assert rejections == []
    assert provenance == []
    assert len(reconciliations) == 1
    reconciliation = reconciliations[0]
    assert reconciliation["schema_version"] == "reconciliation.v1"
    assert reconciliation["game_pk"] == original["game_pk"]
    assert reconciliation["reason"] == "cross_partition_duplicate_reconciled"
    assert reconciliation["source_partitions"] == ["2021-03", "2021-04"]
    assert reconciliation["duplicate_rows_removed"] == 1
    assert len(reconciliation["analytical_game_identity"]) == 64


def test_pooled_evidence_includes_frozen_baselines_and_uncertainty(
    derived_evidence: dict,
):
    pooled = derived_evidence["evaluation"]["pooled"]
    assert set(pooled["baselines"]) == {
        "overall_climatology",
        "prior_season_climatology",
        "rolling_league_200",
    }
    assert set(pooled["paired_improvement"]) == set(pooled["baselines"])
    assert all(
        row["uncertainty"]["lower_95"]
        <= row["p_yrfi"]
        <= row["uncertainty"]["upper_95"]
        for row in derived_evidence["predictions"]
    )
