"""Extract 2015-2024 batter-game history and strict-prior batter profiles.

This mirrors :mod:`nrfi.statcast_extraction` for batters.  It reuses the same
pre-2025 day-file allowlist and ledger, opens only admitted 2015-2024 files, and
aggregates pitch rows into one canonical record per (game_pk, batter).  Profiles
are strict-prior: every window uses only batter-games whose scheduled start and
label-availability precede the target game's prediction cutoff, so a delayed or
suspended game can never enter an earlier profile.  The locked 2025 season is
never opened, listed, or derived from.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd
import pyarrow.parquet as pq

from nrfi.pitcher_statcast import (
    _artifact_entry,
    _identity,
    _numeric,
    _ratio,
    _sha256_file,
    _write_json,
    _write_jsonl,
    _write_parquet,
    load_development_context,
)
from nrfi.statcast_extraction import (
    ADMITTED_MAX_SEASON,
    ADMITTED_MIN_SEASON,
    LOCKED_HOLDOUT_SEASON,
    build_source_ledger,
)

BATTER_EXTRACTION_VERSION = "batter-statcast-strict-prior-2015-2024-v1"
BATTER_FEATURE_VERSION = "batter-statcast-strict-prior-v1"
SOURCE_AUTHORITY = "https://baseballsavant.mlb.com"
MINIMUM_PRIOR_PLATE_APPEARANCES = 50

BATTER_COLUMNS = (
    "game_date",
    "game_pk",
    "batter",
    "pitcher",
    "inning",
    "at_bat_number",
    "pitch_number",
    "events",
    "description",
    "bb_type",
    "launch_speed",
    "launch_speed_angle",
    "stand",
    "p_throws",
)
HIT_EVENTS = {"single": 1, "double": 2, "triple": 3, "home_run": 4}
STRIKEOUT_EVENTS = frozenset({"strikeout", "strikeout_double_play"})
WALK_EVENTS = frozenset({"walk", "intent_walk"})
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
WINDOWS = (("last_20", 20), ("last_50", 50), ("last_100", 100), ("career", None))


class BatterExtractionError(ValueError):
    """Raised when the batter extraction violates its fail-closed contract."""


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _icount(value: Any) -> int:
    return int(value.sum())


def _fsum(value: Any) -> float:
    return float(value.sum())


def _iunique(value: Any) -> int:
    return int(value.nunique())


def _summarize_batter_group(
    group: pd.DataFrame, batter_id: int, context: Mapping[str, Any]
) -> dict[str, Any]:
    events = group["events"].fillna("").astype(str)
    descriptions = group["description"].fillna("").astype(str)
    bb_type = group["bb_type"].fillna("").astype(str)
    launch_speed = _numeric(group["launch_speed"])
    launch_angle = _numeric(group["launch_speed_angle"])
    p_throws = group["p_throws"].fillna("").astype(str)
    stands = sorted(set(group["stand"].dropna().astype(str)))

    swings = descriptions.isin(list(SWING_DESCRIPTIONS))
    whiffs = descriptions.isin(list(WHIFF_DESCRIPTIONS))
    batted = launch_speed.notna()
    strikeouts = events.isin(list(STRIKEOUT_EVENTS))
    walks = events.isin(list(WALK_EVENTS))
    hbp = events == "hit_by_pitch"
    hit_mask = events.isin(list(HIT_EVENTS))
    total_bases = int(sum(HIT_EVENTS[str(e)] for e in events[hit_mask].tolist()))
    plate_appearances = _iunique(group["at_bat_number"])
    on_base_mask = hit_mask | walks | hbp

    def _hand_counts(hand: str) -> tuple[int, int, int]:
        mask = p_throws == hand
        pa = _iunique(group.loc[mask, "at_bat_number"]) if bool(mask.any()) else 0
        return pa, _icount(strikeouts & mask), _icount(on_base_mask & mask)

    vs_l = _hand_counts("L")
    vs_r = _hand_counts("R")
    return {
        "schema_version": "batter_game.v1",
        "game_pk": int(context["game_pk"]),
        "batter_id": int(batter_id),
        "official_date": context["official_date"],
        "scheduled_start_at": context["scheduled_start_at"],
        "label_available_at": context["label_available_at"],
        "prediction_cutoff": context["prediction_cutoff"],
        "batter_stand": stands[0] if len(stands) == 1 else ("S" if stands else None),
        "plate_appearances": plate_appearances,
        "strikeouts": _icount(strikeouts),
        "walks": _icount(walks),
        "hit_by_pitch": _icount(hbp),
        "hits": _icount(hit_mask),
        "total_bases": total_bases,
        "on_base_events": _icount(on_base_mask),
        "swings": _icount(swings),
        "whiffs": _icount(whiffs),
        "contact": _icount(swings & ~whiffs),
        "batted_balls": _icount(batted),
        "hard_hit_balls": _icount(batted & launch_speed.ge(95.0)),
        "barrels": _icount(batted & launch_angle.eq(6)),
        "exit_velocity_sum": _fsum(launch_speed[batted]),
        "ground_balls": _icount(bb_type == "ground_ball"),
        "fly_balls": _icount(bb_type == "fly_ball"),
        "line_drives": _icount(bb_type == "line_drive"),
        "typed_batted_balls": _icount(
            bb_type.isin(["ground_ball", "fly_ball", "line_drive", "popup"])
        ),
        "vs_lhp_plate_appearances": vs_l[0],
        "vs_lhp_strikeouts": vs_l[1],
        "vs_lhp_on_base_events": vs_l[2],
        "vs_rhp_plate_appearances": vs_r[0],
        "vs_rhp_strikeouts": vs_r[1],
        "vs_rhp_on_base_events": vs_r[2],
    }


def build_batter_game_history(
    day_cache_dir: Path,
    admitted: Sequence[Mapping[str, Any]],
    contexts: Mapping[int, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Open only admitted files; aggregate one canonical record per batter-game."""
    history: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    opened: list[dict[str, Any]] = []
    matched: set[tuple[int, int]] = set()
    required = list(BATTER_COLUMNS)
    progress = os.environ.get("NRFI_EXTRACTION_PROGRESS")
    log_every = int(progress) if progress and progress.isdigit() else 0
    total = len(admitted)
    started = time.monotonic()
    for index, entry in enumerate(admitted, start=1):
        rel = str(entry["relative_path"])
        if str(entry.get("game_date", "")).startswith(str(LOCKED_HOLDOUT_SEASON)):
            raise BatterExtractionError("refused to open a locked-2025 file")
        path = day_cache_dir / rel
        parquet_file = pq.ParquetFile(path)
        available = set(parquet_file.schema_arrow.names)
        present = [column for column in required if column in available]
        table = parquet_file.read(columns=present)
        analytic_ready = all(column in available for column in BATTER_COLUMNS)
        opened.append(
            {
                "relative_path": rel,
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
        if log_every and (index % log_every == 0 or index == total):
            elapsed = time.monotonic() - started
            print(
                f"[batter] {index}/{total} files {elapsed:.0f}s "
                f"history={len(history)} last={rel}",
                file=sys.stderr,
                flush=True,
            )
        if not analytic_ready:
            continue
        frame = table.to_pandas()
        if frame.empty:
            continue
        frame["game_pk"] = _numeric(frame["game_pk"]).astype("Int64")
        frame["batter"] = _numeric(frame["batter"]).astype("Int64")
        frame = frame.loc[
            frame["game_pk"].isin(list(contexts)) & frame["batter"].notna()
        ]
        if frame.empty:
            continue
        for (game_pk, batter_id), grp in frame.groupby(
            ["game_pk", "batter"], sort=True
        ):
            key = (int(game_pk), int(batter_id))
            if key in matched:
                raise BatterExtractionError(
                    "batter-game spans duplicate admitted files"
                )
            matched.add(key)
            history.append(
                _summarize_batter_group(grp, int(batter_id), contexts[int(game_pk)])
            )
    history.sort(
        key=lambda row: (row["scheduled_start_at"], row["game_pk"], row["batter_id"])
    )
    opened.sort(key=lambda row: row["relative_path"])
    return history, rejections, opened


_SUM_FIELDS = (
    "plate_appearances",
    "strikeouts",
    "walks",
    "hit_by_pitch",
    "hits",
    "total_bases",
    "on_base_events",
    "swings",
    "whiffs",
    "contact",
    "batted_balls",
    "hard_hit_balls",
    "barrels",
    "exit_velocity_sum",
    "ground_balls",
    "fly_balls",
    "line_drives",
    "typed_batted_balls",
    "vs_lhp_plate_appearances",
    "vs_lhp_strikeouts",
    "vs_lhp_on_base_events",
    "vs_rhp_plate_appearances",
    "vs_rhp_strikeouts",
    "vs_rhp_on_base_events",
)


def _metrics_from_totals(t: Mapping[str, float]) -> dict[str, float | None]:
    """Batter window metrics from summed totals (career or short-window)."""
    pa = t["plate_appearances"]
    bb = t["batted_balls"]
    typed = t["typed_batted_balls"]
    return {
        "on_base_rate": _ratio(t["on_base_events"], pa),
        "walk_rate": _ratio(t["walks"], pa),
        "strikeout_rate": _ratio(t["strikeouts"], pa),
        "strikeout_avoidance_rate": _ratio(pa - t["strikeouts"], pa),
        "contact_rate": _ratio(t["contact"], t["swings"]),
        "whiff_rate": _ratio(t["whiffs"], t["swings"]),
        "hard_hit_rate": _ratio(t["hard_hit_balls"], bb),
        "barrel_rate": _ratio(t["barrels"], bb),
        "average_exit_velocity": _ratio(t["exit_velocity_sum"], bb),
        "ground_ball_rate": _ratio(t["ground_balls"], typed),
        "fly_ball_rate": _ratio(t["fly_balls"], typed),
        "line_drive_rate": _ratio(t["line_drives"], typed),
        "total_bases_per_pa": _ratio(t["total_bases"], pa),
        "vs_lhp_strikeout_rate": _ratio(
            t["vs_lhp_strikeouts"], t["vs_lhp_plate_appearances"]
        ),
        "vs_lhp_on_base_rate": _ratio(
            t["vs_lhp_on_base_events"], t["vs_lhp_plate_appearances"]
        ),
        "vs_rhp_strikeout_rate": _ratio(
            t["vs_rhp_strikeouts"], t["vs_rhp_plate_appearances"]
        ),
        "vs_rhp_on_base_rate": _ratio(
            t["vs_rhp_on_base_events"], t["vs_rhp_plate_appearances"]
        ),
    }


def _window_totals(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = {field: 0.0 for field in _SUM_FIELDS}
    for row in rows:
        for field in _SUM_FIELDS:
            totals[field] += row[field]
    return totals


def _reference_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, float | None]:
    return _metrics_from_totals(_window_totals(rows))


def _parse_utc(value: object) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _snapshot(
    target: Mapping[str, Any],
    window_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    career_totals: Mapping[str, float] | None,
    career_games: int,
) -> dict[str, Any]:
    values: dict[str, float | int | None] = {}
    for name, _length in WINDOWS:
        rows = window_rows[name]
        if name == "career" and career_totals is not None:
            totals = career_totals
            games = career_games
        else:
            totals = _window_totals(rows)
            games = len(rows)
        values[f"prior_games_{name}"] = games
        values[f"prior_plate_appearances_{name}"] = int(totals["plate_appearances"])
        values.update(
            {
                f"{metric}_{name}": v
                for metric, v in _metrics_from_totals(totals).items()
            }
        )
    career_pa = values["prior_plate_appearances_career"]
    eligible = isinstance(career_pa, int) and career_pa >= (
        MINIMUM_PRIOR_PLATE_APPEARANCES
    )
    target_year = int(str(target["official_date"])[:4])
    last_game = window_rows["career"][-1] if window_rows["career"] else None
    gap_seasons = None
    if last_game is not None:
        gap_seasons = max(0, target_year - 1 - int(str(last_game["official_date"])[:4]))
    present = sum(value is not None for value in values.values())
    analytical = {
        "schema_version": "batter_feature_snapshot.v1",
        "feature_version": BATTER_FEATURE_VERSION,
        "game_pk": int(target["game_pk"]),
        "official_date": target["official_date"],
        "prediction_cutoff": str(target["prediction_cutoff"]),
        "batter_id": int(target["batter_id"]),
        "batter_stand": target["batter_stand"],
        "batter_identity_basis": "POSTGAME_PLATE_APPEARANCE_ATTRIBUTION",
        "profile_feature_eligible": bool(eligible),
        "career_history_available": career_games > 0,
        "recent_history_missing": (gap_seasons or 0) > 0,
        "profile_history_gap_seasons": gap_seasons,
        "historical_lineup_timing_unavailable": True,
        "historical_prediction_join_eligible": False,
        "feature_values": values,
        "feature_value_coverage_pct": round(100.0 * present / len(values), 6),
    }
    return {**analytical, "feature_hash": _identity(analytical)}


def _by_batter(
    history: Sequence[Mapping[str, Any]],
) -> dict[int, list[Mapping[str, Any]]]:
    grouped: dict[int, list[Mapping[str, Any]]] = {}
    for row in history:
        grouped.setdefault(int(row["batter_id"]), []).append(row)
    for rows in grouped.values():
        rows.sort(key=lambda row: (row["scheduled_start_at"], row["game_pk"]))
    return grouped


def build_batter_feature_snapshots_reference(
    history: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Clear per-target strict-prior reference used as the equivalence oracle."""
    by_batter = _by_batter(history)
    snapshots: list[dict[str, Any]] = []
    for rows in by_batter.values():
        for target in rows:
            cutoff = str(target["prediction_cutoff"])
            available = [
                row
                for row in rows
                if int(row["game_pk"]) != int(target["game_pk"])
                and str(row["scheduled_start_at"]) < cutoff
                and str(row["label_available_at"]) <= cutoff
            ]
            available.sort(key=lambda row: (row["scheduled_start_at"], row["game_pk"]))
            window_rows = {
                name: (available[-length:] if length is not None else available)
                for name, length in WINDOWS
            }
            snapshots.append(_snapshot(target, window_rows, None, len(available)))
    snapshots.sort(
        key=lambda row: (row["prediction_cutoff"], row["game_pk"], row["batter_id"])
    )
    return snapshots


def build_batter_feature_snapshots(
    history: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Near-linear strict-prior builder; byte-identical to the reference.

    Batters whose cutoffs are non-decreasing and whose each label precedes the
    next cutoff use the fast prefix path (career via running cumulative totals,
    short windows via direct slice sums).  Others fall back to the exact
    reference for that batter (e.g. suspended games with late labels).
    """
    by_batter = _by_batter(history)
    max_window = max(length for _n, length in WINDOWS if length)
    snapshots: list[dict[str, Any]] = []
    for rows in by_batter.values():
        cutoffs = [str(row["prediction_cutoff"]) for row in rows]
        labels = [str(row["label_available_at"]) for row in rows]
        simple = all(
            cutoffs[i] <= cutoffs[i + 1] and labels[i] <= cutoffs[i + 1]
            for i in range(len(rows) - 1)
        )
        if not simple:
            snapshots.extend(build_batter_feature_snapshots_reference(rows))
            continue
        totals: dict[str, float] = {field: 0.0 for field in _SUM_FIELDS}
        career_games = 0
        prior: list[Mapping[str, Any]] = []
        for target in rows:
            window_rows = {
                "last_20": prior[-20:],
                "last_50": prior[-50:],
                "last_100": prior[-100:],
                "career": prior,
            }
            snapshots.append(_snapshot(target, window_rows, dict(totals), career_games))
            for field in _SUM_FIELDS:
                totals[field] += target[field]
            career_games += 1
            prior.append(target)
            if len(prior) > max_window:
                prior.pop(0)
    snapshots.sort(
        key=lambda row: (row["prediction_cutoff"], row["game_pk"], row["batter_id"])
    )
    return snapshots


def generate_batter_package(
    *,
    day_cache_dir: Path,
    multiseason_dir: Path,
    output_dir: Path,
    producing_commit: str,
    seasons: Sequence[int],
    fast: bool = True,
) -> dict[str, Any]:
    """Execute the pre-2025 batter extraction and build strict-prior profiles."""
    season_set = {int(value) for value in seasons}
    if not season_set or any(value >= LOCKED_HOLDOUT_SEASON for value in season_set):
        raise BatterExtractionError("only pre-2025 seasons may be extracted")

    def _stage(message: str) -> None:
        if os.environ.get("NRFI_EXTRACTION_PROGRESS"):
            print(f"[batter] {message}", file=sys.stderr, flush=True)

    ledger = build_source_ledger(day_cache_dir)
    _stage(f"ledger: {len(ledger['admitted'])} admitted; loading contexts")
    _starters, contexts = load_development_context(multiseason_dir, sorted(season_set))
    _stage(f"contexts: {len(contexts)}; aggregating batter-games")
    history, rejections, opened = build_batter_game_history(
        day_cache_dir, ledger["admitted"], contexts
    )
    _stage(f"batter-games: {len(history)}; building profiles")
    builder = (
        build_batter_feature_snapshots
        if fast
        else build_batter_feature_snapshots_reference
    )
    snapshots = builder(history)
    _stage(f"snapshots: {len(snapshots)}; writing artifacts")

    opened_2025 = sum(1 for row in opened if str(row["game_date"]).startswith("2025"))
    if opened_2025:
        raise BatterExtractionError("a locked-2025 file was opened")

    output_dir.mkdir(parents=True, exist_ok=True)
    full_ledger = [
        {k: v for k, v in row.items()} for row in (*opened, *ledger["rejected"])
    ]
    full_ledger.sort(key=lambda row: (str(row.get("opened")), row["relative_path"]))
    row_counts = {
        "batter_game_history.parquet": _write_parquet(
            output_dir / "batter_game_history.parquet", history
        ),
        "batter_features.parquet": _write_parquet(
            output_dir / "batter_features.parquet", snapshots
        ),
        "source_file_ledger.jsonl": _write_jsonl(
            output_dir / "source_file_ledger.jsonl", full_ledger
        ),
        "rejections.jsonl": _write_jsonl(output_dir / "rejections.jsonl", rejections),
    }
    eligible = sum(bool(row["profile_feature_eligible"]) for row in snapshots)
    coverage = {
        "schema_version": "batter_extraction_coverage.v1",
        "extraction_version": BATTER_EXTRACTION_VERSION,
        "feature_version": BATTER_FEATURE_VERSION,
        "seasons": sorted(season_set),
        "source_authority": SOURCE_AUTHORITY,
        "day_files_opened": len(opened),
        "day_files_opened_2025": opened_2025,
        "distinct_batters": len({int(row["batter_id"]) for row in history}),
        "batter_game_rows": len(history),
        "batter_feature_snapshot_rows": len(snapshots),
        "profile_feature_eligible_rows": eligible,
        "profile_feature_eligible_pct": round(100.0 * eligible / len(snapshots), 6)
        if snapshots
        else 0.0,
        "historical_lineup_timing_available": False,
        "history_partition_identity": _identity(history),
        "feature_partition_identity": _identity(snapshots),
        "source_file_ledger_identity": _identity(full_ledger),
        "batter_identity_basis": "POSTGAME_PLATE_APPEARANCE_ATTRIBUTION",
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
        "schema_version": "batter_extraction_manifest.v1",
        "producing_commit": producing_commit,
        "extraction_version": BATTER_EXTRACTION_VERSION,
        "feature_version": BATTER_FEATURE_VERSION,
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
    parser.add_argument("--reference-slow", action="store_true")
    args = parser.parse_args(argv)
    result = generate_batter_package(
        day_cache_dir=args.day_cache_dir,
        multiseason_dir=args.multiseason_dir,
        output_dir=args.output_dir,
        producing_commit=args.producing_commit,
        seasons=args.seasons,
        fast=not args.reference_slow,
    )
    print(json.dumps(result["coverage"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
