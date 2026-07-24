"""Canonical NRFI_CORE_V2_2_ADMISSIBLE starter-INDEPENDENT feature matrix.

One deterministic game-level matrix for the admissible V2.2 program. It joins
ONLY starter-independent strict-prior domains:

  * team first-inning (`team-first-inning-strict-prior-v1`), and
  * the versioned IANA context path (`context-foundation-iana-strict-prior-v2_2`)
    contributing park factors and DST-aware schedule / travel geometry.

It contains NO pitcher, starter, workload, lineup, batter, weather, umpire, or
market feature of any kind, and never reads the locked 2025 season. Continuous
features carry explicit missingness indicators (separating the missingness
regime from schema drift); categoricals are fixed-vocabulary one-hot encodings.
A hard forbidden-column guard fails the build closed if any starter-dependent or
2025 column ever leaks in.

Primary (model + baseline) eligibility requires BOTH team contexts, the park
context, and BOTH sides' schedule/travel to be eligible; the model and the
expanding-climatology baseline are scored on exactly these identical rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from nrfi.context_features import load_venue_reference
from nrfi.context_features import load_games as load_context_games
from nrfi.context_features_iana import (
    build_iana_context_feature_set,
    build_iana_side_log,
    force_tzdata_only,
)
from nrfi.pregame_snapshot import canonical_json_bytes
from nrfi.team_features import (
    build_team_feature_snapshots,
    build_team_game_records,
)
from nrfi.team_features import load_games as load_team_games

CONTRACT_NAME = "NRFI_CORE_V2_2_ADMISSIBLE"
MATRIX_SCHEMA_VERSION = "nrfi_core_v2_2_matrix.v1"
TIMEZONE_MODE = "iana"
ADMITTED_MIN_SEASON = 2015
ADMITTED_MAX_SEASON = 2024
LOCKED_HOLDOUT_SEASON = 2025

NO_COMPLETED_FIRST_INNING = "NO_COMPLETED_FIRST_INNING"
LABEL_UNAVAILABLE = "LABEL_UNAVAILABLE"
AMBIGUOUS_GAME_IDENTITY = "AMBIGUOUS_GAME_IDENTITY"
MISSING_TEAM_SIDE = "MISSING_TEAM_SIDE"
MISSING_CONTEXT_SIDE = "MISSING_CONTEXT_SIDE"

# Hard forbidden-column guard. Any of these substrings (or side-prefixed
# patterns) appearing in a feature column fails the build closed.
FORBIDDEN_SUBSTRINGS: tuple[str, ...] = (
    "pitcher",
    "starter",
    "workload",
    "lineup",
    "batter",
    "weather",
    "umpire",
    "market",
    "2025",
)
FORBIDDEN_PREFIX_PATTERNS: tuple[str, ...] = (
    "away_p_",
    "home_p_",
    "away_ctx_starter_",
    "home_ctx_starter_",
)

# Fixed categorical vocabularies (exhaustive by construction). An observed
# non-null category outside its vocabulary is schema drift and fails closed;
# a null value is an ordinary missing observation and sets a _missing flag.
CATEGORICAL_VOCAB: dict[str, tuple[str, ...]] = {
    "day_night": ("day", "night"),
    "prior_day_night": ("day", "night"),
    "trip_kind": ("home_stand", "road_trip"),
    "doubleheader_code": ("N", "Y", "S"),
}

# Per-side travel keys (differ by club within a game).
SIDE_CONTINUOUS: tuple[str, ...] = (
    "rest_days",
    "games_prior_3d",
    "games_prior_7d",
    "travel_miles",
    "tz_shift_hours",
    "prior_utc_offset_hours",
    "trip_game_index",
)
SIDE_BINARY: tuple[str, ...] = (
    "has_prior_game",
    "trip_is_first_game",
    "prior_dst_active",
    "night_to_day_turnaround",
)
SIDE_CATEGORICAL: tuple[str, ...] = ("prior_day_night", "trip_kind")

# Game-level venue/time keys (identical for both clubs of a game).
GAME_CONTINUOUS: tuple[str, ...] = (
    "local_scheduled_hour",
    "current_utc_offset_hours",
    "altitude_ft",
    "doubleheader_game_number",
)
GAME_BINARY: tuple[str, ...] = ("dst_active", "doubleheader")
GAME_CATEGORICAL: tuple[str, ...] = ("day_night", "doubleheader_code")
PARK_CONTINUOUS: tuple[str, ...] = (
    "park_factor",
    "park_first_inning_runs_per_game",
    "league_first_inning_runs_per_game",
    "park_prior_games_at_venue",
)


class CoreV22MatrixError(ValueError):
    """Raised when V2.2 matrix construction violates its fail-closed contract."""


def _identity(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _season(official_date: str) -> int:
    return int(str(official_date)[:4])


def assert_admissible_columns(columns: Sequence[str]) -> None:
    """Fail closed if any starter-dependent / 2025 column leaks into the matrix."""
    for col in columns:
        low = col.lower()
        for banned in FORBIDDEN_SUBSTRINGS:
            if banned in low:
                raise CoreV22MatrixError(
                    f"forbidden feature column '{col}' contains banned token '{banned}'"
                )
        for pattern in FORBIDDEN_PREFIX_PATTERNS:
            if low.startswith(pattern):
                raise CoreV22MatrixError(
                    f"forbidden feature column '{col}' matches banned pattern '{pattern}'"
                )


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _emit_continuous(
    out: dict[str, Any], schema: dict[str, str], prefix: str, name: str, value: Any
) -> None:
    col = f"{prefix}{name}"
    num = _num(value)
    out[col] = num
    out[f"{col}_missing"] = 1.0 if num is None else 0.0
    schema[col] = "continuous"
    schema[f"{col}_missing"] = "missing_indicator"


def _emit_binary(
    out: dict[str, Any], schema: dict[str, str], prefix: str, name: str, value: Any
) -> None:
    col = f"{prefix}{name}"
    if value is None:
        out[col] = 0.0
        out[f"{col}_missing"] = 1.0
    else:
        out[col] = 1.0 if bool(value) else 0.0
        out[f"{col}_missing"] = 0.0
    schema[col] = "binary"
    schema[f"{col}_missing"] = "missing_indicator"


def _emit_categorical(
    out: dict[str, Any], schema: dict[str, str], prefix: str, name: str, value: Any
) -> None:
    vocab = CATEGORICAL_VOCAB[name]
    if value is not None and str(value) not in vocab:
        raise CoreV22MatrixError(
            f"schema drift: categorical '{name}' saw unknown category '{value}'"
        )
    for cat in vocab:
        col = f"{prefix}{name}_{cat}"
        out[col] = 1.0 if (value is not None and str(value) == cat) else 0.0
        schema[col] = "onehot"
    miss = f"{prefix}{name}_missing"
    out[miss] = 1.0 if value is None else 0.0
    schema[miss] = "missing_indicator"


def _target_rows(
    multiseason_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
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
            raise CoreV22MatrixError("refused a locked-2025 game")
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
    return targets, rejections


def _team_by_side(multiseason_dir: Path) -> dict[tuple[int, bool], dict[str, Any]]:
    games, cutoffs = load_team_games(multiseason_dir)
    records = build_team_game_records(games, cutoffs)
    snapshots = build_team_feature_snapshots(records)
    return {(int(s["game_pk"]), bool(s["is_home"])): s for s in snapshots}


def _iana_context_by_side(
    multiseason_dir: Path, venue_reference_path: Path
) -> dict[tuple[int, bool], dict[str, Any]]:
    games, cutoffs = load_context_games(multiseason_dir)
    reference = load_venue_reference(venue_reference_path)
    rows = build_iana_side_log(games, cutoffs)
    snapshots = build_iana_context_feature_set(rows, reference)
    return {(int(s["game_pk"]), bool(s["is_home"])): s for s in snapshots}


def build_matrix(
    multiseason_dir: Path,
    venue_reference_path: Path,
) -> dict[str, Any]:
    targets, rejections = _target_rows(multiseason_dir)
    team = _team_by_side(multiseason_dir)
    context = _iana_context_by_side(multiseason_dir, venue_reference_path)

    schema: dict[str, str] = {}
    matrix: list[dict[str, Any]] = []
    for tgt in targets:
        game_pk = int(tgt["game_pk"])
        row_reject: list[str] = []
        features: dict[str, Any] = {}
        eligibility: dict[str, Any] = {}
        game_level_done = False
        for side, is_home in (("away", False), ("home", True)):
            t = team.get((game_pk, is_home))
            c = context.get((game_pk, is_home))
            if t is None:
                row_reject.append(f"{side}:{MISSING_TEAM_SIDE}")
            else:
                for key in sorted(t["feature_values"]):
                    _emit_continuous(
                        features, schema, f"{side}_t_", key, t["feature_values"][key]
                    )
                eligibility[f"{side}_team_context_eligible"] = bool(
                    t.get("team_context_feature_eligible")
                )
            if c is None:
                row_reject.append(f"{side}:{MISSING_CONTEXT_SIDE}")
                continue
            cv = c["feature_values"]
            for name in SIDE_CONTINUOUS:
                _emit_continuous(features, schema, f"{side}_", name, cv.get(name))
            for name in SIDE_BINARY:
                _emit_binary(features, schema, f"{side}_", name, cv.get(name))
            for name in SIDE_CATEGORICAL:
                _emit_categorical(features, schema, f"{side}_", name, cv.get(name))
            eligibility[f"{side}_schedule_travel_eligible"] = bool(
                c.get("schedule_travel_feature_eligible")
            )
            if is_home and not game_level_done:
                for name in GAME_CONTINUOUS:
                    _emit_continuous(features, schema, "g_", name, cv.get(name))
                for name in GAME_BINARY:
                    _emit_binary(features, schema, "g_", name, cv.get(name))
                for name in GAME_CATEGORICAL:
                    _emit_categorical(features, schema, "g_", name, cv.get(name))
                for name in PARK_CONTINUOUS:
                    _emit_continuous(features, schema, "park_", name, cv.get(name))
                eligibility["park_context_eligible"] = bool(
                    c.get("park_context_feature_eligible")
                )
                game_level_done = True
        primary_eligible = (
            not row_reject
            and eligibility.get("away_team_context_eligible") is True
            and eligibility.get("home_team_context_eligible") is True
            and eligibility.get("park_context_eligible") is True
            and eligibility.get("away_schedule_travel_eligible") is True
            and eligibility.get("home_schedule_travel_eligible") is True
        )
        eligibility["primary_feature_eligible"] = bool(primary_eligible)
        core = {
            "schema_version": MATRIX_SCHEMA_VERSION,
            "contract_name": CONTRACT_NAME,
            "timezone_mode": TIMEZONE_MODE,
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
    all_columns = sorted(schema)
    assert_admissible_columns(all_columns)
    coverage = {
        "schema_version": "nrfi_core_v2_2_matrix_coverage.v1",
        "contract_name": CONTRACT_NAME,
        "timezone_mode": TIMEZONE_MODE,
        "matrix_rows": len(matrix),
        "target_rows": len(targets),
        "excluded_rows": len(rejections),
        "primary_feature_eligible_rows": sum(
            1 for r in matrix if r["eligibility"]["primary_feature_eligible"]
        ),
        "nrfi_rows": sum(1 for r in matrix if r["nrfi"] == 1),
        "yrfi_rows": sum(1 for r in matrix if r["yrfi"] == 1),
        "seasons": sorted({int(r["season"]) for r in matrix}),
        "matrix_identity": _identity(matrix),
        "rejection_identity": _identity(rejections),
        "feature_column_count": len(all_columns),
        "feature_schema": {c: schema[c] for c in all_columns},
        "categorical_vocab": {k: list(v) for k, v in sorted(CATEGORICAL_VOCAB.items())},
        "forbidden_substrings": list(FORBIDDEN_SUBSTRINGS),
        "forbidden_prefix_patterns": list(FORBIDDEN_PREFIX_PATTERNS),
        "starter_independent": True,
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
    venue_reference_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Isolated offline V2.2 matrix build (forces tzdata-only for IANA context)."""
    force_tzdata_only()
    result = build_matrix(multiseason_dir, venue_reference_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "core_v2_2_matrix.jsonl", result["matrix"])
    _write_jsonl(output_dir / "core_v2_2_rejections.jsonl", result["rejections"])
    (output_dir / "core_v2_2_coverage.json").write_bytes(
        canonical_json_bytes(result["coverage"])
    )
    return result["coverage"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--multiseason-dir", type=Path, required=True)
    parser.add_argument("--venue-reference", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    coverage = generate(args.multiseason_dir, args.venue_reference, args.output_dir)
    print(json.dumps(coverage, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
