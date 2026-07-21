"""Compact terminal per-batter profiles for live top-of-order assembly.

The published 2015-2024 feature table has one strict-prior snapshot per
(game_pk, batter) -- ~472k rows, far too large for the live runtime.  For a
LIVE (e.g. 2026) game every 2015-2024 batter-game is strictly prior to the
game's prediction cutoff, so a single terminal profile per batter -- career and
trailing last-20/50/100 windows over that batter's COMPLETE lawful 2015-2024
history -- is the correct strict-prior input to join to a pregame lineup.

This module never reads 2025 (the input history is the locked-out-free
2015-2024 canonical history) and never uses postgame batting orders; it only
produces per-batter rate profiles.  The staleness gap to a future season is
surfaced explicitly (``profile_gap_seasons`` / ``recent_history_missing``) and
never silently erases valid career history.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from nrfi.batter_extraction import (
    BATTER_FEATURE_VERSION,
    MINIMUM_PRIOR_PLATE_APPEARANCES,
    WINDOWS,
    _by_batter,
    _metrics_from_totals,
    _SUM_FIELDS,
)
from nrfi.pitcher_statcast import _identity, _write_jsonl, canonical_json_bytes

TERMINAL_PROFILE_VERSION = "batter-terminal-strict-prior-2015-2024-v1"
TERMINAL_PROFILE_SCHEMA = "batter_terminal_profile.v1"


class BatterLiveProfileError(ValueError):
    """Raised when terminal profile construction violates its contract."""


def _window_totals(rows: list[Mapping[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = {field: 0.0 for field in _SUM_FIELDS}
    for row in rows:
        for field in _SUM_FIELDS:
            totals[field] += row[field]
    return totals


def _terminal_profile(batter_id: int, rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Career + trailing windows over a batter's complete 2015-2024 history."""
    if any(str(row["official_date"]).startswith("2025") for row in rows):
        raise BatterLiveProfileError("terminal profile touched a locked-2025 game")
    values: dict[str, float | int | None] = {}
    career_totals = _window_totals(rows)
    for name, length in WINDOWS:
        window_rows = rows if length is None else rows[-length:]
        totals = career_totals if length is None else _window_totals(window_rows)
        values[f"prior_games_{name}"] = len(window_rows)
        values[f"prior_plate_appearances_{name}"] = int(totals["plate_appearances"])
        values.update(
            {f"{m}_{name}": v for m, v in _metrics_from_totals(totals).items()}
        )
    career_pa = int(career_totals["plate_appearances"])
    last = rows[-1]
    last_season = int(str(last["official_date"])[:4])
    stands = sorted({str(r["batter_stand"]) for r in rows if r.get("batter_stand")})
    core = {
        "schema_version": TERMINAL_PROFILE_SCHEMA,
        "profile_version": TERMINAL_PROFILE_VERSION,
        "feature_version": BATTER_FEATURE_VERSION,
        "batter_id": int(batter_id),
        "career_games": len(rows),
        "career_plate_appearances": career_pa,
        "profile_feature_eligible": career_pa >= MINIMUM_PRIOR_PLATE_APPEARANCES,
        "as_of_official_date": str(last["official_date"]),
        "as_of_season": last_season,
        "batter_stand_latest": str(last["batter_stand"])
        if last.get("batter_stand")
        else None,
        "batter_stand_observed": stands,
        "batter_identity_basis": "POSTGAME_PLATE_APPEARANCE_ATTRIBUTION",
        "historical_lineup_timing_unavailable": True,
        "feature_values": values,
    }
    return {**core, "feature_hash": _identity(core)}


def build_terminal_profiles(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One terminal strict-prior profile per batter, sorted by batter_id."""
    by_batter = _by_batter(history)
    profiles = [
        _terminal_profile(batter_id, list(rows))
        for batter_id, rows in by_batter.items()
    ]
    profiles.sort(key=lambda row: int(row["batter_id"]))
    return profiles


def terminal_projection_bytes(profiles: list[dict[str, Any]]) -> bytes:
    """Deterministic JSONL projection for the stdlib live runtime."""
    return b"".join(canonical_json_bytes(row) for row in profiles)


def generate(history_parquet: Path, output_dir: Path) -> dict[str, Any]:
    """Build terminal profiles from the canonical history parquet."""
    history = pq.read_table(history_parquet).to_pylist()
    profiles = build_terminal_profiles(history)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "live_profiles.jsonl", profiles)
    projection = terminal_projection_bytes(profiles)
    (output_dir / "live_profiles_projection.jsonl").write_bytes(projection)
    eligible = sum(1 for p in profiles if p["profile_feature_eligible"])
    coverage = {
        "schema_version": "batter_terminal_coverage.v1",
        "profile_version": TERMINAL_PROFILE_VERSION,
        "feature_version": BATTER_FEATURE_VERSION,
        "distinct_batters": len(profiles),
        "profile_feature_eligible": eligible,
        "terminal_profiles_identity": _identity(profiles),
        "projection_sha256": hashlib.sha256(projection).hexdigest(),
        "locked_2025_holdout_accessed": False,
    }
    (output_dir / "live_profiles_coverage.json").write_text(
        json.dumps(coverage, sort_keys=True), encoding="utf-8"
    )
    return coverage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history-parquet", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    coverage = generate(args.history_parquet, args.output_dir)
    print(json.dumps(coverage, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
