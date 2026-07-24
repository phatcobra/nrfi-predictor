"""Build strict-prior pitcher features from the inventoried Statcast cache.

The source cache is read-only and selected through the preserved Phase 0 file
manifest.  Actual starters identify historical pitching observations only; they
are never promoted to pregame probable-starter evidence.  The resulting feature
snapshots therefore prove pitcher-history capability for a supplied pitcher ID,
but remain ineligible for historical game-model joins until a timestamped
probable-starter snapshot exists.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Sequence
from urllib.parse import parse_qs, urlparse

from nrfi.real_vertical_slice import VerticalSliceError, canonical_json_bytes

if TYPE_CHECKING:
    import pandas as pd

# NOTE: pandas / pyarrow are imported lazily inside the three functions that use
# them (_write_parquet, _numeric, _aggregate...). Keeping them off the module top
# lets pure-Python consumers (e.g. nrfi.team_features, which only borrows the
# json/hash helpers below) import this module without loading the heavy parquet
# stack. This is an import-hygiene change only; every emitted artifact — and thus
# every frozen identity — is byte-for-byte unchanged.

DEFAULT_SEASONS = (2021, 2022, 2023, 2024)
LOCKED_HOLDOUT_SEASON = 2025
SOURCE_SCAN_ID = "0f3f19aa1d72525577f460a2fcb9692f81c835ec110c3674a720096c6a23c111"
SOURCE_FILE_MANIFEST_SHA256 = (
    "4ab2f5e74b61743a81152096416a09e8c0b13c121fe045174208af93cfa29fbc"
)
SOURCE_AUTHORITY = "https://baseballsavant.mlb.com"
FEATURE_VERSION = "pitcher-statcast-strict-prior-v1"
MINIMUM_PRIOR_STARTS = 3

STATCAST_COLUMNS = (
    "game_date",
    "game_pk",
    "pitcher",
    "inning",
    "inning_topbot",
    "at_bat_number",
    "pitch_number",
    "events",
    "description",
    "pitch_type",
    "release_speed",
    "launch_speed",
    "launch_speed_angle",
    "zone",
    "p_throws",
)
FASTBALL_TYPES = frozenset({"FA", "FC", "FF", "SI"})
STRIKEOUT_EVENTS = frozenset({"strikeout", "strikeout_double_play"})
WALK_EVENTS = frozenset({"intent_walk", "walk"})
SWING_DESCRIPTIONS = frozenset(
    {
        "foul",
        "foul_bunt",
        "foul_pitchout",
        "foul_tip",
        "hit_into_play",
        "hit_into_play_no_out",
        "hit_into_play_score",
        "missed_bunt",
        "swinging_pitchout",
        "swinging_strike",
        "swinging_strike_blocked",
    }
)
WHIFF_DESCRIPTIONS = frozenset(
    {"missed_bunt", "swinging_pitchout", "swinging_strike", "swinging_strike_blocked"}
)

RATE_FIELDS = (
    "strikeout_rate",
    "walk_rate",
    "home_run_rate",
    "whiff_rate",
    "chase_rate",
    "hard_hit_rate",
    "barrel_rate",
    "average_fastball_velocity",
    "average_pitch_count",
    "first_inning_runs_per_start",
    "first_inning_scoreless_rate",
)
WINDOWS = (("last_5", 5), ("last_20", 20), ("career", None))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _identity(value: object) -> str:
    return _sha256_bytes(canonical_json_bytes(value))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    materialized = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        for row in materialized:
            handle.write(canonical_json_bytes(row))
    return len(materialized)


def _write_parquet(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    import pyarrow as pa
    import pyarrow.parquet as pq

    materialized = list(rows)
    if not materialized:
        raise VerticalSliceError(f"cannot write an empty analytical table: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(materialized)
    pq.write_table(
        table,
        path,
        compression="zstd",
        data_page_version="2.0",
        use_dictionary=True,
        version="2.6",
        write_statistics=True,
    )
    return len(materialized)


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _requested_date(record: Mapping[str, Any]) -> str:
    linked = record.get("linked_metadata")
    if not isinstance(linked, list) or len(linked) != 1:
        raise VerticalSliceError("Statcast partition must have one metadata record")
    requested = linked[0].get("requested_date")
    if not isinstance(requested, str):
        raise VerticalSliceError("Statcast partition requested date is missing")
    return requested


def select_inventory_partitions(
    manifest_path: Path,
    seasons: Sequence[int],
    *,
    expected_manifest_sha256: str = SOURCE_FILE_MANIFEST_SHA256,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Select the Phase 0 canonical partition for each requested date."""
    season_set = {int(value) for value in seasons}
    if not season_set or any(value >= LOCKED_HOLDOUT_SEASON for value in season_set):
        raise VerticalSliceError(
            "only nonempty pre-2025 development seasons are allowed"
        )
    if _sha256_file(manifest_path) != expected_manifest_sha256:
        raise VerticalSliceError("Phase 0 file manifest checksum changed")

    records = _read_jsonl(manifest_path)
    by_path = {str(record["relative_path"]): record for record in records}
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record.get("classification") != "statcast_partition":
            continue
        requested = _requested_date(record)
        if int(requested[:4]) in season_set:
            groups[requested].append(record)

    selected: list[dict[str, Any]] = []
    for requested, candidates in sorted(groups.items()):
        hashes = {str(record["sha256"]) for record in candidates}
        if len(hashes) != 1:
            raise VerticalSliceError(
                f"conflicting inventoried Statcast partitions for {requested}"
            )
        chosen = min(candidates, key=lambda row: str(row["relative_path"]))
        footer = chosen.get("parquet_footer") or {}
        scan = chosen.get("selected_key_scan") or {}
        quarantine = chosen.get("quarantine") or {}
        if (
            footer.get("readable") is not True
            or scan.get("key_contract_valid") is not True
        ):
            raise VerticalSliceError(
                f"selected Statcast partition is unreadable: {requested}"
            )
        if quarantine.get("quarantined") is True:
            raise VerticalSliceError(
                f"selected Statcast partition is quarantined: {requested}"
            )
        selected.append(chosen)
    if not selected:
        raise VerticalSliceError("no inventoried Statcast partitions match the seasons")
    return selected, by_path


def _validate_metadata(
    cache_dir: Path,
    partition: Mapping[str, Any],
    records_by_path: Mapping[str, Mapping[str, Any]],
) -> None:
    metadata_link = partition["linked_metadata"][0]
    metadata_name = str(metadata_link["metadata_path"])
    metadata_record = records_by_path.get(metadata_name)
    if metadata_record is None:
        raise VerticalSliceError("inventoried Statcast metadata record is missing")
    metadata_path = cache_dir / metadata_name
    if metadata_path.stat().st_size != int(metadata_record["bytes"]):
        raise VerticalSliceError("Statcast metadata byte count changed")
    if _sha256_file(metadata_path) != metadata_record["sha256"]:
        raise VerticalSliceError("Statcast metadata checksum changed")

    value = json.loads(metadata_path.read_text(encoding="utf-8"))
    if value.get("func") != "get_statcast_data_from_csv_url":
        raise VerticalSliceError("unexpected Statcast cache producer")
    args = value.get("args")
    if not isinstance(args, list) or len(args) != 1 or not isinstance(args[0], str):
        raise VerticalSliceError("unexpected Statcast cache query metadata")
    parsed = urlparse(args[0])
    if parsed.path != "/statcast_search/csv":
        raise VerticalSliceError("unexpected Statcast source path")
    query = parse_qs(parsed.query)
    requested = _requested_date(partition)
    required = {
        "game_date_gt": [requested],
        "game_date_lt": [requested],
        "player_type": ["pitcher"],
        "type": ["details"],
    }
    if any(query.get(key) != expected for key, expected in required.items()):
        raise VerticalSliceError("Statcast query identity does not match the inventory")
    if "R|" not in "".join(query.get("hfGT", [])):
        raise VerticalSliceError("Statcast query does not include regular-season games")


def verify_inventory_files(
    cache_dir: Path,
    partitions: Sequence[Mapping[str, Any]],
    records_by_path: Mapping[str, Mapping[str, Any]],
) -> None:
    """Verify every selected source and metadata file without rescanning the cache."""
    for partition in partitions:
        path = cache_dir / str(partition["relative_path"])
        if not path.is_file() or path.stat().st_size != int(partition["bytes"]):
            raise VerticalSliceError(
                "inventoried Statcast partition is missing or changed"
            )
        if _sha256_file(path) != partition["sha256"]:
            raise VerticalSliceError("inventoried Statcast partition checksum changed")
        _validate_metadata(cache_dir, partition, records_by_path)


def load_development_context(
    multiseason_dir: Path, seasons: Sequence[int]
) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    season_set = {int(value) for value in seasons}
    games = _read_jsonl(multiseason_dir / "normalized_games.jsonl")
    feature_rows = {
        int(row["game_pk"]): row
        for row in _read_jsonl(multiseason_dir / "features.jsonl")
        if int(str(row["official_date"])[:4]) in season_set
    }
    contexts: dict[int, dict[str, Any]] = {}
    for game in games:
        if int(str(game["official_date"])[:4]) not in season_set:
            continue
        game_pk = int(game["game_pk"])
        feature = feature_rows.get(game_pk)
        if feature is None:
            raise VerticalSliceError(
                f"missing frozen prediction cutoff for game {game_pk}"
            )
        contexts[game_pk] = {
            "game_pk": game_pk,
            "official_date": game["official_date"],
            "scheduled_start_at": game["scheduled_start_at"],
            "prediction_cutoff": feature["prediction_cutoff"],
            "label_available_at": game["time_semantics"]["label_available_at"],
            "away_first_inning_runs": int(game["first_inning"]["away_runs"]),
            "home_first_inning_runs": int(game["first_inning"]["home_runs"]),
        }

    starters = []
    seen: set[tuple[int, str]] = set()
    for row in _read_jsonl(multiseason_dir / "actual_starters.jsonl"):
        game_pk = int(row["game_pk"])
        if game_pk not in contexts:
            continue
        side = str(row["side"])
        key = (game_pk, side)
        if key in seen or side not in {"away", "home"}:
            raise VerticalSliceError("actual-starter game/side identity is not unique")
        seen.add(key)
        if row.get("pregame_feature_eligible") is not False:
            raise VerticalSliceError(
                "actual starter was incorrectly marked pregame eligible"
            )
        starters.append(
            {
                "game_pk": game_pk,
                "side": side,
                "pitcher_id": int(row["player_id"]),
                "pitcher_name": row["player_name"],
                **contexts[game_pk],
            }
        )
    starters.sort(
        key=lambda row: (row["prediction_cutoff"], row["game_pk"], row["side"])
    )
    return starters, contexts


def _numeric(series: Any) -> Any:
    import pandas as pd

    return pd.to_numeric(series, errors="coerce")


def _summarize_statcast_group(
    group: pd.DataFrame,
    starter: Mapping[str, Any],
) -> dict[str, Any]:
    events: Any = group["events"].fillna("").astype(str)
    descriptions: Any = group["description"].fillna("").astype(str)
    pitch_types: Any = group["pitch_type"].fillna("").astype(str)
    at_bat_numbers: Any = group["at_bat_number"]
    release_speed = _numeric(group["release_speed"])
    launch_speed = _numeric(group["launch_speed"])
    launch_speed_angle = _numeric(group["launch_speed_angle"])
    zones = _numeric(group["zone"])
    swings = descriptions.isin(list(SWING_DESCRIPTIONS))
    whiffs = descriptions.isin(list(WHIFF_DESCRIPTIONS))
    out_of_zone = zones.notna() & ~zones.between(1, 9)
    batted_balls = launch_speed.notna()
    fastballs = pitch_types.isin(list(FASTBALL_TYPES)) & release_speed.notna()
    context = starter
    runs_allowed = (
        int(context["home_first_inning_runs"])
        if context["side"] == "away"
        else int(context["away_first_inning_runs"])
    )
    hands = sorted(set(group["p_throws"].dropna().astype(str)))
    if len(hands) > 1:
        raise VerticalSliceError("pitcher handedness changed within one game")
    return {
        "schema_version": "pitcher_statcast_game.v1",
        "game_pk": int(context["game_pk"]),
        "official_date": context["official_date"],
        "scheduled_start_at": context["scheduled_start_at"],
        "label_available_at": context["label_available_at"],
        "pitcher_id": int(context["pitcher_id"]),
        "side": context["side"],
        "pitcher_hand": hands[0] if hands else None,
        "pitch_count": int(len(group)),
        "plate_appearances": int(at_bat_numbers.nunique()),
        "strikeouts": int(events.isin(list(STRIKEOUT_EVENTS)).sum()),
        "walks": int(events.isin(list(WALK_EVENTS)).sum()),
        "hit_by_pitches": int((events == "hit_by_pitch").sum()),
        "home_runs": int((events == "home_run").sum()),
        "swings": int(swings.sum()),
        "whiffs": int(whiffs.sum()),
        "out_of_zone_pitches": int(out_of_zone.sum()),
        "chases": int((out_of_zone & swings).sum()),
        "batted_balls": int(batted_balls.sum()),
        "hard_hit_balls": int((batted_balls & launch_speed.ge(95.0)).sum()),
        "barrels": int((batted_balls & launch_speed_angle.eq(6)).sum()),
        "fastball_pitches": int(fastballs.sum()),
        "fastball_velocity_sum": float(release_speed[fastballs].sum()),
        "first_inning_runs_allowed": runs_allowed,
        "first_inning_scoreless": int(runs_allowed == 0),
    }


def build_pitcher_game_history(
    cache_dir: Path,
    partitions: Sequence[Mapping[str, Any]],
    starters: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Aggregate real Statcast pitches to actual historical starter games."""
    import pandas as pd
    import pyarrow.parquet as pq

    starter_by_pair = {
        (int(row["game_pk"]), int(row["pitcher_id"])): row for row in starters
    }
    matched: set[tuple[int, int]] = set()
    history: list[dict[str, Any]] = []
    for partition in partitions:
        table = pq.read_table(
            cache_dir / str(partition["relative_path"]), columns=list(STATCAST_COLUMNS)
        )
        frame = table.to_pandas()
        if frame.empty:
            continue
        frame["game_pk"] = _numeric(frame["game_pk"]).astype("Int64")
        frame["pitcher"] = _numeric(frame["pitcher"]).astype("Int64")
        mask = [
            (int(game_pk), int(pitcher)) in starter_by_pair
            if pd.notna(game_pk) and pd.notna(pitcher)
            else False
            for game_pk, pitcher in zip(frame["game_pk"], frame["pitcher"], strict=True)
        ]
        selected = frame.loc[mask]
        if selected.empty:
            continue
        for pair, group in selected.groupby(["game_pk", "pitcher"], sort=True):
            key = (int(pair[0]), int(pair[1]))
            if key in matched:
                raise VerticalSliceError(
                    "starter pitches span duplicate source partitions"
                )
            matched.add(key)
            history.append(_summarize_statcast_group(group, starter_by_pair[key]))

    rejections = [
        {
            "schema_version": "pitcher_statcast_rejection.v1",
            "game_pk": int(row["game_pk"]),
            "official_date": row["official_date"],
            "pitcher_id": int(row["pitcher_id"]),
            "side": row["side"],
            "reason": "NO_STATCAST_PITCH_ROWS_FOR_ACTUAL_STARTER",
        }
        for row in starters
        if (int(row["game_pk"]), int(row["pitcher_id"])) not in matched
    ]
    history.sort(
        key=lambda row: (row["scheduled_start_at"], row["game_pk"], row["side"])
    )
    rejections.sort(key=lambda row: (row["official_date"], row["game_pk"], row["side"]))
    return history, rejections


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    return float(numerator / denominator) if denominator else None


def _window_metrics(history: Sequence[Mapping[str, Any]]) -> dict[str, float | None]:
    starts = len(history)
    plate_appearances = sum(int(row["plate_appearances"]) for row in history)
    swings = sum(int(row["swings"]) for row in history)
    out_of_zone = sum(int(row["out_of_zone_pitches"]) for row in history)
    batted_balls = sum(int(row["batted_balls"]) for row in history)
    fastballs = sum(int(row["fastball_pitches"]) for row in history)
    return {
        "strikeout_rate": _ratio(
            sum(int(row["strikeouts"]) for row in history), plate_appearances
        ),
        "walk_rate": _ratio(
            sum(int(row["walks"]) for row in history), plate_appearances
        ),
        "home_run_rate": _ratio(
            sum(int(row["home_runs"]) for row in history), plate_appearances
        ),
        "whiff_rate": _ratio(sum(int(row["whiffs"]) for row in history), swings),
        "chase_rate": _ratio(sum(int(row["chases"]) for row in history), out_of_zone),
        "hard_hit_rate": _ratio(
            sum(int(row["hard_hit_balls"]) for row in history), batted_balls
        ),
        "barrel_rate": _ratio(
            sum(int(row["barrels"]) for row in history), batted_balls
        ),
        "average_fastball_velocity": _ratio(
            sum(float(row["fastball_velocity_sum"]) for row in history), fastballs
        ),
        "average_pitch_count": _ratio(
            sum(int(row["pitch_count"]) for row in history), starts
        ),
        "first_inning_runs_per_start": _ratio(
            sum(int(row["first_inning_runs_allowed"]) for row in history), starts
        ),
        "first_inning_scoreless_rate": _ratio(
            sum(int(row["first_inning_scoreless"]) for row in history), starts
        ),
    }


def build_pitcher_feature_snapshots(
    history: Sequence[Mapping[str, Any]],
    starters: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_pitcher: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for row in history:
        by_pitcher[int(row["pitcher_id"])].append(row)
    snapshots: list[dict[str, Any]] = []
    for starter in starters:
        cutoff = str(starter["prediction_cutoff"])
        available = [
            row
            for row in by_pitcher[int(starter["pitcher_id"])]
            if int(row["game_pk"]) != int(starter["game_pk"])
            and str(row["scheduled_start_at"]) < cutoff
            and str(row["label_available_at"]) <= cutoff
        ]
        available.sort(key=lambda row: (row["scheduled_start_at"], row["game_pk"]))
        values: dict[str, float | int | None] = {}
        for name, length in WINDOWS:
            window = available[-length:] if length is not None else available
            values[f"prior_starts_{name}"] = len(window)
            values.update(
                {
                    f"{metric}_{name}": value
                    for metric, value in _window_metrics(window).items()
                }
            )
        previous_date = (
            date.fromisoformat(str(available[-1]["official_date"]))
            if available
            else None
        )
        target_date = date.fromisoformat(str(starter["official_date"]))
        values["days_since_previous_start"] = (
            (target_date - previous_date).days if previous_date is not None else None
        )
        core = [
            values[f"{metric}_last_20"]
            for metric in RATE_FIELDS
            if metric != "average_fastball_velocity"
        ]
        eligible = len(available) >= MINIMUM_PRIOR_STARTS and all(
            value is not None for value in core
        )
        present = sum(value is not None for value in values.values())
        analytical = {
            "schema_version": "pitcher_feature_snapshot.v1",
            "feature_version": FEATURE_VERSION,
            "game_pk": int(starter["game_pk"]),
            "official_date": starter["official_date"],
            "prediction_cutoff": cutoff,
            "pitcher_id": int(starter["pitcher_id"]),
            "side": starter["side"],
            "pitcher_identity_basis": "POSTGAME_ACTUAL_STARTER_ATTRIBUTION",
            "profile_feature_eligible": eligible,
            "historical_prediction_join_eligible": False,
            "historical_prediction_join_ineligibility_reason": (
                "NO_TIMESTAMPED_PROBABLE_STARTER_SNAPSHOT"
            ),
            "feature_values": values,
            "feature_value_coverage_pct": round(100.0 * present / len(values), 6),
        }
        snapshots.append({**analytical, "feature_hash": _identity(analytical)})
    snapshots.sort(
        key=lambda row: (row["prediction_cutoff"], row["game_pk"], row["side"])
    )
    return snapshots


def _artifact_entry(path: Path, row_count: int) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "path": path.name,
        "bytes": len(payload),
        "row_count": row_count,
        "sha256": _sha256_bytes(payload),
    }


def generate_pitcher_statcast_package(
    *,
    inventory_manifest: Path,
    cache_dir: Path,
    multiseason_dir: Path,
    output_dir: Path,
    producing_commit: str,
    seasons: Sequence[int] = DEFAULT_SEASONS,
    expected_inventory_sha256: str = SOURCE_FILE_MANIFEST_SHA256,
) -> dict[str, Any]:
    partitions, records_by_path = select_inventory_partitions(
        inventory_manifest,
        seasons,
        expected_manifest_sha256=expected_inventory_sha256,
    )
    verify_inventory_files(cache_dir, partitions, records_by_path)
    starters, _ = load_development_context(multiseason_dir, seasons)
    history, rejections = build_pitcher_game_history(cache_dir, partitions, starters)
    snapshots = build_pitcher_feature_snapshots(history, starters)

    output_dir.mkdir(parents=True, exist_ok=True)
    row_counts = {
        "pitcher_game_history.parquet": _write_parquet(
            output_dir / "pitcher_game_history.parquet", history
        ),
        "pitcher_features.parquet": _write_parquet(
            output_dir / "pitcher_features.parquet", snapshots
        ),
        "rejections.jsonl": _write_jsonl(output_dir / "rejections.jsonl", rejections),
    }
    feature_eligible = sum(bool(row["profile_feature_eligible"]) for row in snapshots)
    source_selection = [
        {
            "requested_date": _requested_date(row),
            "sha256": row["sha256"],
            "row_count": row["selected_key_scan"]["row_count"],
            "audit_field_stream_sha256": row["selected_key_scan"][
                "audit_field_stream_sha256"
            ],
        }
        for row in partitions
    ]
    coverage = {
        "schema_version": "pitcher_statcast_coverage.v1",
        "feature_version": FEATURE_VERSION,
        "seasons": list(map(int, seasons)),
        "source_authority": SOURCE_AUTHORITY,
        "source_scan_id": SOURCE_SCAN_ID,
        "source_file_manifest_sha256": expected_inventory_sha256,
        "source_partition_count": len(partitions),
        "source_partition_bytes": sum(int(row["bytes"]) for row in partitions),
        "source_partition_selection_sha256": _identity(source_selection),
        "actual_starter_rows": len(starters),
        "statcast_matched_starter_games": len(history),
        "statcast_rejected_starter_games": len(rejections),
        "pitcher_feature_snapshot_rows": len(snapshots),
        "profile_feature_eligible_rows": feature_eligible,
        "profile_feature_eligible_pct": round(
            100.0 * feature_eligible / len(snapshots), 6
        ),
        "historical_prediction_join_eligible_rows": 0,
        "historical_prediction_join_coverage_pct": 0.0,
        "historical_prediction_join_gap": "NO_TIMESTAMPED_PROBABLE_STARTER_SNAPSHOT",
        "actual_starters_used_for": "POSTGAME_ATTRIBUTION_ONLY",
        "raw_source_payloads_committed": False,
        "locked_2025_holdout_accessed": False,
    }
    _write_json(output_dir / "coverage.json", coverage)
    entries = [
        _artifact_entry(output_dir / name, count)
        for name, count in sorted(row_counts.items())
    ]
    entries.append(_artifact_entry(output_dir / "coverage.json", 1))
    manifest = {
        "schema_version": "pitcher_statcast_manifest.v1",
        "producing_commit": producing_commit,
        "feature_version": FEATURE_VERSION,
        "configuration_identity": _identity(
            {
                "seasons": list(map(int, seasons)),
                "feature_version": FEATURE_VERSION,
                "minimum_prior_starts": MINIMUM_PRIOR_STARTS,
                "windows": WINDOWS,
                "statcast_columns": STATCAST_COLUMNS,
            }
        ),
        "source_partition_selection_sha256": coverage[
            "source_partition_selection_sha256"
        ],
        "entries": sorted(entries, key=lambda row: str(row["path"])),
        "locked_2025_holdout_accessed": False,
    }
    _write_json(output_dir / "artifact_manifest.json", manifest)
    return {"coverage": coverage, "manifest": manifest}


def _default_cache_dir() -> Path:
    from pybaseball import cache

    return Path(cache.config.cache_directory)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory-manifest", required=True, type=Path)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument(
        "--multiseason-dir", type=Path, default=Path("docs/multiseason")
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("docs/pitcher_statcast")
    )
    parser.add_argument("--producing-commit", required=True)
    parser.add_argument("--seasons", nargs="+", type=int, default=list(DEFAULT_SEASONS))
    args = parser.parse_args(argv)
    result = generate_pitcher_statcast_package(
        inventory_manifest=args.inventory_manifest,
        cache_dir=args.cache_dir or _default_cache_dir(),
        multiseason_dir=args.multiseason_dir,
        output_dir=args.output_dir,
        producing_commit=args.producing_commit,
        seasons=args.seasons,
    )
    print(json.dumps(result["coverage"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
