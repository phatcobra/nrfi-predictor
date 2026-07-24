from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from nrfi.pitcher_statcast import (
    _write_parquet,
    build_pitcher_feature_snapshots,
    select_inventory_partitions,
)
from nrfi.real_vertical_slice import VerticalSliceError, canonical_json_bytes


def _write_manifest(path: Path, rows: list[dict[str, object]]) -> str:
    with path.open("wb") as handle:
        for row in rows:
            handle.write(canonical_json_bytes(row))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _partition(name: str, requested: str, digest: str) -> dict[str, object]:
    return {
        "relative_path": name,
        "classification": "statcast_partition",
        "sha256": digest,
        "bytes": 10,
        "linked_metadata": [
            {
                "func": "get_statcast_data_from_csv_url",
                "metadata_path": f"{name}.json",
                "requested_date": requested,
            }
        ],
        "parquet_footer": {"readable": True},
        "selected_key_scan": {"key_contract_valid": True},
        "quarantine": {"quarantined": False},
    }


def test_inventory_selection_uses_proven_duplicate_rule(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    rows = [
        _partition("z.parquet", "2024-04-01", "a" * 64),
        _partition("a.parquet", "2024-04-01", "a" * 64),
        _partition("b.parquet", "2023-04-01", "b" * 64),
        _partition("holdout.parquet", "2025-04-01", "c" * 64),
    ]
    digest = _write_manifest(manifest, rows)

    selected, _ = select_inventory_partitions(
        manifest, [2023, 2024], expected_manifest_sha256=digest
    )

    assert [row["relative_path"] for row in selected] == ["b.parquet", "a.parquet"]


def test_inventory_selection_rejects_locked_holdout(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    digest = _write_manifest(
        manifest, [_partition("x.parquet", "2025-04-01", "a" * 64)]
    )

    with pytest.raises(VerticalSliceError, match="pre-2025"):
        select_inventory_partitions(manifest, [2025], expected_manifest_sha256=digest)


def _history(
    game_pk: int, available: str, pitches: int, runs: int
) -> dict[str, object]:
    return {
        "game_pk": game_pk,
        "official_date": f"2024-04-{game_pk:02d}",
        "scheduled_start_at": f"2024-04-{game_pk:02d}T17:00:00Z",
        "label_available_at": available,
        "pitcher_id": 7,
        "side": "away",
        "pitch_count": pitches,
        "plate_appearances": 20,
        "strikeouts": 5,
        "walks": 2,
        "home_runs": 1,
        "swings": 40,
        "whiffs": 10,
        "out_of_zone_pitches": 25,
        "chases": 8,
        "batted_balls": 12,
        "hard_hit_balls": 4,
        "barrels": 1,
        "fastball_pitches": 30,
        "fastball_velocity_sum": 2820.0,
        "first_inning_runs_allowed": runs,
        "first_inning_scoreless": int(runs == 0),
    }


def test_features_use_only_finalized_strict_prior_history() -> None:
    history = [
        _history(1, "2024-04-01T20:00:00Z", 80, 0),
        _history(2, "2024-04-02T20:00:00Z", 90, 1),
        _history(3, "2024-04-30T20:00:00Z", 100, 0),
    ]
    starters = [
        {
            "game_pk": 4,
            "official_date": "2024-04-04",
            "prediction_cutoff": "2024-04-04T16:00:00Z",
            "pitcher_id": 7,
            "side": "away",
        }
    ]

    row = build_pitcher_feature_snapshots(history, starters)[0]

    assert row["feature_values"]["prior_starts_career"] == 2
    assert row["feature_values"]["average_pitch_count_career"] == 85.0
    assert row["profile_feature_eligible"] is False
    assert row["historical_prediction_join_eligible"] is False
    assert (
        row["historical_prediction_join_ineligibility_reason"]
        == "NO_TIMESTAMPED_PROBABLE_STARTER_SNAPSHOT"
    )


def test_feature_identity_is_deterministic() -> None:
    histories = [
        _history(i, f"2024-04-{i:02d}T20:00:00Z", 80 + i, i % 2) for i in range(1, 4)
    ]
    starters = [
        {
            "game_pk": 4,
            "official_date": "2024-04-04",
            "prediction_cutoff": "2024-04-04T21:00:00Z",
            "pitcher_id": 7,
            "side": "away",
        }
    ]

    first = build_pitcher_feature_snapshots(histories, starters)
    second = build_pitcher_feature_snapshots(histories, starters)

    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_parquet_output_is_byte_deterministic(tmp_path: Path) -> None:
    rows = [
        {"pitcher_id": 7, "feature": 0.25, "missing": None},
        {"pitcher_id": 8, "feature": 0.5, "missing": "explicit"},
    ]
    first = tmp_path / "first.parquet"
    second = tmp_path / "second.parquet"

    assert _write_parquet(first, rows) == 2
    assert _write_parquet(second, rows) == 2
    assert first.read_bytes() == second.read_bytes()
