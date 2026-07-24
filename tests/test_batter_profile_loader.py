"""Tests for the fail-closed terminal batter profile loader."""

from __future__ import annotations

import hashlib
import io
from typing import Any

import pytest

from nrfi import batter_profile_loader as L
from nrfi.pregame_snapshot import canonical_json_bytes


def _profile(batter_id: int, *, eligible: bool = True) -> dict[str, Any]:
    return {
        "schema_version": "batter_terminal_profile.v1",
        "profile_version": "batter-terminal-strict-prior-2015-2024-v1",
        "feature_version": "batter-statcast-strict-prior-v1",
        "batter_id": batter_id,
        "career_games": 100,
        "career_plate_appearances": 400,
        "profile_feature_eligible": eligible,
        "batter_stand_latest": "R",
        "feature_values": {"on_base_rate_career": 0.33},
        "feature_hash": f"h{batter_id}",
    }


def _text(rows: list[dict[str, Any]]) -> str:
    return b"".join(canonical_json_bytes(r) for r in rows).decode("utf-8")


def _bake(monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]]) -> None:
    monkeypatch.setattr(L, "EXPECTED_TERMINAL_IDENTITY", L._identity(rows))
    monkeypatch.setattr(L, "EXPECTED_TERMINAL_ROWS", len(rows))
    monkeypatch.setattr(
        L,
        "EXPECTED_TERMINAL_ELIGIBLE",
        sum(1 for r in rows if r["profile_feature_eligible"]),
    )


def test_loads_valid_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [_profile(1), _profile(2, eligible=False), _profile(3)]
    _bake(monkeypatch, rows)
    r = L.load_terminal_profiles(_text(rows))
    assert r["load_status"] == L.STATUS_LOADED
    assert r["row_count"] == 3
    assert r["eligible_count"] == 2
    assert set(r["profiles"]) == {1, 2, 3}


def test_schema_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [_profile(1)]
    _bake(monkeypatch, rows)
    bad = dict(rows[0])
    bad["schema_version"] = "nope"
    r = L.load_terminal_profiles(_text([bad]))
    assert r["load_status"] == L.STATUS_SCHEMA_INVALID


def test_duplicate_batter_id(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [_profile(1), _profile(1)]
    _bake(monkeypatch, rows)
    r = L.load_terminal_profiles(_text(rows))
    assert r["load_status"] == L.STATUS_ARTIFACT_INVALID
    assert "duplicate" in r["load_failure_reason"]


def test_identity_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [_profile(1), _profile(2)]
    monkeypatch.setattr(L, "EXPECTED_TERMINAL_ROWS", 2)
    monkeypatch.setattr(L, "EXPECTED_TERMINAL_ELIGIBLE", 2)
    monkeypatch.setattr(L, "EXPECTED_TERMINAL_IDENTITY", "0" * 64)
    r = L.load_terminal_profiles(_text(rows))
    assert r["load_status"] == L.STATUS_IDENTITY_MISMATCH


def test_row_count_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [_profile(1)]
    _bake(monkeypatch, rows)
    monkeypatch.setattr(L, "EXPECTED_TERMINAL_ROWS", 99)
    r = L.load_terminal_profiles(_text(rows))
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
    r = L.read_terminal_profiles_from_s3(_FakeS3(None, raise_error=True), "bucket")
    assert r["load_status"] == L.STATUS_LOAD_FAILED


def test_s3_sha_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [_profile(1)]
    _bake(monkeypatch, rows)
    body = _text(rows).encode("utf-8")
    r = L.read_terminal_profiles_from_s3(
        _FakeS3(body), "bucket", expected_sha256="f" * 64
    )
    assert r["load_status"] == L.STATUS_ARTIFACT_INVALID
    assert "sha256" in r["load_failure_reason"]


def test_s3_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [_profile(1), _profile(2)]
    _bake(monkeypatch, rows)
    body = _text(rows).encode("utf-8")
    sha = hashlib.sha256(body).hexdigest()
    r = L.read_terminal_profiles_from_s3(_FakeS3(body), "bucket", expected_sha256=sha)
    assert r["load_status"] == L.STATUS_LOADED
    assert r["version_id"] == "ver-1"
    assert r["sha256"] == sha
