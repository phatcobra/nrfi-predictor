"""Offline tests for the bounded real-data vertical-slice transformations."""

from __future__ import annotations

from datetime import date

import pytest

from nrfi.real_vertical_slice import (
    FEATURE_NAMES,
    VerticalSliceError,
    build_features,
    normalize_game,
    retrieve_normalized_games,
    train_and_evaluate,
)


def _scheduled(game_pk: int = 1):
    return {
        "gamePk": game_pk,
        "gameType": "R",
        "gameDate": "2024-04-01T17:00:00Z",
        "officialDate": "2024-04-01",
        "doubleHeader": "N",
        "gameNumber": 1,
    }


def _player(player_id: int, name: str, games_started: int):
    return {
        "person": {"id": player_id, "fullName": name},
        "stats": {"pitching": {"gamesStarted": games_started}},
    }


def _feed(away_runs=0, home_runs=0, source_time="20240401_203000"):
    return {
        "metaData": {"timeStamp": source_time},
        "gameData": {
            "datetime": {
                "dateTime": "2024-04-01T17:00:00Z",
                "officialDate": "2024-04-01",
            },
            "status": {"abstractGameState": "Final", "detailedState": "Final"},
            "teams": {
                "away": {"id": 10, "name": "Away", "abbreviation": "AWY"},
                "home": {"id": 20, "name": "Home", "abbreviation": "HME"},
            },
            "venue": {"id": 30, "name": "Park"},
        },
        "liveData": {
            "linescore": {
                "innings": [
                    {
                        "num": 1,
                        "away": {"runs": away_runs},
                        "home": {"runs": home_runs},
                    }
                ]
            },
            "boxscore": {
                "teams": {
                    "away": {"players": {"ID1": _player(1, "A", 1)}},
                    "home": {"players": {"ID2": _player(2, "H", 1)}},
                }
            },
        },
    }


def _normalized(game_pk, event_time, available_at, home_id, away_id, yrfi):
    return {
        "game_pk": game_pk,
        "official_date": event_time[:10],
        "scheduled_start_at": event_time,
        "home_team": {"team_id": home_id},
        "away_team": {"team_id": away_id},
        "venue": {"venue_id": 30},
        "first_inning": {
            "home_runs": int(yrfi),
            "away_runs": 0,
            "yrfi": int(yrfi),
        },
        "time_semantics": {"label_available_at": available_at},
    }


def test_finalized_label_and_actual_starters_are_normalized():
    game, reason = normalize_game(
        _scheduled(),
        _feed(away_runs=1),
        "schedule-id",
        "feed-id",
        "2026-07-16T00:00:00Z",
        "2026-07-16T00:00:01Z",
    )
    assert reason is None
    assert game is not None
    assert game["first_inning"] == {
        "away_runs": 1,
        "home_runs": 0,
        "completed": True,
        "yrfi": 1,
        "nrfi": 0,
    }
    assert game["actual_starters"]["away"]["player_id"] == 1
    assert game["actual_starters"]["home"]["player_id"] == 2
    assert game["time_semantics"]["finalized_at"] is None
    assert game["time_semantics"]["label_available_at"] == "2024-04-01T20:30:00Z"


def test_missing_first_inning_is_rejected_not_inferred_as_nrfi():
    feed = _feed()
    feed["liveData"]["linescore"]["innings"] = []
    game, reason = normalize_game(
        _scheduled(), feed, "schedule-id", "feed-id", "r", "n"
    )
    assert game is None
    assert reason == "missing_first_inning_linescore"


def test_features_use_only_labels_available_before_cutoff():
    games = []
    for index in range(12):
        day = index + 1
        games.append(
            _normalized(
                index,
                f"2024-04-{day:02d}T17:00:00Z",
                f"2024-04-{day:02d}T20:00:00Z",
                20,
                10,
                index % 2,
            )
        )
    # This earlier event was not available until after the target cutoff.
    games.append(
        _normalized(
            99,
            "2024-04-05T16:00:00Z",
            "2024-05-01T00:00:00Z",
            20,
            10,
            1,
        )
    )
    target = _normalized(
        100,
        "2024-04-13T17:00:00Z",
        "2024-04-13T20:00:00Z",
        20,
        10,
        0,
    )
    games.append(target)
    row = next(item for item in build_features(games) if item["game_pk"] == 100)
    assert row["home_prior_games"] == 12
    assert row["away_prior_games"] == 12
    assert row["pitcher_features_used"] is False
    assert row["feature_values"]["home_team_yrfi_rate_20"] == 0.5


def test_locked_holdout_date_is_rejected_before_network_access():
    with pytest.raises(VerticalSliceError, match="locked 2025 holdout"):
        retrieve_normalized_games(date(2025, 4, 1), date(2025, 4, 2))


def test_chronological_split_uses_official_date_not_utc_calendar_date():
    rows = []
    for index in range(160):
        is_test = index >= 110
        official_date = "2024-05-16" if is_test else "2024-05-15"
        # A late May 15 MLB game begins after midnight UTC but remains a train date.
        cutoff = (
            f"2024-05-16T{17 + (index % 4):02d}:00:00Z"
            if is_test
            else f"2024-05-16T0{index % 6}:00:00Z"
        )
        rows.append(
            {
                "game_pk": index,
                "official_date": official_date,
                "prediction_cutoff": cutoff,
                "feature_eligible": True,
                "feature_values": {
                    name: 0.4 + 0.01 * (index % 5) for name in FEATURE_NAMES
                },
                "yrfi_actual": index % 2,
                "label_available_at": (
                    f"2024-05-16T0{6 + (index % 4)}:00:00Z"
                    if not is_test
                    else "2024-05-17T00:00:00Z"
                ),
            }
        )
    predictions, evaluation = train_and_evaluate(rows, date(2024, 5, 16))
    assert evaluation["train_count"] == 110
    assert evaluation["test_count"] == 50
    assert all(row["official_date"] == "2024-05-16" for row in predictions)
