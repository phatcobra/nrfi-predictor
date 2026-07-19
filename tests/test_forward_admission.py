"""Focused tests for forward-capture admission, selection, and assembly."""

from __future__ import annotations

import io
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from nrfi import aws_pregame_collector as collector
from nrfi import forward_admission as admission
from nrfi.pregame_snapshot import canonical_json_bytes

TARGET = date(2026, 7, 19)
T1 = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 7, 19, 15, 0, tzinfo=timezone.utc)
AS_OF = datetime(2026, 7, 19, 16, 0, tzinfo=timezone.utc)
CUTOFF_TEXT = "2026-07-19T23:00:00Z"
BUCKET = "test-lake"
KMS = "arn:aws:kms:us-east-2:111122223333:key/abc"
PROFILES_KEY = "features/pitcher_statcast/strict_prior_v1/profiles.jsonl"


def _payload(*, away_pitcher: int | None, home_pitcher: int | None) -> dict[str, Any]:
    def _side(team_id: int, pitcher: int | None) -> dict[str, Any]:
        side: dict[str, Any] = {"team": {"id": team_id, "name": f"Team {team_id}"}}
        if pitcher is not None:
            side["probablePitcher"] = {"id": pitcher, "fullName": f"P{pitcher}"}
        return side

    return {
        "dates": [
            {
                "games": [
                    {
                        "gamePk": 123,
                        "gameType": "R",
                        "officialDate": TARGET.isoformat(),
                        "gameDate": CUTOFF_TEXT,
                        "doubleHeader": "N",
                        "gameNumber": 1,
                        "status": {"statusCode": "S"},
                        "venue": {"id": 10, "name": "Verified Park"},
                        "teams": {
                            "away": _side(1, away_pitcher),
                            "home": _side(2, home_pitcher),
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


def _capture_bytes(
    tmp_path: Path, name: str, payload: dict[str, Any], moment: datetime
) -> bytes:
    capture = collector.collect_capture(
        TARGET,
        tmp_path / name,
        now=lambda: moment,
        get=lambda *a, **k: _Response(payload),
    )
    return canonical_json_bytes(capture)


class _FakeLakeS3:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = dict(objects)
        self.put_calls: list[dict[str, Any]] = []

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        prefix = kwargs["Prefix"]
        contents = [
            {"Key": key} for key in sorted(self.objects) if key.startswith(prefix)
        ]
        return {"Contents": contents, "IsTruncated": False}

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        key = kwargs["Key"]
        if key not in self.objects:
            raise KeyError(key)
        return {
            "Body": io.BytesIO(self.objects[key]),
            "VersionId": f"v-{abs(hash(key)) % 100000}",
            "ServerSideEncryption": "aws:kms",
        }

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.put_calls.append(kwargs)
        self.objects[kwargs["Key"]] = kwargs["Body"]
        return {"VersionId": f"pv{len(self.put_calls)}"}


def _profiles_jsonl(*pitchers: int, cutoff: str = "2026-07-10T23:00:00Z") -> bytes:
    rows = [
        {
            "pitcher_id": pitcher,
            "prediction_cutoff": cutoff,
            "game_pk": 90000 + pitcher,
            "profile_feature_eligible": True,
            "feature_version": "pitcher-statcast-strict-prior-v1",
            "feature_hash": f"hash-{pitcher}",
            "feature_values": {"strikeout_rate": 0.27},
        }
        for pitcher in pitchers
    ]
    return ("\n".join(json.dumps(row) for row in rows) + "\n").encode("utf-8")


def _forward_key(name: str) -> str:
    return f"{admission.FORWARD_KEY_PREFIX}/{TARGET.isoformat()}/capture-{name}.json"


def test_end_to_end_assembly_selects_latest_and_exposes_lineage(
    tmp_path: Path,
) -> None:
    objects = {
        _forward_key("20260719T120000Z"): _capture_bytes(
            tmp_path, "c1", _payload(away_pitcher=7, home_pitcher=8), T1
        ),
        _forward_key("20260719T150000Z"): _capture_bytes(
            tmp_path, "c2", _payload(away_pitcher=9, home_pitcher=8), T2
        ),
        PROFILES_KEY: _profiles_jsonl(7, 8, 9),
    }
    fake = _FakeLakeS3(objects)

    summary = admission.run_assembly(
        fake,
        BUCKET,
        KMS,
        [TARGET.isoformat()],
        profiles_key=PROFILES_KEY,
        now=lambda: AS_OF,
    )

    result = summary["results"][0]
    assert result["profiles_status"] == "PROFILES_LOADED"
    assert result["admitted_captures"] == 2
    assert result["feature_assembly_eligible_games"] == 1
    stored = fake.put_calls[-1]
    assert stored["ServerSideEncryption"] == "aws:kms"
    assert stored["Key"].startswith(
        f"{admission.ASSEMBLY_KEY_PREFIX}/{TARGET.isoformat()}/assembly-"
    )
    package = json.loads(stored["Body"].decode("utf-8"))
    game = package["games"][0]
    away = game["sides"]["away"]
    assert away["probable_pitcher_id"] == 9
    assert away["starter_observed_at"] == "2026-07-19T15:00:00Z"
    assert [
        (change["from_pitcher_id"], change["to_pitcher_id"])
        for change in away["starter_changes"]
    ] == [(7, 9)]
    assert game["sides"]["home"]["probable_pitcher_id"] == 8
    assert game["eligibility"] == {
        "probable_starter_snapshot": True,
        "pitcher_feature": True,
        "feature_assembly": True,
        "probability": False,
        "market_evaluation": False,
        "wager": False,
    }
    assert game["wager_decision"] == "NO QUALIFIED WAGER"
    assert package["wager_decision"] == "NO QUALIFIED WAGER"
    assert game["sides"]["away"]["capture_key"] == _forward_key("20260719T150000Z")


def test_observation_at_or_after_cutoff_is_never_selected(tmp_path: Path) -> None:
    late = datetime(2026, 7, 19, 23, 30, tzinfo=timezone.utc)
    objects = {
        _forward_key("20260719T233000Z"): _capture_bytes(
            tmp_path, "late", _payload(away_pitcher=7, home_pitcher=8), late
        ),
        PROFILES_KEY: _profiles_jsonl(7, 8),
    }
    fake = _FakeLakeS3(objects)

    summary = admission.run_assembly(
        fake,
        BUCKET,
        KMS,
        [TARGET.isoformat()],
        profiles_key=PROFILES_KEY,
        now=lambda: datetime(2026, 7, 19, 23, 45, tzinfo=timezone.utc),
    )

    package = json.loads(fake.put_calls[-1]["Body"].decode("utf-8"))
    game = package["games"][0]
    assert game["sides"]["away"]["selection_status"] == "NO_ADMISSIBLE_OBSERVATION"
    assert game["eligibility"]["probable_starter_snapshot"] is False
    assert game["eligibility"]["feature_assembly"] is False
    assert "away:NO_ADMISSIBLE_OBSERVATION" in game["rejection_reasons"]
    assert summary["results"][0]["feature_assembly_eligible_games"] == 0


def test_stale_snapshot_fails_freshness_gate(tmp_path: Path) -> None:
    objects = {
        _forward_key("20260719T120000Z"): _capture_bytes(
            tmp_path, "c1", _payload(away_pitcher=7, home_pitcher=8), T1
        ),
        PROFILES_KEY: _profiles_jsonl(7, 8),
    }
    fake = _FakeLakeS3(objects)

    admission.run_assembly(
        fake,
        BUCKET,
        KMS,
        [TARGET.isoformat()],
        profiles_key=PROFILES_KEY,
        now=lambda: datetime(2026, 7, 19, 22, 30, tzinfo=timezone.utc),
        freshness_limit_seconds=3600,
    )

    package = json.loads(fake.put_calls[-1]["Body"].decode("utf-8"))
    game = package["games"][0]
    assert game["eligibility"]["pitcher_feature"] is True
    assert game["eligibility"]["feature_assembly"] is False
    assert "game:SNAPSHOT_STALE" in game["rejection_reasons"]


def test_admission_rejects_malformed_and_tampered_captures(
    tmp_path: Path,
) -> None:
    valid = _capture_bytes(tmp_path, "ok", _payload(away_pitcher=7, home_pitcher=8), T1)
    tampered_doc = json.loads(valid.decode("utf-8"))
    tampered_doc["rows"][0]["probable_pitcher_id"] = 999
    no_timestamp_doc = json.loads(valid.decode("utf-8"))
    del no_timestamp_doc["retrieved_at"]
    wrong_schema_doc = json.loads(valid.decode("utf-8"))
    wrong_schema_doc["schema_version"] = "unexpected.v9"
    locked_doc = {
        "schema_version": admission.CAPTURE_SCHEMA_VERSION,
        "target_date": "2025-07-19",
    }
    objects = {
        _forward_key("a-malformed"): b"{not json",
        _forward_key("b-schema"): canonical_json_bytes(wrong_schema_doc),
        _forward_key("c-tampered"): canonical_json_bytes(tampered_doc),
        _forward_key("d-notime"): canonical_json_bytes(no_timestamp_doc),
        _forward_key("e-locked"): canonical_json_bytes(locked_doc),
        _forward_key("f-valid"): valid,
    }
    fake = _FakeLakeS3(objects)

    admissions = [
        admission.read_capture(fake, BUCKET, key)
        for key in admission.list_forward_capture_keys(fake, BUCKET, TARGET.isoformat())
    ]

    by_key = {item["key"]: item for item in admissions}
    assert by_key[_forward_key("a-malformed")]["reason"] == "MALFORMED_CAPTURE"
    assert by_key[_forward_key("b-schema")]["reason"] == "UNKNOWN_CAPTURE_SCHEMA"
    assert by_key[_forward_key("c-tampered")]["reason"] == "CAPTURE_IDENTITY_MISMATCH"
    assert by_key[_forward_key("d-notime")]["reason"] == "MISSING_OBSERVATION_TIMESTAMP"
    assert by_key[_forward_key("e-locked")]["reason"] == "LOCKED_HOLDOUT_RECORD"
    assert by_key[_forward_key("f-valid")]["status"] == "ADMITTED"
    assert by_key[_forward_key("f-valid")]["rows_admitted"] == 2


def test_missing_profiles_object_is_recorded_fail_closed(tmp_path: Path) -> None:
    objects = {
        _forward_key("20260719T120000Z"): _capture_bytes(
            tmp_path, "c1", _payload(away_pitcher=7, home_pitcher=8), T1
        ),
    }
    fake = _FakeLakeS3(objects)

    summary = admission.run_assembly(
        fake,
        BUCKET,
        KMS,
        [TARGET.isoformat()],
        profiles_key=PROFILES_KEY,
        now=lambda: AS_OF,
    )

    result = summary["results"][0]
    assert result["profiles_status"] == "PROFILES_UNAVAILABLE"
    assert result["games"] == 0
    package = json.loads(fake.put_calls[-1]["Body"].decode("utf-8"))
    assert package["profiles_status"] == "PROFILES_UNAVAILABLE"
    assert package["games"] == []
    assert package["admitted_captures"] == 1
    assert package["wager_decision"] == "NO QUALIFIED WAGER"


def test_profiles_loader_sorts_and_blocks_holdout() -> None:
    rows = [
        {"pitcher_id": 7, "prediction_cutoff": "2024-06-02T00:00:00Z", "game_pk": 2},
        {"pitcher_id": 7, "prediction_cutoff": "2024-06-01T00:00:00Z", "game_pk": 1},
    ]
    text = "\n".join(json.dumps(row) for row in rows)

    profiles = admission.load_profiles_jsonl(text)

    assert [row["game_pk"] for row in profiles[7]] == [1, 2]

    with pytest.raises(admission.ForwardAdmissionError):
        admission.load_profiles_jsonl(
            json.dumps(
                {
                    "pitcher_id": 7,
                    "prediction_cutoff": "2025-04-01T00:00:00Z",
                    "game_pk": 3,
                }
            )
        )


def test_run_assembly_refuses_locked_holdout_date() -> None:
    with pytest.raises(admission.ForwardAdmissionError):
        admission.run_assembly(
            _FakeLakeS3({}),
            BUCKET,
            KMS,
            ["2025-07-19"],
            profiles_key=PROFILES_KEY,
        )


def test_locked_2025_gap_is_flagged_without_erasing_career_history(
    tmp_path: Path,
) -> None:
    objects = {
        _forward_key("20260719T120000Z"): _capture_bytes(
            tmp_path, "c1", _payload(away_pitcher=7, home_pitcher=8), T1
        ),
        PROFILES_KEY: _profiles_jsonl(7, 8, cutoff="2024-09-01T18:00:00Z"),
    }
    fake = _FakeLakeS3(objects)

    summary = admission.run_assembly(
        fake,
        BUCKET,
        KMS,
        [TARGET.isoformat()],
        profiles_key=PROFILES_KEY,
        now=lambda: AS_OF,
    )

    package = json.loads(fake.put_calls[-1]["Body"].decode("utf-8"))
    game = package["games"][0]
    for side in ("away", "home"):
        assert game["sides"][side]["feature_status"] == "READY"
        assert game["sides"][side]["profile_history_gap_seasons"] == 1
        assert game["sides"][side]["profile_recent_history_missing"] is True
    assert game["eligibility"]["pitcher_feature"] is True
    assert game["eligibility"]["feature_assembly"] is True
    assert game["eligibility"]["probability"] is False
    assert game["probability_ineligibility_reasons"] == [
        "APPROVED_MODEL_UNAVAILABLE",
        "PREDICTIVE_SKILL_NOT_ESTABLISHED",
    ]
    assert game["wager_decision"] == "NO QUALIFIED WAGER"
    assert summary["results"][0]["feature_assembly_eligible_games"] == 1
