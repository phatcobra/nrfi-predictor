"""Tests for the versioned IANA (timezone_mode=iana) V2.2 context path.

These cover the availability-safe prior-game set, the same-day/doubleheader
policy, the EXPLICIT strict-prior park-factor self-exclusion (proven with a
malformed target whose label is available before its own cutoff), the
DST-aware IANA schedule helpers, and the starter-independence guard.
"""

from __future__ import annotations

import zoneinfo

import pytest

from nrfi.context_features import ContextFeatureError
from nrfi.context_features_iana import (
    PRIOR_SELF_INCLUSION,
    _assert_starter_independent,
    admitted_prior_games,
    compute_iana_schedule_travel,
    force_tzdata_only,
    iana_day_night,
    iana_dst_active,
    iana_utc_offset_hours,
    strict_prior_park_factors_safe,
)


def _row(
    game_pk: int,
    team_id: int,
    is_home: bool,
    date: str,
    start: str,
    label: str,
    cutoff: str,
    venue_id: int,
    rf: int,
    ra: int,
    dh: str = "N",
    gn: int = 1,
) -> dict:
    return {
        "game_pk": game_pk,
        "team_id": team_id,
        "is_home": is_home,
        "official_date": date,
        "season": int(date[:4]),
        "scheduled_start_at": start,
        "label_available_at": label,
        "prediction_cutoff": cutoff,
        "venue_id": venue_id,
        "doubleheader_code": dh,
        "game_number": gn,
        "first_inning_runs_for": rf,
        "first_inning_runs_against": ra,
    }


# --------------------------------------------------------------------------- #
# REQUIRED: strict-prior park factor excludes a MALFORMED target that could
# otherwise see itself (label_available_at <= its own prediction_cutoff).
# --------------------------------------------------------------------------- #
def test_park_factor_excludes_malformed_self_target() -> None:
    # A and B are legitimate priors (label after their own game, but at/before
    # the target cutoff). T is malformed: its label is available BEFORE its own
    # cutoff, so pure timing would let it enter its own park history.
    rows = [
        _row(
            1,
            100,
            True,
            "2019-04-01",
            "2019-04-01T20:00:00Z",
            "2019-04-01T22:00:00Z",
            "2019-04-01T16:00:00Z",
            10,
            1,
            0,
        ),
        _row(
            2,
            100,
            True,
            "2019-04-02",
            "2019-04-02T20:00:00Z",
            "2019-04-02T22:00:00Z",
            "2019-04-02T16:00:00Z",
            10,
            1,
            0,
        ),
        _row(
            3,
            100,
            True,
            "2019-04-03",
            "2019-04-03T20:00:00Z",
            "2019-04-03T10:00:00Z",
            "2019-04-03T16:00:00Z",
            10,
            99,
            0,
        ),
    ]
    park = strict_prior_park_factors_safe(rows)
    entry = park[3]
    # Only A and B may be counted; the malformed target's own 99 runs must NOT.
    assert entry["park_prior_games_at_venue"] == 2
    assert entry["park_first_inning_runs_per_game"] == pytest.approx(1.0)
    # If self-inclusion leaked, the venue rate would be (1+1+99)/3 == 33.67.
    assert entry["league_first_inning_runs_per_game"] == pytest.approx(1.0)


def test_park_factor_league_matches_venue_when_single_park() -> None:
    rows = [
        _row(
            1,
            100,
            True,
            "2019-04-01",
            "2019-04-01T20:00:00Z",
            "2019-04-01T22:00:00Z",
            "2019-04-01T16:00:00Z",
            10,
            2,
            1,
        ),
        _row(
            2,
            100,
            True,
            "2019-04-05",
            "2019-04-05T20:00:00Z",
            "2019-04-05T22:00:00Z",
            "2019-04-05T16:00:00Z",
            10,
            0,
            0,
        ),
    ]
    park = strict_prior_park_factors_safe(rows)
    # Game 1 has no admissible prior; game 2 sees only game 1.
    assert park[1]["park_prior_games_at_venue"] == 0
    assert park[2]["park_prior_games_at_venue"] == 1


# --------------------------------------------------------------------------- #
# Availability-safe priors: ordered by label_available_at, NOT official_date.
# --------------------------------------------------------------------------- #
def test_prior_set_uses_label_available_not_official_date() -> None:
    team_games = [
        # Legit prior: earlier date, label before target cutoff -> admitted.
        _row(
            10,
            100,
            False,
            "2019-05-01",
            "2019-05-01T23:00:00Z",
            "2019-05-02T02:00:00Z",
            "2019-05-01T18:00:00Z",
            10,
            0,
            0,
        ),
        # Suspended/late game: EARLIER official_date than target, but its label
        # only becomes available AFTER the target cutoff -> must be rejected.
        _row(
            11,
            100,
            False,
            "2019-05-02",
            "2019-05-02T23:00:00Z",
            "2019-05-06T22:00:00Z",
            "2019-05-02T18:00:00Z",
            10,
            5,
            5,
        ),
        _row(
            12,
            100,
            False,
            "2019-05-05",
            "2019-05-05T23:00:00Z",
            "2019-05-06T02:00:00Z",
            "2019-05-05T18:00:00Z",
            10,
            0,
            0,
        ),
    ]
    target = team_games[2]
    admitted, census = admitted_prior_games(team_games, target)
    admitted_pks = {int(r["game_pk"]) for r in admitted}
    assert admitted_pks == {10}
    assert 11 not in admitted_pks
    assert census["prior_rejected_after_cutoff_count"] == 1
    assert census["prior_admitted_count"] == 1
    assert census["target_self_exclusion_count"] == 1


def test_prior_self_exclusion_constant_and_census() -> None:
    # Duplicate target game_pk rows must never enter the admitted set even if
    # their label is available before the cutoff.
    tgt_cut = "2019-05-05T18:00:00Z"
    team_games = [
        _row(
            50,
            100,
            False,
            "2019-05-05",
            "2019-05-05T23:00:00Z",
            "2019-05-05T10:00:00Z",
            tgt_cut,
            10,
            3,
            0,
        ),
        _row(
            50,
            100,
            True,
            "2019-05-05",
            "2019-05-05T23:00:00Z",
            "2019-05-05T10:00:00Z",
            tgt_cut,
            10,
            0,
            3,
        ),
    ]
    target = team_games[0]
    admitted, census = admitted_prior_games(team_games, target)
    assert admitted == []
    assert census["target_self_exclusion_count"] == 2
    assert PRIOR_SELF_INCLUSION == "TARGET_ENTERED_OWN_PRIOR_HISTORY"


# --------------------------------------------------------------------------- #
# Same-day / doubleheader policy.
# --------------------------------------------------------------------------- #
def test_doubleheader_first_admitted_only_when_label_ready() -> None:
    dh1 = _row(
        20,
        200,
        True,
        "2019-06-01",
        "2019-06-01T17:00:00Z",
        "2019-06-01T18:00:00Z",
        "2019-06-01T15:00:00Z",
        20,
        1,
        0,
        dh="Y",
        gn=1,
    )
    # Second game's cutoff is AFTER game one's label -> game one is admitted.
    dh2_ready = _row(
        21,
        200,
        True,
        "2019-06-01",
        "2019-06-01T21:00:00Z",
        "2019-06-01T23:00:00Z",
        "2019-06-01T20:00:00Z",
        20,
        0,
        0,
        dh="Y",
        gn=2,
    )
    admitted, census = admitted_prior_games([dh1, dh2_ready], dh2_ready)
    assert {int(r["game_pk"]) for r in admitted} == {20}
    assert census["prior_same_day_admitted_count"] == 1


def test_doubleheader_first_not_admitted_when_label_late() -> None:
    dh1 = _row(
        20,
        200,
        True,
        "2019-06-01",
        "2019-06-01T17:00:00Z",
        "2019-06-01T18:00:00Z",
        "2019-06-01T15:00:00Z",
        20,
        1,
        0,
        dh="Y",
        gn=1,
    )
    # Second game's cutoff is BEFORE game one's label -> game one excluded.
    dh2_early = _row(
        21,
        200,
        True,
        "2019-06-01",
        "2019-06-01T21:00:00Z",
        "2019-06-01T23:00:00Z",
        "2019-06-01T17:30:00Z",
        20,
        0,
        0,
        dh="Y",
        gn=2,
    )
    admitted, census = admitted_prior_games([dh1, dh2_early], dh2_early)
    assert admitted == []
    assert census["prior_same_day_admitted_count"] == 0


# --------------------------------------------------------------------------- #
# DST-aware IANA helpers (distinct from fixed standard offsets).
# --------------------------------------------------------------------------- #
def test_iana_offset_is_dst_aware() -> None:
    # America/New_York: summer EDT = -4 (DST on), winter EST = -5 (DST off).
    assert iana_utc_offset_hours("2019-07-01T23:00:00Z", "America/New_York") == -4.0
    assert iana_utc_offset_hours("2019-01-01T23:00:00Z", "America/New_York") == -5.0
    assert iana_dst_active("2019-07-01T23:00:00Z", "America/New_York") is True
    assert iana_dst_active("2019-01-01T23:00:00Z", "America/New_York") is False
    # Europe/London summer = British Summer Time (+1), not +0.
    assert iana_utc_offset_hours("2019-07-01T18:00:00Z", "Europe/London") == 1.0
    # Asia/Tokyo has no DST -> +9 year round.
    assert iana_utc_offset_hours("2019-07-01T09:00:00Z", "Asia/Tokyo") == 9.0
    assert iana_dst_active("2019-01-01T09:00:00Z", "Asia/Tokyo") is False


def test_iana_day_night_boundary() -> None:
    # 1:05pm EDT -> day; 7:10pm EDT -> night.
    assert iana_day_night("2019-07-02T17:05:00Z", "America/New_York") == "day"
    assert iana_day_night("2019-07-02T23:10:00Z", "America/New_York") == "night"


def test_force_tzdata_only_returns_empty_path() -> None:
    original = list(zoneinfo.TZPATH)
    try:
        assert force_tzdata_only() == []
        # tzdata package still resolves zones even with an empty search path.
        assert iana_utc_offset_hours("2019-07-01T23:00:00Z", "America/New_York") == -4.0
    finally:
        zoneinfo.reset_tzpath(to=original)
        zoneinfo.ZoneInfo.clear_cache()


# --------------------------------------------------------------------------- #
# Schedule/travel from the admitted-prior set (night->day turnaround, tz shift).
# --------------------------------------------------------------------------- #
_VENUE_REF = {
    30: {
        "tz_label": "America/Los_Angeles",
        "latitude": 34.0739,
        "longitude": -118.2400,
        "altitude_ft": 500,
    },
    31: {
        "tz_label": "America/New_York",
        "latitude": 40.8296,
        "longitude": -73.9262,
        "altitude_ft": 55,
    },
}


def test_schedule_travel_night_to_day_and_tz_shift() -> None:
    # Prior: night home game in Los Angeles (7:10pm PDT = 02:10Z next day).
    prior = _row(
        60,
        300,
        True,
        "2019-07-01",
        "2019-07-02T02:10:00Z",
        "2019-07-02T05:00:00Z",
        "2019-07-01T23:00:00Z",
        30,
        0,
        0,
    )
    # Target: day road game in New York the next day (1:05pm EDT).
    target = _row(
        61,
        300,
        False,
        "2019-07-02",
        "2019-07-02T17:05:00Z",
        "2019-07-02T20:00:00Z",
        "2019-07-02T15:00:00Z",
        31,
        0,
        0,
    )
    values = compute_iana_schedule_travel([prior], target, _VENUE_REF)
    assert values["day_night"] == "day"
    assert values["prior_day_night"] == "night"
    assert values["rest_days"] == 1
    assert values["night_to_day_turnaround"] is True
    # NY (-4) minus LA (-7) = +3 hours eastward.
    assert values["tz_shift_hours"] == pytest.approx(3.0)
    assert values["current_utc_offset_hours"] == -4.0
    assert values["prior_utc_offset_hours"] == -7.0
    assert values["travel_miles"] == pytest.approx(2450, abs=60)
    assert values["trip_game_index"] == 1  # home->road breaks the streak


def test_schedule_travel_no_prior_is_null_safe() -> None:
    target = _row(
        61,
        300,
        False,
        "2019-07-02",
        "2019-07-02T17:05:00Z",
        "2019-07-02T20:00:00Z",
        "2019-07-02T15:00:00Z",
        31,
        0,
        0,
    )
    values = compute_iana_schedule_travel([], target, _VENUE_REF)
    assert values["has_prior_game"] is False
    assert values["rest_days"] is None
    assert values["night_to_day_turnaround"] is None
    assert values["day_night"] == "day"  # target-only features still populate


# --------------------------------------------------------------------------- #
# Starter-independence guard.
# --------------------------------------------------------------------------- #
def test_assert_starter_independent_allows_clean_schedule() -> None:
    clean = {
        "day_night": "day",
        "prior_day_night": "night",
        "rest_days": 1,
        "tz_shift_hours": 3.0,
        "night_to_day_turnaround": True,
        "trip_game_index": 1,
        "park_factor": 1.02,
    }
    _assert_starter_independent(clean)  # must not raise


@pytest.mark.parametrize(
    "bad_key",
    [
        "starter_era",
        "home_pitcher_id",
        "away_ctx_starter_rest",
        "workload_pitch_count",
        "lineup_slot",
        "batter_woba",
        "weather_temp_f",
        "umpire_id",
        "market_open_total",
    ],
)
def test_assert_starter_independent_rejects_forbidden(bad_key: str) -> None:
    with pytest.raises(ContextFeatureError):
        _assert_starter_independent({bad_key: 1, "day_night": "day"})
