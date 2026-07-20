"""Tests for lineup snapshot normalization and forward lineup capture."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import pytest

from nrfi import aws_pregame_collector as collector
from nrfi import lineup_snapshot as ls
from nrfi.pregame_snapshot import canonical_json_bytes

TARGET = date(2026, 7, 20)
NOW = datetime(2026, 7, 20, 15, 0, tzinfo=timezone.utc)


def _payload(*, away_posted: bool, home_posted: bool) -> dict[str, Any]:
    def _players(base: int) -> list[dict[str, Any]]:
        return [
            {
                "id": base + i,
                "fullName": f"Batter {base + i}",
                "primaryPosition": {"abbreviation": "CF" if i == 0 else "1B"},
            }
            for i in range(9)
        ]

    lineups: dict[str, Any] = {}
    if away_posted:
        lineups["awayPlayers"] = _players(100)
    if home_posted:
        lineups["homePlayers"] = _players(200)
    return {
        "dates": [
            {
                "games": [
                    {
                        "gamePk": 800,
                        "gameType": "R",
                        "officialDate": TARGET.isoformat(),
                        "gameDate": f"{TARGET.isoformat()}T23:10:00Z",
                        "status": {"statusCode": "S"},
                        "teams": {
                            "away": {"team": {"id": 1, "name": "Away"}},
                            "home": {"team": {"id": 2, "name": "Home"}},
                        },
                        "lineups": lineups,
                    }
                ]
            }
        ]
    }


def _source(payload: dict[str, Any], retrieved_at: str = "2026-07-20T15:00:00Z"):
    raw = canonical_json_bytes(payload)
    import hashlib

    return {
        "request_parameters": {"date": TARGET.isoformat()},
        "retrieved_at": retrieved_at,
        "response_sha256": hashlib.sha256(raw).hexdigest(),
        "payload": payload,
    }


def test_confirmed_and_missing_lineup_sides_are_distinguished() -> None:
    rows = ls.build_lineup_snapshot_rows(
        _source(_payload(away_posted=True, home_posted=False)), TARGET
    )
    by_side = {row["side"]: row for row in rows}
    assert by_side["away"]["lineup_status"] == "CONFIRMED"
    assert by_side["away"]["batting_order_length"] == 9
    assert by_side["away"]["batting_order"][0] == {
        "batting_order": 1,
        "player_id": 100,
        "player_name": "Batter 100",
        "defensive_position": "CF",
    }
    assert by_side["away"]["source_publication_time"] is None
    assert by_side["away"]["observed_before_cutoff"] is True
    assert by_side["home"]["lineup_status"] == "NOT_AVAILABLE"
    assert by_side["home"]["batting_order"] == []


def test_snapshot_identity_is_deterministic() -> None:
    source = _source(_payload(away_posted=True, home_posted=True))
    first = ls.build_lineup_snapshot_rows(source, TARGET)
    second = ls.build_lineup_snapshot_rows(source, TARGET)
    assert first == second
    assert [r["snapshot_id"] for r in first] == [r["snapshot_id"] for r in second]


def test_duplicate_player_id_is_rejected() -> None:
    payload = _payload(away_posted=True, home_posted=False)
    payload["dates"][0]["games"][0]["lineups"]["awayPlayers"][1]["id"] = 100
    with pytest.raises(ls.LineupSnapshotError, match="duplicate"):
        ls.build_lineup_snapshot_rows(_source(payload), TARGET)


def test_locked_2025_lineup_target_is_rejected() -> None:
    with pytest.raises(ls.LineupSnapshotError, match="locked 2025"):
        ls.build_lineup_snapshot_rows(
            _source(_payload(away_posted=True, home_posted=True)), date(2025, 7, 20)
        )


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.content = canonical_json_bytes(payload)

    def raise_for_status(self) -> None:
        return None


def test_collect_lineup_capture_normalizes_and_counts() -> None:
    capture = collector.collect_lineup_capture(
        TARGET,
        now=lambda: NOW,
        get=lambda *a, **k: _Response(_payload(away_posted=True, home_posted=True)),
    )
    assert capture["schema_version"] == "forward_lineup_capture.v1"
    assert capture["row_count"] == 2
    assert capture["confirmed_lineups"] == 2
    assert capture["raw_source_payload_uploaded"] is False
    assert capture["locked_2025_holdout_accessed"] is False
    key = collector.lineup_capture_object_key(capture)
    assert key == (
        "signals/pregame/official-statsapi/lineups/2026-07-20/"
        "capture-20260720T150000Z.json"
    )


def test_lineup_key_rejects_2025() -> None:
    with pytest.raises(collector.ForwardCollectorError):
        collector.lineup_capture_object_key(
            {"target_date": "2025-07-20", "retrieved_at": "2026-07-20T15:00:00Z"}
        )


class _FakeS3:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"VersionId": f"v{len(self.calls)}"}


def test_run_forward_collection_stores_lineups(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("NRFI_LAKE_BUCKET", "test-lake")
    monkeypatch.setenv(
        "NRFI_PLATFORM_KMS_KEY_ARN", "arn:aws:kms:us-east-2:111122223333:key/abc"
    )
    monkeypatch.setenv("NRFI_LOCKED_HOLDOUT_ACCESS", "DENIED")

    def _get(*args: Any, **kwargs: Any) -> _Response:
        params = kwargs["params"]
        target = date.fromisoformat(str(params["date"]))
        if params.get("hydrate", "").startswith("lineups"):
            return _Response(_lineup_for(target))
        return _Response(_starter_for(target))

    fake = _FakeS3()
    summary = collector.run_forward_collection(
        s3_client=fake, now=lambda: NOW, get=_get, cache_dir=tmp_path
    )
    lineup_keys = [c["Key"] for c in fake.calls if "/lineups/" in c["Key"]]
    assert len(lineup_keys) == 2
    assert summary["schema_version"] == "forward_collector_run.v2"
    assert len(summary["lineup_captures"]) == 2
    for call in fake.calls:
        assert call["ServerSideEncryption"] == "aws:kms"
        assert call["CacheControl"] == "no-store"


def _starter_for(target: date) -> dict[str, Any]:
    return {
        "dates": [
            {
                "games": [
                    {
                        "gamePk": 800,
                        "gameType": "R",
                        "officialDate": target.isoformat(),
                        "gameDate": f"{target.isoformat()}T23:10:00Z",
                        "doubleHeader": "N",
                        "gameNumber": 1,
                        "status": {"statusCode": "S"},
                        "venue": {"id": 10, "name": "Park"},
                        "teams": {
                            "away": {
                                "team": {"id": 1, "name": "Away"},
                                "probablePitcher": {"id": 7, "fullName": "P7"},
                            },
                            "home": {"team": {"id": 2, "name": "Home"}},
                        },
                    }
                ]
            }
        ]
    }


def _lineup_for(target: date) -> dict[str, Any]:
    payload = _starter_for(target)
    payload["dates"][0]["games"][0]["lineups"] = {
        "awayPlayers": [
            {
                "id": 100 + i,
                "fullName": f"A{i}",
                "primaryPosition": {"abbreviation": "CF"},
            }
            for i in range(9)
        ]
    }
    return payload
