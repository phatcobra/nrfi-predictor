"""Tests for the Context Foundation V1 reproduce/verify/publish path."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nrfi import aws_publish_context_features as pub

MULTISEASON = Path("docs/multiseason_2015_2024")
EVIDENCE = Path("docs/context_foundation_v1")
REFERENCE = Path("docs/context_foundation_v1/venue_reference.json")


class _FakeS3:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"VersionId": f"v{len(self.calls)}", "ETag": '"tag"'}


def test_reproduce_matches_baked_identities() -> None:
    _terminal, projection, meta = pub.reproduce_context(MULTISEASON, REFERENCE)
    assert meta["features_identity"] == pub.EXPECTED_FEATURES_IDENTITY
    assert meta["terminal_identity"] == pub.EXPECTED_TERMINAL_IDENTITY
    assert meta["side_schedule_identity"] == pub.EXPECTED_SIDE_SCHEDULE_IDENTITY
    assert meta["terminal_projection_sha256"] == pub.EXPECTED_TERMINAL_SHA256
    assert meta["venue_reference_sha256"] == pub.EXPECTED_VENUE_REFERENCE_SHA256
    assert meta["distinct_venues"] == pub.EXPECTED_VENUES
    assert meta["park_eligible_venues"] == pub.EXPECTED_PARK_ELIGIBLE
    assert len(projection) > 0


def test_reproduce_rejects_wrong_source(tmp_path: Path) -> None:
    (tmp_path / "features.jsonl").write_text(
        '{"game_pk": 1, "prediction_cutoff": "2024-04-01T22:00:00Z"}\n',
        encoding="utf-8",
    )
    (tmp_path / "normalized_games.jsonl").write_text(
        '{"game_type": "R", "game_pk": 1, "official_date": "2024-04-01",'
        ' "game_number": 1, "doubleheader_code": "N",'
        ' "scheduled_start_at": "2024-04-01T23:05:00Z",'
        ' "time_semantics": {"label_available_at": "2024-04-01T23:59:00Z"},'
        ' "venue": {"venue_id": 3}, "away_team": {"team_id": 100},'
        ' "home_team": {"team_id": 200},'
        ' "actual_starters": {"away": {"player_id": 5}, "home": {"player_id": 6}},'
        ' "first_inning": {"completed": true, "away_runs": 0, "home_runs": 0}}\n',
        encoding="utf-8",
    )
    with pytest.raises(pub.PublicationRefused):
        pub.reproduce_context(tmp_path, REFERENCE)


def _stub_reproduce(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        pub,
        "reproduce_context",
        lambda _m, _r: ([], b"projection-bytes", {"features_identity": "x"}),
    )


def test_publish_uploads_new_prefix_with_kms(monkeypatch: Any) -> None:
    _stub_reproduce(monkeypatch)
    fake = _FakeS3()
    published = pub.publish_context(
        multiseason_dir=MULTISEASON,
        evidence_dir=EVIDENCE,
        venue_reference_path=REFERENCE,
        bucket="lake",
        kms_key_arn="arn:kms",
        producing_commit="abc1234",
        s3_client=fake,
    )
    keys = [c["Key"] for c in fake.calls]
    assert f"{pub.LAKE_PREFIX}/park_terminal_factors.jsonl" in keys
    assert f"{pub.LAKE_PREFIX}/venue_reference.json" in keys
    assert f"{pub.LAKE_PREFIX}/context_published_manifest.json" in keys
    assert published["unified_feature_set_eligible"] is False
    assert published["park_context_eligible"] is False
    for call in fake.calls:
        assert call["ServerSideEncryption"] == "aws:kms"
        assert call["SSEKMSKeyId"] == "arn:kms"


def test_publish_refuses_invalid_commit(monkeypatch: Any) -> None:
    _stub_reproduce(monkeypatch)
    with pytest.raises(pub.PublicationRefused):
        pub.publish_context(
            multiseason_dir=MULTISEASON,
            evidence_dir=EVIDENCE,
            venue_reference_path=REFERENCE,
            bucket="lake",
            kms_key_arn="arn:kms",
            producing_commit="NOT-HEX",
            s3_client=_FakeS3(),
        )


def test_publish_refuses_missing_evidence(tmp_path: Path, monkeypatch: Any) -> None:
    _stub_reproduce(monkeypatch)
    with pytest.raises(pub.PublicationRefused):
        pub.publish_context(
            multiseason_dir=MULTISEASON,
            evidence_dir=tmp_path,
            venue_reference_path=REFERENCE,
            bucket="lake",
            kms_key_arn="arn:kms",
            producing_commit="abc1234",
            s3_client=_FakeS3(),
        )
