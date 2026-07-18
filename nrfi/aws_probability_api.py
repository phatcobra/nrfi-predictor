"""Fail-closed Lambda response for the sanitized NRFI/YRFI probability object."""

from __future__ import annotations

import importlib
import json
import math
import os
from typing import Any

PROBABILITY_OBJECT_KEY = "signals/sanitized/current/probability-response.json"
MAX_RESPONSE_BYTES = 16_384
COMPLEMENT_TOLERANCE = 1e-12
RESPONSE_KEYS = frozenset({"p_nrfi", "p_yrfi", "uncertainty"})
UNCERTAINTY_KEYS = frozenset(
    {"lower_95", "method", "replicates", "standard_error", "upper_95"}
)


class InvalidProbabilityResponse(ValueError):
    """Raised when the sanitized object violates its response contract."""


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidProbabilityResponse(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise InvalidProbabilityResponse(f"{name} must be finite")
    return number


def _validate_probability_response(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != RESPONSE_KEYS:
        raise InvalidProbabilityResponse("response keys differ")

    p_nrfi = _finite_number(value["p_nrfi"], "p_nrfi")
    p_yrfi = _finite_number(value["p_yrfi"], "p_yrfi")
    if not 0.0 <= p_nrfi <= 1.0 or not 0.0 <= p_yrfi <= 1.0:
        raise InvalidProbabilityResponse("probability outside [0, 1]")
    if not math.isclose(
        p_nrfi + p_yrfi,
        1.0,
        rel_tol=0.0,
        abs_tol=COMPLEMENT_TOLERANCE,
    ):
        raise InvalidProbabilityResponse("probabilities are not complementary")

    uncertainty = value["uncertainty"]
    if not isinstance(uncertainty, dict) or set(uncertainty) != UNCERTAINTY_KEYS:
        raise InvalidProbabilityResponse("uncertainty keys differ")
    lower = _finite_number(uncertainty["lower_95"], "uncertainty.lower_95")
    upper = _finite_number(uncertainty["upper_95"], "uncertainty.upper_95")
    standard_error = _finite_number(
        uncertainty["standard_error"], "uncertainty.standard_error"
    )
    replicates = uncertainty["replicates"]
    method = uncertainty["method"]
    if not 0.0 <= lower <= p_nrfi <= upper <= 1.0:
        raise InvalidProbabilityResponse("uncertainty bounds are invalid")
    if standard_error < 0.0:
        raise InvalidProbabilityResponse("uncertainty standard error is invalid")
    if (
        isinstance(replicates, bool)
        or not isinstance(replicates, int)
        or replicates < 1
    ):
        raise InvalidProbabilityResponse("uncertainty replicates are invalid")
    if not isinstance(method, str) or not method or len(method) > 128:
        raise InvalidProbabilityResponse("uncertainty method is invalid")

    return {
        "p_nrfi": p_nrfi,
        "p_yrfi": p_yrfi,
        "uncertainty": {
            "lower_95": lower,
            "method": method,
            "replicates": replicates,
            "standard_error": standard_error,
            "upper_95": upper,
        },
    }


def _read_probability_response() -> dict[str, Any]:
    bucket = os.environ.get("NRFI_LAKE_BUCKET", "")
    if not bucket or os.environ.get("NRFI_LOCKED_HOLDOUT_ACCESS") != "DENIED":
        raise InvalidProbabilityResponse("runtime boundary is not configured")

    boto3_client = getattr(importlib.import_module("boto3"), "client")
    response = boto3_client("s3").get_object(
        Bucket=bucket,
        Key=PROBABILITY_OBJECT_KEY,
    )
    payload = response["Body"].read(MAX_RESPONSE_BYTES + 1)
    if len(payload) > MAX_RESPONSE_BYTES:
        raise InvalidProbabilityResponse("response object is too large")
    return _validate_probability_response(json.loads(payload.decode("utf-8")))


def _response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "content-type": "application/json",
            "cache-control": "no-store",
        },
        "body": json.dumps(body, sort_keys=True, separators=(",", ":")),
    }


def lambda_handler(event: Any, context: Any) -> dict[str, Any]:
    """Return the sanitized probability response for an authenticated GET."""
    del context
    try:
        method = event["requestContext"]["http"]["method"]
    except (KeyError, TypeError):
        method = None
    if method != "GET":
        return _response(405, {"error": "request_failed"})

    try:
        return _response(200, _read_probability_response())
    except Exception:
        return _response(500, {"error": "request_failed"})
