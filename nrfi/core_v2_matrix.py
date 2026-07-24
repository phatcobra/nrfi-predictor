"""Canonical NRFI_CORE_V2 historical feature matrix (2015-2024).

One deterministic game-level matrix joining the newly engineered strict-prior
artifacts — pitcher Statcast (`pitcher-statcast-strict-prior-v1`), team
first-inning (`team-first-inning-strict-prior-v1`), and Context Foundation V1
park / schedule / travel / workload (`context-foundation-strict-prior-v1`) — via
their shared semantic reproducers. Every joined feature is strict-prior (prior
games only, label available before the target game's prediction cutoff, target
excluded). The first-inning NRFI target comes from the committed normalized
games. The locked 2025 season is never read; the current and future games are
absent by construction. This is NOT a rename of the legacy fv3.1 matrix.

The matrix is the shared input for training, chronological evaluation,
deterministic replay, AWS Batch, and (feature-definition) live inference.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from nrfi.context_features import (
    build_context_feature_set,
    build_side_schedule_log,
    load_venue_reference,
)
from nrfi.context_features import load_games as load_context_games
from nrfi.pregame_snapshot import canonical_json_bytes
from nrfi.team_features import (
    build_team_feature_snapshots,
    build_team_game_records,
)
from nrfi.team_features import load_games as load_team_games

CONTRACT_NAME = "NRFI_CORE_V2"
MATRIX_SCHEMA_VERSION = "nrfi_core_v2_matrix.v1"
ADMITTED_MIN_SEASON = 2015
ADMITTED_MAX_SEASON = 2024
LOCKED_HOLDOUT_SEASON = 2025

# Row-exclusion reason codes.
NO_COMPLETED_FIRST_INNING = "NO_COMPLETED_FIRST_INNING"
LABEL_UNAVAILABLE = "LABEL_UNAVAILABLE"
AMBIGUOUS_GAME_IDENTITY = "AMBIGUOUS_GAME_IDENTITY"
MISSING_PITCHER_SIDE = "MISSING_PITCHER_SIDE"
MISSING_TEAM_SIDE = "MISSING_TEAM_SIDE"
MISSING_CONTEXT_SIDE = "MISSING_CONTEXT_SIDE"


class CoreV2MatrixError(ValueError):
    """Raised when matrix construction violates its fail-closed contract."""


def _identity(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _season(official_date: str) -> int:
    return int(str(official_date)[:4])


def _numeric_features(feature_values: Mapping[str, Any], prefix: str) -> dict[str, Any]:
    """Flatten a feature_values mapping to a prefixed numeric dict (None->null)."""
    out: dict[str, Any] = {}
    for key in sorted(feature_values):
        value = feature_values[key]
        if isinstance(value, bool):
            out[f"{prefix}{key}"] = 1.0 if value else 0.0
        elif value is None:
            out[f"{prefix}{key}"] = None
        elif isinstance(value, (int, float)):
            out[f"{prefix}{key}"] = float(value)
        # non-numeric feature_values (strings such as day_night) are dropped from
        # the numeric matrix but their eligibility is captured by the flags.
    return out


def load_pitcher_features(
    parquet_path: Path,
) -> dict[tuple[int, str], dict[str, Any]]:
    """Load strict-prior pitcher feature snapshots keyed by (game_pk, side)."""
    import importlib

    pq = importlib.import_module("pyarrow.parquet")
    table = pq.read_table(parquet_path)
    rows = table.to_pylist()
    out: dict[tuple[int, str], dict[str, Any]] = {}
    for row in rows:
        key = (int(row["game_pk"]), str(row["side"]))
        fv = row.get("feature_values")
        if isinstance(fv, str):
            fv = json.loads(fv)
        out[key] = {
            "pitcher_id": row.get("pitcher_id"),
            "profile_feature_eligible": bool(row.get("profile_feature_eligible")),
            "feature_values": fv or {},
        }
    return out


def _team_by_side(
    multiseason_dir: Path,
) -> dict[tuple[int, bool], dict[str, Any]]:
    games, cutoffs = load_team_games(multiseason_dir)
    records = build_team_game_records(games, cutoffs)
    snapshots = build_team_feature_snapshots(records)
    return {(int(s["game_pk"]), bool(s["is_home"])): s for s in snapshots}


def _context_by_side(
    multiseason_dir: Path, venue_reference_path: Path
) -> dict[tuple[int, bool], dict[str, Any]]:
    games, cutoffs = load_context_games(multiseason_dir)
    reference = load_venue_reference(venue_reference_path)
    rows = build_side_schedule_log(games, cutoffs)
    snapshots = build_context_feature_set(rows, reference)
    return {(int(s["game_pk"]), bool(s["is_home"])): s for s in snapshots}


def _target_rows(
    multiseason_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Game-level target rows + prediction cutoffs; deterministic exclusions."""
    games_path = multiseason_dir / "normalized_games.jsonl"
    features_path = multiseason_dir / "features.jsonl"
    cutoffs: dict[int, str] = {}
    for line in features_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        cutoff = row.get("prediction_cutoff")
        if isinstance(cutoff, str):
            cutoffs[int(row["game_pk"])] = cutoff
    seen: set[int] = set()
    duplicates: set[int] = set()
    targets: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    for line in games_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        game = json.loads(line)
        if _season(game["official_date"]) == LOCKED_HOLDOUT_SEASON:
            raise CoreV2MatrixError("refused a locked-2025 game")
        if game.get("game_type") != "R":
            continue
        game_pk = int(game["game_pk"])
        if game_pk in seen:
            duplicates.add(game_pk)
            continue
        seen.add(game_pk)
        first = game.get("first_inning") or {}
        official_date = str(game["official_date"])
        cutoff = cutoffs.get(game_pk)
        if not first.get("completed"):
            rejections.append({"game_pk": game_pk, "reason": NO_COMPLETED_FIRST_INNING})
            continue
        if cutoff is None:
            rejections.append({"game_pk": game_pk, "reason": LABEL_UNAVAILABLE})
            continue
        total = int(first["away_runs"]) + int(first["home_runs"])
        targets.append(
            {
                "game_pk": game_pk,
                "official_date": official_date,
                "season": _season(official_date),
                "scheduled_start_at": str(game["scheduled_start_at"]),
                "prediction_cutoff": cutoff,
                "away_team_id": int(game["away_team"]["team_id"]),
                "home_team_id": int(game["home_team"]["team_id"]),
                "venue_id": int(game["venue"]["venue_id"]),
                "nrfi": 1 if total == 0 else 0,
                "yrfi": 1 if total > 0 else 0,
            }
        )
    for game_pk in sorted(duplicates):
        rejections.append({"game_pk": game_pk, "reason": AMBIGUOUS_GAME_IDENTITY})
    targets.sort(key=lambda r: (r["prediction_cutoff"], r["game_pk"]))
    rejections.sort(key=lambda r: (r["reason"], r["game_pk"]))
    return targets, {"rejections": rejections}


def build_matrix(
    multiseason_dir: Path,
    pitcher_parquet: Path,
    venue_reference_path: Path,
) -> dict[str, Any]:
    """Join all strict-prior domains into the canonical game-level matrix."""
    targets, target_meta = _target_rows(multiseason_dir)
    rejections = list(target_meta["rejections"])
    pitcher = load_pitcher_features(pitcher_parquet)
    team = _team_by_side(multiseason_dir)
    context = _context_by_side(multiseason_dir, venue_reference_path)

    matrix: list[dict[str, Any]] = []
    for tgt in targets:
        game_pk = int(tgt["game_pk"])
        row_reject: list[str] = []
        features: dict[str, Any] = {}
        eligibility: dict[str, Any] = {}
        park_recorded = False
        for side, is_home in (("away", False), ("home", True)):
            p = pitcher.get((game_pk, side))
            t = team.get((game_pk, is_home))
            c = context.get((game_pk, is_home))
            if p is None:
                row_reject.append(f"{side}:{MISSING_PITCHER_SIDE}")
            else:
                features.update(_numeric_features(p["feature_values"], f"{side}_p_"))
                eligibility[f"{side}_pitcher_profile_eligible"] = bool(
                    p["profile_feature_eligible"]
                )
            if t is None:
                row_reject.append(f"{side}:{MISSING_TEAM_SIDE}")
            else:
                features.update(_numeric_features(t["feature_values"], f"{side}_t_"))
                eligibility[f"{side}_team_context_eligible"] = bool(
                    t.get("team_context_feature_eligible")
                )
            if c is None:
                row_reject.append(f"{side}:{MISSING_CONTEXT_SIDE}")
            else:
                cv = c["feature_values"]
                features.update(_numeric_features(cv, f"{side}_ctx_"))
                eligibility[f"{side}_workload_eligible"] = bool(
                    c.get("workload_feature_eligible")
                )
                eligibility[f"{side}_schedule_travel_eligible"] = bool(
                    c.get("schedule_travel_feature_eligible")
                )
                if not park_recorded:
                    eligibility["park_context_eligible"] = bool(
                        c.get("park_context_feature_eligible")
                    )
                    features["park_factor"] = cv.get("park_factor")
                    features["park_first_inning_runs_per_game"] = cv.get(
                        "park_first_inning_runs_per_game"
                    )
                    features["altitude_ft"] = (
                        float(cv["altitude_ft"])
                        if cv.get("altitude_ft") is not None
                        else None
                    )
                    park_recorded = True
        core_eligible = (
            not row_reject
            and eligibility.get("away_pitcher_profile_eligible") is True
            and eligibility.get("home_pitcher_profile_eligible") is True
            and eligibility.get("away_team_context_eligible") is True
            and eligibility.get("home_team_context_eligible") is True
            and eligibility.get("park_context_eligible") is True
            and eligibility.get("away_workload_eligible") is True
            and eligibility.get("home_workload_eligible") is True
            and eligibility.get("away_schedule_travel_eligible") is True
            and eligibility.get("home_schedule_travel_eligible") is True
        )
        eligibility["core_model_feature_eligible"] = bool(core_eligible)
        core = {
            "schema_version": MATRIX_SCHEMA_VERSION,
            "contract_name": CONTRACT_NAME,
            "game_pk": game_pk,
            "official_date": tgt["official_date"],
            "season": int(tgt["season"]),
            "scheduled_start_at": tgt["scheduled_start_at"],
            "prediction_cutoff": tgt["prediction_cutoff"],
            "away_team_id": int(tgt["away_team_id"]),
            "home_team_id": int(tgt["home_team_id"]),
            "venue_id": int(tgt["venue_id"]),
            "nrfi": int(tgt["nrfi"]),
            "yrfi": int(tgt["yrfi"]),
            "eligibility": eligibility,
            "row_rejection_reasons": sorted(set(row_reject)),
            "features": features,
        }
        matrix.append({**core, "row_hash": _identity(core)})
    matrix.sort(key=lambda r: (r["prediction_cutoff"], r["game_pk"]))
    coverage = {
        "schema_version": "nrfi_core_v2_matrix_coverage.v1",
        "contract_name": CONTRACT_NAME,
        "matrix_rows": len(matrix),
        "target_rows": len(targets),
        "excluded_rows": len(rejections),
        "core_model_feature_eligible_rows": sum(
            1 for r in matrix if r["eligibility"]["core_model_feature_eligible"]
        ),
        "nrfi_rows": sum(1 for r in matrix if r["nrfi"] == 1),
        "yrfi_rows": sum(1 for r in matrix if r["yrfi"] == 1),
        "seasons": sorted({int(r["season"]) for r in matrix}),
        "matrix_identity": _identity(matrix),
        "rejection_identity": _identity(rejections),
        "feature_column_count": len(matrix[0]["features"]) if matrix else 0,
        "locked_2025_holdout_accessed": False,
    }
    return {"matrix": matrix, "rejections": rejections, "coverage": coverage}


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        for row in rows:
            handle.write(canonical_json_bytes(row))


def generate(
    multiseason_dir: Path,
    pitcher_parquet: Path,
    venue_reference_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    result = build_matrix(multiseason_dir, pitcher_parquet, venue_reference_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "core_v2_matrix.jsonl", result["matrix"])
    _write_jsonl(output_dir / "core_v2_rejections.jsonl", result["rejections"])
    path = output_dir / "core_v2_coverage.json"
    path.write_bytes(canonical_json_bytes(result["coverage"]))
    return result["coverage"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--multiseason-dir", type=Path, required=True)
    parser.add_argument("--pitcher-parquet", type=Path, required=True)
    parser.add_argument("--venue-reference", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    coverage = generate(
        args.multiseason_dir,
        args.pitcher_parquet,
        args.venue_reference,
        args.output_dir,
    )
    print(json.dumps(coverage, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
