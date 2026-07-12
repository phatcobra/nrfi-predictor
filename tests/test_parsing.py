from fixture_payloads import (
    PITCHER_A,
    PITCHER_B,
    game,
    schedule_payload,
    venues_payload,
)

from nrfi.data.statsapi import GAME_COLUMNS, parse_schedule_payload, parse_venues_payload


def test_parse_final_game_extracts_first_inning_and_probables():
    payload = schedule_payload([game(1000001, "2021-05-01", first_away=2, first_home=0)])
    rows = parse_schedule_payload(payload)
    assert len(rows) == 1
    row = rows[0]
    assert set(GAME_COLUMNS) <= set(row.keys())
    assert row["game_pk"] == 1000001
    assert row["season"] == 2021
    assert row["status"] == "Final"
    assert row["first_inning_runs_away"] == 2
    assert row["first_inning_runs_home"] == 0
    assert row["innings_recorded"] == 9
    assert row["home_probable_pitcher_id"] == PITCHER_A["id"]
    assert row["away_probable_pitcher_id"] == PITCHER_B["id"]
    assert row["venue_id"] == 7001
    assert row["day_night"] == "night"


def test_parse_preview_game_has_no_linescore_fields():
    payload = schedule_payload([game(1000002, "2021-05-02", status="Preview", first_away=None, away_pitcher=None)])
    rows = parse_schedule_payload(payload)
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "Preview"
    assert row["first_inning_runs_away"] is None
    assert row["first_inning_runs_home"] is None
    assert row["innings_recorded"] == 0
    assert row["away_probable_pitcher_id"] is None
    assert row["home_probable_pitcher_id"] == PITCHER_A["id"]


def test_parse_skips_non_regular_season_games():
    payload = schedule_payload(
        [
            game(1000003, "2021-03-15", game_type="S"),
            game(1000004, "2021-05-03"),
        ]
    )
    rows = parse_schedule_payload(payload)
    assert [r["game_pk"] for r in rows] == [1000004]


def test_parse_missing_home_half_of_first_inning():
    payload = schedule_payload([game(1000005, "2021-05-04", first_away=3, first_home=None)])
    row = parse_schedule_payload(payload)[0]
    assert row["first_inning_runs_away"] == 3
    assert row["first_inning_runs_home"] is None


def test_parse_venues_payload_handles_missing_fields():
    rows = parse_venues_payload(venues_payload())
    by_id = {r["venue_id"]: r for r in rows}
    assert by_id[7001]["latitude"] == 41.0
    assert by_id[7001]["roof_type"] == "Open"
    assert by_id[7002]["roof_type"] == "Dome"
    assert by_id[7003]["latitude"] is None
