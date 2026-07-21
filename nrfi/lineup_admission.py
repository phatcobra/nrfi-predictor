"""Admit immutable forward lineup captures into the shared point-in-time path.

Reads the collector's versioned lineup captures under
``signals/pregame/official-statsapi/lineups/`` (schema ``forward_lineup_capture``
wrapping ``lineup_snapshot`` rows), validates schema + deterministic snapshot
identity + game/team/side identity, preserves the complete revision lineage per
game side, and selects the latest eligible snapshot observed strictly before the
prediction cutoff.  It never infers a publication timestamp, never treats an
after-cutoff or postgame lineup as pregame evidence, and never collapses earlier
revisions.  Status is derived from the observed lineage:
NOT_AVAILABLE / CONFIRMED / UPDATED / WITHDRAWN (PROJECTED is not derivable from
this official source and is passed through only if a future source sets it).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from nrfi.lineup_snapshot import LINEUP_SNAPSHOT_SCHEMA_VERSION
from nrfi.pregame_snapshot import canonical_json_bytes

LINEUP_KEY_PREFIX = "signals/pregame/official-statsapi/lineups"
LINEUP_CAPTURE_SCHEMA_VERSION = "forward_lineup_capture.v1"
LOCKED_HOLDOUT_SEASON = 2025
MAX_CAPTURE_BYTES = 8_388_608

STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"
STATUS_CONFIRMED = "CONFIRMED"
STATUS_PROJECTED = "PROJECTED"
STATUS_UPDATED = "UPDATED"
STATUS_WITHDRAWN = "WITHDRAWN"

REJECT_MALFORMED = "LINEUP_SCHEMA_INVALID"
REJECT_UNKNOWN_SCHEMA = "LINEUP_SCHEMA_INVALID"
REJECT_MISSING_TIMESTAMP = "LINEUP_SCHEMA_INVALID"
REJECT_LOCKED_HOLDOUT = "LINEUP_LOCKED_HOLDOUT"
REJECT_MISSING_CHECKSUM = "LINEUP_SCHEMA_INVALID"
REJECT_RAW_PAYLOAD = "LINEUP_RAW_PAYLOAD_MARKED_UPLOADED"
REJECT_IDENTITY_MISMATCH = "LINEUP_IDENTITY_MISMATCH"
REJECT_ROW_SCHEMA = "LINEUP_SCHEMA_INVALID"
REJECT_AMBIGUOUS = "LINEUP_REVISION_AMBIGUOUS"


class LineupAdmissionError(ValueError):
    """Raised when the lineup admission path violates its fail-closed contract."""


def _identity(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise LineupAdmissionError("required timestamp is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise LineupAdmissionError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _integer(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if not isinstance(value, (str, int, float)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def list_lineup_capture_keys(
    s3_client: Any, bucket: str, official_date: str
) -> list[str]:
    """List every preserved lineup capture key for one date, deterministically."""
    prefix = f"{LINEUP_KEY_PREFIX}/{official_date}/"
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


def _validate_rows(
    capture: Mapping[str, Any], target_date: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    admitted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    retrieved_at = capture["retrieved_at"]
    rows = capture.get("rows")
    if not isinstance(rows, list):
        raise LineupAdmissionError(REJECT_MALFORMED)
    for row in rows:
        if not isinstance(row, Mapping):
            rejected.append({"reason": REJECT_MALFORMED})
            continue
        game_pk = _integer(row.get("game_pk"))
        side = row.get("side")
        reason = None
        if row.get("schema_version") != LINEUP_SNAPSHOT_SCHEMA_VERSION:
            reason = REJECT_ROW_SCHEMA
        elif game_pk is None or game_pk <= 0 or side not in ("away", "home"):
            reason = REJECT_MALFORMED
        elif (game_pk, str(side)) in seen:
            reason = REJECT_AMBIGUOUS
        elif str(row.get("official_date")) != target_date:
            reason = REJECT_MALFORMED
        elif str(row.get("official_date")).startswith(str(LOCKED_HOLDOUT_SEASON)):
            reason = REJECT_LOCKED_HOLDOUT
        elif _integer(row.get("team_id")) is None:
            reason = REJECT_MALFORMED
        elif row.get("lineup_observed_at") != retrieved_at:
            reason = REJECT_IDENTITY_MISMATCH
        elif row.get("snapshot_id") != _identity(
            {k: v for k, v in row.items() if k != "snapshot_id"}
        ):
            reason = REJECT_IDENTITY_MISMATCH
        else:
            try:
                cutoff = _parse_utc(row.get("prediction_cutoff"))
            except LineupAdmissionError:
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


def read_lineup_capture(s3_client: Any, bucket: str, key: str) -> dict[str, Any]:
    """Read one lineup capture object; admit or reject with explicit reasons."""
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
    if capture.get("schema_version") != LINEUP_CAPTURE_SCHEMA_VERSION:
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
    except LineupAdmissionError:
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
        admitted_rows, row_rejections = _validate_rows(capture, target_date)
    except LineupAdmissionError as error:
        admission["reason"] = str(error)
        return admission
    admission["rows"] = admitted_rows
    admission["rows_admitted"] = len(admitted_rows)
    admission["row_rejections"] = row_rejections
    admission["status"] = "ADMITTED"
    return admission


def _batting_order_ids(row: Mapping[str, Any]) -> list[int]:
    order = row.get("batting_order")
    if not isinstance(order, list):
        return []
    return [int(p["player_id"]) for p in order if isinstance(p, Mapping)]


def build_lineup_observation_history(
    admissions: Iterable[Mapping[str, Any]],
) -> dict[tuple[int, str], list[dict[str, Any]]]:
    """Preserve every admitted lineup observation per game side, in order."""
    history: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for admission in admissions:
        if admission.get("status") != "ADMITTED":
            continue
        for row in admission.get("rows", []):
            observation = {
                "row": dict(row),
                "observed_at": str(row["lineup_observed_at"]),
                "prediction_cutoff": str(row["prediction_cutoff"]),
                "observed_before_cutoff": bool(row.get("observed_before_cutoff")),
                "lineup_status": str(row.get("lineup_status")),
                "batting_order_ids": _batting_order_ids(row),
                "snapshot_id": row.get("snapshot_id"),
                "team_id": _integer(row.get("team_id")),
                "capture_key": admission["key"],
                "capture_version_id": admission.get("version_id"),
                "response_sha256": admission.get("response_sha256"),
            }
            key = (int(row["game_pk"]), str(row["side"]))
            history.setdefault(key, []).append(observation)
    for observations in history.values():
        observations.sort(key=lambda item: (item["observed_at"], item["capture_key"]))
    return history


def _derive_status(
    admissible: list[dict[str, Any]], selected: dict[str, Any]
) -> tuple[str, int, list[Any], list[Any]]:
    """Derive lineup status + revision lineage from the admissible lineage."""
    confirmed_orders: list[list[int]] = []
    previous_snapshot_ids: list[Any] = []
    for obs in admissible:
        previous_snapshot_ids.append(obs["snapshot_id"])
        if obs["lineup_status"] == STATUS_CONFIRMED:
            if not confirmed_orders or confirmed_orders[-1] != obs["batting_order_ids"]:
                confirmed_orders.append(obs["batting_order_ids"])
    revision_count = len(confirmed_orders)
    had_confirmed = revision_count > 0
    if selected["lineup_status"] == STATUS_CONFIRMED:
        status = STATUS_UPDATED if revision_count > 1 else STATUS_CONFIRMED
    elif selected["lineup_status"] == STATUS_PROJECTED:
        status = STATUS_PROJECTED
    elif had_confirmed:
        status = STATUS_WITHDRAWN
    else:
        status = STATUS_NOT_AVAILABLE
    # exclude the selected snapshot id from "previous"
    prev = [s for s in previous_snapshot_ids if s != selected["snapshot_id"]]
    return status, revision_count, prev, confirmed_orders


def select_lineups(
    history: Mapping[tuple[int, str], list[dict[str, Any]]],
    *,
    as_of: datetime,
    producing_commit: str = "",
) -> dict[tuple[int, str], dict[str, Any]]:
    """Select the latest admissible pre-cutoff lineup snapshot per game side."""
    selections: dict[tuple[int, str], dict[str, Any]] = {}
    for (game_pk, side), observations in history.items():
        cutoff = _parse_utc(observations[-1]["prediction_cutoff"])
        admissible = [
            obs
            for obs in observations
            if _parse_utc(obs["observed_at"]) < cutoff
            and _parse_utc(obs["observed_at"]) <= as_of
        ]
        reasons: list[str] = []
        selected = admissible[-1] if admissible else None
        status = STATUS_NOT_AVAILABLE
        revision_count = 0
        previous_ids: list[Any] = []
        if selected is not None:
            status, revision_count, previous_ids, _orders = _derive_status(
                admissible, selected
            )
        row = selected["row"] if selected is not None else None
        selections[(game_pk, side)] = {
            "schema_version": "lineup_selection.v1",
            "game_pk": game_pk,
            "official_date": (row["official_date"] if row else None),
            "team_id": (selected["team_id"] if selected else None),
            "side": side,
            "snapshot_id": (selected["snapshot_id"] if selected else None),
            "capture_key": (selected["capture_key"] if selected else None),
            "capture_version_id": (
                selected["capture_version_id"] if selected else None
            ),
            "lineup_observed_at": (selected["observed_at"] if selected else None),
            "source_publication_time": None,
            "prediction_cutoff": _utc_text(cutoff),
            "observed_before_cutoff": (
                bool(selected["observed_before_cutoff"]) if selected else False
            ),
            "lineup_status": status,
            "revision_count": revision_count,
            "previous_snapshot_ids": previous_ids,
            "observation_count": len(observations),
            "admissible_count": len(admissible),
            "batting_order_ids": (selected["batting_order_ids"] if selected else []),
            "batting_order": (row.get("batting_order") if row else []),
            "response_sha256": (selected["response_sha256"] if selected else None),
            "rejection_reasons": reasons,
            "producing_commit": producing_commit,
        }
    return selections
