from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from nrfi.pregame_snapshot import (
    PregameSnapshotError,
    acquire_source_snapshot,
    build_package,
    build_probable_starter_rows,
    canonical_json_bytes,
    join_pitcher_profiles,
)


TARGET_DATE = date(2026, 7, 19)
RETRIEVED_AT = "2026-07-18T12:00:00Z"


def _payload() -> dict[str, Any]:
    return {
        "dates": [
            {
                "games": [
                    {
                        "gamePk": 123,
                        "gameType": "R",
                        "officialDate": TARGET_DATE.isoformat(),
                        "gameDate": "2026-07-19T18:00:00Z",
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


def _source(*, retrieved_at: str = RETRIEVED_AT) -> dict[str, Any]:
    raw = canonical_json_bytes(_payload())
    return {
        "endpoint": "https://statsapi.mlb.com/api/v1/schedule",
        "request_parameters": {
            "date": TARGET_DATE.isoformat(),
            "hydrate": "probablePitcher,team,venue",
            "sportId": 1,
        },
        "retrieved_at": retrieved_at,
        "response_bytes": len(raw),
        "response_sha256": hashlib.sha256(raw).hexdigest(),
        "payload": _payload(),
    }


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.content = canonical_json_bytes(payload)

    def raise_for_status(self) -> None:
        return None


def _write_profiles(path: Path, rows: list[dict[str, Any]]) -> None:
    pq.write_table(pa.Table.from_pylist(rows), path)


def _profile(cutoff: str, *, eligible: bool = True) -> dict[str, Any]:
    return {
        "pitcher_id": 7,
        "game_pk": 99,
        "prediction_cutoff": cutoff,
        "feature_version": "pitcher_statcast_profile.v1",
        "profile_feature_eligible": eligible,
        "feature_hash": "a" * 64,
        "feature_values": {"prior_starts_career": 12.0},
    }


def test_acquisition_is_cached_and_replayed_without_network(tmp_path: Path) -> None:
    cache = tmp_path / "source.json"
    calls = 0

    def get(*args: object, **kwargs: object) -> _Response:
        nonlocal calls
        calls += 1
        return _Response(_payload())

    first = acquire_source_snapshot(
        TARGET_DATE,
        cache,
        allow_network=True,
        now=lambda: datetime(2026, 7, 18, 12, tzinfo=timezone.utc),
        get=get,
    )
    second = acquire_source_snapshot(
        TARGET_DATE,
        cache,
        allow_network=False,
        get=lambda *args, **kwargs: pytest.fail("network replay attempted"),
    )

    assert calls == 1
    assert first == second
    assert second["retrieved_at"] == RETRIEVED_AT
    assert (
        second["response_sha256"]
        == hashlib.sha256(_Response(_payload()).content).hexdigest()
    )


def test_snapshot_is_point_in_time_and_never_backfills_missing_pitcher() -> None:
    rows = build_probable_starter_rows(_source(), TARGET_DATE)

    assert len(rows) == 2
    assert rows[0]["probable_pitcher_id"] == 7
    assert rows[0]["pregame_feature_eligible"] is True
    assert rows[0]["source_publication_time"] is None
    assert rows[1]["probable_pitcher_id"] is None
    assert rows[1]["pregame_feature_ineligibility_reason"] == (
        "PROBABLE_STARTER_MISSING"
    )


def test_snapshot_at_cutoff_is_rejected() -> None:
    rows = build_probable_starter_rows(
        _source(retrieved_at="2026-07-19T18:00:00Z"), TARGET_DATE
    )

    assert all(row["pregame_feature_eligible"] is False for row in rows)
    assert all(
        row["pregame_feature_ineligibility_reason"]
        == "SNAPSHOT_AT_OR_AFTER_PREDICTION_CUTOFF"
        for row in rows
    )


def test_locked_2025_target_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(PregameSnapshotError, match="locked 2025"):
        acquire_source_snapshot(
            date(2025, 7, 19),
            tmp_path / "source.json",
            allow_network=False,
        )


def test_profile_join_uses_latest_strict_prior_profile(tmp_path: Path) -> None:
    profiles = tmp_path / "profiles.parquet"
    _write_profiles(
        profiles,
        [
            _profile("2024-09-01T18:00:00Z"),
            _profile("2026-07-17T18:00:00Z"),
            _profile("2026-07-18T13:00:00Z"),
        ],
    )

    rows = join_pitcher_profiles(
        build_probable_starter_rows(_source(), TARGET_DATE), profiles
    )

    assert rows[0]["profile_prediction_cutoff"] == "2026-07-17T18:00:00Z"
    assert rows[0]["feature_status"] == "READY"
    assert rows[0]["inference_eligible"] is True
    assert rows[1]["feature_status"] == "BLOCKED_PREGAME_SNAPSHOT"


def test_profile_join_flags_intervening_history_gap_without_erasure(
    tmp_path: Path,
) -> None:
    profiles = tmp_path / "profiles.parquet"
    _write_profiles(profiles, [_profile("2024-09-01T18:00:00Z")])

    row = join_pitcher_profiles(
        build_probable_starter_rows(_source(), TARGET_DATE), profiles
    )[0]

    assert row["feature_status"] == "READY"
    assert row["feature_status_reason"] is None
    assert row["inference_eligible"] is True
    assert row["profile_history_gap_seasons"] == 1
    assert row["profile_recent_history_missing"] is True


def test_profile_join_reports_zero_gap_for_current_history(
    tmp_path: Path,
) -> None:
    profiles = tmp_path / "profiles.parquet"
    _write_profiles(profiles, [_profile("2026-07-17T18:00:00Z")])

    row = join_pitcher_profiles(
        build_probable_starter_rows(_source(), TARGET_DATE), profiles
    )[0]

    assert row["feature_status"] == "READY"
    assert row["profile_history_gap_seasons"] == 0
    assert row["profile_recent_history_missing"] is False


def test_derived_package_replays_byte_identically_without_raw_payload(
    tmp_path: Path,
) -> None:
    profiles = tmp_path / "profiles.parquet"
    _write_profiles(profiles, [_profile("2024-09-01T18:00:00Z")])
    first = tmp_path / "first"
    second = tmp_path / "second"
    commit = "a" * 40

    build_package(TARGET_DATE, _source(), profiles, first, code_commit=commit)
    build_package(TARGET_DATE, _source(), profiles, second, code_commit=commit)

    assert sorted(path.name for path in first.iterdir()) == sorted(
        path.name for path in second.iterdir()
    )
    for first_path in first.iterdir():
        assert first_path.read_bytes() == (second / first_path.name).read_bytes()
    provenance = json.loads((first / "provenance.json").read_text())
    assert provenance["raw_source_payload_committed"] is False
    assert "response_body_base64" not in provenance
    assert "payload" not in provenance
