"""Tests for immutable lineup capture admission + pre-cutoff selection."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any

from nrfi import lineup_admission as la
from nrfi.pregame_snapshot import canonical_json_bytes

DATE = "2026-07-20"
CUTOFF = "2026-07-20T23:05:00Z"


def _dt(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def _row(
    game_pk: int,
    side: str,
    observed_at: str,
    order_ids: list[int],
    status: str = "CONFIRMED",
    cutoff: str = CUTOFF,
) -> dict[str, Any]:
    row = {
        "schema_version": la.LINEUP_SNAPSHOT_SCHEMA_VERSION,
        "source_observation_id": "obs",
        "game_pk": game_pk,
        "official_date": DATE,
        "scheduled_start_at": cutoff,
        "prediction_cutoff": cutoff,
        "game_status_code": "P",
        "side": side,
        "team_id": 100 if side == "away" else 200,
        "lineup_status": status,
        "batting_order_length": len(order_ids),
        "batting_order": [
            {
                "batting_order": i + 1,
                "player_id": pid,
                "player_name": f"P{pid}",
                "defensive_position": "SS",
            }
            for i, pid in enumerate(order_ids)
        ],
        "lineup_observed_at": observed_at,
        "source_publication_time": None,
        "availability_basis": "OFFICIAL_STATSAPI_LINEUP_OBSERVED_AT_RETRIEVAL",
        "observed_before_cutoff": _dt(observed_at) < _dt(cutoff),
    }
    row["snapshot_id"] = la._identity(row)
    return row


def _capture(observed_at: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": la.LINEUP_CAPTURE_SCHEMA_VERSION,
        "target_date": DATE,
        "endpoint": "https://statsapi",
        "request_parameters": {"date": DATE},
        "retrieved_at": observed_at,
        "response_bytes": 10,
        "response_sha256": "a" * 64,
        "raw_source_payload_uploaded": False,
        "row_count": len(rows),
        "confirmed_lineups": sum(1 for r in rows if r["lineup_status"] == "CONFIRMED"),
        "lineups_observed_before_cutoff": sum(
            1 for r in rows if r["observed_before_cutoff"]
        ),
        "snapshot_identity": la._identity(rows),
        "rows": rows,
        "locked_2025_holdout_accessed": False,
    }


class _FakeS3:
    def __init__(self, objects: dict[str, dict[str, Any]]) -> None:
        self._objects = objects

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        prefix = kwargs["Prefix"]
        keys = [k for k in self._objects if k.startswith(prefix)]
        return {"Contents": [{"Key": k} for k in keys], "IsTruncated": False}

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        cap = self._objects[Key]
        return {
            "Body": io.BytesIO(canonical_json_bytes(cap)),
            "VersionId": "ver-" + Key[-8:],
            "ServerSideEncryption": "aws:kms",
        }


def _key(observed_at: str) -> str:
    compact = observed_at[:19].replace("-", "").replace(":", "") + "Z"
    return f"{la.LINEUP_KEY_PREFIX}/{DATE}/capture-{compact}.json"


def _admit(objects: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    s3 = _FakeS3(objects)
    keys = la.list_lineup_capture_keys(s3, "bucket", DATE)
    return [la.read_lineup_capture(s3, "bucket", k) for k in keys]


def test_admits_valid_capture() -> None:
    cap = _capture(
        "2026-07-20T20:00:00Z",
        [_row(1, "away", "2026-07-20T20:00:00Z", [11, 12, 13, 14])],
    )
    adm = _admit({_key("2026-07-20T20:00:00Z"): cap})
    assert adm[0]["status"] == "ADMITTED"
    assert adm[0]["rows_admitted"] == 1


def test_rejects_unknown_schema() -> None:
    cap = _capture(
        "2026-07-20T20:00:00Z", [_row(1, "away", "2026-07-20T20:00:00Z", [1])]
    )
    cap["schema_version"] = "something_else"
    adm = _admit({_key("2026-07-20T20:00:00Z"): cap})
    assert adm[0]["status"] == "REJECTED"
    assert adm[0]["reason"] == "LINEUP_SCHEMA_INVALID"


def test_rejects_identity_mismatch() -> None:
    cap = _capture(
        "2026-07-20T20:00:00Z", [_row(1, "away", "2026-07-20T20:00:00Z", [1])]
    )
    cap["snapshot_identity"] = "b" * 64
    adm = _admit({_key("2026-07-20T20:00:00Z"): cap})
    assert adm[0]["reason"] == "LINEUP_IDENTITY_MISMATCH"


def test_rejects_locked_2025() -> None:
    cap = _capture(
        "2026-07-20T20:00:00Z", [_row(1, "away", "2026-07-20T20:00:00Z", [1])]
    )
    cap["target_date"] = "2025-07-20"
    adm = _admit({_key("2026-07-20T20:00:00Z"): cap})
    assert adm[0]["reason"] == "LINEUP_LOCKED_HOLDOUT"


def test_selects_latest_pre_cutoff_and_stores_after_cutoff() -> None:
    early = _capture(
        "2026-07-20T20:00:00Z",
        [_row(1, "away", "2026-07-20T20:00:00Z", [11, 12, 13, 14])],
    )
    late = _capture(
        "2026-07-20T22:00:00Z",
        [_row(1, "away", "2026-07-20T22:00:00Z", [11, 12, 13, 15])],
    )
    after = _capture(
        "2026-07-20T23:30:00Z",
        [_row(1, "away", "2026-07-20T23:30:00Z", [99, 98, 97, 96])],
    )
    objects = {
        _key("2026-07-20T20:00:00Z"): early,
        _key("2026-07-20T22:00:00Z"): late,
        _key("2026-07-20T23:30:00Z"): after,
    }
    hist = la.build_lineup_observation_history(_admit(objects))
    # all three revisions preserved (after-cutoff stored, not dropped)
    assert len(hist[(1, "away")]) == 3
    sel = la.select_lineups(hist, as_of=_dt("2026-07-20T23:59:00Z"))[(1, "away")]
    # latest PRE-cutoff revision selected (22:00), not the after-cutoff one
    assert sel["lineup_observed_at"] == "2026-07-20T22:00:00Z"
    assert sel["batting_order_ids"] == [11, 12, 13, 15]
    assert sel["observed_before_cutoff"] is True
    # order changed between 20:00 and 22:00 -> UPDATED, revision_count 2
    assert sel["lineup_status"] == "UPDATED"
    assert sel["revision_count"] == 2
    assert len(sel["previous_snapshot_ids"]) == 1


def test_withdrawn_when_confirmed_then_not_available() -> None:
    early = _capture(
        "2026-07-20T20:00:00Z",
        [_row(1, "home", "2026-07-20T20:00:00Z", [21, 22, 23, 24])],
    )
    later = _capture(
        "2026-07-20T21:00:00Z",
        [_row(1, "home", "2026-07-20T21:00:00Z", [], status="NOT_AVAILABLE")],
    )
    objects = {
        _key("2026-07-20T20:00:00Z"): early,
        _key("2026-07-20T21:00:00Z"): later,
    }
    hist = la.build_lineup_observation_history(_admit(objects))
    sel = la.select_lineups(hist, as_of=_dt("2026-07-20T22:00:00Z"))[(1, "home")]
    assert sel["lineup_status"] == "WITHDRAWN"


def test_duplicate_snapshot_not_double_counted() -> None:
    r1 = _row(1, "away", "2026-07-20T20:00:00Z", [11, 12, 13, 14])
    r2 = _row(1, "away", "2026-07-20T21:00:00Z", [11, 12, 13, 14])  # same order
    objects = {
        _key("2026-07-20T20:00:00Z"): _capture("2026-07-20T20:00:00Z", [r1]),
        _key("2026-07-20T21:00:00Z"): _capture("2026-07-20T21:00:00Z", [r2]),
    }
    hist = la.build_lineup_observation_history(_admit(objects))
    sel = la.select_lineups(hist, as_of=_dt("2026-07-20T22:00:00Z"))[(1, "away")]
    # identical batting order across revisions -> still CONFIRMED, revision_count 1
    assert sel["lineup_status"] == "CONFIRMED"
    assert sel["revision_count"] == 1
