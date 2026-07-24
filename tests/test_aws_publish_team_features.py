"""Tests for the team-feature reproduce/verify/publish path (real source)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nrfi import aws_publish_team_features as pub

MULTISEASON = Path("docs/multiseason_2015_2024")
EVIDENCE = Path("docs/team_first_inning_2015_2024")


class _FakeS3:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"VersionId": "v1", "ETag": '"e"', "ChecksumSHA256": "chk"}


def test_reproduce_matches_baked_identities() -> None:
    _rec, _snap, _term, _proj, meta = pub.reproduce_team(MULTISEASON)
    assert meta["records_identity"] == pub.EXPECTED_RECORDS_IDENTITY
    assert meta["features_identity"] == pub.EXPECTED_FEATURES_IDENTITY
    assert meta["terminal_identity"] == pub.EXPECTED_TERMINAL_IDENTITY
    assert meta["distinct_teams"] == 30
    assert meta["team_game_records"] == 45522


def test_reproduce_rejects_wrong_source(tmp_path: Path) -> None:
    (tmp_path / "features.jsonl").write_text(
        '{"game_pk": 1, "prediction_cutoff": "2024-04-01T22:00:00Z"}\n',
        encoding="utf-8",
    )
    (tmp_path / "normalized_games.jsonl").write_text(
        '{"game_type":"R","game_pk":1,"official_date":"2024-04-01",'
        '"scheduled_start_at":"2024-04-01T23:05:00Z",'
        '"time_semantics":{"label_available_at":"2024-04-01T23:59:00Z"},'
        '"away_team":{"team_id":100},"home_team":{"team_id":200},'
        '"first_inning":{"completed":true,"away_runs":1,"home_runs":0}}\n',
        encoding="utf-8",
    )
    with pytest.raises(pub.PublicationRefused):
        pub.reproduce_team(tmp_path)


def test_publish_team_uploads_new_prefix_with_kms() -> None:
    fake = _FakeS3()
    published = pub.publish_team(
        multiseason_dir=MULTISEASON,
        evidence_dir=EVIDENCE,
        bucket="lake-bucket",
        kms_key_arn="arn:aws:kms:us-east-2:660838763909:key/abc",
        producing_commit="ab61d4f",
        s3_client=fake,
    )
    assert (
        published["profile_identity"] == "team-first-inning-strict-prior-2015-2024-v1"
    )
    assert published["unified_feature_set_eligible"] is False
    assert published["distinct_teams"] == 30
    keys = [c["Key"] for c in fake.calls]
    assert all(
        k.startswith("features/team-first-inning-strict-prior-2015-2024-v1/")
        for k in keys
    )
    for name in (
        "team_game_records.jsonl",
        "team_features.jsonl",
        "team_terminal_profiles.jsonl",
        "team_coverage.json",
        "team_schema.json",
        "team_determinism_evidence.json",
        "team_published_manifest.json",
    ):
        assert f"{pub.LAKE_PREFIX}/{name}" in keys
    # never touches pitcher/batter prefixes
    assert not any("pitcher-statcast" in k or "batter-statcast" in k for k in keys)
    for call in fake.calls:
        assert call["ServerSideEncryption"] == "aws:kms"
        assert call["ChecksumAlgorithm"] == "SHA256"


def test_publish_refuses_invalid_commit() -> None:
    with pytest.raises(pub.PublicationRefused):
        pub.publish_team(
            multiseason_dir=MULTISEASON,
            evidence_dir=EVIDENCE,
            bucket="b",
            kms_key_arn="arn",
            producing_commit="not-hex!",
            s3_client=_FakeS3(),
        )


def test_publish_refuses_missing_evidence(tmp_path: Path) -> None:
    with pytest.raises(pub.PublicationRefused):
        pub.publish_team(
            multiseason_dir=MULTISEASON,
            evidence_dir=tmp_path,  # empty -> missing evidence
            bucket="b",
            kms_key_arn="arn",
            producing_commit="ab61d4f",
            s3_client=_FakeS3(),
        )
