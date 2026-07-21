"""Fail-closed Lambda response for the sanitized NRFI/YRFI probability object."""

from __future__ import annotations

import importlib
import json
import math
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

from nrfi.aws_pregame_collector import market_today
from nrfi.forward_admission import ASSEMBLY_KEY_PREFIX, WAGER_DECISION

PROBABILITY_OBJECT_KEY = "signals/sanitized/current/probability-response.json"
PACKAGE_SCHEMA_VERSION = "pregame_assembly_package.v1"
PRESERVED_RESPONSE_CLASS = "preserved-baseline-not-current-inference"
MAX_RESPONSE_BYTES = 16_384
MAX_ASSEMBLY_BYTES = 8_388_608
LOCKED_HOLDOUT_SEASON = 2025
COMPLEMENT_TOLERANCE = 1e-12
RESPONSE_KEYS = frozenset({"p_nrfi", "p_yrfi", "uncertainty"})
UNCERTAINTY_KEYS = frozenset(
    {"lower_95", "method", "replicates", "standard_error", "upper_95"}
)


class InvalidProbabilityResponse(ValueError):
    """Raised when the sanitized object violates its response contract."""


class InvalidGameRequest(ValueError):
    """Raised when a game-status request fails validation."""


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


def _runtime_bucket() -> str:
    bucket = os.environ.get("NRFI_LAKE_BUCKET", "")
    if not bucket or os.environ.get("NRFI_LOCKED_HOLDOUT_ACCESS") != "DENIED":
        raise InvalidProbabilityResponse("runtime boundary is not configured")
    return bucket


def _s3_client() -> Any:
    return getattr(importlib.import_module("boto3"), "client")("s3")


def _read_probability_response() -> dict[str, Any]:
    bucket = _runtime_bucket()
    response = _s3_client().get_object(
        Bucket=bucket,
        Key=PROBABILITY_OBJECT_KEY,
    )
    payload = response["Body"].read(MAX_RESPONSE_BYTES + 1)
    if len(payload) > MAX_RESPONSE_BYTES:
        raise InvalidProbabilityResponse("response object is too large")
    return _validate_probability_response(json.loads(payload.decode("utf-8")))


def _response(
    status_code: int,
    body: dict[str, Any],
    *,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    headers = {
        "content-type": "application/json",
        "cache-control": "no-store",
    }
    if extra_headers:
        headers.update(extra_headers)
    return {
        "statusCode": status_code,
        "headers": headers,
        "body": json.dumps(body, sort_keys=True, separators=(",", ":")),
    }


def _latest_assembly_key(s3_client: Any, bucket: str, official_date: str) -> str | None:
    prefix = f"{ASSEMBLY_KEY_PREFIX}/{official_date}/"
    latest: str | None = None
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        page = s3_client.list_objects_v2(**kwargs)
        for item in page.get("Contents", []):
            key = item.get("Key")
            if isinstance(key, str) and key.endswith(".json"):
                if latest is None or key > latest:
                    latest = key
        if not page.get("IsTruncated"):
            break
        token = page.get("NextContinuationToken")
    return latest


def _read_assembly_package(s3_client: Any, bucket: str, key: str) -> dict[str, Any]:
    response = s3_client.get_object(Bucket=bucket, Key=key)
    payload = response["Body"].read(MAX_ASSEMBLY_BYTES + 1)
    if len(payload) > MAX_ASSEMBLY_BYTES:
        raise InvalidProbabilityResponse("assembly package is too large")
    package = json.loads(payload.decode("utf-8"))
    if (
        not isinstance(package, dict)
        or package.get("schema_version") != PACKAGE_SCHEMA_VERSION
        or package.get("locked_2025_holdout_accessed") is not False
    ):
        raise InvalidProbabilityResponse("assembly package violates its contract")
    return package


def _parse_game_request(params: dict[str, Any]) -> tuple[int, str | None]:
    raw_game_pk = str(params.get("game_pk", ""))
    if not raw_game_pk.isdigit() or not 1 <= len(raw_game_pk) <= 10:
        raise InvalidGameRequest("INVALID_GAME_PK")
    game_pk = int(raw_game_pk)
    if game_pk <= 0:
        raise InvalidGameRequest("INVALID_GAME_PK")
    raw_date = params.get("date")
    if raw_date is None:
        return game_pk, None
    try:
        requested = date.fromisoformat(str(raw_date))
    except ValueError as error:
        raise InvalidGameRequest("INVALID_DATE") from error
    if requested.year == LOCKED_HOLDOUT_SEASON:
        raise InvalidGameRequest("LOCKED_HOLDOUT_RECORD")
    return game_pk, requested.isoformat()


def _game_assembly_response(game_pk: int, requested_date: str | None) -> dict[str, Any]:
    bucket = _runtime_bucket()
    s3_client = _s3_client()
    if requested_date is not None:
        dates = [requested_date]
    else:
        base = market_today(datetime.now(timezone.utc))
        dates = [base.isoformat(), (base + timedelta(days=1)).isoformat()]

    packages_seen: list[dict[str, Any]] = []
    for official_date in dates:
        key = _latest_assembly_key(s3_client, bucket, official_date)
        if key is None:
            continue
        package = _read_assembly_package(s3_client, bucket, key)
        package_meta = {
            "key": key,
            "package_id": package.get("package_id"),
            "generated_at": package.get("generated_at"),
            "profiles_status": package.get("profiles_status"),
            "batter_profiles_status": package.get("batter_profiles_status"),
            "batter_profile_identity": package.get("batter_profile_identity"),
            "team_profiles_status": package.get("team_profiles_status"),
            "team_profile_identity": package.get("team_profile_identity"),
            "official_date": official_date,
        }
        game = next(
            (
                item
                for item in package.get("games", [])
                if item.get("game_pk") == game_pk
            ),
            None,
        )
        if game is not None:
            return _response(
                200,
                {
                    "response_class": "game-assembly-status",
                    "requested_game_pk": game_pk,
                    "assembly_package": package_meta,
                    "game": game,
                    "wager_decision": WAGER_DECISION,
                },
            )
        packages_seen.append(package_meta)

    if packages_seen:
        return _response(
            404,
            {
                "error": "game_not_found",
                "requested_game_pk": game_pk,
                "searched_dates": dates,
                "packages": packages_seen,
                "wager_decision": WAGER_DECISION,
            },
        )
    return _response(
        200,
        {
            "response_class": "game-assembly-status",
            "assembly_status": "ASSEMBLY_UNAVAILABLE",
            "requested_game_pk": game_pk,
            "searched_dates": dates,
            "reasons": ["NO_ASSEMBLY_PACKAGE_FOR_DATE"],
            "wager_decision": WAGER_DECISION,
        },
    )


def lambda_handler(event: Any, context: Any) -> dict[str, Any]:
    """Serve the preserved baseline or a real game-specific assembly status."""
    del context
    try:
        method = event["requestContext"]["http"]["method"]
    except (KeyError, TypeError):
        method = None
    if method != "GET":
        return _response(405, {"error": "request_failed"})

    params: dict[str, Any] = {}
    if isinstance(event, dict):
        raw_params = event.get("queryStringParameters")
        if isinstance(raw_params, dict):
            params = raw_params

    try:
        if "game_pk" in params:
            try:
                game_pk, requested_date = _parse_game_request(params)
            except InvalidGameRequest as error:
                return _response(
                    400,
                    {
                        "error": "invalid_request",
                        "reasons": [str(error)],
                        "wager_decision": WAGER_DECISION,
                    },
                )
            return _game_assembly_response(game_pk, requested_date)
        return _response(
            200,
            _read_probability_response(),
            extra_headers={"x-nrfi-response-class": PRESERVED_RESPONSE_CLASS},
        )
    except Exception:
        return _response(500, {"error": "request_failed"})
