"""Shared, fail-closed loader for the compact terminal team projection.

Reads ONLY the configured S3 key (the tiny 30-row terminal team projection),
verifies the object SHA-256, the canonical terminal identity, the team count,
and the per-row schema, and rejects duplicate team ids.  Every outcome carries
an explicit status so the live assembly can fall back to the current
pitcher/lineup/batter assembly when the team artifact is absent or invalid.
Pure over the object text so replay, the API, and future Batch share exactly the
same verification.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from nrfi.pregame_snapshot import canonical_json_bytes

TEAM_TERMINAL_KEY = (
    "features/team-first-inning-strict-prior-2015-2024-v1/team_terminal_profiles.jsonl"
)
TEAM_TERMINAL_SCHEMA = "team_terminal_profile.v1"
EXPECTED_TERMINAL_IDENTITY = (
    "c99563f7a42c87219833ef4b629834c5a750c6de020601450cc97147b5807716"
)
EXPECTED_PROJECTION_SHA256 = (
    "4e931e27d0aefd309a132037604b82bbb3b70123c6ef59653900242805efd67b"
)
EXPECTED_TEAMS = 30

STATUS_LOADED = "TEAM_PROFILES_LOADED"
STATUS_ARTIFACT_INVALID = "TEAM_PROFILE_ARTIFACT_INVALID"
STATUS_IDENTITY_MISMATCH = "TEAM_PROFILE_IDENTITY_MISMATCH"
STATUS_SCHEMA_INVALID = "TEAM_PROFILE_SCHEMA_INVALID"
STATUS_LOAD_FAILED = "TEAM_PROFILE_LOAD_FAILED"


def _identity(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _result(status: str, reason: str | None, **extra: Any) -> dict[str, Any]:
    return {
        "load_status": status,
        "load_failure_reason": reason,
        "profiles": {},
        "profile_identity": None,
        "team_count": 0,
        **extra,
    }


def load_team_profiles(
    text: str,
    *,
    expected_identity: str | None = None,
    expected_teams: int | None = None,
    object_key: str | None = None,
    version_id: str | None = None,
    object_sha256: str | None = None,
) -> dict[str, Any]:
    """Parse + fully verify the terminal team projection text; fail closed."""
    expected_identity = (
        EXPECTED_TERMINAL_IDENTITY if expected_identity is None else expected_identity
    )
    expected_teams = EXPECTED_TEAMS if expected_teams is None else expected_teams
    base = {"object_key": object_key, "version_id": version_id, "sha256": object_sha256}
    profiles: dict[int, dict[str, Any]] = {}
    ordered: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            return _result(
                STATUS_ARTIFACT_INVALID, f"line {line_number} is malformed", **base
            )
        if not isinstance(row, dict):
            return _result(
                STATUS_ARTIFACT_INVALID, f"line {line_number} is not an object", **base
            )
        if row.get("schema_version") != TEAM_TERMINAL_SCHEMA:
            return _result(
                STATUS_SCHEMA_INVALID, f"line {line_number} unknown schema", **base
            )
        team_id = row.get("team_id")
        if not isinstance(team_id, int) or isinstance(team_id, bool):
            return _result(
                STATUS_SCHEMA_INVALID, f"line {line_number} no integer team_id", **base
            )
        if team_id in profiles:
            return _result(
                STATUS_ARTIFACT_INVALID, f"duplicate team_id {team_id}", **base
            )
        profiles[team_id] = row
        ordered.append(row)

    if len(ordered) != expected_teams:
        return _result(
            STATUS_ARTIFACT_INVALID,
            f"team count {len(ordered)} != expected {expected_teams}",
            team_count=len(ordered),
            **base,
        )
    identity = _identity(ordered)
    if identity != expected_identity:
        return _result(
            STATUS_IDENTITY_MISMATCH,
            f"terminal identity {identity} != expected {expected_identity}",
            profile_identity=identity,
            team_count=len(ordered),
            **base,
        )
    return {
        "load_status": STATUS_LOADED,
        "load_failure_reason": None,
        "profiles": profiles,
        "profile_identity": identity,
        "team_count": len(ordered),
        **base,
    }


def read_team_profiles_from_s3(
    s3_client: Any,
    bucket: str,
    key: str = TEAM_TERMINAL_KEY,
    *,
    expected_sha256: str | None = None,
    verify_sha256: bool = True,
    expected_identity: str | None = None,
    expected_teams: int | None = None,
) -> dict[str, Any]:
    """Read the configured terminal team projection object; verify fully."""
    if expected_sha256 is None and verify_sha256:
        expected_sha256 = EXPECTED_PROJECTION_SHA256
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        raw = response["Body"].read()
        version_id = response.get("VersionId")
    except Exception as error:  # noqa: BLE001 - explicit fail-closed status
        return _result(
            STATUS_LOAD_FAILED, f"{type(error).__name__}: {error}", object_key=key
        )
    sha = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and sha != expected_sha256:
        return _result(
            STATUS_ARTIFACT_INVALID,
            f"object sha256 {sha} != expected {expected_sha256}",
            object_key=key,
            version_id=version_id,
            sha256=sha,
        )
    return load_team_profiles(
        raw.decode("utf-8"),
        expected_identity=expected_identity,
        expected_teams=expected_teams,
        object_key=key,
        version_id=version_id,
        object_sha256=sha,
    )
