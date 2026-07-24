"""Tests for batter extraction: boundary, strict-prior, and determinism."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from nrfi import batter_extraction as bx

BATTER = 600001


def _game_row(game_pk: int, day: str, **over: object) -> dict[str, object]:
    row = {
        "game_pk": game_pk,
        "official_date": day,
        "scheduled_start_at": f"{day}T23:05:00Z",
        "label_available_at": f"{day}T23:59:00Z",
        "prediction_cutoff": f"{day}T22:00:00Z",
        "batter_id": BATTER,
        "batter_stand": "R",
        "plate_appearances": 4,
        "strikeouts": 1,
        "walks": 1,
        "hit_by_pitch": 0,
        "hits": 1,
        "total_bases": 2,
        "on_base_events": 2,
        "swings": 12,
        "whiffs": 3,
        "contact": 9,
        "batted_balls": 3,
        "hard_hit_balls": 1,
        "barrels": 0,
        "exit_velocity_sum": 88.5 * 3,
        "ground_balls": 1,
        "fly_balls": 1,
        "line_drives": 1,
        "typed_batted_balls": 3,
        "vs_lhp_plate_appearances": 2,
        "vs_lhp_strikeouts": 1,
        "vs_lhp_on_base_events": 1,
        "vs_rhp_plate_appearances": 2,
        "vs_rhp_strikeouts": 0,
        "vs_rhp_on_base_events": 1,
    }
    row.update(over)
    return row


def test_fast_builder_matches_reference_exactly() -> None:
    history = [_game_row(300000 + i, f"2016-04-{i:02d}") for i in range(1, 26)]
    reference = bx.build_batter_feature_snapshots_reference(history)
    fast = bx.build_batter_feature_snapshots(history)
    assert fast == reference
    assert bx._identity(fast) == bx._identity(reference)


def test_strict_prior_window_excludes_current_and_future() -> None:
    history = [
        _game_row(500001, "2016-04-01"),
        _game_row(500002, "2016-04-03"),
        _game_row(500003, "2016-04-08"),
    ]
    snaps = {int(s["game_pk"]): s for s in bx.build_batter_feature_snapshots(history)}
    assert snaps[500001]["feature_values"]["prior_games_career"] == 0
    assert snaps[500002]["feature_values"]["prior_games_career"] == 1
    assert snaps[500003]["feature_values"]["prior_games_career"] == 2
    # career PA accumulates only prior games
    assert snaps[500003]["feature_values"]["prior_plate_appearances_career"] == 8


def test_suspended_game_late_label_falls_back_to_reference() -> None:
    history = [
        _game_row(500001, "2016-04-01", label_available_at="2016-04-05T23:59:00Z"),
        _game_row(500002, "2016-04-03"),
        _game_row(500003, "2016-04-08"),
    ]
    fast = bx.build_batter_feature_snapshots(history)
    reference = bx.build_batter_feature_snapshots_reference(history)
    assert fast == reference
    snaps = {int(s["game_pk"]): s for s in fast}
    # game 2's cutoff precedes game 1's late label, so game 1 is not yet available
    assert snaps[500002]["feature_values"]["prior_games_career"] == 0


def _seed_daycache(root: Path) -> None:
    def _pitches(game_pk: int, batter: int, p_throws: str) -> list[dict[str, object]]:
        return [
            {
                "game_date": None,
                "game_pk": game_pk,
                "batter": batter,
                "pitcher": 7,
                "inning": 1,
                "at_bat_number": ab,
                "pitch_number": 1,
                "events": "single" if ab == 1 else ("strikeout" if ab == 2 else "walk"),
                "description": "hit_into_play" if ab == 1 else "swinging_strike",
                "bb_type": "line_drive" if ab == 1 else "",
                "launch_speed": 99.0 if ab == 1 else None,
                "launch_speed_angle": 6.0 if ab == 1 else None,
                "stand": "R",
                "p_throws": p_throws,
            }
            for ab in range(1, 4)
        ]

    for game_pk, day, sub, hand in (
        (201600001, "2016-04-10", "2016/04", "L"),
        (202400001, "2024-04-10", "2024/04", "R"),
    ):
        target = root / sub
        target.mkdir(parents=True, exist_ok=True)
        name = "statcast_" + day.replace("-", "_") + ".parquet"
        pq.write_table(
            pa.Table.from_pylist(_pitches(game_pk, BATTER, hand)), target / name
        )


def _seed_multiseason(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    games, features, starters = [], [], []
    for game_pk, day in ((201600001, "2016-04-10"), (202400001, "2024-04-10")):
        games.append(
            {
                "game_pk": game_pk,
                "official_date": day,
                "scheduled_start_at": f"{day}T23:05:00Z",
                "time_semantics": {"label_available_at": f"{day}T23:59:00Z"},
                "first_inning": {"away_runs": 0, "home_runs": 0},
            }
        )
        features.append(
            {
                "game_pk": game_pk,
                "official_date": day,
                "prediction_cutoff": f"{day}T22:00:00Z",
            }
        )
        starters.append(
            {
                "game_pk": game_pk,
                "side": "away",
                "player_id": 7,
                "player_name": "P",
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
        return bx.generate_batter_package(
            day_cache_dir=day_cache,
            multiseason_dir=multiseason,
            output_dir=out,
            producing_commit="a" * 40,
            seasons=[2016, 2024],
        )

    first = _run(tmp_path / "b1")
    second = _run(tmp_path / "b2")
    assert first["coverage"]["day_files_opened"] == 2
    assert first["coverage"]["day_files_opened_2025"] == 0
    assert first["coverage"]["batter_game_rows"] == 2
    assert (
        first["manifest"]["feature_partition_identity"]
        == (second["manifest"]["feature_partition_identity"])
    )
    for name in (
        "batter_game_history.parquet",
        "batter_features.parquet",
        "source_file_ledger.jsonl",
        "coverage.json",
        "artifact_manifest.json",
    ):
        assert (tmp_path / "b1" / name).read_bytes() == (
            tmp_path / "b2" / name
        ).read_bytes()


def test_generate_rejects_seasons_touching_2025(tmp_path: Path) -> None:
    with pytest.raises(bx.BatterExtractionError):
        bx.generate_batter_package(
            day_cache_dir=tmp_path,
            multiseason_dir=tmp_path,
            output_dir=tmp_path / "out",
            producing_commit="a" * 40,
            seasons=[2024, 2025],
        )
