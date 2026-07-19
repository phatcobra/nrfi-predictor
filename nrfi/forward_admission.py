"""Admit forward probable-starter captures into the shared point-in-time path."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping

from nrfi.pregame_snapshot import (
    SNAPSHOT_SCHEMA_VERSION,
    canonical_json_bytes,
    join_pitcher_profiles_from_profiles,
)

FORWARD_KEY_PREFIX = "signals/pregame/official-statsapi/forward"
ASSEMBLY_KEY_PREFIX = "signals/pregame/assembly"
CAPTURE_SCHEMA_VERSION = "forward_probable_starter_capture.v1"
ASSEMBLY_SCHEMA_VERSION = "pregame_game_assembly.v1"
PACKAGE_SCHEMA_VERSION = "pregame_assembly_package.v1"
PROFILE_TABLE_SCHEMA = "pitcher-statcast-strict-prior-v1"
LOCKED_HOLDOUT_SEASON = 2025
MAX_CAPTURE_BYTES = 4_194_304
DEFAULT_FRESHNESS_LIMIT_SECONDS = 21_600
WAGER_DECISION = "NO QUALIFIED WAGER"

REJECT_MALFORMED = "MALFORMED_CAPTURE"
REJECT_UNKNOWN_SCHEMA = "UNKNOWN_CAPTURE_SCHEMA"
REJECT_MISSING_TIMESTAMP = "MISSING_OBSERVATION_TIMESTAMP"
REJECT_LOCKED_HOLDOUT = "LOCKED_HOLDOUT_RECORD"
REJECT_MISSING_CHECKSUM = "MISSING_SOURCE_CHECKSUM"
REJECT_RAW_PAYLOAD = "RAW_PAYLOAD_MARKED_UPLOADED"
REJECT_IDENTITY_MISMATCH = "CAPTURE_IDENTITY_MISMATCH"
REJECT_ROW_SCHEMA = "UNKNOWN_SNAPSHOT_ROW_SCHEMA"
REJECT_AMBIGUOUS_GAME = "AMBIGUOUS_GAME_IDENTITY"
REJECT_AMBIGUOUS_TEAM = "AMBIGUOUS_TEAM_IDENTITY"
REJECT_INCONSISTENT_TIME = "INCONSISTENT_OBSERVATION_TIME"


class ForwardAdmissionError(ValueError):
    """Raised when the admission path violates its fail-closed contract."""


def _identity(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise ForwardAdmissionError("required timestamp is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ForwardAdmissionError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _integer(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if not isinstance(value, (str, int, float)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def list_forward_capture_keys(
    s3_client: Any, bucket: str, official_date: str
) -> list[str]:
    """List every preserved capture key for one date in deterministic order."""
    prefix = f"{FORWARD_KEY_PREFIX}/{official_date}/"
    keys: list[str] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        page = s3_client.list_objects_v2(**kwargs)
        for item in page.get("Contents", []):
            key = item.get("Key")
            if isinstance(key, str) and key.endswith(".json"):
                keys.append(key)
        if not page.get("IsTruncated"):
            break
        token = page.get("NextContinuationToken")
    return sorted(keys)


def _validate_capture_rows(
    capture: Mapping[str, Any], target_date: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    admitted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    retrieved_at = capture["retrieved_at"]
    rows = capture.get("rows")
    if not isinstance(rows, list):
        raise ForwardAdmissionError(REJECT_MALFORMED)
    for row in rows:
        if not isinstance(row, Mapping):
            rejected.append({"reason": REJECT_MALFORMED})
            continue
        game_pk = _integer(row.get("game_pk"))
        side = row.get("side")
        reason = None
        if row.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
            reason = REJECT_ROW_SCHEMA
        elif game_pk is None or game_pk <= 0 or side not in ("away", "home"):
            reason = REJECT_AMBIGUOUS_GAME
        elif (game_pk, str(side)) in seen:
            reason = REJECT_AMBIGUOUS_GAME
        elif str(row.get("official_date")) != target_date:
            reason = REJECT_AMBIGUOUS_GAME
        elif str(row.get("official_date")).startswith(str(LOCKED_HOLDOUT_SEASON)):
            reason = REJECT_LOCKED_HOLDOUT
        elif _integer(row.get("team_id")) is None:
            reason = REJECT_AMBIGUOUS_TEAM
        elif row.get("probable_starter_observed_at") != retrieved_at:
            reason = REJECT_INCONSISTENT_TIME
        else:
            try:
                cutoff = _parse_utc(row.get("prediction_cutoff"))
                _parse_utc(row.get("scheduled_start_at"))
            except ForwardAdmissionError:
                reason = REJECT_MISSING_TIMESTAMP
            else:
                if cutoff.year == LOCKED_HOLDOUT_SEASON:
                    reason = REJECT_LOCKED_HOLDOUT
        if reason is None:
            seen.add((int(game_pk or 0), str(side)))
            admitted.append(dict(row))
        else:
            rejected.append({"game_pk": game_pk, "side": side, "reason": reason})
    return admitted, rejected


def read_capture(s3_client: Any, bucket: str, key: str) -> dict[str, Any]:
    """Read one capture object and admit or reject it with explicit reasons."""
    admission: dict[str, Any] = {
        "key": key,
        "status": "REJECTED",
        "reason": None,
        "version_id": None,
        "server_side_encryption": None,
        "observed_at": None,
        "target_date": None,
        "response_sha256": None,
        "rows_admitted": 0,
        "row_rejections": [],
        "rows": [],
    }
    response = s3_client.get_object(Bucket=bucket, Key=key)
    admission["version_id"] = response.get("VersionId")
    admission["server_side_encryption"] = response.get("ServerSideEncryption")
    payload = response["Body"].read(MAX_CAPTURE_BYTES + 1)
    if len(payload) > MAX_CAPTURE_BYTES:
        admission["reason"] = REJECT_MALFORMED
        return admission
    try:
        capture = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        admission["reason"] = REJECT_MALFORMED
        return admission
    if not isinstance(capture, dict):
        admission["reason"] = REJECT_MALFORMED
        return admission
    if capture.get("schema_version") != CAPTURE_SCHEMA_VERSION:
        admission["reason"] = REJECT_UNKNOWN_SCHEMA
        return admission

    target_date = str(capture.get("target_date") or "")
    admission["target_date"] = target_date or None
    if target_date.startswith(str(LOCKED_HOLDOUT_SEASON)):
        admission["reason"] = REJECT_LOCKED_HOLDOUT
        return admission
    if capture.get("locked_2025_holdout_accessed") is not False:
        admission["reason"] = REJECT_LOCKED_HOLDOUT
        return admission
    if capture.get("raw_source_payload_uploaded") is not False:
        admission["reason"] = REJECT_RAW_PAYLOAD
        return admission
    try:
        observed = _parse_utc(capture.get("retrieved_at"))
    except ForwardAdmissionError:
        admission["reason"] = REJECT_MISSING_TIMESTAMP
        return admission
    admission["observed_at"] = _utc_text(observed)

    sha = capture.get("response_sha256")
    if (
        not isinstance(sha, str)
        or len(sha) != 64
        or any(char not in "0123456789abcdef" for char in sha)
    ):
        admission["reason"] = REJECT_MISSING_CHECKSUM
        return admission
    admission["response_sha256"] = sha

    rows = capture.get("rows")
    if not isinstance(rows, list) or capture.get("row_count") != len(rows):
        admission["reason"] = REJECT_IDENTITY_MISMATCH
        return admission
    if capture.get("snapshot_identity") != _identity(rows):
        admission["reason"] = REJECT_IDENTITY_MISMATCH
        return admission

    try:
        admitted_rows, row_rejections = _validate_capture_rows(capture, target_date)
    except ForwardAdmissionError as error:
        admission["reason"] = str(error)
        return admission
    admission["rows"] = admitted_rows
    admission["rows_admitted"] = len(admitted_rows)
    admission["row_rejections"] = row_rejections
    admission["status"] = "ADMITTED"
    return admission


def build_observation_history(
    admissions: Iterable[Mapping[str, Any]],
) -> dict[tuple[int, str], list[dict[str, Any]]]:
    """Preserve every admitted observation per game side in observed order."""
    history: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for admission in admissions:
        if admission.get("status") != "ADMITTED":
            continue
        for row in admission.get("rows", []):
            observation = {
                "row": dict(row),
                "observed_at": str(row["probable_starter_observed_at"]),
                "pitcher_id": _integer(row.get("probable_pitcher_id")),
                "pitcher_name": row.get("probable_pitcher_name"),
                "snapshot_id": row.get("snapshot_id"),
                "capture_key": admission["key"],
                "capture_version_id": admission.get("version_id"),
                "response_sha256": admission.get("response_sha256"),
            }
            key = (int(row["game_pk"]), str(row["side"]))
            history.setdefault(key, []).append(observation)
    for observations in history.values():
        observations.sort(key=lambda item: (item["observed_at"], item["capture_key"]))
    return history


def _starter_changes(
    observations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    previous: int | None = None
    for index, observation in enumerate(observations):
        current = observation["pitcher_id"]
        if index > 0 and current != previous:
            changes.append(
                {
                    "observed_at": observation["observed_at"],
                    "from_pitcher_id": previous,
                    "to_pitcher_id": current,
                    "capture_key": observation["capture_key"],
                }
            )
        previous = current
    return changes


def select_starters(
    history: Mapping[tuple[int, str], list[dict[str, Any]]],
    *,
    as_of: datetime | None = None,
) -> dict[tuple[int, str], dict[str, Any]]:
    """Select the latest admissible observation before each prediction cutoff."""
    selections: dict[tuple[int, str], dict[str, Any]] = {}
    for key, observations in history.items():
        cutoff = _parse_utc(observations[-1]["row"]["prediction_cutoff"])
        admissible = [
            observation
            for observation in observations
            if _parse_utc(observation["observed_at"]) < cutoff
            and (as_of is None or _parse_utc(observation["observed_at"]) <= as_of)
        ]
        selected = admissible[-1] if admissible else None
        if selected is None:
            status = "NO_ADMISSIBLE_OBSERVATION"
        elif selected["pitcher_id"] is None:
            status = "PROBABLE_STARTER_MISSING"
        else:
            status = "SELECTED"
        selections[key] = {
            "selection_status": status,
            "selected": selected,
            "prediction_cutoff": _utc_text(cutoff),
            "observation_count": len(observations),
            "starter_changes": _starter_changes(observations),
        }
    return selections


def load_profiles_jsonl(text: str) -> dict[int, list[dict[str, Any]]]:
    """Load the strict-prior profile table from its JSONL projection."""
    grouped: dict[int, list[dict[str, Any]]] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ForwardAdmissionError(
                f"profile line {line_number} is malformed"
            ) from error
        if not isinstance(row, Mapping):
            raise ForwardAdmissionError(f"profile line {line_number} is malformed")
        pitcher_id = _integer(row.get("pitcher_id"))
        cutoff = row.get("prediction_cutoff")
        if pitcher_id is None or not isinstance(cutoff, str) or not cutoff:
            raise ForwardAdmissionError(
                f"profile line {line_number} lacks identity or cutoff"
            )
        if _parse_utc(cutoff).year == LOCKED_HOLDOUT_SEASON:
            raise ForwardAdmissionError(
                f"profile line {line_number} violates the locked holdout"
            )
        grouped.setdefault(pitcher_id, []).append(dict(row))
    for rows in grouped.values():
        rows.sort(key=lambda row: (str(row["prediction_cutoff"]), int(row["game_pk"])))
    return grouped


def _freshness_seconds(
    selections: Mapping[tuple[int, str], Mapping[str, Any]],
    game_pk: int,
    as_of: datetime,
) -> int | None:
    observed: list[datetime] = []
    for side in ("away", "home"):
        selected = selections.get((game_pk, side), {}).get("selected")
        if selected is not None:
            observed.append(_parse_utc(selected["observed_at"]))
    if not observed:
        return None
    return int((as_of - max(observed)).total_seconds())


def assemble_games(
    selections: Mapping[tuple[int, str], dict[str, Any]],
    profiles: Mapping[int, list[dict[str, Any]]],
    *,
    as_of: datetime,
    freshness_limit_seconds: int = DEFAULT_FRESHNESS_LIMIT_SECONDS,
) -> list[dict[str, Any]]:
    """Produce one fail-closed assembly result per game."""
    selected_rows = [
        dict(selection["selected"]["row"])
        for selection in selections.values()
        if selection["selected"] is not None
    ]
    features = join_pitcher_profiles_from_profiles(selected_rows, profiles)
    features_by_snapshot = {row["snapshot_id"]: row for row in features}

    assemblies: list[dict[str, Any]] = []
    for game_pk in sorted({key[0] for key in selections}):
        sides: dict[str, dict[str, Any]] = {}
        reasons: list[str] = []
        meta_row: Mapping[str, Any] | None = None
        for side in ("away", "home"):
            selection = selections.get((game_pk, side))
            if selection is None:
                sides[side] = {"selection_status": "NO_OBSERVATIONS"}
                reasons.append(f"{side}:NO_OBSERVATIONS")
                continue
            selected = selection["selected"]
            side_result: dict[str, Any] = {
                "selection_status": selection["selection_status"],
                "prediction_cutoff": selection["prediction_cutoff"],
                "observation_count": selection["observation_count"],
                "starter_changes": selection["starter_changes"],
                "snapshot_id": None,
                "capture_key": None,
                "capture_version_id": None,
                "probable_pitcher_id": None,
                "probable_pitcher_name": None,
                "starter_observed_at": None,
                "feature_status": None,
                "feature_status_reason": None,
                "feature_version": None,
                "profile_prediction_cutoff": None,
                "profile_feature_hash": None,
                "profile_age_days": None,
                "feature_values": None,
            }
            if selected is None:
                reasons.append(f"{side}:{selection['selection_status']}")
                sides[side] = side_result
                continue
            meta_row = meta_row or selected["row"]
            side_result.update(
                {
                    "snapshot_id": selected["snapshot_id"],
                    "capture_key": selected["capture_key"],
                    "capture_version_id": selected["capture_version_id"],
                    "probable_pitcher_id": selected["pitcher_id"],
                    "probable_pitcher_name": selected["pitcher_name"],
                    "starter_observed_at": selected["observed_at"],
                }
            )
            if selection["selection_status"] != "SELECTED":
                reasons.append(f"{side}:{selection['selection_status']}")
            feature = features_by_snapshot.get(selected["snapshot_id"])
            if feature is not None:
                side_result.update(
                    {
                        "feature_status": feature["feature_status"],
                        "feature_status_reason": feature["feature_status_reason"],
                        "feature_version": feature["feature_version"],
                        "profile_prediction_cutoff": feature[
                            "profile_prediction_cutoff"
                        ],
                        "profile_feature_hash": feature["profile_feature_hash"],
                        "profile_age_days": feature["profile_age_days"],
                        "feature_values": feature["feature_values"],
                    }
                )
                if feature["feature_status"] != "READY":
                    reasons.append(
                        f"{side}:{feature['feature_status_reason'] or feature['feature_status']}"
                    )
            sides[side] = side_result
        assemblies.append(
            _finalize_assembly(
                game_pk,
                sides,
                reasons,
                meta_row,
                as_of=as_of,
                freshness_limit_seconds=freshness_limit_seconds,
                selections=selections,
            )
        )
    return assemblies


def _finalize_assembly(
    game_pk: int,
    sides: dict[str, dict[str, Any]],
    reasons: list[str],
    meta_row: Mapping[str, Any] | None,
    *,
    as_of: datetime,
    freshness_limit_seconds: int,
    selections: Mapping[tuple[int, str], Mapping[str, Any]],
) -> dict[str, Any]:
    snapshot_eligible = all(
        sides.get(side, {}).get("selection_status") == "SELECTED"
        for side in ("away", "home")
    )
    pitcher_feature_eligible = snapshot_eligible and all(
        sides[side].get("feature_status") == "READY" for side in ("away", "home")
    )
    freshness = _freshness_seconds(selections, game_pk, as_of)
    fresh = freshness is not None and 0 <= freshness <= freshness_limit_seconds
    cutoff_text = None
    before_cutoff = False
    if meta_row is not None:
        cutoff = _parse_utc(meta_row["prediction_cutoff"])
        cutoff_text = _utc_text(cutoff)
        before_cutoff = as_of < cutoff
    if pitcher_feature_eligible and not fresh:
        reasons.append("game:SNAPSHOT_STALE")
    if pitcher_feature_eligible and not before_cutoff:
        reasons.append("game:PREDICTION_CUTOFF_PASSED")
    feature_assembly_eligible = pitcher_feature_eligible and fresh and before_cutoff
    probability_reasons = [
        "APPROVED_MODEL_UNAVAILABLE",
        "PREDICTIVE_SKILL_NOT_ESTABLISHED",
    ]
    assembly = {
        "schema_version": ASSEMBLY_SCHEMA_VERSION,
        "game_pk": game_pk,
        "official_date": (
            str(meta_row["official_date"]) if meta_row is not None else None
        ),
        "scheduled_start_at": (
            str(meta_row["scheduled_start_at"]) if meta_row is not None else None
        ),
        "prediction_cutoff": cutoff_text,
        "venue_id": meta_row.get("venue_id") if meta_row is not None else None,
        "venue_name": meta_row.get("venue_name") if meta_row is not None else None,
        "as_of": _utc_text(as_of),
        "sides": sides,
        "freshness_seconds": freshness,
        "freshness_limit_seconds": freshness_limit_seconds,
        "eligibility": {
            "probable_starter_snapshot": snapshot_eligible,
            "pitcher_feature": pitcher_feature_eligible,
            "feature_assembly": feature_assembly_eligible,
            "probability": False,
            "market_evaluation": False,
            "wager": False,
        },
        "probability_ineligibility_reasons": probability_reasons,
        "market_ineligibility_reasons": ["MARKET_DATA_UNAVAILABLE"],
        "rejection_reasons": sorted(set(reasons)),
        "wager_decision": WAGER_DECISION,
    }
    assembly["assembly_id"] = _identity(assembly)
    return assembly


def build_assembly_package(
    official_date: str,
    admissions: list[dict[str, Any]],
    assemblies: list[dict[str, Any]],
    *,
    generated_at: datetime,
    profiles_status: str,
) -> dict[str, Any]:
    """Bundle admissions and assemblies into one auditable package document."""
    capture_admissions = [
        {
            "key": admission["key"],
            "status": admission["status"],
            "reason": admission["reason"],
            "version_id": admission["version_id"],
            "observed_at": admission["observed_at"],
            "response_sha256": admission["response_sha256"],
            "rows_admitted": admission["rows_admitted"],
            "row_rejections": admission["row_rejections"],
        }
        for admission in admissions
    ]
    package = {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "official_date": official_date,
        "generated_at": _utc_text(generated_at),
        "profile_table_schema": PROFILE_TABLE_SCHEMA,
        "profiles_status": profiles_status,
        "capture_admissions": capture_admissions,
        "admitted_captures": sum(
            1 for item in capture_admissions if item["status"] == "ADMITTED"
        ),
        "games": assemblies,
        "feature_assembly_eligible_games": sum(
            1 for assembly in assemblies if assembly["eligibility"]["feature_assembly"]
        ),
        "locked_2025_holdout_accessed": False,
        "wager_decision": WAGER_DECISION,
    }
    package["package_id"] = _identity(package)
    return package


def read_profiles_from_s3(
    s3_client: Any, bucket: str, key: str
) -> tuple[str, dict[int, list[dict[str, Any]]]]:
    """Read the JSONL profile projection; report an explicit absence status."""
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
    except Exception:
        return "PROFILES_UNAVAILABLE", {}
    text = response["Body"].read().decode("utf-8")
    return "PROFILES_LOADED", load_profiles_jsonl(text)


def assembly_object_key(official_date: str, generated_at: datetime) -> str:
    """Derive the versioned assembly package key for one date."""
    compact = _utc_text(generated_at)[:19].replace("-", "").replace(":", "") + "Z"
    key = f"{ASSEMBLY_KEY_PREFIX}/{official_date}/assembly-{compact}.json"
    if official_date.startswith(str(LOCKED_HOLDOUT_SEASON)):
        raise ForwardAdmissionError(REJECT_LOCKED_HOLDOUT)
    return key


def store_assembly_package(
    s3_client: Any,
    bucket: str,
    kms_key_arn: str,
    package: Mapping[str, Any],
) -> dict[str, Any]:
    """Write one assembly package as a versioned KMS-encrypted object."""
    key = assembly_object_key(
        str(package["official_date"]), _parse_utc(package["generated_at"])
    )
    body = canonical_json_bytes(package)
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


def run_assembly(
    s3_client: Any,
    bucket: str,
    kms_key_arn: str,
    official_dates: Iterable[str],
    *,
    profiles_key: str,
    now: Callable[[], datetime] | None = None,
    freshness_limit_seconds: int = DEFAULT_FRESHNESS_LIMIT_SECONDS,
) -> dict[str, Any]:
    """Admit captures and publish one assembly package per requested date."""
    clock = now or (lambda: datetime.now(timezone.utc))
    profiles_status, profiles = read_profiles_from_s3(s3_client, bucket, profiles_key)
    results: list[dict[str, Any]] = []
    for official_date in official_dates:
        if str(official_date).startswith(str(LOCKED_HOLDOUT_SEASON)):
            raise ForwardAdmissionError(REJECT_LOCKED_HOLDOUT)
        as_of = clock()
        keys = list_forward_capture_keys(s3_client, bucket, str(official_date))
        admissions = [read_capture(s3_client, bucket, key) for key in keys]
        history = build_observation_history(admissions)
        selections = select_starters(history, as_of=as_of)
        assemblies = (
            assemble_games(
                selections,
                profiles,
                as_of=as_of,
                freshness_limit_seconds=freshness_limit_seconds,
            )
            if profiles_status == "PROFILES_LOADED"
            else []
        )
        package = build_assembly_package(
            str(official_date),
            admissions,
            assemblies,
            generated_at=as_of,
            profiles_status=profiles_status,
        )
        stored = store_assembly_package(s3_client, bucket, kms_key_arn, package)
        results.append(
            {
                "official_date": str(official_date),
                "capture_keys": keys,
                "admitted_captures": package["admitted_captures"],
                "games": len(package["games"]),
                "feature_assembly_eligible_games": package[
                    "feature_assembly_eligible_games"
                ],
                "profiles_status": profiles_status,
                "stored": stored,
            }
        )
    return {
        "schema_version": "forward_assembly_run.v1",
        "profiles_key": profiles_key,
        "results": results,
        "wager_decision": WAGER_DECISION,
    }
