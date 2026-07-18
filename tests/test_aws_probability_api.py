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
