"""Reproduce and publish Context Foundation V1 artifacts.

Reproduction rebuilds the side schedule log, the strict-prior context feature
set, and the compact terminal per-venue park projection deterministically from
the committed 2015-2024 multiseason source plus the committed venue reference,
then requires the side-schedule / features / terminal canonical identities, the
terminal projection SHA-256, the venue-reference SHA-256, the venue count, the
park-eligible venue count, and the snapshot count to equal the locally verified
values before any upload.  Publication writes the terminal park projection, the
venue reference, and the evidence to the existing private, versioned, SSE-KMS
S3 lake under a NEW immutable context prefix, touching no pitcher/batter/team/
lineup evidence.  The context domain only populates ``park_context_eligible``
(and stages ``schedule_travel``/``workload``); the unified feature set stays
false and the required output stays ``PREDICTIVE SKILL NOT ESTABLISHED`` /
``NO QUALIFIED WAGER``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from nrfi.context_features import (
    CONTEXT_EXTRACTION_VERSION,
    CONTEXT_FEATURE_VERSION,
    PARK_TERMINAL_VERSION,
    VENUE_REFERENCE_VERSION,
    build_context_feature_set,
    build_side_schedule_log,
    build_terminal_park_factors,
    load_games,
    load_venue_reference,
    terminal_park_projection_bytes,
)
from nrfi.pitcher_statcast import canonical_json_bytes

EXPECTED_SIDE_SCHEDULE_IDENTITY = (
    "5654333afdc22b79b96359c8fe44515fb5cd2772d883a06e05b1272319046fac"
)
EXPECTED_FEATURES_IDENTITY = (
    "6b3fafac08a7a6ec70cd38b4ad480af76d10bf6cf26b5de19db368ba95eed421"
)
EXPECTED_TERMINAL_IDENTITY = (
    "3dacfdb58fb0b9bb706d7f3a31bb82eff55213f1d1998668805afa1d104c3b0b"
)
EXPECTED_TERMINAL_SHA256 = (
    "a536de6aafda1e860bc942efc97d5cd7ccf254b4f13f2b226d2766e09b6b37f6"
)
EXPECTED_VENUE_REFERENCE_SHA256 = (
    "d7b9c606357453ffce006f5b038dbe1fff14d221234c4885baf1ecb800a04041"
)
EXPECTED_VENUES = 44
EXPECTED_PARK_ELIGIBLE = 33
EXPECTED_SNAPSHOTS = 45522

PROFILE_IDENTITY = "context-foundation-2015-2024-v1"
LAKE_PREFIX = f"features/{PROFILE_IDENTITY}"
REQUIRED_EVIDENCE = (
    "context_coverage.json",
    "context_schema.json",
    "context_determinism_evidence.json",
    "venue_reference.json",
)


class PublicationRefused(SystemExit):
    """Raised (fail-closed) when a context publication precondition fails."""


def _identity(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def reproduce_context(
    multiseason_dir: Path, venue_reference_path: Path
) -> tuple[list[dict[str, Any]], bytes, dict[str, Any]]:
    """Rebuild + fully verify the context artifacts from the committed source."""
    games, cutoffs = load_games(multiseason_dir)
    reference = load_venue_reference(venue_reference_path)
    rows = build_side_schedule_log(games, cutoffs)
    snapshots = build_context_feature_set(rows, reference)
    terminal = build_terminal_park_factors(rows)
    sid_ident = _identity(rows)
    feat_ident = _identity(snapshots)
    term_ident = _identity(terminal)
    if any(int(r["season"]) == 2025 for r in rows):
        raise PublicationRefused("zero-2025 evidence absent (a 2025 row present)")
    if sid_ident != EXPECTED_SIDE_SCHEDULE_IDENTITY:
        raise PublicationRefused(f"side schedule identity mismatch: {sid_ident}")
    if feat_ident != EXPECTED_FEATURES_IDENTITY:
        raise PublicationRefused(f"features identity mismatch: {feat_ident}")
    if term_ident != EXPECTED_TERMINAL_IDENTITY:
        raise PublicationRefused(f"terminal identity mismatch: {term_ident}")
    if len(terminal) != EXPECTED_VENUES:
        raise PublicationRefused(f"venue count differs: {len(terminal)}")
    if len(snapshots) != EXPECTED_SNAPSHOTS:
        raise PublicationRefused(f"snapshot count differs: {len(snapshots)}")
    park_eligible = sum(1 for p in terminal if p["park_context_feature_eligible"])
    if park_eligible != EXPECTED_PARK_ELIGIBLE:
        raise PublicationRefused(f"park-eligible venues differ: {park_eligible}")
    projection = terminal_park_projection_bytes(terminal)
    proj_sha = hashlib.sha256(projection).hexdigest()
    if proj_sha != EXPECTED_TERMINAL_SHA256:
        raise PublicationRefused(f"terminal projection sha mismatch: {proj_sha}")
    ref_sha = hashlib.sha256(venue_reference_path.read_bytes()).hexdigest()
    if ref_sha != EXPECTED_VENUE_REFERENCE_SHA256:
        raise PublicationRefused(f"venue reference sha mismatch: {ref_sha}")
    meta = {
        "side_schedule_identity": sid_ident,
        "features_identity": feat_ident,
        "terminal_identity": term_ident,
        "terminal_projection_sha256": proj_sha,
        "venue_reference_sha256": ref_sha,
        "distinct_venues": len(terminal),
        "park_eligible_venues": park_eligible,
        "context_snapshots": len(snapshots),
    }
    return terminal, projection, meta


def _guard(evidence_dir: Path, producing_commit: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{7,40}", producing_commit or ""):
        raise PublicationRefused(f"invalid producing commit: {producing_commit!r}")
    for name in REQUIRED_EVIDENCE:
        if not (evidence_dir / name).is_file():
            raise PublicationRefused(f"missing required context evidence: {name}")
    cov = json.loads((evidence_dir / "context_coverage.json").read_text())
    if cov.get("locked_2025_holdout_accessed") is not False:
        raise PublicationRefused("zero-2025 evidence absent (coverage)")
    if cov.get("features_identity") != EXPECTED_FEATURES_IDENTITY:
        raise PublicationRefused("coverage features identity differs")
    if cov.get("terminal_identity") != EXPECTED_TERMINAL_IDENTITY:
        raise PublicationRefused("coverage terminal identity differs")
    if cov.get("terminal_projection_sha256") != EXPECTED_TERMINAL_SHA256:
        raise PublicationRefused("coverage terminal projection sha differs")


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


def publish_context(
    *,
    multiseason_dir: Path,
    evidence_dir: Path,
    venue_reference_path: Path,
    bucket: str,
    kms_key_arn: str,
    producing_commit: str,
    s3_client: Any | None = None,
) -> dict[str, Any]:
    """Reproduce, verify, and publish the context artifacts to the lake."""
    _guard(evidence_dir, producing_commit)
    _terminal, projection, meta = reproduce_context(
        multiseason_dir, venue_reference_path
    )

    if s3_client is None:
        import importlib

        s3_client = importlib.import_module("boto3").client("s3")

    uploads: list[dict[str, Any]] = []
    uploads.append(
        _put(
            s3_client,
            bucket,
            f"{LAKE_PREFIX}/park_terminal_factors.jsonl",
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
        "schema_version": "context_feature_publication.v1",
        "profile_identity": PROFILE_IDENTITY,
        "extraction_version": CONTEXT_EXTRACTION_VERSION,
        "feature_version": CONTEXT_FEATURE_VERSION,
        "terminal_version": PARK_TERMINAL_VERSION,
        "reference_version": VENUE_REFERENCE_VERSION,
        "producing_commit": producing_commit,
        "reproduced_in_runner": True,
        "terminal_projection_key": f"{LAKE_PREFIX}/park_terminal_factors.jsonl",
        "venue_reference_key": f"{LAKE_PREFIX}/venue_reference.json",
        "park_context_eligible": False,
        "schedule_travel_eligible": False,
        "unified_feature_set_eligible": False,
        "locked_2025_holdout_accessed": False,
        "uploads": uploads,
        **meta,
    }
    _put(
        s3_client,
        bucket,
        f"{LAKE_PREFIX}/context_published_manifest.json",
        canonical_json_bytes(published),
        kms_key_arn,
    )
    return published


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--multiseason-dir", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--venue-reference", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--bucket")
    parser.add_argument("--kms-key-arn")
    parser.add_argument("--producing-commit", default="")
    args = parser.parse_args(argv)

    if args.verify_only:
        _terminal, _projection, meta = reproduce_context(
            args.multiseason_dir, args.venue_reference
        )
        print(json.dumps({"verified": True, **meta}, sort_keys=True))
        return 0

    if not args.bucket or not args.kms_key_arn:
        raise SystemExit("--bucket and --kms-key-arn are required to publish")
    published = publish_context(
        multiseason_dir=args.multiseason_dir,
        evidence_dir=args.evidence_dir,
        venue_reference_path=args.venue_reference,
        bucket=args.bucket,
        kms_key_arn=args.kms_key_arn,
        producing_commit=args.producing_commit,
    )
    print(json.dumps(published, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
