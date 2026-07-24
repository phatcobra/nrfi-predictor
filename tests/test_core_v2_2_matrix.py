"""Tests for the starter-independent NRFI_CORE_V2_2_ADMISSIBLE matrix.

Focus: the hard forbidden-column guard (no starter-dependent or 2025 columns),
fixed-vocabulary categorical one-hot encoding, and the separation of the
missingness regime (explicit _missing indicators) from schema drift (an
unexpected category fails closed).
"""

from __future__ import annotations

import pytest

from nrfi.core_v2_2_matrix import (
    CATEGORICAL_VOCAB,
    FORBIDDEN_PREFIX_PATTERNS,
    FORBIDDEN_SUBSTRINGS,
    CoreV22MatrixError,
    _emit_binary,
    _emit_categorical,
    _emit_continuous,
    assert_admissible_columns,
)


def test_admissible_columns_accepts_v2_2_shape() -> None:
    cols = [
        "away_t_fi_runs_for_rate_career",
        "home_t_fi_runs_against_rate_last_10",
        "away_rest_days",
        "home_travel_miles",
        "away_prior_day_night_night",
        "home_trip_kind_road_trip",
        "g_local_scheduled_hour",
        "g_day_night_day",
        "g_dst_active",
        "park_factor",
        "park_prior_games_at_venue",
        "away_tz_shift_hours_missing",
    ]
    assert_admissible_columns(cols)  # must not raise


@pytest.mark.parametrize(
    "leaked",
    [
        "away_p_k_rate",
        "home_p_first_inning_traffic",
        "away_ctx_starter_rest_days",
        "home_ctx_starter_starts_prior_30d",
        "home_pitcher_id",
        "away_starter_era",
        "workload_pitch_count",
        "batter_woba",
        "lineup_slot_1",
        "weather_temp_f",
        "umpire_id",
        "market_open_total",
        "team_fi_rate_2025",
    ],
)
def test_admissible_columns_rejects_forbidden(leaked: str) -> None:
    with pytest.raises(CoreV22MatrixError):
        assert_admissible_columns(["away_t_ok", leaked])


def test_forbidden_tokens_cover_required_families() -> None:
    for token in (
        "pitcher",
        "starter",
        "workload",
        "lineup",
        "batter",
        "weather",
        "umpire",
        "market",
        "2025",
    ):
        assert token in FORBIDDEN_SUBSTRINGS
    for pattern in ("away_p_", "home_p_", "away_ctx_starter_", "home_ctx_starter_"):
        assert pattern in FORBIDDEN_PREFIX_PATTERNS


def test_emit_continuous_value_and_missing() -> None:
    out: dict[str, object] = {}
    schema: dict[str, str] = {}
    _emit_continuous(out, schema, "away_", "rest_days", 3)
    assert out["away_rest_days"] == 3.0
    assert out["away_rest_days_missing"] == 0.0
    assert schema["away_rest_days"] == "continuous"
    assert schema["away_rest_days_missing"] == "missing_indicator"

    out2: dict[str, object] = {}
    schema2: dict[str, str] = {}
    _emit_continuous(out2, schema2, "away_", "travel_miles", None)
    assert out2["away_travel_miles"] is None
    assert out2["away_travel_miles_missing"] == 1.0


def test_emit_binary_true_false_none() -> None:
    out: dict[str, object] = {}
    schema: dict[str, str] = {}
    _emit_binary(out, schema, "home_", "night_to_day_turnaround", True)
    assert out["home_night_to_day_turnaround"] == 1.0
    assert out["home_night_to_day_turnaround_missing"] == 0.0
    _emit_binary(out, schema, "home_", "prior_dst_active", None)
    assert out["home_prior_dst_active"] == 0.0
    assert out["home_prior_dst_active_missing"] == 1.0


def test_emit_categorical_onehot_and_null_missing() -> None:
    out: dict[str, object] = {}
    schema: dict[str, str] = {}
    _emit_categorical(out, schema, "g_", "day_night", "night")
    assert out["g_day_night_night"] == 1.0
    assert out["g_day_night_day"] == 0.0
    assert out["g_day_night_missing"] == 0.0
    assert schema["g_day_night_night"] == "onehot"

    out2: dict[str, object] = {}
    schema2: dict[str, str] = {}
    _emit_categorical(out2, schema2, "g_", "day_night", None)
    assert out2["g_day_night_day"] == 0.0
    assert out2["g_day_night_night"] == 0.0
    assert out2["g_day_night_missing"] == 1.0


def test_emit_categorical_unknown_category_is_schema_drift() -> None:
    # A null value is ordinary missingness; a non-null UNKNOWN category is schema
    # drift and must fail closed (Correction 6: separate the two).
    with pytest.raises(CoreV22MatrixError):
        _emit_categorical({}, {}, "g_", "day_night", "twilight")


def test_categorical_vocab_is_exhaustive_and_fixed() -> None:
    assert CATEGORICAL_VOCAB["day_night"] == ("day", "night")
    assert CATEGORICAL_VOCAB["prior_day_night"] == ("day", "night")
    assert CATEGORICAL_VOCAB["trip_kind"] == ("home_stand", "road_trip")
    assert CATEGORICAL_VOCAB["doubleheader_code"] == ("N", "Y", "S")
