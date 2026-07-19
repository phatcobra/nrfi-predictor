"""Extract the >=2015 and <=2024 Statcast day cache under a hard date boundary.

The quarantined ``mlb-model`` day cache is laid out as
``statcast_days/<year>/<month>/statcast_<year>_<month>_<day>.parquet`` where
each season is a physically separate top-level directory.  This module builds an
allowlist purely from directory and filename tokens, opens only files whose
resolved date is between 2015-01-01 and 2024-12-31, and records a machine
readable ledger of every file decision so that zero locked-2025 files are read.
It never touches the mixed DuckDB warehouse.  Pitch aggregation and the
strict-prior profile logic are reused unchanged from :mod:`nrfi.pitcher_statcast`.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd
import pyarrow.parquet as pq

from nrfi.pitcher_statcast import (
    FEATURE_VERSION,
    MINIMUM_PRIOR_STARTS,
    STATCAST_COLUMNS,
    WINDOWS,
    _artifact_entry,
    _identity,
    _numeric,
    _sha256_file,
    _summarize_statcast_group,
    _write_json,
    _write_jsonl,
    _write_parquet,
    build_pitcher_feature_snapshots,
    load_development_context,
)

LOCKED_HOLDOUT_SEASON = 2025
ADMITTED_MIN_SEASON = 2015
ADMITTED_MAX_SEASON = 2024
EXTRACTION_VERSION = "statcast-canonical-2015-2024-v1"
SOURCE_AUTHORITY = "https://baseballsavant.mlb.com"
FILENAME_PATTERN = re.compile(r"^statcast_(20\d{2})_(\d{2})_(\d{2})\.parquet$")
PLATOON_STANDS = ("L", "R")


class StatcastExtractionError(ValueError):
    """Raised when the extraction contract's boundary is violated."""


def build_source_ledger(day_cache_dir: Path) -> dict[str, Any]:
    """Classify every day-cache entry from tokens alone; never open a data file.

    Only season directories 2015-2024 are traversed, so the locked-2025
    directory is never listed for content.  Each entry is ADMIT or REJECT with a
    reason; no admitted entry may resolve to a 2025 (or otherwise out-of-range)
    date.
    """
    admitted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    if not day_cache_dir.is_dir():
        raise StatcastExtractionError(f"day cache is missing: {day_cache_dir}")

    season_dirs = sorted(
        child
        for child in day_cache_dir.iterdir()
        if child.is_dir() and re.fullmatch(r"20\d{2}", child.name)
    )
    for season_dir in season_dirs:
        season = int(season_dir.name)
        if season == LOCKED_HOLDOUT_SEASON:
            rejected.append(
                {
                    "relative_path": season_dir.name,
                    "decision": "REJECT",
                    "reason": "LOCKED_2025_SEASON_DIRECTORY_NOT_TRAVERSED",
                    "opened": False,
                }
            )
            continue
        if not ADMITTED_MIN_SEASON <= season <= ADMITTED_MAX_SEASON:
            rejected.append(
                {
                    "relative_path": season_dir.name,
                    "decision": "REJECT",
                    "reason": "SEASON_OUT_OF_ADMITTED_RANGE",
                    "opened": False,
                }
            )
            continue
        for path in sorted(season_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(day_cache_dir).as_posix()
            match = FILENAME_PATTERN.match(path.name)
            if match is None:
                rejected.append(
                    {
                        "relative_path": rel,
                        "decision": "REJECT",
                        "reason": "FILENAME_NOT_ADMITTED_PARQUET",
                        "opened": False,
                    }
                )
                continue
            file_year, file_month, file_day = (int(part) for part in match.groups())
            try:
                resolved = date(file_year, file_month, file_day)
            except ValueError:
                rejected.append(
                    {
                        "relative_path": rel,
                        "decision": "REJECT",
                        "reason": "UNRESOLVABLE_CALENDAR_DATE",
                        "opened": False,
                    }
                )
                continue
            if file_year != season:
                rejected.append(
                    {
                        "relative_path": rel,
                        "decision": "REJECT",
                        "reason": "FILENAME_SEASON_DIRECTORY_MISMATCH",
                        "opened": False,
                    }
                )
                continue
            if (
                not date(ADMITTED_MIN_SEASON, 1, 1)
                <= resolved
                <= date(ADMITTED_MAX_SEASON, 12, 31)
            ):
                rejected.append(
                    {
                        "relative_path": rel,
                        "decision": "REJECT",
                        "reason": "RESOLVED_DATE_OUT_OF_RANGE",
                        "opened": False,
                    }
                )
                continue
            admitted.append(
                {
                    "relative_path": rel,
                    "decision": "ADMIT",
                    "reason": "IN_RANGE_STATCAST_DAY_FILE",
                    "game_date": resolved.isoformat(),
                    "opened": False,
                }
            )
    admitted.sort(key=lambda row: row["relative_path"])
    rejected.sort(key=lambda row: row["relative_path"])
    if any(str(row["game_date"]).startswith("2025") for row in admitted):
        raise StatcastExtractionError("allowlist admitted a locked-2025 date")
    return {"admitted": admitted, "rejected": rejected}


def _platoon_counts(group: pd.DataFrame) -> dict[str, int]:
    stand = group["stand"].fillna("").astype(str)
    events = group["events"].fillna("").astype(str)
    strikeout_events = ["strikeout", "strikeout_double_play"]
    counts: dict[str, int] = {}
    for hand in PLATOON_STANDS:
        mask = stand == hand
        subset = group.loc[mask]
        counts[f"vs_{hand.lower()}hb_plate_appearances"] = (
            int(subset["at_bat_number"].nunique()) if not subset.empty else 0
        )
        counts[f"vs_{hand.lower()}hb_strikeouts"] = int(
            events.loc[mask].isin(strikeout_events).sum()
        )
    return counts


def build_pitcher_game_history_from_daycache(
    day_cache_dir: Path,
    admitted: Sequence[Mapping[str, Any]],
    starters: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Open only admitted files, aggregate real pitches to actual starter games.

    Returns (history, starter_rejections, opened_ledger).  A start's pitches all
    share one game date, so each (game_pk, pitcher) group resolves within a
    single admitted file; duplicate cross-file groups are rejected.
    """
    starter_by_pair = {
        (int(row["game_pk"]), int(row["pitcher_id"])): row for row in starters
    }
    starter_pairs = set(starter_by_pair)
    matched: set[tuple[int, int]] = set()
    history: list[dict[str, Any]] = []
    opened: list[dict[str, Any]] = []
    required = list(dict.fromkeys((*STATCAST_COLUMNS, "stand")))
    for entry in admitted:
        rel = str(entry["relative_path"])
        if str(entry.get("game_date", "")).startswith(str(LOCKED_HOLDOUT_SEASON)):
            raise StatcastExtractionError("refused to open a locked-2025 file")
        path = day_cache_dir / rel
        parquet_file = pq.ParquetFile(path)
        available = set(parquet_file.schema_arrow.names)
        present = [column for column in required if column in available]
        table = parquet_file.read(columns=present)
        analytic_ready = all(column in available for column in STATCAST_COLUMNS)
        opened.append(
            {
                "relative_path": rel,
                "decision": "ADMIT",
                "reason": entry["reason"]
                if analytic_ready
                else "OPENED_WITHOUT_ANALYTIC_SCHEMA",
                "game_date": entry["game_date"],
                "opened": True,
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
                "row_count": int(table.num_rows),
            }
        )
        if not analytic_ready:
            continue
        frame = table.to_pandas()
        if "stand" not in frame.columns:
            frame["stand"] = ""
        if frame.empty:
            continue
        frame["game_pk"] = _numeric(frame["game_pk"]).astype("Int64")
        frame["pitcher"] = _numeric(frame["pitcher"]).astype("Int64")
        pairs = pd.MultiIndex.from_arrays([frame["game_pk"], frame["pitcher"]])
        selected = frame.loc[pairs.isin(starter_pairs)]
        if selected.empty:
            continue
        for pair, grp in selected.groupby(["game_pk", "pitcher"], sort=True):
            key = (int(pair[0]), int(pair[1]))
            if key in matched:
                raise StatcastExtractionError(
                    "starter pitches span duplicate admitted files"
                )
            matched.add(key)
            record = _summarize_statcast_group(grp, starter_by_pair[key])
            record.update(_platoon_counts(grp))
            record["source_relative_path"] = rel
            history.append(record)

    rejections = [
        {
            "schema_version": "statcast_extraction_rejection.v1",
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
    opened.sort(key=lambda row: row["relative_path"])
    return history, rejections, opened


def generate_expanded_pitcher_statcast_package(
    *,
    day_cache_dir: Path,
    multiseason_dir: Path,
    output_dir: Path,
    producing_commit: str,
    seasons: Sequence[int],
) -> dict[str, Any]:
    """Execute the <=2024 extraction contract and rebuild strict-prior profiles."""
    season_set = {int(value) for value in seasons}
    if not season_set or any(value >= LOCKED_HOLDOUT_SEASON for value in season_set):
        raise StatcastExtractionError("only pre-2025 seasons may be extracted")

    ledger = build_source_ledger(day_cache_dir)
    starters, _ = load_development_context(multiseason_dir, sorted(season_set))
    history, starter_rejections, opened = build_pitcher_game_history_from_daycache(
        day_cache_dir, ledger["admitted"], starters
    )
    snapshots = build_pitcher_feature_snapshots(history, starters)

    opened_2025 = sum(1 for row in opened if str(row["game_date"]).startswith("2025"))
    if opened_2025:
        raise StatcastExtractionError("a locked-2025 file was opened")

    output_dir.mkdir(parents=True, exist_ok=True)
    full_ledger = [
        {k: v for k, v in row.items() if k != "reason"} | {"reason": row["reason"]}
        for row in (*opened, *ledger["rejected"])
    ]
    full_ledger.sort(key=lambda row: (str(row.get("opened")), row["relative_path"]))
    row_counts = {
        "pitcher_game_history.parquet": _write_parquet(
            output_dir / "pitcher_game_history.parquet", history
        ),
        "pitcher_features.parquet": _write_parquet(
            output_dir / "pitcher_features.parquet", snapshots
        ),
        "source_file_ledger.jsonl": _write_jsonl(
            output_dir / "source_file_ledger.jsonl", full_ledger
        ),
        "rejections.jsonl": _write_jsonl(
            output_dir / "rejections.jsonl", starter_rejections
        ),
    }
    feature_eligible = sum(bool(row["profile_feature_eligible"]) for row in snapshots)
    opened_bytes = sum(int(row["bytes"]) for row in opened)
    coverage = {
        "schema_version": "statcast_extraction_coverage.v1",
        "extraction_version": EXTRACTION_VERSION,
        "feature_version": FEATURE_VERSION,
        "seasons": sorted(season_set),
        "source_authority": SOURCE_AUTHORITY,
        "day_files_admitted": len(ledger["admitted"]),
        "day_files_opened": len(opened),
        "day_files_rejected": len(ledger["rejected"]),
        "day_files_opened_2025": opened_2025,
        "opened_source_bytes": opened_bytes,
        "source_file_ledger_identity": _identity(full_ledger),
        "actual_starter_rows": len(starters),
        "statcast_matched_starter_games": len(history),
        "statcast_rejected_starter_games": len(starter_rejections),
        "pitcher_feature_snapshot_rows": len(snapshots),
        "profile_feature_eligible_rows": feature_eligible,
        "profile_feature_eligible_pct": round(
            100.0 * feature_eligible / len(snapshots), 6
        )
        if snapshots
        else 0.0,
        "history_partition_identity": _identity(history),
        "feature_partition_identity": _identity(snapshots),
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
        "schema_version": "statcast_extraction_manifest.v1",
        "producing_commit": producing_commit,
        "extraction_version": EXTRACTION_VERSION,
        "feature_version": FEATURE_VERSION,
        "configuration_identity": _identity(
            {
                "seasons": sorted(season_set),
                "extraction_version": EXTRACTION_VERSION,
                "feature_version": FEATURE_VERSION,
                "minimum_prior_starts": MINIMUM_PRIOR_STARTS,
                "windows": WINDOWS,
                "admitted_range": [ADMITTED_MIN_SEASON, ADMITTED_MAX_SEASON],
            }
        ),
        "history_partition_identity": coverage["history_partition_identity"],
        "feature_partition_identity": coverage["feature_partition_identity"],
        "source_file_ledger_identity": coverage["source_file_ledger_identity"],
        "entries": sorted(entries, key=lambda row: str(row["path"])),
        "locked_2025_holdout_accessed": False,
    }
    _write_json(output_dir / "artifact_manifest.json", manifest)
    return {"coverage": coverage, "manifest": manifest}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day-cache-dir", required=True, type=Path)
    parser.add_argument("--multiseason-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--producing-commit", required=True)
    parser.add_argument(
        "--seasons",
        nargs="+",
        type=int,
        default=list(range(ADMITTED_MIN_SEASON, ADMITTED_MAX_SEASON + 1)),
    )
    args = parser.parse_args(argv)
    result = generate_expanded_pitcher_statcast_package(
        day_cache_dir=args.day_cache_dir,
        multiseason_dir=args.multiseason_dir,
        output_dir=args.output_dir,
        producing_commit=args.producing_commit,
        seasons=args.seasons,
    )
    print(json.dumps(result["coverage"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
