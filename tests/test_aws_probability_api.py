"""Focused tests for the fail-closed AWS probability response Lambda."""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

from nrfi import aws_probability_api as api


VALID_RESPONSE = {
    "p_nrfi": 0.511138831136253,
    "p_yrfi": 0.4888611688637469,
    "uncertainty": {
        "lower_95": 0.4164458332468519,
        "method": "official-date-cluster-model-bootstrap-v1",
        "replicates": 32,
        "standard_error": 0.03987121250858687,
        "upper_95": 0.5626698522933542,
    },
}


class FakeS3:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get_object(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.payload, Exception):
            raise self.payload
        return {"Body": io.BytesIO(self.payload)}


def _event(method="GET"):
    return {"requestContext": {"http": {"method": method}}}


def _configure(monkeypatch, payload):
    client = FakeS3(payload)
    monkeypatch.setenv("NRFI_LAKE_BUCKET", "sanitized-lake")
    monkeypatch.setenv("NRFI_LOCKED_HOLDOUT_ACCESS", "DENIED")
    runtime_boto3 = SimpleNamespace(client=lambda service: client)
    monkeypatch.setattr(
        api.importlib,
        "import_module",
        lambda name: runtime_boto3 if name == "boto3" else None,
    )
    return client


def test_get_returns_only_validated_probability_and_uncertainty(monkeypatch):
    payload = json.dumps(VALID_RESPONSE).encode()
    client = _configure(monkeypatch, payload)

    response = api.lambda_handler(_event(), None)

    assert response["statusCode"] == 200
    assert response["headers"]["cache-control"] == "no-store"
    assert json.loads(response["body"]) == VALID_RESPONSE
    assert client.calls == [
        {
            "Bucket": "sanitized-lake",
            "Key": api.PROBABILITY_OBJECT_KEY,
        }
    ]


def test_committed_sanitized_artifact_matches_response_contract():
    artifact = (
        Path(__file__).resolve().parents[1]
        / "terraform"
        / "assets"
        / "probability-response.json"
    )

    assert json.loads(artifact.read_text(encoding="utf-8")) == VALID_RESPONSE
    assert api._validate_probability_response(VALID_RESPONSE) == VALID_RESPONSE


def test_non_get_request_fails_without_reading_s3(monkeypatch):
    client = _configure(monkeypatch, json.dumps(VALID_RESPONSE).encode())

    response = api.lambda_handler(_event("POST"), None)

    assert response["statusCode"] == 405
    assert json.loads(response["body"]) == {"error": "request_failed"}
    assert client.calls == []


def test_invalid_probability_values_fail_closed(monkeypatch):
    for invalid in (
        {**VALID_RESPONSE, "p_nrfi": float("nan")},
        {**VALID_RESPONSE, "p_nrfi": 0.6},
        {**VALID_RESPONSE, "p_nrfi": 1.1, "p_yrfi": -0.1},
        {**VALID_RESPONSE, "unexpected": "field"},
    ):
        _configure(monkeypatch, json.dumps(invalid).encode())
        response = api.lambda_handler(_event(), None)
        assert response["statusCode"] == 500
        assert json.loads(response["body"]) == {"error": "request_failed"}


def test_invalid_uncertainty_fails_closed(monkeypatch):
    invalid = json.loads(json.dumps(VALID_RESPONSE))
    invalid["uncertainty"]["lower_95"] = 0.9
    _configure(monkeypatch, json.dumps(invalid).encode())

    response = api.lambda_handler(_event(), None)

    assert response["statusCode"] == 500
    assert json.loads(response["body"]) == {"error": "request_failed"}


def test_oversized_object_fails_closed(monkeypatch):
    _configure(monkeypatch, b"x" * (api.MAX_RESPONSE_BYTES + 1))

    response = api.lambda_handler(_event(), None)

    assert response["statusCode"] == 500
    assert json.loads(response["body"]) == {"error": "request_failed"}


def test_runtime_boundary_and_s3_errors_are_generic(monkeypatch):
    client = _configure(monkeypatch, RuntimeError("private provider detail"))
    response = api.lambda_handler(_event(), None)
    assert response["statusCode"] == 500
    assert response["body"] == '{"error":"request_failed"}'
    assert "private provider detail" not in response["body"]

    monkeypatch.setenv("NRFI_LOCKED_HOLDOUT_ACCESS", "ALLOWED")
    response = api.lambda_handler(_event(), None)
    assert response["statusCode"] == 500
    assert client.calls == [
        {"Bucket": "sanitized-lake", "Key": api.PROBABILITY_OBJECT_KEY}
    ]


class FakeAssemblyS3:
    def __init__(self, objects):
        self.objects = dict(objects)
        self.calls = []

    def list_objects_v2(self, **kwargs):
        prefix = kwargs["Prefix"]
        contents = [
            {"Key": key} for key in sorted(self.objects) if key.startswith(prefix)
        ]
        return {"Contents": contents, "IsTruncated": False}

    def get_object(self, **kwargs):
        self.calls.append(kwargs)
        return {"Body": io.BytesIO(self.objects[kwargs["Key"]])}


def _assembly_package(game_pk=745, official_date="2026-07-19"):
    return {
        "schema_version": api.PACKAGE_SCHEMA_VERSION,
        "official_date": official_date,
        "generated_at": "2026-07-19T16:00:00Z",
        "profiles_status": "PROFILES_LOADED",
        "package_id": "pkg-1",
        "locked_2025_holdout_accessed": False,
        "games": [
            {
                "game_pk": game_pk,
                "eligibility": {
                    "probable_starter_eligible": True,
                    "pitcher_profile_eligible": True,
                    "unified_feature_set_eligible": False,
                    "model_probability_eligible": False,
                    "market_eligible": False,
                    "wager_eligible": False,
                },
                "wager_decision": "NO QUALIFIED WAGER",
            }
        ],
        "wager_decision": "NO QUALIFIED WAGER",
    }


def _configure_assembly(monkeypatch, objects):
    client = FakeAssemblyS3(objects)
    monkeypatch.setenv("NRFI_LAKE_BUCKET", "sanitized-lake")
    monkeypatch.setenv("NRFI_LOCKED_HOLDOUT_ACCESS", "DENIED")
    runtime_boto3 = SimpleNamespace(client=lambda service: client)
    monkeypatch.setattr(
        api.importlib,
        "import_module",
        lambda name: runtime_boto3 if name == "boto3" else None,
    )
    return client


def _game_event(game_pk="745", date_value="2026-07-19"):
    return {
        "requestContext": {"http": {"method": "GET"}},
        "queryStringParameters": {"game_pk": game_pk, "date": date_value},
    }


def test_root_response_is_marked_preserved_not_current(monkeypatch):
    _configure(monkeypatch, json.dumps(VALID_RESPONSE).encode())

    response = api.lambda_handler(_event(), None)

    assert response["statusCode"] == 200
    assert response["headers"]["x-nrfi-response-class"] == api.PRESERVED_RESPONSE_CLASS
    assert json.loads(response["body"]) == VALID_RESPONSE


def test_game_query_returns_real_assembly_status(monkeypatch):
    key = f"{api.ASSEMBLY_KEY_PREFIX}/2026-07-19/assembly-20260719T160000Z.json"
    package = _assembly_package()
    _configure_assembly(
        monkeypatch,
        {key: json.dumps(package).encode("utf-8")},
    )

    response = api.lambda_handler(_game_event(), None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["response_class"] == "game-assembly-status"
    assert body["requested_game_pk"] == 745
    assert body["assembly_package"]["key"] == key
    assert body["game"]["eligibility"]["model_probability_eligible"] is False
    assert body["game"]["eligibility"]["unified_feature_set_eligible"] is False
    assert body["wager_decision"] == "NO QUALIFIED WAGER"


def test_game_query_prefers_latest_assembly_package(monkeypatch):
    older = f"{api.ASSEMBLY_KEY_PREFIX}/2026-07-19/assembly-20260719T120000Z.json"
    newer = f"{api.ASSEMBLY_KEY_PREFIX}/2026-07-19/assembly-20260719T160000Z.json"
    old_package = _assembly_package()
    old_package["package_id"] = "pkg-old"
    _configure_assembly(
        monkeypatch,
        {
            older: json.dumps(old_package).encode("utf-8"),
            newer: json.dumps(_assembly_package()).encode("utf-8"),
        },
    )

    response = api.lambda_handler(_game_event(), None)

    assert json.loads(response["body"])["assembly_package"]["key"] == newer


def test_unknown_game_is_explicit_not_found(monkeypatch):
    key = f"{api.ASSEMBLY_KEY_PREFIX}/2026-07-19/assembly-20260719T160000Z.json"
    _configure_assembly(
        monkeypatch,
        {key: json.dumps(_assembly_package(game_pk=1)).encode("utf-8")},
    )

    response = api.lambda_handler(_game_event(), None)

    assert response["statusCode"] == 404
    body = json.loads(response["body"])
    assert body["error"] == "game_not_found"
    assert body["searched_dates"] == ["2026-07-19"]
    assert body["wager_decision"] == "NO QUALIFIED WAGER"


def test_missing_assembly_package_fails_closed_with_reason(monkeypatch):
    _configure_assembly(monkeypatch, {})

    response = api.lambda_handler(_game_event(), None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["assembly_status"] == "ASSEMBLY_UNAVAILABLE"
    assert body["reasons"] == ["NO_ASSEMBLY_PACKAGE_FOR_DATE"]
    assert body["wager_decision"] == "NO QUALIFIED WAGER"


def test_invalid_and_locked_game_requests_are_rejected(monkeypatch):
    _configure_assembly(monkeypatch, {})

    invalid = api.lambda_handler(_game_event(game_pk="not-a-number"), None)
    assert invalid["statusCode"] == 400
    assert json.loads(invalid["body"])["reasons"] == ["INVALID_GAME_PK"]

    locked = api.lambda_handler(_game_event(date_value="2025-07-19"), None)
    assert locked["statusCode"] == 400
    body = json.loads(locked["body"])
    assert body["reasons"] == ["LOCKED_HOLDOUT_RECORD"]
    assert body["wager_decision"] == "NO QUALIFIED WAGER"
