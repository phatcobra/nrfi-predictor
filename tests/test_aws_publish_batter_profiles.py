"""Tests for the batter-profile reproduce/verify/publish path."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from nrfi import aws_publish_batter_profiles as pub
from nrfi import batter_extraction as bx
from nrfi import batter_live_profiles as blp


def _history(n: int, batter: int = 700001) -> list[dict[str, Any]]:
    rows = []
    for i in range(1, n + 1):
        day = f"2016-05-{i:02d}"
        rows.append(
            {
                "schema_version": "batter_game.v1",
                "game_pk": 400000 + i,
                "batter_id": batter,
                "official_date": day,
                "scheduled_start_at": f"{day}T23:05:00Z",
                "label_available_at": f"{day}T23:59:00Z",
                "prediction_cutoff": f"{day}T22:00:00Z",
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
                "exit_velocity_sum": 265.5,
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
        )
    return rows


class _FakeS3:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"VersionId": "v1", "ETag": '"etag"', "ChecksumSHA256": "chk"}


def test_projection_is_sorted_and_shaped() -> None:
    snapshots = bx.build_batter_feature_snapshots(_history(3))
    rows = pub._profile_jsonl_rows(snapshots)
    assert [r["game_pk"] for r in rows] == sorted(r["game_pk"] for r in rows)
    first = rows[0]
    assert set(first) == {
        "batter_id",
        "prediction_cutoff",
        "game_pk",
        "batter_stand",
        "profile_feature_eligible",
        "historical_prediction_join_eligible",
        "feature_version",
        "feature_hash",
        "feature_values",
    }
    assert first["historical_prediction_join_eligible"] is False
    assert pub.build_projection_bytes(snapshots) == pub.build_projection_bytes(
        snapshots
    )


def test_reproduce_rejects_identity_mismatch(tmp_path: Path) -> None:
    parquet = tmp_path / "batter_game_history.parquet"
    pq.write_table(pa.Table.from_pylist(_history(3)), parquet)
    # Baked constants are the real 472k-row identities; a 3-row fixture cannot match.
    with pytest.raises(SystemExit):
        pub.reproduce_features(parquet)


def _valid_artifact_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, n: int = 4
) -> tuple[Path, list[dict[str, Any]]]:
    """Build an artifact dir + coverage that satisfies the hardened guards."""
    history = _history(n)
    snapshots = bx.build_batter_feature_snapshots(history)
    hid = pub._identity(history)
    fid = pub._identity(snapshots)
    ledger_rows = [
        {"relative_path": "2016/05/x.parquet", "opened": True, "reason": "ADMITTED"}
    ]
    lid = pub._identity(ledger_rows)

    monkeypatch.setattr(pub, "EXPECTED_HISTORY_IDENTITY", hid)
    monkeypatch.setattr(pub, "EXPECTED_FEATURE_IDENTITY", fid)
    monkeypatch.setattr(pub, "EXPECTED_LEDGER_IDENTITY", lid)
    monkeypatch.setattr(pub, "EXPECTED_HISTORY_ROWS", len(history))
    monkeypatch.setattr(pub, "EXPECTED_FEATURE_ROWS", len(snapshots))
    monkeypatch.setattr(pub, "EXPECTED_ADMITTED_SOURCES", 2450)

    art = tmp_path / "art"
    art.mkdir()
    pq.write_table(pa.Table.from_pylist(history), art / "batter_game_history.parquet")
    (art / "source_file_ledger.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in ledger_rows), encoding="utf-8"
    )
    (art / "rejections.jsonl").write_text("", encoding="utf-8")
    coverage = {
        "schema_version": "batter_extraction_coverage.v1",
        "extraction_version": pub.BATTER_EXTRACTION_VERSION,
        "feature_version": pub.BATTER_FEATURE_VERSION,
        "day_files_opened": 2450,
        "day_files_opened_2025": 0,
        "locked_2025_holdout_accessed": False,
        "batter_game_rows": len(history),
        "batter_feature_snapshot_rows": len(snapshots),
        "distinct_batters": 1,
        "history_partition_identity": hid,
        "feature_partition_identity": fid,
        "source_file_ledger_identity": lid,
    }
    (art / "coverage.json").write_text(json.dumps(coverage), encoding="utf-8")
    for name in (
        "artifact_manifest.json",
        "determinism_evidence.json",
        "schema_definitions.json",
        "historical_lineup_timing.json",
    ):
        (art / name).write_text("{}", encoding="utf-8")
    return art, snapshots


def test_publish_uploads_new_prefix_with_kms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    art, snapshots = _valid_artifact_dir(tmp_path, monkeypatch)
    fake = _FakeS3()
    published = pub.publish(
        artifact_dir=art,
        bucket="lake-bucket",
        kms_key_arn="arn:aws:kms:us-east-2:660838763909:key/abc",
        producing_commit="cc3bf81",
        s3_client=fake,
    )

    assert published["profile_identity"] == "batter-statcast-strict-prior-2015-2024-v1"
    assert published["historical_prediction_join_eligible"] is False
    assert published["locked_2025_holdout_accessed"] is False
    assert published["features_parquet_reproduced_in_runner"] is True
    keys = [c["Key"] for c in fake.calls]
    assert all(
        k.startswith("features/batter-statcast-strict-prior-2015-2024-v1/")
        for k in keys
    )
    assert f"{pub.LAKE_PREFIX}/batter_features.parquet" in keys
    assert f"{pub.LAKE_PREFIX}/profiles.jsonl" in keys
    assert f"{pub.LAKE_PREFIX}/published_manifest.json" in keys
    assert f"{pub.LAKE_PREFIX}/historical_lineup_timing.json" in keys
    for call in fake.calls:
        assert call["ServerSideEncryption"] == "aws:kms"
        assert call["ChecksumAlgorithm"] == "SHA256"


def test_publish_refuses_invalid_producing_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    art, _ = _valid_artifact_dir(tmp_path, monkeypatch)
    with pytest.raises(pub.PublicationRefused):
        pub.publish(
            artifact_dir=art,
            bucket="b",
            kms_key_arn="arn",
            producing_commit="not-hex!",
            s3_client=_FakeS3(),
        )


def test_publish_refuses_nonzero_2025(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    art, _ = _valid_artifact_dir(tmp_path, monkeypatch)
    cov = json.loads((art / "coverage.json").read_text())
    cov["day_files_opened_2025"] = 1
    (art / "coverage.json").write_text(json.dumps(cov), encoding="utf-8")
    with pytest.raises(pub.PublicationRefused):
        pub.publish(
            artifact_dir=art,
            bucket="b",
            kms_key_arn="arn",
            producing_commit="cc3bf81",
            s3_client=_FakeS3(),
        )


def test_publish_refuses_missing_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    art, _ = _valid_artifact_dir(tmp_path, monkeypatch)
    (art / "schema_definitions.json").unlink()
    with pytest.raises(pub.PublicationRefused):
        pub.publish(
            artifact_dir=art,
            bucket="b",
            kms_key_arn="arn",
            producing_commit="cc3bf81",
            s3_client=_FakeS3(),
        )


def _valid_terminal_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, str, int, int]:
    # Two batters, one eligible (>=50 PA) and one not, so counts are non-trivial.
    history = _history(20, batter=800001) + _history(4, batter=800002)
    profiles = blp.build_terminal_profiles(history)
    identity = pub._identity(profiles)
    eligible = sum(1 for p in profiles if p["profile_feature_eligible"])
    monkeypatch.setattr(pub, "EXPECTED_TERMINAL_IDENTITY", identity)
    monkeypatch.setattr(pub, "EXPECTED_TERMINAL_ROWS", len(profiles))
    monkeypatch.setattr(pub, "EXPECTED_TERMINAL_ELIGIBLE", eligible)

    art = tmp_path / "art"
    art.mkdir()
    pq.write_table(pa.Table.from_pylist(history), art / "batter_game_history.parquet")
    (art / "coverage.json").write_text(
        json.dumps({"day_files_opened_2025": 0, "locked_2025_holdout_accessed": False}),
        encoding="utf-8",
    )
    for name in (
        "terminal_profile_coverage.json",
        "terminal_profile_schema.json",
        "terminal_determinism_evidence.json",
    ):
        (art / name).write_text("{}", encoding="utf-8")
    return art, identity, len(profiles), eligible


def test_terminal_reproduce_rejects_identity_mismatch(tmp_path: Path) -> None:
    parquet = tmp_path / "batter_game_history.parquet"
    pq.write_table(pa.Table.from_pylist(_history(20)), parquet)
    with pytest.raises(pub.PublicationRefused):
        pub.reproduce_terminal(parquet)  # fixture identity != baked 7e7fc570


def test_publish_terminal_uploads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    art, identity, rows, eligible = _valid_terminal_dir(tmp_path, monkeypatch)
    fake = _FakeS3()
    published = pub.publish_terminal(
        artifact_dir=art,
        bucket="lake-bucket",
        kms_key_arn="arn:aws:kms:us-east-2:660838763909:key/abc",
        producing_commit="19ac2ad",
        s3_client=fake,
    )
    assert published["terminal_profiles_identity"] == identity
    assert published["profile_count"] == rows
    assert published["eligible_count"] == eligible
    assert published["historical_lineup_timing_available"] is False
    keys = [c["Key"] for c in fake.calls]
    assert f"{pub.LAKE_PREFIX}/terminal_batter_profiles.jsonl" in keys
    assert f"{pub.LAKE_PREFIX}/terminal_published_manifest.json" in keys
    # never overwrites the full historical artifacts
    assert f"{pub.LAKE_PREFIX}/batter_features.parquet" not in keys
    assert f"{pub.LAKE_PREFIX}/profiles.jsonl" not in keys
    for call in fake.calls:
        assert call["ServerSideEncryption"] == "aws:kms"


def test_publish_terminal_refuses_missing_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    art, _identity, _rows, _eligible = _valid_terminal_dir(tmp_path, monkeypatch)
    (art / "terminal_profile_schema.json").unlink()
    with pytest.raises(pub.PublicationRefused):
        pub.publish_terminal(
            artifact_dir=art,
            bucket="b",
            kms_key_arn="arn",
            producing_commit="19ac2ad",
            s3_client=_FakeS3(),
        )
