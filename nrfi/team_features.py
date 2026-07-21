"""Strict-prior team first-inning offense/prevention features (2015-2024).

Deterministic, leakage-free team features sourced only from the committed
2015-2024 multiseason first-inning outcomes.  For each game two team-side
records are emitted (the away club batted for `away_runs` and allowed
`home_runs` in the first; the home club the reverse).  Strict-prior snapshots
aggregate ONLY prior games whose outcome label was available before the target
game's prediction cutoff, excluding the target game, over career / last-10 /
last-25 / last-50 windows plus a season-to-date window and home/away splits.
The locked 2025 season is never read.  A compact terminal per-team projection
(one row per team, complete-history as-of end of 2024) is the live-servable join
table, analogous to the terminal batter projection.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from nrfi.pitcher_statcast import (
    _identity,
    _ratio,
    _write_json,
    _write_jsonl,
    canonical_json_bytes,
)

TEAM_EXTRACTION_VERSION = "team-first-inning-strict-prior-2015-2024-v1"
TEAM_FEATURE_VERSION = "team-first-inning-strict-prior-v1"
TEAM_TERMINAL_VERSION = "team-first-inning-terminal-2015-2024-v1"
ADMITTED_MIN_SEASON = 2015
ADMITTED_MAX_SEASON = 2024
LOCKED_HOLDOUT_SEASON = 2025
MINIMUM_PRIOR_GAMES = 20
WINDOWS: tuple[tuple[str, int | None], ...] = (
    ("last_10", 10),
    ("last_25", 25),
    ("last_50", 50),
    ("career", None),
)
_SUM_FIELDS = (
    "games",
    "runs_scored",
    "runs_allowed",
    "scored",
    "allowed",
    "off_scoreless",
    "def_scoreless",
)


class TeamFeatureError(ValueError):
    """Raised when team feature construction violates its fail-closed contract."""


def _season(official_date: str) -> int:
    return int(str(official_date)[:4])


def load_games(
    multiseason_dir: Path,
) -> tuple[list[dict[str, Any]], dict[int, str]]:
    """Load normalized games + per-game prediction cutoffs (2015-2024 only)."""
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
    games: list[dict[str, Any]] = []
    for line in games_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        game = json.loads(line)
        if _season(game["official_date"]) == LOCKED_HOLDOUT_SEASON:
            raise TeamFeatureError("refused a locked-2025 game")
        games.append(game)
    return games, cutoffs


def build_team_game_records(
    games: Sequence[Mapping[str, Any]], cutoffs: Mapping[int, str]
) -> list[dict[str, Any]]:
    """Two canonical team-side first-inning records per completed R game."""
    records: list[dict[str, Any]] = []
    for game in games:
        if game.get("game_type") != "R":
            continue
        first = game.get("first_inning") or {}
        if not first.get("completed"):
            continue
        game_pk = int(game["game_pk"])
        official_date = str(game["official_date"])
        season = _season(official_date)
        if season < ADMITTED_MIN_SEASON or season > ADMITTED_MAX_SEASON:
            continue
        cutoff = cutoffs.get(game_pk)
        if cutoff is None:
            continue
        away_runs = int(first["away_runs"])
        home_runs = int(first["home_runs"])
        away_id = int(game["away_team"]["team_id"])
        home_id = int(game["home_team"]["team_id"])
        base = {
            "schema_version": "team_game_first_inning.v1",
            "game_pk": game_pk,
            "official_date": official_date,
            "season": season,
            "scheduled_start_at": str(game["scheduled_start_at"]),
            "label_available_at": str(game["time_semantics"]["label_available_at"]),
            "prediction_cutoff": cutoff,
        }
        for team_id, opp_id, is_home, scored_runs, allowed_runs in (
            (away_id, home_id, False, away_runs, home_runs),
            (home_id, away_id, True, home_runs, away_runs),
        ):
            records.append(
                {
                    **base,
                    "team_id": team_id,
                    "opponent_team_id": opp_id,
                    "is_home": is_home,
                    "runs_scored": scored_runs,
                    "runs_allowed": allowed_runs,
                    "scored": 1 if scored_runs > 0 else 0,
                    "allowed": 1 if allowed_runs > 0 else 0,
                    "off_scoreless": 1 if scored_runs == 0 else 0,
                    "def_scoreless": 1 if allowed_runs == 0 else 0,
                }
            )
    records.sort(
        key=lambda row: (row["scheduled_start_at"], row["game_pk"], row["team_id"])
    )
    return records


def _totals(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    totals = {field: 0 for field in _SUM_FIELDS}
    for row in rows:
        totals["games"] += 1
        for field in _SUM_FIELDS[1:]:
            totals[field] += int(row[field])
    return totals


def _metrics(t: Mapping[str, int]) -> dict[str, float | None]:
    g = t["games"]
    return {
        "first_inning_runs_scored_per_game": _ratio(t["runs_scored"], g),
        "first_inning_runs_allowed_per_game": _ratio(t["runs_allowed"], g),
        "first_inning_scored_rate": _ratio(t["scored"], g),
        "first_inning_allowed_rate": _ratio(t["allowed"], g),
        "offense_scoreless_rate": _ratio(t["off_scoreless"], g),
        "defense_scoreless_rate": _ratio(t["def_scoreless"], g),
    }


def _window_values(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for name, length in WINDOWS:
        window = rows if length is None else rows[-length:]
        totals = _totals(window)
        values[f"prior_games_{name}"] = totals["games"]
        values.update({f"{m}_{name}": v for m, v in _metrics(totals).items()})
    home_rows = [r for r in rows if r["is_home"]]
    away_rows = [r for r in rows if not r["is_home"]]
    values["home_scored_rate"] = _ratio(
        sum(r["scored"] for r in home_rows), len(home_rows)
    )
    values["home_allowed_rate"] = _ratio(
        sum(r["allowed"] for r in home_rows), len(home_rows)
    )
    values["away_scored_rate"] = _ratio(
        sum(r["scored"] for r in away_rows), len(away_rows)
    )
    values["away_allowed_rate"] = _ratio(
        sum(r["allowed"] for r in away_rows), len(away_rows)
    )
    return values


def _by_team(
    records: Sequence[Mapping[str, Any]],
) -> dict[int, list[Mapping[str, Any]]]:
    grouped: dict[int, list[Mapping[str, Any]]] = {}
    for row in records:
        grouped.setdefault(int(row["team_id"]), []).append(row)
    for rows in grouped.values():
        rows.sort(key=lambda row: (row["scheduled_start_at"], row["game_pk"]))
    return grouped


def build_team_feature_snapshots(
    records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Strict-prior snapshot per (game_pk, team_id): prior games only."""
    snapshots: list[dict[str, Any]] = []
    for team_id, rows in _by_team(records).items():
        prior: list[Mapping[str, Any]] = []
        season_rows: list[Mapping[str, Any]] = []
        current_season: int | None = None
        for target in rows:
            if target["season"] != current_season:
                current_season = target["season"]
                season_rows = [r for r in prior if r["season"] == current_season]
            values = _window_values(prior)
            std = _totals(season_rows)
            values["prior_games_season_to_date"] = std["games"]
            values.update({f"{m}_season_to_date": v for m, v in _metrics(std).items()})
            career_games = len(prior)
            core = {
                "schema_version": "team_feature_snapshot.v1",
                "feature_version": TEAM_FEATURE_VERSION,
                "game_pk": int(target["game_pk"]),
                "team_id": int(team_id),
                "opponent_team_id": int(target["opponent_team_id"]),
                "is_home": bool(target["is_home"]),
                "official_date": target["official_date"],
                "prediction_cutoff": target["prediction_cutoff"],
                "prior_games": career_games,
                "team_context_feature_eligible": career_games >= MINIMUM_PRIOR_GAMES,
                "minimum_history_met": career_games >= MINIMUM_PRIOR_GAMES,
                "feature_values": values,
            }
            snapshots.append({**core, "feature_hash": _identity(core)})
            prior.append(target)
            if target["season"] == current_season:
                season_rows.append(target)
    snapshots.sort(
        key=lambda row: (row["prediction_cutoff"], row["game_pk"], row["team_id"])
    )
    return snapshots


def build_terminal_team_profiles(
    records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """One terminal team profile over the complete 2015-2024 history per team."""
    profiles: list[dict[str, Any]] = []
    for team_id, rows in _by_team(records).items():
        if any(r["season"] == LOCKED_HOLDOUT_SEASON for r in rows):
            raise TeamFeatureError("terminal team profile touched locked 2025")
        values = _window_values(rows)
        last = rows[-1]
        core = {
            "schema_version": "team_terminal_profile.v1",
            "profile_version": TEAM_TERMINAL_VERSION,
            "feature_version": TEAM_FEATURE_VERSION,
            "team_id": int(team_id),
            "career_games": len(rows),
            "team_context_feature_eligible": len(rows) >= MINIMUM_PRIOR_GAMES,
            "as_of_official_date": str(last["official_date"]),
            "as_of_season": int(last["season"]),
            "feature_values": values,
        }
        profiles.append({**core, "feature_hash": _identity(core)})
    profiles.sort(key=lambda row: int(row["team_id"]))
    return profiles


def terminal_team_projection_bytes(profiles: Sequence[Mapping[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(row) for row in profiles)


def generate(multiseason_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Build team records, snapshots, and the terminal projection."""
    games, cutoffs = load_games(multiseason_dir)
    records = build_team_game_records(games, cutoffs)
    snapshots = build_team_feature_snapshots(records)
    terminal = build_terminal_team_profiles(records)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "team_game_records.jsonl", records)
    _write_jsonl(output_dir / "team_features.jsonl", snapshots)
    projection = terminal_team_projection_bytes(terminal)
    (output_dir / "team_terminal_profiles.jsonl").write_bytes(projection)
    eligible = sum(1 for p in terminal if p["team_context_feature_eligible"])
    import hashlib

    coverage = {
        "schema_version": "team_feature_coverage.v1",
        "extraction_version": TEAM_EXTRACTION_VERSION,
        "feature_version": TEAM_FEATURE_VERSION,
        "terminal_version": TEAM_TERMINAL_VERSION,
        "team_game_records": len(records),
        "team_feature_snapshots": len(snapshots),
        "distinct_teams": len(terminal),
        "terminal_eligible_teams": eligible,
        "records_identity": _identity(records),
        "features_identity": _identity(snapshots),
        "terminal_identity": _identity(terminal),
        "terminal_projection_sha256": hashlib.sha256(projection).hexdigest(),
        "seasons": sorted({r["season"] for r in records}),
        "locked_2025_holdout_accessed": False,
    }
    _write_json(output_dir / "team_coverage.json", coverage)
    return coverage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--multiseason-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    coverage = generate(args.multiseason_dir, args.output_dir)
    print(json.dumps(coverage, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
