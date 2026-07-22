"""Tests for the fail-closed Context Foundation V1 artifact loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nrfi import context_profile_loader as loader

PARK = Path("docs/context_foundation_v1/park_terminal_factors.jsonl")
REFERENCE = Path("docs/context_foundation_v1/venue_reference.json")


class _FakeS3:
    def __init__(self, body: bytes, *, raise_error: bool = False) -> None:
        self._body = body
        self._raise = raise_error

    def get_object(self, **_kwargs: Any) -> dict[str, Any]:
        if self._raise:
            raise RuntimeError("no such key")

        class _Body:
            def __init__(self, data: bytes) -> None:
                self._data = data

            def read(self) -> bytes:
                return self._data

        return {"Body": _Body(self._body), "VersionId": "v1"}


def test_committed_park_projection_loads_and_matches_identity() -> None:
    result = loader.load_park_profiles(PARK.read_text(encoding="utf-8"))
    assert result["load_status"] == loader.STATUS_LOADED
    assert result["venue_count"] == loader.EXPECTED_VENUES
    assert result["profile_identity"] == loader.EXPECTED_TERMINAL_IDENTITY


def test_identity_mismatch_fails_closed() -> None:
    result = loader.load_park_profiles(
        PARK.read_text(encoding="utf-8"), expected_identity="deadbeef"
    )
    assert result["load_status"] == loader.STATUS_IDENTITY_MISMATCH
    assert not result["park_profiles"]


def test_bad_schema_fails_closed() -> None:
    result = loader.load_park_profiles('{"schema_version": "nope", "venue_id": 1}\n')
    assert result["load_status"] == loader.STATUS_SCHEMA_INVALID


def test_duplicate_venue_fails_closed() -> None:
    line = '{"schema_version": "park_terminal_factor.v1", "venue_id": 1}'
    result = loader.load_park_profiles(f"{line}\n{line}\n")
    assert result["load_status"] == loader.STATUS_ARTIFACT_INVALID


def test_wrong_count_fails_closed() -> None:
    line = '{"schema_version": "park_terminal_factor.v1", "venue_id": 1}\n'
    result = loader.load_park_profiles(line, expected_identity="x")
    assert result["load_status"] == loader.STATUS_ARTIFACT_INVALID
    assert "venue count" in (result["load_failure_reason"] or "")


def test_s3_read_sha_mismatch_fails_closed() -> None:
    fake = _FakeS3(b"corrupt-bytes")
    result = loader.read_park_profiles_from_s3(fake, "bucket")
    assert result["load_status"] == loader.STATUS_ARTIFACT_INVALID


def test_s3_read_error_fails_closed() -> None:
    fake = _FakeS3(b"", raise_error=True)
    result = loader.read_park_profiles_from_s3(fake, "bucket")
    assert result["load_status"] == loader.STATUS_LOAD_FAILED


def test_s3_read_happy_path_matches_committed() -> None:
    body = PARK.read_bytes()
    fake = _FakeS3(body)
    result = loader.read_park_profiles_from_s3(
        fake, "bucket", expected_sha256=loader.EXPECTED_PROJECTION_SHA256
    )
    assert result["load_status"] == loader.STATUS_LOADED
    assert result["version_id"] == "v1"


def test_venue_reference_loads_and_verifies_sha() -> None:
    result = loader.load_venue_reference_text(REFERENCE.read_text(encoding="utf-8"))
    assert result["load_status"] == loader.STATUS_LOADED
    assert result["venue_count"] == loader.EXPECTED_VENUES
    assert result["sha256"] == loader.EXPECTED_VENUE_REFERENCE_SHA256


def test_venue_reference_sha_mismatch_fails_closed() -> None:
    result = loader.load_venue_reference_text(
        '{"schema_version": "venue_reference.v1"}'
    )
    assert result["load_status"] == loader.STATUS_ARTIFACT_INVALID
