"""Full-pipeline determinism: two complete builds produce identical outputs."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from nrfi import statcast_extraction as sx

# One admitted 2016 start and one admitted 2024 start for a single pitcher, so
# the 2024 start has a strict-prior window and the profile logic exercises the
# full path.  Each start is nine inning-1 pitches with a strikeout and a walk.
PITCHER = 4001
GAMES = [
    {"game_pk": 201600001, "date": "2016-04-10", "dir": "2016/04", "runs": 0},
    {"game_pk": 202400001, "date": "2024-04-10", "dir": "2024/04", "runs": 1},
]


def _pitch_rows(game_pk: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for pitch in range(1, 10):
        rows.append(
            {
                "game_date": None,
                "game_pk": game_pk,
                "pitcher": PITCHER,
                "batter": 5000 + pitch,
                "inning": 1,
                "inning_topbot": "Top",
                "at_bat_number": pitch,
                "pitch_number": 1,
                "events": "strikeout" if pitch == 1 else ("walk" if pitch == 2 else ""),
                "description": "swinging_strike" if pitch == 1 else "ball",
                "pitch_type": "FF",
                "release_speed": 94.0,
                "launch_speed": 88.0 if pitch == 3 else None,
                "launch_speed_angle": 3.0 if pitch == 3 else None,
                "zone": 5,
                "p_throws": "R",
                "stand": "L" if pitch % 2 else "R",
            }
        )
    return rows


def _seed_daycache(root: Path) -> None:
    for game in GAMES:
        target = root / str(game["dir"])
        target.mkdir(parents=True, exist_ok=True)
        name = "statcast_" + str(game["date"]).replace("-", "_") + ".parquet"
        pq.write_table(
            pa.Table.from_pylist(_pitch_rows(int(game["game_pk"]))), target / name
        )


def _seed_multiseason(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    games, features, starters = [], [], []
    for game in GAMES:
        gp = int(game["game_pk"])
        cutoff = f"{game['date']}T22:00:00Z"
        games.append(
            {
                "game_pk": gp,
                "official_date": game["date"],
                "scheduled_start_at": f"{game['date']}T23:05:00Z",
                "time_semantics": {"label_available_at": f"{game['date']}T23:59:00Z"},
                "first_inning": {"away_runs": int(game["runs"]), "home_runs": 0},
            }
        )
        features.append(
            {"game_pk": gp, "official_date": game["date"], "prediction_cutoff": cutoff}
        )
        starters.append(
            {
                "game_pk": gp,
                "side": "away",
                "player_id": PITCHER,
                "player_name": "Fixture Ace",
                "pregame_feature_eligible": False,
            }
        )
    (root / "normalized_games.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in games), encoding="utf-8"
    )
    (root / "features.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in features), encoding="utf-8"
    )
    (root / "actual_starters.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in starters), encoding="utf-8"
    )


def test_two_complete_builds_are_byte_identical(tmp_path: Path) -> None:
    day_cache = tmp_path / "statcast_days"
    multiseason = tmp_path / "multiseason"
    _seed_daycache(day_cache)
    _seed_multiseason(multiseason)

    def _run(out: Path) -> dict:
        return sx.generate_expanded_pitcher_statcast_package(
            day_cache_dir=day_cache,
            multiseason_dir=multiseason,
            output_dir=out,
            producing_commit="a" * 40,
            seasons=[2016, 2024],
        )

    first = _run(tmp_path / "build1")
    second = _run(tmp_path / "build2")

    assert first["coverage"]["day_files_opened"] == 2
    assert first["coverage"]["day_files_opened_2025"] == 0
    assert first["coverage"]["statcast_matched_starter_games"] == 2
    assert (
        first["manifest"]["history_partition_identity"]
        == (second["manifest"]["history_partition_identity"])
    )
    assert (
        first["manifest"]["feature_partition_identity"]
        == (second["manifest"]["feature_partition_identity"])
    )
    assert (
        first["manifest"]["source_file_ledger_identity"]
        == (second["manifest"]["source_file_ledger_identity"])
    )
    # every written artifact is byte-identical across the two complete builds
    for name in (
        "pitcher_game_history.parquet",
        "pitcher_features.parquet",
        "source_file_ledger.jsonl",
        "coverage.json",
        "artifact_manifest.json",
    ):
        assert (tmp_path / "build1" / name).read_bytes() == (
            tmp_path / "build2" / name
        ).read_bytes()


def test_fast_builder_matches_reference_builder_exactly() -> None:
    # A single pitcher with a run of starts on distinct dates, so the fast
    # cumulative career window and the reference full-sum window must agree.
    history = []
    starters = []
    for i in range(1, 26):
        gp = 300000 + i
        day = f"2016-04-{i:02d}"
        history.append(
            {
                "game_pk": gp,
                "official_date": day,
                "scheduled_start_at": f"{day}T23:05:00Z",
                "label_available_at": f"{day}T23:59:00Z",
                "pitcher_id": PITCHER,
                "side": "away",
                "pitch_count": 90 + i,
                "plate_appearances": 20 + (i % 3),
                "strikeouts": 5 + (i % 4),
                "walks": 2 + (i % 2),
                "home_runs": i % 2,
                "swings": 40 + i,
                "whiffs": 8 + (i % 5),
                "out_of_zone_pitches": 30 + i,
                "chases": 7 + (i % 3),
                "batted_balls": 12 + (i % 4),
                "hard_hit_balls": 3 + (i % 3),
                "barrels": i % 2,
                "fastball_pitches": 45 + i,
                "fastball_velocity_sum": 94.3 * (45 + i),
                "first_inning_runs_allowed": i % 3,
                "first_inning_scoreless": 1 if i % 3 == 0 else 0,
            }
        )
        starters.append(
            {
                "game_pk": gp,
                "official_date": day,
                "prediction_cutoff": f"{day}T22:00:00Z",
                "pitcher_id": PITCHER,
                "side": "away",
            }
        )

    reference = sx.build_pitcher_feature_snapshots(history, starters)
    fast = sx.build_pitcher_feature_snapshots_fast(history, starters)

    assert fast == reference
    assert sx._identity(fast) == sx._identity(reference)


def test_fast_builder_matches_reference_for_suspended_game_pitcher() -> None:
    # Start 1 is suspended: its label becomes available AFTER start 2's cutoff,
    # so the reference excludes it from start 2's availability.  This makes the
    # pitcher "complex", exercising the exact-reference fallback path.
    def _row(gp, day, label_day):
        return {
            "game_pk": gp,
            "official_date": day,
            "scheduled_start_at": f"{day}T23:05:00Z",
            "label_available_at": f"{label_day}T23:59:00Z",
            "pitcher_id": PITCHER,
            "side": "away",
            "pitch_count": 90,
            "plate_appearances": 21,
            "strikeouts": 6,
            "walks": 2,
            "home_runs": 1,
            "swings": 41,
            "whiffs": 9,
            "out_of_zone_pitches": 31,
            "chases": 7,
            "batted_balls": 13,
            "hard_hit_balls": 4,
            "barrels": 1,
            "fastball_pitches": 46,
            "fastball_velocity_sum": 94.3 * 46,
            "first_inning_runs_allowed": 1,
            "first_inning_scoreless": 0,
        }

    history = [
        _row(500001, "2016-04-01", "2016-04-05"),  # suspended, late label
        _row(500002, "2016-04-03", "2016-04-03"),
        _row(500003, "2016-04-08", "2016-04-08"),
        _row(500004, "2016-04-13", "2016-04-13"),
        _row(500005, "2016-04-18", "2016-04-18"),
    ]
    starters = [
        {
            "game_pk": r["game_pk"],
            "official_date": r["official_date"],
            "prediction_cutoff": f"{r['official_date']}T22:00:00Z",
            "pitcher_id": PITCHER,
            "side": "away",
        }
        for r in history
    ]

    reference = sx.build_pitcher_feature_snapshots(history, starters)
    fast = sx.build_pitcher_feature_snapshots_fast(history, starters)

    assert fast == reference
    # start 2 must see zero prior starts because start 1's label is not yet
    # available at start 2's cutoff.
    by_game = {int(s["game_pk"]): s for s in fast}
    assert by_game[500002]["feature_values"]["prior_starts_career"] == 0


def test_strict_prior_window_excludes_current_and_future_starts(tmp_path: Path) -> None:
    day_cache = tmp_path / "statcast_days"
    multiseason = tmp_path / "multiseason"
    _seed_daycache(day_cache)
    _seed_multiseason(multiseason)

    sx.generate_expanded_pitcher_statcast_package(
        day_cache_dir=day_cache,
        multiseason_dir=multiseason,
        output_dir=tmp_path / "out",
        producing_commit="a" * 40,
        seasons=[2016, 2024],
    )
    features = pq.read_table(tmp_path / "out" / "pitcher_features.parquet").to_pylist()
    by_game = {int(row["game_pk"]): row for row in features}

    # the 2016 start has no prior history; the 2024 start sees exactly one prior
    assert by_game[201600001]["feature_values"]["prior_starts_career"] == 0
    assert by_game[202400001]["feature_values"]["prior_starts_career"] == 1
