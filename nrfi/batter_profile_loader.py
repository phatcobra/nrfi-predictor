"""Shared, fail-closed loader for the compact terminal batter projection.

Reads ONLY the configured S3 key (the ~9.46 MB terminal projection), never the
1.7 GB historical projection, verifies the object SHA-256, the canonical terminal
profile identity, the row count, the eligible count, and the per-row schema, and
rejects duplicate batter ids.  Every outcome carries an explicit status so the
live assembly can fall back to pitcher-only when the batter artifact is absent or
invalid.  The loader is pure over the object text so historical replay, the API,
and future Batch share exactly the same verification.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from nrfi.pregame_snapshot import canonical_json_bytes

TERMINAL_PROFILE_KEY = (
    "features/batter-statcast-strict-prior-2015-2024-v1/terminal_batter_profiles.jsonl"
)
TERMINAL_PROFILE_SCHEMA = "batter_terminal_profile.v1"
EXPECTED_TERMINAL_IDENTITY = (
    "7e7fc570d5ad4ea58fc087a87a488f54c63a07e729ae532ace1fd20e37f97299"
)
EXPECTED_PROJECTION_SHA256 = (
    "5ce26a4a87b66ea4a34b150a07e0ac53eb1303e27d9ef4b65ca1e9ab87a86be2"
)
EXPECTED_TERMINAL_ROWS = 2606
EXPECTED_TERMINAL_ELIGIBLE = 1543

STATUS_LOADED = "BATTER_PROFILES_LOADED"
STATUS_ARTIFACT_INVALID = "BATTER_PROFILE_ARTIFACT_INVALID"
STATUS_LOAD_FAILED = "BATTER_PROFILE_LOAD_FAILED"
STATUS_SCHEMA_INVALID = "BATTER_PROFILE_SCHEMA_INVALID"
STATUS_IDENTITY_MISMATCH = "BATTER_PROFILE_IDENTITY_MISMATCH"


def _identity(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _result(status: str, reason: str | None, **extra: Any) -> dict[str, Any]:
    return {
        "load_status": status,
        "load_failure_reason": reason,
        "profiles": {},
        "profile_identity": None,
        "row_count": 0,
        "eligible_count": 0,
        **extra,
    }


def load_terminal_profiles(
    text: str,
    *,
    expected_identity: str | None = None,
    expected_rows: int | None = None,
    expected_eligible: int | None = None,
    object_key: str | None = None,
    version_id: str | None = None,
    object_sha256: str | None = None,
) -> dict[str, Any]:
    """Parse + fully verify the terminal projection text; fail closed.

    Expected values resolve from the module constants at call time (so they can
    be overridden in tests) unless passed explicitly.
    """
    expected_identity = (
        EXPECTED_TERMINAL_IDENTITY if expected_identity is None else expected_identity
    )
    expected_rows = EXPECTED_TERMINAL_ROWS if expected_rows is None else expected_rows
    expected_eligible = (
        EXPECTED_TERMINAL_ELIGIBLE if expected_eligible is None else expected_eligible
    )
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
        if row.get("schema_version") != TERMINAL_PROFILE_SCHEMA:
            return _result(
                STATUS_SCHEMA_INVALID,
                f"line {line_number} has an unknown schema",
                **base,
            )
        batter_id = row.get("batter_id")
        if not isinstance(batter_id, int) or isinstance(batter_id, bool):
            return _result(
                STATUS_SCHEMA_INVALID,
                f"line {line_number} has no integer batter_id",
                **base,
            )
        if batter_id in profiles:
            return _result(
                STATUS_ARTIFACT_INVALID,
                f"duplicate batter_id {batter_id}",
                **base,
            )
        profiles[batter_id] = row
        ordered.append(row)

    row_count = len(ordered)
    eligible = sum(1 for r in ordered if r.get("profile_feature_eligible") is True)
    if row_count != expected_rows:
        return _result(
            STATUS_ARTIFACT_INVALID,
            f"row count {row_count} != expected {expected_rows}",
            row_count=row_count,
            **base,
        )
    if eligible != expected_eligible:
        return _result(
            STATUS_ARTIFACT_INVALID,
            f"eligible count {eligible} != expected {expected_eligible}",
            row_count=row_count,
            eligible_count=eligible,
            **base,
        )
    identity = _identity(ordered)
    if identity != expected_identity:
        return _result(
            STATUS_IDENTITY_MISMATCH,
            f"terminal identity {identity} != expected {expected_identity}",
            profile_identity=identity,
            row_count=row_count,
            eligible_count=eligible,
            **base,
        )
    return {
        "load_status": STATUS_LOADED,
        "load_failure_reason": None,
        "profiles": profiles,
        "profile_identity": identity,
        "row_count": row_count,
        "eligible_count": eligible,
        **base,
    }


def read_terminal_profiles_from_s3(
    s3_client: Any,
    bucket: str,
    key: str = TERMINAL_PROFILE_KEY,
    *,
    expected_sha256: str | None = None,
    verify_sha256: bool = True,
    expected_identity: str | None = None,
    expected_rows: int | None = None,
    expected_eligible: int | None = None,
) -> dict[str, Any]:
    """Read the configured terminal projection object and verify it fully."""
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
    return load_terminal_profiles(
        raw.decode("utf-8"),
        expected_identity=expected_identity,
        expected_rows=expected_rows,
        expected_eligible=expected_eligible,
        object_key=key,
        version_id=version_id,
        object_sha256=sha,
    )
