"""Tests for the fail-closed terminal team profile loader."""

from __future__ import annotations

import hashlib
import io
from typing import Any

import pytest

from nrfi import team_profile_loader as L
from nrfi.pregame_snapshot import canonical_json_bytes


def _profile(team_id: int) -> dict[str, Any]:
    return {
        "schema_version": "team_terminal_profile.v1",
        "profile_version": "team-first-inning-terminal-2015-2024-v1",
        "feature_version": "team-first-inning-strict-prior-v1",
        "team_id": team_id,
        "career_games": 300,
        "team_context_feature_eligible": True,
        "feature_values": {"first_inning_scored_rate_career": 0.55},
        "feature_hash": f"h{team_id}",
    }


def _text(rows: list[dict[str, Any]]) -> str:
    return b"".join(canonical_json_bytes(r) for r in rows).decode("utf-8")


def _bake(monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]]) -> None:
    monkeypatch.setattr(L, "EXPECTED_TERMINAL_IDENTITY", L._identity(rows))
    monkeypatch.setattr(L, "EXPECTED_TEAMS", len(rows))


def test_loads_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [_profile(i) for i in (100, 200, 300)]
    _bake(monkeypatch, rows)
    r = L.load_team_profiles(_text(rows))
    assert r["load_status"] == L.STATUS_LOADED
    assert r["team_count"] == 3
    assert set(r["profiles"]) == {100, 200, 300}


def test_schema_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [_profile(100)]
    _bake(monkeypatch, rows)
    bad = dict(rows[0])
    bad["schema_version"] = "nope"
    r = L.load_team_profiles(_text([bad]))
    assert r["load_status"] == L.STATUS_SCHEMA_INVALID


def test_duplicate_team(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [_profile(100), _profile(100)]
    _bake(monkeypatch, rows)
    r = L.load_team_profiles(_text(rows))
    assert r["load_status"] == L.STATUS_ARTIFACT_INVALID
    assert "duplicate" in r["load_failure_reason"]


def test_identity_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [_profile(100), _profile(200)]
    monkeypatch.setattr(L, "EXPECTED_TEAMS", 2)
    monkeypatch.setattr(L, "EXPECTED_TERMINAL_IDENTITY", "0" * 64)
    r = L.load_team_profiles(_text(rows))
    assert r["load_status"] == L.STATUS_IDENTITY_MISMATCH


def test_team_count_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [_profile(100)]
    _bake(monkeypatch, rows)
    monkeypatch.setattr(L, "EXPECTED_TEAMS", 30)
    r = L.load_team_profiles(_text(rows))
    assert r["load_status"] == L.STATUS_ARTIFACT_INVALID


class _FakeS3:
    def __init__(self, body: bytes | None, *, raise_error: bool = False) -> None:
        self._body = body
        self._raise = raise_error

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        if self._raise:
            raise RuntimeError("access denied")
        return {"Body": io.BytesIO(self._body or b""), "VersionId": "ver-1"}


def test_s3_load_failed() -> None:
    r = L.read_team_profiles_from_s3(_FakeS3(None, raise_error=True), "bucket")
    assert r["load_status"] == L.STATUS_LOAD_FAILED


def test_s3_sha_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [_profile(100)]
    _bake(monkeypatch, rows)
    body = _text(rows).encode("utf-8")
    r = L.read_team_profiles_from_s3(_FakeS3(body), "bucket", expected_sha256="f" * 64)
    assert r["load_status"] == L.STATUS_ARTIFACT_INVALID


def test_s3_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [_profile(100), _profile(200)]
    _bake(monkeypatch, rows)
    body = _text(rows).encode("utf-8")
    sha = hashlib.sha256(body).hexdigest()
    r = L.read_team_profiles_from_s3(_FakeS3(body), "bucket", expected_sha256=sha)
    assert r["load_status"] == L.STATUS_LOADED
    assert r["version_id"] == "ver-1"
