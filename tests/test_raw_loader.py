"""Offline tests for raw dataset validation before Snowflake upsert."""
from __future__ import annotations

import pandas as pd
import pytest

from nrfi.raw_loader import validate_frame


def _pitcher_innings():
    return pd.DataFrame({
        "pitcher_id": [1, 2],
        "game_id": ["g1", "g2"],
        "game_date": ["2024-04-01", "2024-04-02"],
        "inning": [1, 1],
        "first_inning_runs": [0, 1],
        "first_inning_hits": [1, 2],
        "first_inning_walks": [0, 1],
        "first_inning_strikeouts": [2, 1],
        "first_inning_pa": [4, 6],
    })


def test_valid_frame_adds_provenance_without_imputing_stats():
    result = validate_frame(
        _pitcher_innings(), "pitcher_innings", "observed-test-source")
    assert len(result) == 2
    assert set(result["source"]) == {"observed-test-source"}
    assert result["ingested_at"].notna().all()
    assert result["first_inning_runs"].tolist() == [0, 1]


def test_missing_required_column_is_rejected():
    frame = _pitcher_innings().drop(columns=["game_id"])
    with pytest.raises(ValueError, match="missing required columns"):
        validate_frame(frame, "pitcher_innings", "source")


def test_unknown_column_is_rejected():
    frame = _pitcher_innings().assign(invented_metric=1.0)
    with pytest.raises(ValueError, match="unknown columns"):
        validate_frame(frame, "pitcher_innings", "source")


def test_duplicate_keys_are_rejected():
    frame = pd.concat([_pitcher_innings(), _pitcher_innings().iloc[[0]]],
                      ignore_index=True)
    with pytest.raises(ValueError, match="duplicate dataset keys"):
        validate_frame(frame, "pitcher_innings", "source")


def test_null_key_is_rejected():
    frame = _pitcher_innings()
    frame.loc[0, "game_id"] = None
    with pytest.raises(ValueError, match="null values"):
        validate_frame(frame, "pitcher_innings", "source")


def test_invalid_numeric_value_is_rejected():
    frame = _pitcher_innings()
    frame.loc[0, "first_inning_runs"] = "not-a-number"
    with pytest.raises(ValueError):
        validate_frame(frame, "pitcher_innings", "source")


def test_source_provenance_is_required():
    with pytest.raises(ValueError, match="source provenance"):
        validate_frame(_pitcher_innings(), "pitcher_innings", "")
