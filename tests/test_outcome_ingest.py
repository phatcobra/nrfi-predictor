"""Offline tests for authoritative first-inning label attribution."""
from __future__ import annotations

import pytest

from nrfi.ingest_first_inning_outcomes import actual_starter_id


def _feed(away_players=None, home_players=None):
    return {
        "liveData": {
            "boxscore": {
                "teams": {
                    "away": {"players": away_players or {}},
                    "home": {"players": home_players or {}},
                }
            }
        }
    }


def _player(player_id, games_started):
    return {
        "person": {"id": player_id},
        "stats": {"pitching": {"gamesStarted": games_started}},
    }


def test_unique_actual_starter_is_returned():
    feed = _feed(
        away_players={
            "ID10": _player(10, 1),
            "ID11": _player(11, 0),
        },
        home_players={"ID20": _player(20, 1)},
    )
    assert actual_starter_id(feed, "away") == 10
    assert actual_starter_id(feed, "home") == 20


def test_missing_actual_starter_returns_none_not_probable_fallback():
    feed = _feed(away_players={"ID11": _player(11, 0)})
    assert actual_starter_id(feed, "away") is None


def test_ambiguous_multiple_starters_returns_none():
    feed = _feed(away_players={
        "ID10": _player(10, 1),
        "ID11": _player(11, 1),
    })
    assert actual_starter_id(feed, "away") is None


def test_invalid_side_is_rejected():
    with pytest.raises(ValueError):
        actual_starter_id(_feed(), "visitor")
