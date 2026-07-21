"""Reproduce and publish the strict-prior 2015-2024 batter profile artifacts.

Reproduction rebuilds ``batter_features`` deterministically from the committed
canonical ``batter_game_history.parquet`` (batter snapshots need no external
starter context), then requires the feature and history partition identities
(canonical-JSON, platform independent) to equal the locally verified values.
Publication uploads the verified artifacts to the existing private, versioned,
SSE-KMS S3 lake under a NEW immutable batter-profile prefix without touching the
pitcher-profile evidence.  The batter feature domain never sources postgame
batting orders, so the runtime join stays ineligible and the required output
remains ``PREDICTIVE SKILL NOT ESTABLISHED`` / ``NO QUALIFIED WAGER``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from nrfi.batter_extraction import (
    BATTER_EXTRACTION_VERSION,
    BATTER_FEATURE_VERSION,
    build_batter_feature_snapshots,
)
from nrfi.batter_live_profiles import (
    TERMINAL_PROFILE_VERSION,
    build_terminal_profiles,
    terminal_projection_bytes,
)
from nrfi.pitcher_statcast import _write_parquet, canonical_json_bytes

EXPECTED_TERMINAL_IDENTITY = (
    "7e7fc570d5ad4ea58fc087a87a488f54c63a07e729ae532ace1fd20e37f97299"
)
EXPECTED_TERMINAL_ROWS = 2606
EXPECTED_TERMINAL_ELIGIBLE = 1543
TERMINAL_REQUIRED_ARTIFACTS = (
    "batter_game_history.parquet",
    "coverage.json",
    "terminal_profile_coverage.json",
    "terminal_profile_schema.json",
    "terminal_determinism_evidence.json",
)

EXPECTED_HISTORY_IDENTITY = (
    "596194c2fbf6b7b6d3e0ce1ebc727cc83a69d23f4f151ffaf5d9a7b234759496"
)
EXPECTED_FEATURE_IDENTITY = (
    "edd1ff171779a57854dbefea4ad654a13746dc4bf2814969f3c31415b0de355d"
)
EXPECTED_LEDGER_IDENTITY = (
    "b0f2a0f9e96819d29910f52250bdb4a033add742c43284fef75b7ad0f0069d16"
)
EXPECTED_HISTORY_ROWS = 472585
EXPECTED_FEATURE_ROWS = 472585
EXPECTED_ADMITTED_SOURCES = 2450
PROFILE_IDENTITY = "batter-statcast-strict-prior-2015-2024-v1"
LAKE_PREFIX = f"features/{PROFILE_IDENTITY}"

# Files that must be present (committed) in the artifact directory before any
# publication is attempted.  The 107 MB features parquet is NOT committed (it
# exceeds GitHub's 100 MiB limit); it is reproduced in-runner from the canonical
# history and uploaded, its identity verified against EXPECTED_FEATURE_IDENTITY.
REQUIRED_ARTIFACTS = (
    "batter_game_history.parquet",
    "source_file_ledger.jsonl",
    "rejections.jsonl",
    "coverage.json",
    "artifact_manifest.json",
    "determinism_evidence.json",
    "schema_definitions.json",
    "historical_lineup_timing.json",
)


class PublicationRefused(SystemExit):
    """Raised (fail-closed) when a required publication precondition is unmet."""


def _identity(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _ledger_identity(path: Path) -> str:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return _identity(rows)


def _guard_preconditions(artifact_dir: Path, producing_commit: str) -> dict[str, Any]:
    """Fail closed unless every publication precondition holds."""
    if not re.fullmatch(r"[0-9a-f]{7,40}", producing_commit or ""):
        raise PublicationRefused(f"invalid producing commit: {producing_commit!r}")
    for name in REQUIRED_ARTIFACTS:
        if not (artifact_dir / name).is_file():
            raise PublicationRefused(f"missing required artifact: {name}")
    coverage = json.loads((artifact_dir / "coverage.json").read_text())
    if coverage.get("schema_version") != "batter_extraction_coverage.v1":
        raise PublicationRefused("coverage schema identity differs")
    if coverage.get("extraction_version") != BATTER_EXTRACTION_VERSION:
        raise PublicationRefused("extraction version differs")
    if coverage.get("feature_version") != BATTER_FEATURE_VERSION:
        raise PublicationRefused("feature version differs")
    if coverage.get("day_files_opened_2025") != 0:
        raise PublicationRefused("zero-2025 evidence absent (opened_2025 != 0)")
    if coverage.get("locked_2025_holdout_accessed") is not False:
        raise PublicationRefused("zero-2025 evidence absent (holdout accessed)")
    if coverage.get("day_files_opened") != EXPECTED_ADMITTED_SOURCES:
        raise PublicationRefused("admitted-source count differs")
    if coverage.get("batter_game_rows") != EXPECTED_HISTORY_ROWS:
        raise PublicationRefused("history row count differs")
    if coverage.get("batter_feature_snapshot_rows") != EXPECTED_FEATURE_ROWS:
        raise PublicationRefused("feature row count differs")
    if coverage.get("history_partition_identity") != EXPECTED_HISTORY_IDENTITY:
        raise PublicationRefused("coverage history identity differs")
    if coverage.get("feature_partition_identity") != EXPECTED_FEATURE_IDENTITY:
        raise PublicationRefused("coverage feature identity differs")
    if coverage.get("source_file_ledger_identity") != EXPECTED_LEDGER_IDENTITY:
        raise PublicationRefused("coverage ledger identity differs")
    ledger_id = _ledger_identity(artifact_dir / "source_file_ledger.jsonl")
    if ledger_id != EXPECTED_LEDGER_IDENTITY:
        raise PublicationRefused(f"recomputed ledger identity differs: {ledger_id}")
    return coverage


def reproduce_features(
    history_parquet: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    """Rebuild batter features from the canonical history parquet; verify ids."""
    history = pq.read_table(history_parquet).to_pylist()
    snapshots = build_batter_feature_snapshots(history)
    identities = {
        "history_partition_identity": _identity(history),
        "feature_partition_identity": _identity(snapshots),
    }
    if identities["history_partition_identity"] != EXPECTED_HISTORY_IDENTITY:
        raise SystemExit(
            "history identity mismatch: "
            f"{identities['history_partition_identity']} != {EXPECTED_HISTORY_IDENTITY}"
        )
    if identities["feature_partition_identity"] != EXPECTED_FEATURE_IDENTITY:
        raise SystemExit(
            "feature identity mismatch: "
            f"{identities['feature_partition_identity']} != {EXPECTED_FEATURE_IDENTITY}"
        )
    return history, snapshots, identities


def _profile_jsonl_rows(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project feature snapshots to the flat JSONL rows the runtime reads."""
    rows: list[dict[str, Any]] = []
    for snapshot in snapshots:
        rows.append(
            {
                "batter_id": int(snapshot["batter_id"]),
                "prediction_cutoff": snapshot["prediction_cutoff"],
                "game_pk": int(snapshot["game_pk"]),
                "batter_stand": snapshot["batter_stand"],
                "profile_feature_eligible": bool(snapshot["profile_feature_eligible"]),
                "historical_prediction_join_eligible": bool(
                    snapshot["historical_prediction_join_eligible"]
                ),
                "feature_version": snapshot["feature_version"],
                "feature_hash": snapshot["feature_hash"],
                "feature_values": snapshot["feature_values"],
            }
        )
    rows.sort(
        key=lambda row: (row["prediction_cutoff"], row["game_pk"], row["batter_id"])
    )
    return rows


def build_projection_bytes(snapshots: list[dict[str, Any]]) -> bytes:
    """Deterministic JSONL projection bytes for the stdlib Lambda runtime."""
    rows = _profile_jsonl_rows(snapshots)
    return b"".join(canonical_json_bytes(row) for row in rows)


def _put(
    s3_client: Any, bucket: str, key: str, body: bytes, kms_key_arn: str
) -> dict[str, Any]:
    response = s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="application/octet-stream",
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=kms_key_arn,
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


def publish(
    *,
    artifact_dir: Path,
    bucket: str,
    kms_key_arn: str,
    producing_commit: str,
    s3_client: Any | None = None,
) -> dict[str, Any]:
    """Reproduce, verify, and publish the batter artifacts to the lake."""
    coverage = _guard_preconditions(artifact_dir, producing_commit)
    history_parquet = artifact_dir / "batter_game_history.parquet"
    history, snapshots, identities = reproduce_features(history_parquet)
    if len(history) != EXPECTED_HISTORY_ROWS:
        raise PublicationRefused("reproduced history row count differs")
    if len(snapshots) != EXPECTED_FEATURE_ROWS:
        raise PublicationRefused("reproduced feature row count differs")
    projection = build_projection_bytes(snapshots)

    # Reproduce the 107 MB features parquet in-process (it is not committed);
    # its canonical identity is already verified equal to EXPECTED_FEATURE_IDENTITY.
    with tempfile.TemporaryDirectory() as tmp:
        features_parquet = Path(tmp) / "batter_features.parquet"
        _write_parquet(features_parquet, snapshots)
        features_bytes = features_parquet.read_bytes()

    if s3_client is None:
        import importlib

        s3_client = importlib.import_module("boto3").client("s3")

    uploads: list[dict[str, Any]] = []
    for name in REQUIRED_ARTIFACTS:
        uploads.append(
            _put(
                s3_client,
                bucket,
                f"{LAKE_PREFIX}/{name}",
                (artifact_dir / name).read_bytes(),
                kms_key_arn,
            )
        )
    uploads.append(
        _put(
            s3_client,
            bucket,
            f"{LAKE_PREFIX}/batter_features.parquet",
            features_bytes,
            kms_key_arn,
        )
    )
    uploads.append(
        _put(
            s3_client,
            bucket,
            f"{LAKE_PREFIX}/profiles.jsonl",
            projection,
            kms_key_arn,
        )
    )

    published = {
        "schema_version": "batter_profile_publication.v1",
        "profile_identity": PROFILE_IDENTITY,
        "extraction_version": BATTER_EXTRACTION_VERSION,
        "feature_version": BATTER_FEATURE_VERSION,
        "producing_commit": producing_commit,
        "reproduced_in_runner": True,
        "history_partition_identity": identities["history_partition_identity"],
        "feature_partition_identity": identities["feature_partition_identity"],
        "source_file_ledger_identity": _ledger_identity(
            artifact_dir / "source_file_ledger.jsonl"
        ),
        "coverage_history_identity": coverage["history_partition_identity"],
        "coverage_feature_identity": coverage["feature_partition_identity"],
        "features_parquet_reproduced_in_runner": True,
        "features_parquet_sha256": hashlib.sha256(features_bytes).hexdigest(),
        "features_parquet_rows": len(snapshots),
        "projection_key": f"{LAKE_PREFIX}/profiles.jsonl",
        "projection_sha256": hashlib.sha256(projection).hexdigest(),
        "projection_rows": len(snapshots),
        "history_rows": len(history),
        "distinct_batters": coverage["distinct_batters"],
        "admitted_sources": coverage["day_files_opened"],
        "historical_prediction_join_eligible": False,
        "historical_lineup_timing_available": False,
        "uploads": uploads,
        "locked_2025_holdout_accessed": False,
    }
    _put(
        s3_client,
        bucket,
        f"{LAKE_PREFIX}/published_manifest.json",
        canonical_json_bytes(published),
        kms_key_arn,
    )
    return published


def reproduce_terminal(
    history_parquet: Path,
) -> tuple[list[dict[str, Any]], bytes, dict[str, Any]]:
    """Rebuild terminal per-batter profiles; verify identity/rows/eligible."""
    history = pq.read_table(history_parquet).to_pylist()
    profiles = build_terminal_profiles(history)
    identity = _identity(profiles)
    eligible = sum(1 for p in profiles if p["profile_feature_eligible"])
    if identity != EXPECTED_TERMINAL_IDENTITY:
        raise PublicationRefused(
            f"terminal identity mismatch: {identity} != {EXPECTED_TERMINAL_IDENTITY}"
        )
    if len(profiles) != EXPECTED_TERMINAL_ROWS:
        raise PublicationRefused(
            f"terminal row count differs: {len(profiles)} != {EXPECTED_TERMINAL_ROWS}"
        )
    if eligible != EXPECTED_TERMINAL_ELIGIBLE:
        raise PublicationRefused(
            f"terminal eligible count differs: {eligible} != {EXPECTED_TERMINAL_ELIGIBLE}"
        )
    projection = terminal_projection_bytes(profiles)
    meta = {
        "terminal_profiles_identity": identity,
        "profile_count": len(profiles),
        "eligible_count": eligible,
        "projection_sha256": hashlib.sha256(projection).hexdigest(),
        "projection_bytes": len(projection),
    }
    return profiles, projection, meta


def _guard_terminal_preconditions(artifact_dir: Path, producing_commit: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{7,40}", producing_commit or ""):
        raise PublicationRefused(f"invalid producing commit: {producing_commit!r}")
    for name in TERMINAL_REQUIRED_ARTIFACTS:
        if not (artifact_dir / name).is_file():
            raise PublicationRefused(f"missing required terminal artifact: {name}")
    coverage = json.loads((artifact_dir / "coverage.json").read_text())
    if coverage.get("day_files_opened_2025") != 0:
        raise PublicationRefused("zero-2025 evidence absent (opened_2025 != 0)")
    if coverage.get("locked_2025_holdout_accessed") is not False:
        raise PublicationRefused("zero-2025 evidence absent (holdout accessed)")


def publish_terminal(
    *,
    artifact_dir: Path,
    bucket: str,
    kms_key_arn: str,
    producing_commit: str,
    s3_client: Any | None = None,
) -> dict[str, Any]:
    """Reproduce, verify, and publish the compact terminal projection.

    Uploads under the existing batter feature identity prefix WITHOUT overwriting
    the full historical artifacts (distinct filenames).
    """
    _guard_terminal_preconditions(artifact_dir, producing_commit)
    _profiles, projection, meta = reproduce_terminal(
        artifact_dir / "batter_game_history.parquet"
    )

    if s3_client is None:
        import importlib

        s3_client = importlib.import_module("boto3").client("s3")

    uploads: list[dict[str, Any]] = []
    uploads.append(
        _put(
            s3_client,
            bucket,
            f"{LAKE_PREFIX}/terminal_batter_profiles.jsonl",
            projection,
            kms_key_arn,
        )
    )
    for name in (
        "terminal_profile_coverage.json",
        "terminal_profile_schema.json",
        "terminal_determinism_evidence.json",
    ):
        uploads.append(
            _put(
                s3_client,
                bucket,
                f"{LAKE_PREFIX}/{name}",
                (artifact_dir / name).read_bytes(),
                kms_key_arn,
            )
        )

    published = {
        "schema_version": "batter_terminal_publication.v1",
        "profile_identity": PROFILE_IDENTITY,
        "terminal_profile_version": TERMINAL_PROFILE_VERSION,
        "feature_version": BATTER_FEATURE_VERSION,
        "producing_commit": producing_commit,
        "reproduced_in_runner": True,
        "terminal_projection_key": f"{LAKE_PREFIX}/terminal_batter_profiles.jsonl",
        "historical_prediction_join_eligible": False,
        "historical_lineup_timing_available": False,
        "locked_2025_holdout_accessed": False,
        "uploads": uploads,
        **meta,
    }
    _put(
        s3_client,
        bucket,
        f"{LAKE_PREFIX}/terminal_published_manifest.json",
        canonical_json_bytes(published),
        kms_key_arn,
    )
    return published


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument(
        "--terminal",
        action="store_true",
        help="operate on the compact terminal per-batter projection",
    )
    parser.add_argument("--bucket")
    parser.add_argument("--kms-key-arn")
    parser.add_argument("--producing-commit", default="")
    args = parser.parse_args(argv)

    if args.verify_only:
        if args.terminal:
            _profiles, _projection, meta = reproduce_terminal(
                args.artifact_dir / "batter_game_history.parquet"
            )
            print(json.dumps({"verified": True, **meta}, sort_keys=True))
            return 0
        _history, _snapshots, identities = reproduce_features(
            args.artifact_dir / "batter_game_history.parquet"
        )
        print(json.dumps({"verified": True, **identities}, sort_keys=True))
        return 0

    if not args.bucket or not args.kms_key_arn:
        raise SystemExit("--bucket and --kms-key-arn are required to publish")
    if args.terminal:
        published = publish_terminal(
            artifact_dir=args.artifact_dir,
            bucket=args.bucket,
            kms_key_arn=args.kms_key_arn,
            producing_commit=args.producing_commit,
        )
    else:
        published = publish(
            artifact_dir=args.artifact_dir,
            bucket=args.bucket,
            kms_key_arn=args.kms_key_arn,
            producing_commit=args.producing_commit,
        )
    print(json.dumps(published, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
