"""Reproduce and publish the expanded 2015-2024 pitcher profile artifacts.

Reproduction rebuilds ``pitcher_features`` deterministically from the committed
canonical ``pitcher_game_history.parquet`` plus the committed 2015-2024
multiseason starters, then requires the feature and history partition
identities (canonical-JSON, platform independent) to equal the locally verified
values.  Publication uploads the verified artifacts to the existing private,
versioned, SSE-KMS S3 lake under a new immutable expanded-history prefix without
overwriting the prior 2021-2024 evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from nrfi.pitcher_statcast import FEATURE_VERSION, canonical_json_bytes
from nrfi.statcast_extraction import (
    EXTRACTION_VERSION,
    build_pitcher_feature_snapshots_fast,
)

EXPECTED_HISTORY_IDENTITY = (
    "3d2243a43deb2b70287c4efd777c510f1f0ef89c558251989981dcdc01f6b5e5"
)
EXPECTED_FEATURE_IDENTITY = (
    "52c0d0a9405ee2096301d52c1d06e54c9c588a7ff4041738da916befa1ba90b8"
)
PROFILE_IDENTITY = "pitcher-statcast-strict-prior-2015-2024-v1"
LAKE_PREFIX = f"features/{PROFILE_IDENTITY}"


def _identity(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _load_starters(multiseason_dir: Path) -> list[dict[str, Any]]:
    from nrfi.statcast_extraction import ADMITTED_MAX_SEASON, ADMITTED_MIN_SEASON
    from nrfi.pitcher_statcast import load_development_context

    seasons = list(range(ADMITTED_MIN_SEASON, ADMITTED_MAX_SEASON + 1))
    starters, _ = load_development_context(multiseason_dir, seasons)
    return starters


def reproduce_features(
    history_parquet: Path, multiseason_dir: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    """Rebuild features from the canonical history parquet; verify identities."""
    history = pq.read_table(history_parquet).to_pylist()
    starters = _load_starters(multiseason_dir)
    snapshots = build_pitcher_feature_snapshots_fast(history, starters)
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
    """Project feature snapshots to the flat JSONL rows the Lambda runtime reads."""
    rows: list[dict[str, Any]] = []
    for snapshot in snapshots:
        values = snapshot["feature_values"]
        rows.append(
            {
                "pitcher_id": int(snapshot["pitcher_id"]),
                "prediction_cutoff": snapshot["prediction_cutoff"],
                "game_pk": int(snapshot["game_pk"]),
                "profile_feature_eligible": bool(snapshot["profile_feature_eligible"]),
                "feature_version": snapshot["feature_version"],
                "feature_hash": snapshot["feature_hash"],
                "feature_values": values,
            }
        )
    rows.sort(key=lambda row: (row["prediction_cutoff"], row["game_pk"]))
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
    multiseason_dir: Path,
    bucket: str,
    kms_key_arn: str,
    producing_commit: str,
    s3_client: Any | None = None,
) -> dict[str, Any]:
    """Reproduce, verify, and publish the expanded artifacts to the lake."""
    history_parquet = artifact_dir / "pitcher_game_history.parquet"
    _history, snapshots, identities = reproduce_features(
        history_parquet, multiseason_dir
    )
    projection = build_projection_bytes(snapshots)

    if s3_client is None:
        import importlib

        s3_client = importlib.import_module("boto3").client("s3")

    uploads: list[dict[str, Any]] = []
    file_names = [
        "pitcher_game_history.parquet",
        "pitcher_features.parquet",
        "source_file_ledger.jsonl",
        "rejections.jsonl",
        "coverage.json",
        "artifact_manifest.json",
        "determinism_evidence.json",
        "rejection_census_2026_07_19.json",
    ]
    for name in file_names:
        path = artifact_dir / name
        if not path.is_file():
            continue
        uploads.append(
            _put(
                s3_client,
                bucket,
                f"{LAKE_PREFIX}/{name}",
                path.read_bytes(),
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
        "schema_version": "expanded_profile_publication.v1",
        "profile_identity": PROFILE_IDENTITY,
        "extraction_version": EXTRACTION_VERSION,
        "feature_version": FEATURE_VERSION,
        "producing_commit": producing_commit,
        "reproduced_in_runner": True,
        "history_partition_identity": identities["history_partition_identity"],
        "feature_partition_identity": identities["feature_partition_identity"],
        "projection_key": f"{LAKE_PREFIX}/profiles.jsonl",
        "projection_sha256": hashlib.sha256(projection).hexdigest(),
        "projection_rows": len(snapshots),
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--multiseason-dir", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--bucket")
    parser.add_argument("--kms-key-arn")
    parser.add_argument("--producing-commit", default="")
    args = parser.parse_args(argv)

    if args.verify_only:
        _history, _snapshots, identities = reproduce_features(
            args.artifact_dir / "pitcher_game_history.parquet", args.multiseason_dir
        )
        print(json.dumps({"verified": True, **identities}, sort_keys=True))
        return 0

    if not args.bucket or not args.kms_key_arn:
        raise SystemExit("--bucket and --kms-key-arn are required to publish")
    published = publish(
        artifact_dir=args.artifact_dir,
        multiseason_dir=args.multiseason_dir,
        bucket=args.bucket,
        kms_key_arn=args.kms_key_arn,
        producing_commit=args.producing_commit,
    )
    print(json.dumps(published, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
