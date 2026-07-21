"""Focused tests for the forward probable-starter snapshot collector."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from nrfi import aws_pregame_collector as collector
from nrfi.pregame_snapshot import (
    PregameSnapshotError,
    acquire_source_snapshot,
    build_probable_starter_rows,
    canonical_json_bytes,
)

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)


def _payload(target: date, *, game_pk: int = 123) -> dict[str, Any]:
    return {
        "dates": [
            {
                "games": [
                    {
                        "gamePk": game_pk,
                        "gameType": "R",
                        "officialDate": target.isoformat(),
                        "gameDate": f"{target.isoformat()}T23:00:00Z",
                        "doubleHeader": "N",
                        "gameNumber": 1,
                        "status": {"statusCode": "S"},
                        "venue": {"id": 10, "name": "Verified Park"},
                        "teams": {
                            "away": {
                                "team": {"id": 1, "name": "Away"},
                                "probablePitcher": {"id": 7, "fullName": "Pitcher"},
                            },
                            "home": {"team": {"id": 2, "name": "Home"}},
                        },
                    }
                ]
            }
        ]
    }


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.content = canonical_json_bytes(payload)

    def raise_for_status(self) -> None:
        return None


class _FakeS3:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"VersionId": f"v{len(self.calls)}"}


def _get(*args: object, **kwargs: object) -> _Response:
    params = kwargs.get("params")
    assert isinstance(params, dict)
    return _Response(_payload(date.fromisoformat(str(params["date"]))))


def _configure_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NRFI_LAKE_BUCKET", "test-lake")
    monkeypatch.setenv(
        "NRFI_PLATFORM_KMS_KEY_ARN", "arn:aws:kms:us-east-2:111122223333:key/abc"
    )
    monkeypatch.setenv("NRFI_LOCKED_HOLDOUT_ACCESS", "DENIED")


def test_run_preserves_two_derived_snapshots_without_raw_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure_env(monkeypatch)
    fake_s3 = _FakeS3()

    summary = collector.run_forward_collection(
        s3_client=fake_s3,
        now=lambda: NOW,
        get=_get,
        cache_dir=tmp_path,
    )

    forward_keys = [c["Key"] for c in fake_s3.calls if "/forward/" in c["Key"]]
    assert forward_keys == [
        "signals/pregame/official-statsapi/forward/2026-07-18/"
        "capture-20260718T120000Z.json",
        "signals/pregame/official-statsapi/forward/2026-07-19/"
        "capture-20260718T120000Z.json",
    ]
    for call in fake_s3.calls:
        assert call["Bucket"] == "test-lake"
        assert call["ContentType"] == "application/json"
        assert call["CacheControl"] == "no-store"
        assert call["ServerSideEncryption"] == "aws:kms"
        assert call["SSEKMSKeyId"].startswith("arn:aws:kms:")
        body = json.loads(call["Body"].decode("utf-8"))
        assert body["raw_source_payload_uploaded"] is False
        assert body["locked_2025_holdout_accessed"] is False
        assert "response_body_base64" not in call["Body"].decode("utf-8")
    forward_bodies = [
        json.loads(c["Body"].decode("utf-8"))
        for c in fake_s3.calls
        if "/forward/" in c["Key"]
    ]
    for body in forward_bodies:
        assert body["schema_version"] == collector.CAPTURE_SCHEMA_VERSION
        assert body["row_count"] == 2
    assert summary["schema_version"] == collector.RUN_SCHEMA_VERSION
    # each date stores a forward capture then a lineup capture, so version ids
    # interleave v1(forward) v2(lineup) v3(forward) v4(lineup).
    assert [item["stored"]["version_id"] for item in summary["captures"]] == [
        "v1",
        "v3",
    ]
    assert [item["stored"]["version_id"] for item in summary["lineup_captures"]] == [
        "v2",
        "v4",
    ]
    assert not sorted(tmp_path.glob("source-*.json"))


def test_capture_rows_match_shared_pregame_normalization(tmp_path: Path) -> None:
    target = date(2026, 7, 18)

    capture = collector.collect_capture(target, tmp_path, now=lambda: NOW, get=_get)
    source = acquire_source_snapshot(
        target,
        tmp_path / f"source-{target.isoformat()}.json",
        allow_network=False,
    )

    assert capture["rows"] == build_probable_starter_rows(source, target)
    assert capture["response_sha256"] == source["response_sha256"]
    assert (
        capture["snapshot_identity"]
        == hashlib.sha256(canonical_json_bytes(capture["rows"])).hexdigest()
    )


def test_environment_boundary_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NRFI_LAKE_BUCKET", raising=False)
    monkeypatch.delenv("NRFI_PLATFORM_KMS_KEY_ARN", raising=False)
    monkeypatch.delenv("NRFI_LOCKED_HOLDOUT_ACCESS", raising=False)
    with pytest.raises(collector.ForwardCollectorError):
        collector.run_forward_collection(s3_client=_FakeS3(), get=_get)

    _configure_env(monkeypatch)
    monkeypatch.setenv("NRFI_LOCKED_HOLDOUT_ACCESS", "ALLOWED")
    with pytest.raises(collector.ForwardCollectorError):
        collector.run_forward_collection(s3_client=_FakeS3(), get=_get)


def test_locked_2025_capture_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(PregameSnapshotError):
        collector.collect_capture(
            date(2025, 7, 18), tmp_path, now=lambda: NOW, get=_get
        )
    with pytest.raises(collector.ForwardCollectorError):
        collector.capture_object_key(
            {"target_date": "2025-07-18", "retrieved_at": "2026-07-18T12:00:00Z"}
        )


def test_no_games_day_preserves_empty_capture(tmp_path: Path) -> None:
    def empty_get(*args: object, **kwargs: object) -> _Response:
        return _Response({"dates": []})

    capture = collector.collect_capture(
        date(2026, 7, 18), tmp_path, now=lambda: NOW, get=empty_get
    )

    assert capture["row_count"] == 0
    assert capture["rows"] == []
    assert capture["pregame_feature_eligible_rows"] == 0


def test_market_date_resolves_and_survives_missing_tzdata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert collector.market_today(NOW) == date(2026, 7, 18)
    assert collector.market_today(
        datetime(2026, 7, 19, 2, 0, tzinfo=timezone.utc)
    ) == date(2026, 7, 18)

    real_import = collector.importlib.import_module

    def broken(name: str) -> Any:
        if name == "zoneinfo":
            raise ImportError("tzdata unavailable")
        return real_import(name)

    monkeypatch.setattr(collector.importlib, "import_module", broken)
    assert collector.market_today(NOW) == date(2026, 7, 18)


def test_handler_publishes_assembly_when_profiles_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_env(monkeypatch)
    monkeypatch.setenv("NRFI_PITCHER_PROFILES_KEY", "features/profiles.jsonl")
    monkeypatch.setenv("NRFI_ASSEMBLY_FRESHNESS_SECONDS", "1234")
    fake_s3 = _FakeS3()
    runtime_boto3 = __import__("types").SimpleNamespace(client=lambda service: fake_s3)
    monkeypatch.setattr(
        collector.importlib,
        "import_module",
        lambda name: runtime_boto3 if name == "boto3" else None,
    )
    summary_stub = {
        "captures": [{"target_date": "2026-07-18"}, {"target_date": "2026-07-19"}]
    }
    monkeypatch.setattr(collector, "run_forward_collection", lambda: dict(summary_stub))
    recorded: dict[str, Any] = {}

    def fake_run_assembly(
        s3_client: Any,
        bucket: str,
        kms_key_arn: str,
        dates: Any,
        *,
        profiles_key: str,
        freshness_limit_seconds: int,
        terminal_profiles_key: Any = None,
        team_profiles_key: Any = None,
    ) -> dict[str, Any]:
        recorded.update(
            {
                "s3_client": s3_client,
                "bucket": bucket,
                "kms_key_arn": kms_key_arn,
                "dates": list(dates),
                "profiles_key": profiles_key,
                "freshness_limit_seconds": freshness_limit_seconds,
                "terminal_profiles_key": terminal_profiles_key,
                "team_profiles_key": team_profiles_key,
            }
        )
        return {"schema_version": "forward_assembly_run.v1"}

    monkeypatch.setattr(collector.forward_admission, "run_assembly", fake_run_assembly)

    summary = collector.lambda_handler({}, None)

    assert summary["assembly"] == {"schema_version": "forward_assembly_run.v1"}
    assert recorded["bucket"] == "test-lake"
    assert recorded["dates"] == ["2026-07-18", "2026-07-19"]
    assert recorded["profiles_key"] == "features/profiles.jsonl"
    assert recorded["freshness_limit_seconds"] == 1234
    assert recorded["s3_client"] is fake_s3
