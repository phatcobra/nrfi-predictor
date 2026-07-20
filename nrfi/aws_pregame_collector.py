"""Scheduled AWS collector for immutable timestamped probable-starter snapshots."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from nrfi import forward_admission
from nrfi.lineup_snapshot import (
    LineupSnapshotError,
    build_lineup_snapshot_rows,
    summarize_lineups,
)
from nrfi.pregame_snapshot import (
    HTTP_TIMEOUT_SECONDS,
    STATSAPI_ENDPOINT,
    PregameSnapshotError,
    acquire_source_snapshot,
    build_probable_starter_rows,
    canonical_json_bytes,
)

CAPTURE_SCHEMA_VERSION = "forward_probable_starter_capture.v1"
LINEUP_CAPTURE_SCHEMA_VERSION = "forward_lineup_capture.v1"
RUN_SCHEMA_VERSION = "forward_collector_run.v2"
FORWARD_KEY_PREFIX = "signals/pregame/official-statsapi/forward"
LINEUP_KEY_PREFIX = "signals/pregame/official-statsapi/lineups"
NO_LINEUP_GAMES_MESSAGE = "no regular-season games found for target date"
MARKET_TIMEZONE = "America/New_York"
FALLBACK_UTC_OFFSET_HOURS = -4
TARGET_DATE_OFFSETS = (0, 1)
NO_GAMES_MESSAGE = "no regular-season games found for target date"
USER_AGENT = "nrfi-probability-forward-collector/1.0"


class ForwardCollectorError(ValueError):
    """Raised when the forward collector violates its fail-closed contract."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class _HttpResponse:
    def __init__(self, status_code: int, content: bytes) -> None:
        self.status_code = status_code
        self.content = content

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise ForwardCollectorError(
                f"source request failed with HTTP {self.status_code}"
            )


def stdlib_get(url: str, *, params: Mapping[str, Any], timeout: float) -> _HttpResponse:
    """Fetch the official schedule endpoint with the standard library only."""
    query = urllib.parse.urlencode(sorted((key, str(params[key])) for key in params))
    request = urllib.request.Request(
        f"{url}?{query}",
        headers={"User-Agent": USER_AGENT},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return _HttpResponse(int(response.status), response.read())


def market_today(now: datetime) -> date:
    """Resolve the MLB market date; fall back to fixed EDT if tzdata is absent."""
    try:
        zoneinfo = importlib.import_module("zoneinfo")
        market_zone = zoneinfo.ZoneInfo(MARKET_TIMEZONE)
    except (ImportError, KeyError, OSError):
        market_zone = timezone(timedelta(hours=FALLBACK_UTC_OFFSET_HOURS))
    return now.astimezone(market_zone).date()


def _required_environment() -> tuple[str, str]:
    bucket = os.environ.get("NRFI_LAKE_BUCKET", "")
    kms_key_arn = os.environ.get("NRFI_PLATFORM_KMS_KEY_ARN", "")
    if (
        not bucket
        or not kms_key_arn.startswith("arn:")
        or os.environ.get("NRFI_LOCKED_HOLDOUT_ACCESS") != "DENIED"
    ):
        raise ForwardCollectorError("runtime boundary is not configured")
    if "2025" in bucket or "holdout" in bucket.lower():
        raise ForwardCollectorError("bucket violates the locked-holdout boundary")
    return bucket, kms_key_arn


def collect_capture(
    target_date: date,
    cache_dir: Path,
    *,
    now: Callable[[], datetime] = _utc_now,
    get: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Capture one derived, timestamped probable-starter snapshot for one date."""
    cache_path = cache_dir / f"source-{target_date.isoformat()}.json"
    source = acquire_source_snapshot(
        target_date,
        cache_path,
        allow_network=True,
        now=now,
        get=get or stdlib_get,
    )
    try:
        rows = build_probable_starter_rows(source, target_date)
    except PregameSnapshotError as error:
        if str(error) != NO_GAMES_MESSAGE:
            raise
        rows = []
    eligible = sum(bool(row["pregame_feature_eligible"]) for row in rows)
    return {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "target_date": target_date.isoformat(),
        "endpoint": source["endpoint"],
        "request_parameters": source["request_parameters"],
        "retrieved_at": source["retrieved_at"],
        "response_bytes": source["response_bytes"],
        "response_sha256": source["response_sha256"],
        "raw_source_payload_uploaded": False,
        "row_count": len(rows),
        "pregame_feature_eligible_rows": eligible,
        "snapshot_identity": hashlib.sha256(canonical_json_bytes(rows)).hexdigest(),
        "rows": rows,
        "locked_2025_holdout_accessed": False,
    }


def _lineup_request_parameters(target_date: date) -> dict[str, str | int]:
    return {
        "date": target_date.isoformat(),
        "hydrate": "lineups,team",
        "sportId": 1,
    }


def collect_lineup_capture(
    target_date: date,
    *,
    now: Callable[[], datetime] = _utc_now,
    get: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Fetch and normalize one immutable, timestamped lineup snapshot capture."""
    if target_date.year == 2025:
        raise ForwardCollectorError("the locked 2025 holdout is prohibited")
    requester = get or stdlib_get
    params = _lineup_request_parameters(target_date)
    response = requester(STATSAPI_ENDPOINT, params=params, timeout=HTTP_TIMEOUT_SECONDS)
    response.raise_for_status()
    raw = bytes(response.content)
    source = {
        "request_parameters": params,
        "retrieved_at": _utc_text(now()),
        "response_bytes": len(raw),
        "response_sha256": hashlib.sha256(raw).hexdigest(),
        "payload": json.loads(raw),
    }
    try:
        rows = build_lineup_snapshot_rows(source, target_date)
    except LineupSnapshotError as error:
        if str(error) != NO_LINEUP_GAMES_MESSAGE:
            raise
        rows = []
    coverage = summarize_lineups(rows)
    return {
        "schema_version": LINEUP_CAPTURE_SCHEMA_VERSION,
        "target_date": target_date.isoformat(),
        "endpoint": STATSAPI_ENDPOINT,
        "request_parameters": params,
        "retrieved_at": source["retrieved_at"],
        "response_bytes": source["response_bytes"],
        "response_sha256": source["response_sha256"],
        "raw_source_payload_uploaded": False,
        "row_count": len(rows),
        "confirmed_lineups": coverage["confirmed_lineups"],
        "lineups_observed_before_cutoff": coverage["lineups_observed_before_cutoff"],
        "snapshot_identity": hashlib.sha256(canonical_json_bytes(rows)).hexdigest(),
        "rows": rows,
        "locked_2025_holdout_accessed": False,
    }


def lineup_capture_object_key(capture: Mapping[str, Any]) -> str:
    """Derive the immutable, versioned S3 key for one lineup capture."""
    target_date = str(capture["target_date"])
    compact = str(capture["retrieved_at"])[:19].replace("-", "").replace(":", "") + "Z"
    key = f"{LINEUP_KEY_PREFIX}/{target_date}/capture-{compact}.json"
    if target_date.startswith("2025") or "holdout" in key.lower():
        raise ForwardCollectorError("lineup key violates the locked-holdout boundary")
    return key


def store_lineup_capture(
    s3_client: Any,
    bucket: str,
    kms_key_arn: str,
    capture: Mapping[str, Any],
) -> dict[str, Any]:
    """Write one lineup capture as a versioned, KMS-encrypted, no-store object."""
    key = lineup_capture_object_key(capture)
    body = canonical_json_bytes(capture)
    response = s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="application/json",
        CacheControl="no-store",
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=kms_key_arn,
    )
    return {
        "key": key,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "version_id": response.get("VersionId"),
    }


def capture_object_key(capture: Mapping[str, Any]) -> str:
    """Derive the immutable, versioned S3 key for one capture."""
    target_date = str(capture["target_date"])
    retrieved_at = str(capture["retrieved_at"])
    compact = retrieved_at[:19].replace("-", "").replace(":", "") + "Z"
    key = f"{FORWARD_KEY_PREFIX}/{target_date}/capture-{compact}.json"
    if target_date.startswith("2025") or "holdout" in key.lower():
        raise ForwardCollectorError("capture key violates the locked-holdout boundary")
    return key


def store_capture(
    s3_client: Any,
    bucket: str,
    kms_key_arn: str,
    capture: Mapping[str, Any],
) -> dict[str, Any]:
    """Write one capture as a versioned, KMS-encrypted, no-store JSON object."""
    key = capture_object_key(capture)
    body = canonical_json_bytes(capture)
    response = s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="application/json",
        CacheControl="no-store",
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=kms_key_arn,
    )
    return {
        "key": key,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "version_id": response.get("VersionId"),
    }


def run_forward_collection(
    *,
    s3_client: Any | None = None,
    now: Callable[[], datetime] = _utc_now,
    get: Callable[..., Any] | None = None,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    """Capture and preserve snapshots for the market's today and tomorrow."""
    bucket, kms_key_arn = _required_environment()
    if s3_client is None:
        s3_client = getattr(importlib.import_module("boto3"), "client")("s3")
    started_at = now()
    run_token = _utc_text(started_at).replace("-", "").replace(":", "")
    run_cache = cache_dir or Path("/tmp") / "nrfi-forward" / run_token
    base_date = market_today(started_at)
    captures: list[dict[str, Any]] = []
    lineup_captures: list[dict[str, Any]] = []
    try:
        for offset in TARGET_DATE_OFFSETS:
            target_date = base_date + timedelta(days=offset)
            capture = collect_capture(target_date, run_cache, now=now, get=get)
            stored = store_capture(s3_client, bucket, kms_key_arn, capture)
            captures.append(
                {
                    "target_date": capture["target_date"],
                    "retrieved_at": capture["retrieved_at"],
                    "response_sha256": capture["response_sha256"],
                    "row_count": capture["row_count"],
                    "pregame_feature_eligible_rows": capture[
                        "pregame_feature_eligible_rows"
                    ],
                    "stored": stored,
                }
            )
            lineup = collect_lineup_capture(target_date, now=now, get=get)
            lineup_stored = store_lineup_capture(s3_client, bucket, kms_key_arn, lineup)
            lineup_captures.append(
                {
                    "target_date": lineup["target_date"],
                    "retrieved_at": lineup["retrieved_at"],
                    "response_sha256": lineup["response_sha256"],
                    "row_count": lineup["row_count"],
                    "confirmed_lineups": lineup["confirmed_lineups"],
                    "lineups_observed_before_cutoff": lineup[
                        "lineups_observed_before_cutoff"
                    ],
                    "stored": lineup_stored,
                }
            )
    finally:
        for stale in sorted(run_cache.glob("source-*.json")):
            stale.unlink()
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "market_timezone": MARKET_TIMEZONE,
        "run_started_at": _utc_text(started_at),
        "run_completed_at": _utc_text(now()),
        "bucket": bucket,
        "captures": captures,
        "lineup_captures": lineup_captures,
        "locked_2025_holdout_accessed": False,
    }


def lambda_handler(event: Any, context: Any) -> dict[str, Any]:
    """Preserve snapshots, then publish fail-closed assembly packages."""
    del event, context
    summary = run_forward_collection()
    profiles_key = os.environ.get("NRFI_PITCHER_PROFILES_KEY", "")
    if profiles_key:
        bucket, kms_key_arn = _required_environment()
        s3_client = getattr(importlib.import_module("boto3"), "client")("s3")
        freshness_limit = int(
            os.environ.get(
                "NRFI_ASSEMBLY_FRESHNESS_SECONDS",
                str(forward_admission.DEFAULT_FRESHNESS_LIMIT_SECONDS),
            )
        )
        summary["assembly"] = forward_admission.run_assembly(
            s3_client,
            bucket,
            kms_key_arn,
            [capture["target_date"] for capture in summary["captures"]],
            profiles_key=profiles_key,
            freshness_limit_seconds=freshness_limit,
        )
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return summary
