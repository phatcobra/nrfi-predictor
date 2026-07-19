"""Capture official probable starters and join preserved strict-prior profiles."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib
import json
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

STATSAPI_ENDPOINT = "https://statsapi.mlb.com/api/v1/schedule"
SOURCE_SCHEMA_VERSION = "statsapi_probable_starters_source.v1"
SNAPSHOT_SCHEMA_VERSION = "probable_starter_snapshot.v1"
FEATURE_SCHEMA_VERSION = "pregame_pitcher_statcast_feature.v1"
PACKAGE_SCHEMA_VERSION = "pregame_pitcher_snapshot_package.v1"
LOCKED_HOLDOUT_SEASON = 2025
HTTP_TIMEOUT_SECONDS = 20


class PregameSnapshotError(ValueError):
    """Raised when a pregame snapshot violates its fail-closed contract."""


def canonical_json_bytes(value: object) -> bytes:
    """Serialize deterministic JSON with one trailing newline."""
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _identity(value: object) -> str:
    return _sha256(canonical_json_bytes(value))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise PregameSnapshotError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise PregameSnapshotError("required timestamp is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise PregameSnapshotError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _request_parameters(target_date: date) -> dict[str, str | int]:
    return {
        "date": target_date.isoformat(),
        "hydrate": "probablePitcher,team,venue",
        "sportId": 1,
    }


def _validate_target_date(target_date: date) -> None:
    if target_date.year == LOCKED_HOLDOUT_SEASON:
        raise PregameSnapshotError("the locked 2025 holdout is prohibited")


def _read_source_cache(path: Path, target_date: date) -> dict[str, Any]:
    if not path.is_file():
        raise PregameSnapshotError(f"probable-starter cache is missing: {path}")
    source = json.loads(path.read_text(encoding="utf-8"))
    if source.get("schema_version") != SOURCE_SCHEMA_VERSION:
        raise PregameSnapshotError("probable-starter cache schema differs")
    if source.get("endpoint") != STATSAPI_ENDPOINT:
        raise PregameSnapshotError("probable-starter source endpoint differs")
    if source.get("request_parameters") != _request_parameters(target_date):
        raise PregameSnapshotError("probable-starter request parameters differ")
    encoded = source.get("response_body_base64")
    if not isinstance(encoded, str):
        raise PregameSnapshotError("cached response body is missing")
    raw = base64.b64decode(encoded, validate=True)
    if len(raw) != source.get("response_bytes"):
        raise PregameSnapshotError("cached response byte count changed")
    if _sha256(raw) != source.get("response_sha256"):
        raise PregameSnapshotError("cached response checksum changed")
    _parse_utc(source.get("retrieved_at"))
    source["payload"] = json.loads(raw)
    return source


def acquire_source_snapshot(
    target_date: date,
    cache_path: Path,
    *,
    allow_network: bool,
    now: Callable[[], datetime] = _utc_now,
    get: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Acquire once or replay a verified official StatsAPI schedule response."""
    _validate_target_date(target_date)
    if cache_path.exists():
        return _read_source_cache(cache_path, target_date)
    if not allow_network:
        raise PregameSnapshotError(f"probable-starter cache is missing: {cache_path}")

    if get is None:
        requester = getattr(importlib.import_module("requests"), "get")
    else:
        requester = get
    response = requester(
        STATSAPI_ENDPOINT,
        params=_request_parameters(target_date),
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    raw = bytes(response.content)
    payload = json.loads(raw)
    retrieved_at = _utc_text(now())
    source = {
        "schema_version": SOURCE_SCHEMA_VERSION,
        "endpoint": STATSAPI_ENDPOINT,
        "request_parameters": _request_parameters(target_date),
        "retrieved_at": retrieved_at,
        "response_bytes": len(raw),
        "response_sha256": _sha256(raw),
        "response_body_base64": base64.b64encode(raw).decode("ascii"),
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(canonical_json_bytes(source))
    source["payload"] = payload
    return source


def _integer(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if not isinstance(value, (str, int, float)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value: object) -> str | None:
    return str(value) if value not in (None, "") else None


def _person(value: object) -> tuple[int | None, str | None]:
    if not isinstance(value, Mapping):
        return None, None
    return _integer(value.get("id")), _text(value.get("fullName"))


def build_probable_starter_rows(
    source: Mapping[str, Any], target_date: date
) -> list[dict[str, Any]]:
    """Normalize one row per game side without inventing publication time."""
    _validate_target_date(target_date)
    retrieved_at = _utc_text(_parse_utc(source.get("retrieved_at")))
    response_sha256 = source.get("response_sha256")
    payload = source.get("payload")
    if not isinstance(payload, Mapping) or not isinstance(response_sha256, str):
        raise PregameSnapshotError("source snapshot is incomplete")
    source_observation_id = _identity(
        {
            "endpoint": STATSAPI_ENDPOINT,
            "request_parameters": _request_parameters(target_date),
            "retrieved_at": retrieved_at,
            "response_sha256": response_sha256,
        }
    )

    games = [
        game
        for day in payload.get("dates", [])
        if isinstance(day, Mapping)
        for game in day.get("games", [])
        if isinstance(game, Mapping)
    ]
    rows: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for game in sorted(
        games,
        key=lambda item: (
            _text(item.get("gameDate")) or "",
            _integer(item.get("gamePk")) or -1,
        ),
    ):
        if game.get("gameType") != "R":
            continue
        game_pk = _integer(game.get("gamePk"))
        official_date = _text(game.get("officialDate"))
        scheduled_start_at = _text(game.get("gameDate"))
        if game_pk is None or official_date != target_date.isoformat():
            continue
        cutoff = _parse_utc(scheduled_start_at)
        observed = _parse_utc(retrieved_at)
        teams = game.get("teams")
        if not isinstance(teams, Mapping):
            teams = {}
        status = game.get("status")
        if not isinstance(status, Mapping):
            status = {}
        status_code = _text(status.get("statusCode"))
        venue = game.get("venue")
        if not isinstance(venue, Mapping):
            venue = {}

        for side in ("away", "home"):
            key = (game_pk, side)
            if key in seen:
                raise PregameSnapshotError("duplicate game/side probable starter")
            seen.add(key)
            side_value = teams.get(side)
            if not isinstance(side_value, Mapping):
                side_value = {}
            team = side_value.get("team")
            if not isinstance(team, Mapping):
                team = {}
            pitcher_id, pitcher_name = _person(side_value.get("probablePitcher"))

            reason = None
            if observed >= cutoff:
                reason = "SNAPSHOT_AT_OR_AFTER_PREDICTION_CUTOFF"
            elif status_code not in {"S", "P"}:
                reason = "GAME_STATUS_NOT_PREGAME_ELIGIBLE"
            elif pitcher_id is None:
                reason = "PROBABLE_STARTER_MISSING"
            eligible = reason is None
            row = {
                "schema_version": SNAPSHOT_SCHEMA_VERSION,
                "source_observation_id": source_observation_id,
                "game_pk": game_pk,
                "official_date": official_date,
                "scheduled_start_at": _utc_text(cutoff),
                "prediction_cutoff": _utc_text(cutoff),
                "game_status_code": status_code,
                "doubleheader_code": _text(game.get("doubleHeader")),
                "game_number": _integer(game.get("gameNumber")),
                "venue_id": _integer(venue.get("id")),
                "venue_name": _text(venue.get("name")),
                "side": side,
                "team_id": _integer(team.get("id")),
                "team_name": _text(team.get("name")),
                "probable_pitcher_id": pitcher_id,
                "probable_pitcher_name": pitcher_name,
                "probable_starter_observed_at": retrieved_at,
                "source_publication_time": None,
                "availability_basis": "OFFICIAL_STATSAPI_OBSERVED_AT_RETRIEVAL",
                "pregame_feature_eligible": eligible,
                "pregame_feature_ineligibility_reason": reason,
            }
            row["snapshot_id"] = _identity(row)
            rows.append(row)
    if not rows:
        raise PregameSnapshotError("no regular-season games found for target date")
    rows.sort(key=lambda row: (row["scheduled_start_at"], row["game_pk"], row["side"]))
    return rows


def _load_latest_profiles(profile_path: Path) -> dict[int, list[dict[str, Any]]]:
    if not profile_path.is_file():
        raise PregameSnapshotError(f"pitcher profile table is missing: {profile_path}")
    pq = importlib.import_module("pyarrow.parquet")
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in pq.read_table(profile_path).to_pylist():
        pitcher_id = _integer(row.get("pitcher_id"))
        if pitcher_id is not None:
            grouped[pitcher_id].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda row: (str(row["prediction_cutoff"]), int(row["game_pk"])))
    return grouped


def join_pitcher_profiles(
    snapshots: Sequence[Mapping[str, Any]], profile_path: Path
) -> list[dict[str, Any]]:
    """Join only strict-prior profiles and block gaps across whole seasons."""
    return join_pitcher_profiles_from_profiles(
        snapshots, _load_latest_profiles(profile_path)
    )


def join_pitcher_profiles_from_profiles(
    snapshots: Sequence[Mapping[str, Any]],
    profiles: Mapping[int, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Join preloaded strict-prior profiles; shared by local and AWS paths."""
    joined: list[dict[str, Any]] = []
    for snapshot in snapshots:
        observed = _parse_utc(snapshot["probable_starter_observed_at"])
        pitcher_id = _integer(snapshot.get("probable_pitcher_id"))
        candidates = [
            row
            for row in profiles.get(pitcher_id or -1, [])
            if _parse_utc(row["prediction_cutoff"]) < observed
        ]
        profile = candidates[-1] if candidates else None

        status = "READY"
        reason = None
        if snapshot.get("pregame_feature_eligible") is not True:
            status = "BLOCKED_PREGAME_SNAPSHOT"
            reason = snapshot.get("pregame_feature_ineligibility_reason")
        elif profile is None:
            status = "BLOCKED_NO_INVENTORIED_PROFILE"
            reason = "NO_STRICT_PRIOR_STATCAST_PROFILE"
        elif profile.get("profile_feature_eligible") is not True:
            status = "BLOCKED_INSUFFICIENT_PROFILE_HISTORY"
            reason = "PROFILE_MINIMUM_PRIOR_STARTS_NOT_MET"
        else:
            profile_time = _parse_utc(profile["prediction_cutoff"])
            target_year = int(str(snapshot["official_date"])[:4])
            if profile_time.year < target_year - 1:
                status = "DEGRADED_PROFILE_HISTORY_GAP"
                reason = "PROFILE_MISSING_INTERVENING_SEASON_HISTORY"

        profile_time = (
            _parse_utc(profile["prediction_cutoff"]) if profile is not None else None
        )
        feature_row = {
            "schema_version": FEATURE_SCHEMA_VERSION,
            "snapshot_id": snapshot["snapshot_id"],
            "game_pk": snapshot["game_pk"],
            "official_date": snapshot["official_date"],
            "scheduled_start_at": snapshot["scheduled_start_at"],
            "side": snapshot["side"],
            "probable_pitcher_id": pitcher_id,
            "probable_pitcher_name": snapshot.get("probable_pitcher_name"),
            "probable_starter_observed_at": snapshot["probable_starter_observed_at"],
            "feature_status": status,
            "feature_status_reason": reason,
            "inference_eligible": status == "READY",
            "feature_version": (
                profile.get("feature_version") if profile is not None else None
            ),
            "profile_prediction_cutoff": (
                _utc_text(profile_time) if profile_time is not None else None
            ),
            "profile_age_days": (
                int((observed - profile_time).total_seconds() // 86400)
                if profile_time is not None
                else None
            ),
            "profile_feature_eligible": (
                profile.get("profile_feature_eligible") if profile is not None else None
            ),
            "profile_feature_hash": (
                profile.get("feature_hash") if profile is not None else None
            ),
            "feature_values": (
                profile.get("feature_values") if profile is not None else None
            ),
        }
        feature_row["pregame_feature_id"] = _identity(feature_row)
        joined.append(feature_row)
    joined.sort(
        key=lambda row: (row["scheduled_start_at"], row["game_pk"], row["side"])
    )
    return joined


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def _write_jsonl(path: Path, values: Iterable[Mapping[str, Any]]) -> int:
    rows = list(values)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        for row in rows:
            handle.write(canonical_json_bytes(row))
    return len(rows)


def _artifact(path: Path, row_count: int) -> dict[str, object]:
    content = path.read_bytes()
    return {
        "path": path.name,
        "bytes": len(content),
        "row_count": row_count,
        "sha256": _sha256(content),
    }


def build_package(
    target_date: date,
    source: Mapping[str, Any],
    profile_path: Path,
    output_dir: Path,
    *,
    code_commit: str,
) -> dict[str, Any]:
    """Write the bounded derived package; raw source payload remains local-only."""
    if len(code_commit) != 40 or any(
        char not in "0123456789abcdef" for char in code_commit
    ):
        raise PregameSnapshotError("code_commit must be a full lowercase Git SHA")
    snapshots = build_probable_starter_rows(source, target_date)
    features = join_pitcher_profiles(snapshots, profile_path)
    provenance = {
        "schema_version": "pregame_snapshot_provenance.v1",
        "source_observation_id": snapshots[0]["source_observation_id"],
        "endpoint": source["endpoint"],
        "request_parameters": source["request_parameters"],
        "retrieved_at": source["retrieved_at"],
        "response_bytes": source["response_bytes"],
        "response_sha256": source["response_sha256"],
        "raw_source_payload_committed": False,
    }
    total = len(snapshots)
    probable = sum(row["probable_pitcher_id"] is not None for row in snapshots)
    pregame = sum(bool(row["pregame_feature_eligible"]) for row in snapshots)
    matched = sum(row["profile_prediction_cutoff"] is not None for row in features)
    profile_eligible = sum(row["profile_feature_eligible"] is True for row in features)
    inference = sum(bool(row["inference_eligible"]) for row in features)
    coverage = {
        "schema_version": "pregame_snapshot_coverage.v1",
        "target_date": target_date.isoformat(),
        "games": len({int(row["game_pk"]) for row in snapshots}),
        "game_sides": total,
        "probable_starter_rows": probable,
        "probable_starter_coverage_pct": round(100.0 * probable / total, 6),
        "pregame_snapshot_eligible_rows": pregame,
        "pregame_snapshot_coverage_pct": round(100.0 * pregame / total, 6),
        "statcast_profile_matched_rows": matched,
        "statcast_profile_match_coverage_pct": round(100.0 * matched / total, 6),
        "statcast_profile_feature_eligible_rows": profile_eligible,
        "statcast_profile_feature_coverage_pct": round(
            100.0 * profile_eligible / total, 6
        ),
        "inference_eligible_rows": inference,
        "inference_coverage_pct": round(100.0 * inference / total, 6),
        "inference_gap": "INTERVENING_2025_HISTORY_LOCKED_AND_UNAVAILABLE",
        "locked_2025_holdout_accessed": False,
        "source_response_sha256": source["response_sha256"],
        "snapshot_identity": _identity(snapshots),
        "feature_table_identity": _identity(features),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    row_counts = {
        "probable_starters.jsonl": _write_jsonl(
            output_dir / "probable_starters.jsonl", snapshots
        ),
        "pitcher_features.jsonl": _write_jsonl(
            output_dir / "pitcher_features.jsonl", features
        ),
        "provenance.json": 1,
        "coverage.json": 1,
    }
    _write_json(output_dir / "provenance.json", provenance)
    _write_json(output_dir / "coverage.json", coverage)
    entries = [
        _artifact(output_dir / name, row_count)
        for name, row_count in sorted(row_counts.items())
    ]
    manifest = {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "target_date": target_date.isoformat(),
        "producing_commit": code_commit,
        "source_observation_id": provenance["source_observation_id"],
        "snapshot_identity": coverage["snapshot_identity"],
        "feature_table_identity": coverage["feature_table_identity"],
        "entries": entries,
        "locked_2025_holdout_accessed": False,
    }
    _write_json(output_dir / "artifact_manifest.json", manifest)
    return {"coverage": coverage, "manifest": manifest}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-date", type=date.fromisoformat, required=True)
    parser.add_argument("--cache-file", type=Path, required=True)
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--allow-network", action="store_true")
    args = parser.parse_args(argv)
    source = acquire_source_snapshot(
        args.target_date,
        args.cache_file,
        allow_network=args.allow_network,
    )
    result = build_package(
        args.target_date,
        source,
        args.profiles,
        args.output,
        code_commit=args.code_commit,
    )
    print(json.dumps(result["coverage"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
