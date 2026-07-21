"""Reproduce and publish the strict-prior team first-inning feature artifacts.

Reproduction rebuilds the canonical team-game records, the strict-prior
snapshots, and the compact terminal per-team projection deterministically from
the committed 2015-2024 multiseason source, then requires the records / feature /
terminal canonical identities, the team count, and the record count to equal the
locally verified values before any upload.  Publication writes the verified
artifacts to the existing private, versioned, SSE-KMS S3 lake under a NEW
immutable team-feature prefix without touching the pitcher, batter, or lineup
evidence.  The team domain only populates ``team_context_eligible``; the unified
feature set stays false and the required output stays ``PREDICTIVE SKILL NOT
ESTABLISHED`` / ``NO QUALIFIED WAGER``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from nrfi.pitcher_statcast import canonical_json_bytes
from nrfi.team_features import (
    TEAM_EXTRACTION_VERSION,
    TEAM_FEATURE_VERSION,
    TEAM_TERMINAL_VERSION,
    build_team_feature_snapshots,
    build_team_game_records,
    build_terminal_team_profiles,
    load_games,
    terminal_team_projection_bytes,
)

EXPECTED_RECORDS_IDENTITY = (
    "1520a5eab901fbf2190fd2089484b9d8064e8c8ebd6b2ce6dc5f1c8731c7f58a"
)
EXPECTED_FEATURES_IDENTITY = (
    "5124bebb0883f57d9c92715a0ba675504a028e31b4a4c2e7ec8fed1cae3b1942"
)
EXPECTED_TERMINAL_IDENTITY = (
    "c99563f7a42c87219833ef4b629834c5a750c6de020601450cc97147b5807716"
)
EXPECTED_TERMINAL_SHA256 = (
    "4e931e27d0aefd309a132037604b82bbb3b70123c6ef59653900242805efd67b"
)
EXPECTED_TEAMS = 30
EXPECTED_RECORDS = 45522

PROFILE_IDENTITY = "team-first-inning-strict-prior-2015-2024-v1"
LAKE_PREFIX = f"features/{PROFILE_IDENTITY}"
REQUIRED_EVIDENCE = (
    "team_coverage.json",
    "team_schema.json",
    "team_determinism_evidence.json",
)


class PublicationRefused(SystemExit):
    """Raised (fail-closed) when a required team publication precondition fails."""


def _identity(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(row) for row in rows)


def reproduce_team(
    multiseason_dir: Path,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    bytes,
    dict[str, Any],
]:
    """Rebuild + fully verify the team artifacts from the committed source."""
    games, cutoffs = load_games(multiseason_dir)
    records = build_team_game_records(games, cutoffs)
    snapshots = build_team_feature_snapshots(records)
    terminal = build_terminal_team_profiles(records)
    rid, fid, tid = _identity(records), _identity(snapshots), _identity(terminal)
    if any(int(r["season"]) == 2025 for r in records):
        raise PublicationRefused("zero-2025 evidence absent (a 2025 record present)")
    if rid != EXPECTED_RECORDS_IDENTITY:
        raise PublicationRefused(f"records identity mismatch: {rid}")
    if fid != EXPECTED_FEATURES_IDENTITY:
        raise PublicationRefused(f"features identity mismatch: {fid}")
    if tid != EXPECTED_TERMINAL_IDENTITY:
        raise PublicationRefused(f"terminal identity mismatch: {tid}")
    if len(terminal) != EXPECTED_TEAMS:
        raise PublicationRefused(f"team count differs: {len(terminal)}")
    if len(records) != EXPECTED_RECORDS or len(snapshots) != EXPECTED_RECORDS:
        raise PublicationRefused("record/snapshot count differs")
    projection = terminal_team_projection_bytes(terminal)
    sha = hashlib.sha256(projection).hexdigest()
    if sha != EXPECTED_TERMINAL_SHA256:
        raise PublicationRefused(f"terminal projection sha mismatch: {sha}")
    meta = {
        "records_identity": rid,
        "features_identity": fid,
        "terminal_identity": tid,
        "terminal_projection_sha256": sha,
        "distinct_teams": len(terminal),
        "team_game_records": len(records),
        "team_feature_snapshots": len(snapshots),
    }
    return records, snapshots, terminal, projection, meta


def _guard(evidence_dir: Path, producing_commit: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{7,40}", producing_commit or ""):
        raise PublicationRefused(f"invalid producing commit: {producing_commit!r}")
    for name in REQUIRED_EVIDENCE:
        if not (evidence_dir / name).is_file():
            raise PublicationRefused(f"missing required team evidence: {name}")
    cov = json.loads((evidence_dir / "team_coverage.json").read_text())
    if cov.get("locked_2025_holdout_accessed") is not False:
        raise PublicationRefused("zero-2025 evidence absent (coverage)")
    if cov.get("records_identity") != EXPECTED_RECORDS_IDENTITY:
        raise PublicationRefused("coverage records identity differs")
    if cov.get("features_identity") != EXPECTED_FEATURES_IDENTITY:
        raise PublicationRefused("coverage features identity differs")
    if cov.get("terminal_identity") != EXPECTED_TERMINAL_IDENTITY:
        raise PublicationRefused("coverage terminal identity differs")


def _put(s3: Any, bucket: str, key: str, body: bytes, kms: str) -> dict[str, Any]:
    response = s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="application/octet-stream",
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=kms,
        ChecksumAlgorithm="SHA256",
    )
    return {
        "key": key,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "version_id": response.get("VersionId"),
        "etag": response.get("ETag"),
        "checksum_sha256": response.get("ChecksumSHA256"),
    }


def publish_team(
    *,
    multiseason_dir: Path,
    evidence_dir: Path,
    bucket: str,
    kms_key_arn: str,
    producing_commit: str,
    s3_client: Any | None = None,
) -> dict[str, Any]:
    """Reproduce, verify, and publish the team artifacts to the lake."""
    _guard(evidence_dir, producing_commit)
    records, snapshots, terminal, projection, meta = reproduce_team(multiseason_dir)

    if s3_client is None:
        import importlib

        s3_client = importlib.import_module("boto3").client("s3")

    uploads: list[dict[str, Any]] = []
    uploads.append(
        _put(
            s3_client,
            bucket,
            f"{LAKE_PREFIX}/team_game_records.jsonl",
            _jsonl_bytes(records),
            kms_key_arn,
        )
    )
    uploads.append(
        _put(
            s3_client,
            bucket,
            f"{LAKE_PREFIX}/team_features.jsonl",
            _jsonl_bytes(snapshots),
            kms_key_arn,
        )
    )
    uploads.append(
        _put(
            s3_client,
            bucket,
            f"{LAKE_PREFIX}/team_terminal_profiles.jsonl",
            projection,
            kms_key_arn,
        )
    )
    for name in REQUIRED_EVIDENCE:
        uploads.append(
            _put(
                s3_client,
                bucket,
                f"{LAKE_PREFIX}/{name}",
                (evidence_dir / name).read_bytes(),
                kms_key_arn,
            )
        )

    published = {
        "schema_version": "team_feature_publication.v1",
        "profile_identity": PROFILE_IDENTITY,
        "extraction_version": TEAM_EXTRACTION_VERSION,
        "feature_version": TEAM_FEATURE_VERSION,
        "terminal_version": TEAM_TERMINAL_VERSION,
        "producing_commit": producing_commit,
        "reproduced_in_runner": True,
        "terminal_projection_key": f"{LAKE_PREFIX}/team_terminal_profiles.jsonl",
        "park_context_eligible": False,
        "unified_feature_set_eligible": False,
        "locked_2025_holdout_accessed": False,
        "uploads": uploads,
        **meta,
    }
    _put(
        s3_client,
        bucket,
        f"{LAKE_PREFIX}/team_published_manifest.json",
        canonical_json_bytes(published),
        kms_key_arn,
    )
    return published


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--multiseason-dir", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--bucket")
    parser.add_argument("--kms-key-arn")
    parser.add_argument("--producing-commit", default="")
    args = parser.parse_args(argv)

    if args.verify_only:
        _records, _snapshots, _terminal, _projection, meta = reproduce_team(
            args.multiseason_dir
        )
        print(json.dumps({"verified": True, **meta}, sort_keys=True))
        return 0

    if not args.bucket or not args.kms_key_arn:
        raise SystemExit("--bucket and --kms-key-arn are required to publish")
    published = publish_team(
        multiseason_dir=args.multiseason_dir,
        evidence_dir=args.evidence_dir,
        bucket=args.bucket,
        kms_key_arn=args.kms_key_arn,
        producing_commit=args.producing_commit,
    )
    print(json.dumps(published, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
