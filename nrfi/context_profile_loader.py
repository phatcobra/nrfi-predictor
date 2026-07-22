"""Shared, fail-closed loader for Context Foundation V1 live artifacts.

Two tiny artifacts back the live park-context stage:
  * the terminal per-venue park-factor projection (published to S3), and
  * the effective-dated venue reference (bundled with the function).

Both are fully verified - object SHA-256, canonical identity, row/venue count,
per-row schema, duplicate-id rejection - and every outcome carries an explicit
status so the assembly falls back cleanly when an artifact is absent or
invalid.  Pure over the object text so replay, the API, and Batch share exactly
the same verification.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from nrfi.pregame_snapshot import canonical_json_bytes

PARK_TERMINAL_KEY = (
    "features/context-foundation-2015-2024-v1/park_terminal_factors.jsonl"
)
PARK_TERMINAL_SCHEMA = "park_terminal_factor.v1"
VENUE_REFERENCE_SCHEMA = "venue_reference.v1"

EXPECTED_TERMINAL_IDENTITY = (
    "3dacfdb58fb0b9bb706d7f3a31bb82eff55213f1d1998668805afa1d104c3b0b"
)
EXPECTED_PROJECTION_SHA256 = (
    "a536de6aafda1e860bc942efc97d5cd7ccf254b4f13f2b226d2766e09b6b37f6"
)
EXPECTED_VENUES = 44
EXPECTED_VENUE_REFERENCE_SHA256 = (
    "d7b9c606357453ffce006f5b038dbe1fff14d221234c4885baf1ecb800a04041"
)

STATUS_LOADED = "CONTEXT_PROFILES_LOADED"
STATUS_ARTIFACT_INVALID = "CONTEXT_PROFILE_ARTIFACT_INVALID"
STATUS_IDENTITY_MISMATCH = "CONTEXT_PROFILE_IDENTITY_MISMATCH"
STATUS_SCHEMA_INVALID = "CONTEXT_PROFILE_SCHEMA_INVALID"
STATUS_LOAD_FAILED = "CONTEXT_PROFILE_LOAD_FAILED"


def _identity(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _result(status: str, reason: str | None, **extra: Any) -> dict[str, Any]:
    return {
        "load_status": status,
        "load_failure_reason": reason,
        "park_profiles": {},
        "profile_identity": None,
        "venue_count": 0,
        **extra,
    }


def load_park_profiles(
    text: str,
    *,
    expected_identity: str | None = None,
    expected_venues: int | None = None,
    object_key: str | None = None,
    version_id: str | None = None,
    object_sha256: str | None = None,
) -> dict[str, Any]:
    """Parse + fully verify the terminal park-factor projection; fail closed."""
    expected_identity = (
        EXPECTED_TERMINAL_IDENTITY if expected_identity is None else expected_identity
    )
    expected_venues = EXPECTED_VENUES if expected_venues is None else expected_venues
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
        if row.get("schema_version") != PARK_TERMINAL_SCHEMA:
            return _result(
                STATUS_SCHEMA_INVALID, f"line {line_number} unknown schema", **base
            )
        venue_id = row.get("venue_id")
        if not isinstance(venue_id, int) or isinstance(venue_id, bool):
            return _result(
                STATUS_SCHEMA_INVALID,
                f"line {line_number} no integer venue_id",
                **base,
            )
        if venue_id in profiles:
            return _result(
                STATUS_ARTIFACT_INVALID, f"duplicate venue_id {venue_id}", **base
            )
        profiles[venue_id] = row
        ordered.append(row)

    if len(ordered) != expected_venues:
        return _result(
            STATUS_ARTIFACT_INVALID,
            f"venue count {len(ordered)} != expected {expected_venues}",
            venue_count=len(ordered),
            **base,
        )
    identity = _identity(ordered)
    if identity != expected_identity:
        return _result(
            STATUS_IDENTITY_MISMATCH,
            f"terminal identity {identity} != expected {expected_identity}",
            profile_identity=identity,
            venue_count=len(ordered),
            **base,
        )
    return {
        "load_status": STATUS_LOADED,
        "load_failure_reason": None,
        "park_profiles": profiles,
        "profile_identity": identity,
        "venue_count": len(ordered),
        **base,
    }


def read_park_profiles_from_s3(
    s3_client: Any,
    bucket: str,
    key: str = PARK_TERMINAL_KEY,
    *,
    expected_sha256: str | None = None,
    verify_sha256: bool = True,
    expected_identity: str | None = None,
    expected_venues: int | None = None,
) -> dict[str, Any]:
    """Read the configured terminal park projection object; verify fully."""
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
    return load_park_profiles(
        raw.decode("utf-8"),
        expected_identity=expected_identity,
        expected_venues=expected_venues,
        object_key=key,
        version_id=version_id,
        object_sha256=sha,
    )


def load_venue_reference_text(
    text: str, *, expected_sha256: str | None = None
) -> dict[str, Any]:
    """Parse + verify the bundled venue reference JSON; fail closed."""
    if expected_sha256 is None:
        expected_sha256 = EXPECTED_VENUE_REFERENCE_SHA256
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if expected_sha256 is not None and sha != expected_sha256:
        return {
            "load_status": STATUS_ARTIFACT_INVALID,
            "load_failure_reason": f"venue reference sha256 {sha} != expected",
            "venues": {},
            "venue_count": 0,
            "sha256": sha,
        }
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        return {
            "load_status": STATUS_ARTIFACT_INVALID,
            "load_failure_reason": f"venue reference malformed: {error}",
            "venues": {},
            "venue_count": 0,
            "sha256": sha,
        }
    if payload.get("schema_version") != VENUE_REFERENCE_SCHEMA:
        return {
            "load_status": STATUS_SCHEMA_INVALID,
            "load_failure_reason": "unexpected venue reference schema",
            "venues": {},
            "venue_count": 0,
            "sha256": sha,
        }
    venues = {int(v["venue_id"]): v for v in payload.get("venues", [])}
    return {
        "load_status": STATUS_LOADED,
        "load_failure_reason": None,
        "venues": venues,
        "venue_count": len(venues),
        "sha256": sha,
    }
