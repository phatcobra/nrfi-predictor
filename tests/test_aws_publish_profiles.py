"""Tests for the expanded-profile publication path (reproduce + upload)."""

from __future__ import annotations

import io
import json
from typing import Any

from nrfi import aws_publish_profiles as pub
from nrfi.pitcher_statcast import canonical_json_bytes


def _snapshot(game_pk: int, cutoff: str, eligible: bool) -> dict[str, Any]:
    return {
        "pitcher_id": 7,
        "game_pk": game_pk,
        "prediction_cutoff": cutoff,
        "profile_feature_eligible": eligible,
        "feature_version": "pitcher-statcast-strict-prior-v1",
        "feature_hash": f"hash-{game_pk}",
        "feature_values": {"strikeout_rate_career": 0.25},
    }


def test_projection_is_deterministic_and_sorted() -> None:
    snaps = [
        _snapshot(2, "2024-05-02T22:00:00Z", True),
        _snapshot(1, "2024-05-01T22:00:00Z", False),
    ]
    first = pub.build_projection_bytes(snaps)
    second = pub.build_projection_bytes(list(reversed(snaps)))
    assert first == second
    rows = [json.loads(line) for line in first.decode().splitlines()]
    assert [r["game_pk"] for r in rows] == [1, 2]
    assert rows[0]["feature_values"] == {"strikeout_rate_career": 0.25}


class _FakeS3:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "VersionId": f"v{len(self.calls)}",
            "ETag": '"etag"',
            "ChecksumSHA256": "abc",
        }


def test_put_uses_sse_kms_and_records_version(monkeypatch) -> None:
    fake = _FakeS3()
    result = pub._put(fake, "lake", "features/x/profiles.jsonl", b"data", "arn:kms")
    assert fake.calls[0]["ServerSideEncryption"] == "aws:kms"
    assert fake.calls[0]["SSEKMSKeyId"] == "arn:kms"
    assert fake.calls[0]["ChecksumAlgorithm"] == "SHA256"
    assert result["version_id"] == "v1"
    assert result["key"] == "features/x/profiles.jsonl"


def test_lake_prefix_is_new_immutable_identity() -> None:
    assert pub.LAKE_PREFIX == "features/pitcher-statcast-strict-prior-2015-2024-v1"
    # must not collide with the prior 2021-2024 artifact prefix
    assert "2015-2024" in pub.LAKE_PREFIX
    assert pub.LAKE_PREFIX != "features/pitcher-statcast-strict-prior-v1"


def test_projection_rows_carry_required_join_fields() -> None:
    rows = pub._profile_jsonl_rows([_snapshot(5, "2024-06-01T22:00:00Z", True)])
    assert set(rows[0]) >= {
        "pitcher_id",
        "prediction_cutoff",
        "game_pk",
        "profile_feature_eligible",
        "feature_version",
        "feature_hash",
        "feature_values",
    }
    # canonical bytes round-trip
    assert json.loads(canonical_json_bytes(rows[0]).decode()) == rows[0]


def test_reproduce_reads_history_and_checks_identity(monkeypatch, tmp_path) -> None:
    # a fake history/starters path is not needed: assert the guard rejects a
    # wrong identity by feeding an empty history through a patched loader.
    monkeypatch.setattr(pub, "_load_starters", lambda _dir: [])
    fake_table = type("T", (), {"to_pylist": lambda self: []})()
    monkeypatch.setattr(pub.pq, "read_table", lambda _p: fake_table)
    monkeypatch.setattr(pub, "build_pitcher_feature_snapshots_fast", lambda _h, _s: [])
    raised = False
    try:
        pub.reproduce_features(tmp_path / "h.parquet", tmp_path)
    except SystemExit:
        raised = True
    assert raised  # empty rebuild cannot match the expected real identity


def _unused(_: Any) -> Any:
    return io.BytesIO(b"")
