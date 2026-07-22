"""Context Foundation V1 - one deterministic shared feature package (2015-2024).

A single, leakage-free implementation of pregame context features, reused
identically by training, replay, AWS Batch, the live collector, and the API.
It sources only the committed 2015-2024 multiseason schedule/outcomes plus a
committed, effective-dated venue reference (fixed stadium geography and
standard-time UTC offsets - no DST, no external tzdata, so the build is
byte-identical across environments).  The locked 2025 season is never read and
neither current nor future games are admitted.

Seven context dimensions are produced:
  * effective-dated park / venue context (identity, geography, altitude),
  * strictly-prior rolling first-inning park factors (per venue vs league),
  * starter workload and rest (days rest, starts in the trailing 30 days),
  * doubleheaders and schedule congestion (games in trailing 3 / 7 days),
  * travel distance and time-zone movement (great-circle miles, offset shift),
  * day / night classification and night->day short-turnaround transitions,
  * road-trip / home-stand position (consecutive same-side game index).

Anything derived from outcomes (park factors, workload) is strict-prior: only
games whose label was available before the target game's prediction cutoff,
excluding the target.  Schedule geometry (travel, congestion, road-trip,
day/night) is known pregame from the public schedule and is computed from the
club's strictly earlier games.  A compact terminal per-venue park projection
(complete 2015-2024 history) is the live-servable join table.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from nrfi.pregame_snapshot import canonical_json_bytes


def _identity(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    return float(numerator / denominator) if denominator else None


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


CONTEXT_EXTRACTION_VERSION = "context-foundation-2015-2024-v1"
CONTEXT_FEATURE_VERSION = "context-foundation-strict-prior-v1"
PARK_TERMINAL_VERSION = "park-first-inning-terminal-2015-2024-v1"
VENUE_REFERENCE_VERSION = "venue-reference-v1"

ADMITTED_MIN_SEASON = 2015
ADMITTED_MAX_SEASON = 2024
LOCKED_HOLDOUT_SEASON = 2025

PARK_MINIMUM_PRIOR_GAMES = 30
STARTER_MINIMUM_PRIOR_STARTS = 1
DAY_NIGHT_CUTOFF_HOUR = 17
CONGESTION_WINDOWS_DAYS: tuple[int, ...] = (3, 7)
STARTER_WORKLOAD_WINDOW_DAYS = 30
EARTH_RADIUS_MILES = 3958.7613


class ContextFeatureError(ValueError):
    """Raised when context feature construction violates its fail-closed contract."""


# --------------------------------------------------------------------------- #
# Venue reference + geometry (deterministic, no DST / tzdata dependency)
# --------------------------------------------------------------------------- #
def load_venue_reference(path: Path) -> dict[int, dict[str, Any]]:
    """Load the committed effective-dated venue reference, keyed by venue_id."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("reference_version") != VENUE_REFERENCE_VERSION:
        raise ContextFeatureError("unexpected venue reference version")
    venues = payload.get("venues")
    if not isinstance(venues, list) or not venues:
        raise ContextFeatureError("venue reference is empty")
    reference: dict[int, dict[str, Any]] = {}
    for row in venues:
        vid = int(row["venue_id"])
        reference[vid] = {
            "venue_id": vid,
            "name": str(row["name"]),
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
            "altitude_ft": int(row["altitude_ft"]),
            "utc_offset_standard_hours": float(row["utc_offset_standard_hours"]),
            "tz_label": str(row["tz_label"]),
        }
    return reference


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in statute miles, rounded to 3 decimals."""
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.asin(min(1.0, math.sqrt(a)))
    return round(EARTH_RADIUS_MILES * c, 3)


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def local_hour(scheduled_start_at: str, utc_offset_standard_hours: float) -> int:
    """Local clock hour under standard time (no DST), 0-23."""
    local = _parse_utc(scheduled_start_at) + timedelta(hours=utc_offset_standard_hours)
    return local.hour


def day_night(scheduled_start_at: str, utc_offset_standard_hours: float) -> str:
    return (
        "day"
        if local_hour(scheduled_start_at, utc_offset_standard_hours)
        < DAY_NIGHT_CUTOFF_HOUR
        else "night"
    )


def _season(official_date: str) -> int:
    return int(str(official_date)[:4])


# --------------------------------------------------------------------------- #
# Source loading
# --------------------------------------------------------------------------- #
def load_games(
    multiseason_dir: Path,
) -> tuple[list[dict[str, Any]], dict[int, str]]:
    """Load normalized R games + per-game prediction cutoffs (2015-2024 only)."""
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
            raise ContextFeatureError("refused a locked-2025 game")
        games.append(game)
    return games, cutoffs


def _starter_id(game: Mapping[str, Any], side: str) -> int | None:
    starters = game.get("actual_starters") or {}
    entry = starters.get(side) or {}
    pid = entry.get("player_id")
    return int(pid) if pid is not None else None


def build_side_schedule_log(
    games: Sequence[Mapping[str, Any]], cutoffs: Mapping[int, str]
) -> list[dict[str, Any]]:
    """Two club-side schedule rows per completed regular-season game."""
    rows: list[dict[str, Any]] = []
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
        venue_id = int(game["venue"]["venue_id"])
        start_at = str(game["scheduled_start_at"])
        dh_code = str(game.get("doubleheader_code", "N"))
        game_number = int(game.get("game_number", 1))
        away_runs = int(first["away_runs"])
        home_runs = int(first["home_runs"])
        label_at = str(game["time_semantics"]["label_available_at"])
        away_id = int(game["away_team"]["team_id"])
        home_id = int(game["home_team"]["team_id"])
        for team_id, is_home, runs_for, runs_against in (
            (away_id, False, away_runs, home_runs),
            (home_id, True, home_runs, away_runs),
        ):
            rows.append(
                {
                    "game_pk": game_pk,
                    "team_id": team_id,
                    "is_home": is_home,
                    "official_date": official_date,
                    "season": season,
                    "scheduled_start_at": start_at,
                    "label_available_at": label_at,
                    "prediction_cutoff": cutoff,
                    "venue_id": venue_id,
                    "doubleheader_code": dh_code,
                    "game_number": game_number,
                    "starter_id": _starter_id(game, "home" if is_home else "away"),
                    "first_inning_runs_for": runs_for,
                    "first_inning_runs_against": runs_against,
                }
            )
    rows.sort(
        key=lambda r: (
            r["official_date"],
            r["game_number"],
            r["game_pk"],
            r["team_id"],
        )
    )
    return rows


# --------------------------------------------------------------------------- #
# Schedule / travel / road-trip / day-night (pure, reused live)
# --------------------------------------------------------------------------- #
def compute_schedule_travel_features(
    prior_side_games: Sequence[Mapping[str, Any]],
    target: Mapping[str, Any],
    venue_reference: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    """Pregame travel/rest/congestion/road-trip/day-night for one club-game.

    `prior_side_games` are the club's strictly-earlier games (chronological).
    Deterministic and identical whether fed committed history (training) or a
    live current-season schedule window (collector).
    """
    tgt_venue = venue_reference.get(int(target["venue_id"]))
    values: dict[str, Any] = {
        "is_home": bool(target["is_home"]),
        "doubleheader": str(target.get("doubleheader_code", "N")) != "N",
        "doubleheader_code": str(target.get("doubleheader_code", "N")),
        "doubleheader_game_number": int(target.get("game_number", 1)),
        "venue_known": tgt_venue is not None,
    }
    if tgt_venue is not None:
        values["day_night"] = day_night(
            str(target["scheduled_start_at"]),
            float(tgt_venue["utc_offset_standard_hours"]),
        )
        values["altitude_ft"] = int(tgt_venue["altitude_ft"])
    else:
        values["day_night"] = None
        values["altitude_ft"] = None

    target_date = str(target["official_date"])
    tdate = datetime.fromisoformat(target_date).date()

    # Road-trip / home-stand streak (consecutive same-side games incl. target).
    streak = 1
    for prev in reversed(prior_side_games):
        if bool(prev["is_home"]) == bool(target["is_home"]):
            streak += 1
        else:
            break
    values["trip_game_index"] = streak
    values["trip_is_first_game"] = streak == 1
    values["trip_kind"] = "home_stand" if target["is_home"] else "road_trip"

    # Congestion: games strictly before the target date within N days.
    for win in CONGESTION_WINDOWS_DAYS:
        lo = tdate - timedelta(days=win)
        count = 0
        for prev in prior_side_games:
            pdate = datetime.fromisoformat(str(prev["official_date"])).date()
            if lo <= pdate < tdate:
                count += 1
        values[f"games_prior_{win}d"] = count

    if not prior_side_games:
        values.update(
            {
                "has_prior_game": False,
                "rest_days": None,
                "travel_miles": None,
                "tz_shift_hours": None,
                "prior_day_night": None,
                "night_to_day_turnaround": None,
                "prior_venue_id": None,
                "prior_official_date": None,
            }
        )
        return values

    prev = prior_side_games[-1]
    pdate = datetime.fromisoformat(str(prev["official_date"])).date()
    values["has_prior_game"] = True
    values["rest_days"] = (tdate - pdate).days
    values["prior_venue_id"] = int(prev["venue_id"])
    values["prior_official_date"] = str(prev["official_date"])

    prev_venue = venue_reference.get(int(prev["venue_id"]))
    if tgt_venue is not None and prev_venue is not None:
        values["travel_miles"] = haversine_miles(
            float(prev_venue["latitude"]),
            float(prev_venue["longitude"]),
            float(tgt_venue["latitude"]),
            float(tgt_venue["longitude"]),
        )
        values["tz_shift_hours"] = round(
            float(tgt_venue["utc_offset_standard_hours"])
            - float(prev_venue["utc_offset_standard_hours"]),
            2,
        )
        prior_dn = day_night(
            str(prev["scheduled_start_at"]),
            float(prev_venue["utc_offset_standard_hours"]),
        )
        values["prior_day_night"] = prior_dn
        values["night_to_day_turnaround"] = (
            prior_dn == "night"
            and values["day_night"] == "day"
            and values["rest_days"] <= 1
        )
    else:
        values["travel_miles"] = None
        values["tz_shift_hours"] = None
        values["prior_day_night"] = None
        values["night_to_day_turnaround"] = None
    return values


def compute_starter_workload(
    prior_starts: Sequence[Mapping[str, Any]],
    target: Mapping[str, Any],
) -> dict[str, Any]:
    """Days rest and trailing-30d start count for the club's starter."""
    starter_id = target.get("starter_id")
    if starter_id is None:
        return {
            "starter_id": None,
            "starter_known": False,
            "workload_feature_eligible": False,
            "starter_rest_days": None,
            "starter_starts_prior_30d": None,
            "starter_prior_starts": 0,
        }
    tdate = datetime.fromisoformat(str(target["official_date"])).date()
    lo = tdate - timedelta(days=STARTER_WORKLOAD_WINDOW_DAYS)
    starts_30d = 0
    for s in prior_starts:
        sdate = datetime.fromisoformat(str(s["official_date"])).date()
        if lo <= sdate < tdate:
            starts_30d += 1
    rest_days: int | None = None
    if prior_starts:
        last = datetime.fromisoformat(str(prior_starts[-1]["official_date"])).date()
        rest_days = (tdate - last).days
    return {
        "starter_id": int(starter_id),
        "starter_known": True,
        "workload_feature_eligible": len(prior_starts) >= STARTER_MINIMUM_PRIOR_STARTS,
        "starter_rest_days": rest_days,
        "starter_starts_prior_30d": starts_30d,
        "starter_prior_starts": len(prior_starts),
    }


# --------------------------------------------------------------------------- #
# Strict-prior park factors + terminal per-venue projection
# --------------------------------------------------------------------------- #
def _game_level(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Collapse two side-rows back to one game-level row for park factors."""
    seen: dict[int, dict[str, Any]] = {}
    for r in rows:
        gp = int(r["game_pk"])
        if gp in seen:
            continue
        seen[gp] = {
            "game_pk": gp,
            "venue_id": int(r["venue_id"]),
            "scheduled_start_at": r["scheduled_start_at"],
            "label_available_at": r["label_available_at"],
            "prediction_cutoff": r["prediction_cutoff"],
            "official_date": r["official_date"],
            "season": int(r["season"]),
            "first_inning_total_runs": int(r["first_inning_runs_for"])
            + int(r["first_inning_runs_against"]),
        }
    return list(seen.values())


def strict_prior_park_factors(
    rows: Sequence[Mapping[str, Any]],
) -> dict[int, dict[str, Any]]:
    """Per game_pk: strict-prior venue vs league first-inning run rate.

    Two-pointer sweep - a source game is admitted once its label was available
    at or before the target's prediction cutoff (so it is strictly prior).
    """
    games = _game_level(rows)
    targets = sorted(games, key=lambda g: (g["prediction_cutoff"], g["game_pk"]))
    sources = sorted(games, key=lambda g: (g["label_available_at"], g["game_pk"]))
    venue_runs: dict[int, int] = defaultdict(int)
    venue_games: dict[int, int] = defaultdict(int)
    league_runs = 0
    league_games = 0
    out: dict[int, dict[str, Any]] = {}
    ptr = 0
    n = len(sources)
    for tgt in targets:
        cutoff = tgt["prediction_cutoff"]
        while ptr < n and sources[ptr]["label_available_at"] <= cutoff:
            s = sources[ptr]
            vid = int(s["venue_id"])
            venue_runs[vid] += int(s["first_inning_total_runs"])
            venue_games[vid] += 1
            league_runs += int(s["first_inning_total_runs"])
            league_games += 1
            ptr += 1
        vid = int(tgt["venue_id"])
        vg = venue_games[vid]
        venue_rate = _ratio(venue_runs[vid], vg)
        league_rate = _ratio(league_runs, league_games)
        factor: float | None = None
        if (
            venue_rate is not None
            and league_rate not in (None, 0)
            and vg >= PARK_MINIMUM_PRIOR_GAMES
        ):
            factor = round(venue_rate / float(league_rate), 6)
        out[int(tgt["game_pk"])] = {
            "park_prior_games_at_venue": vg,
            "park_first_inning_runs_per_game": venue_rate,
            "league_first_inning_runs_per_game": league_rate,
            "park_factor": factor,
            "park_context_feature_eligible": factor is not None,
        }
    return out


def build_terminal_park_factors(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Complete-history per-venue first-inning park factor (live join table)."""
    games = _game_level(rows)
    for g in games:
        if int(g["season"]) == LOCKED_HOLDOUT_SEASON:
            raise ContextFeatureError("terminal park factor touched locked 2025")
    league_runs = sum(int(g["first_inning_total_runs"]) for g in games)
    league_games = len(games)
    league_rate = _ratio(league_runs, league_games)
    by_venue: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for g in games:
        by_venue[int(g["venue_id"])].append(g)
    profiles: list[dict[str, Any]] = []
    for venue_id, vgames in by_venue.items():
        runs = sum(int(g["first_inning_total_runs"]) for g in vgames)
        n = len(vgames)
        venue_rate = _ratio(runs, n)
        factor: float | None = None
        if (
            venue_rate is not None
            and league_rate not in (None, 0)
            and (n >= PARK_MINIMUM_PRIOR_GAMES)
        ):
            factor = round(venue_rate / float(league_rate), 6)
        last = max(vgames, key=lambda g: (g["official_date"], g["game_pk"]))
        core = {
            "schema_version": "park_terminal_factor.v1",
            "profile_version": PARK_TERMINAL_VERSION,
            "feature_version": CONTEXT_FEATURE_VERSION,
            "venue_id": int(venue_id),
            "prior_games_at_venue": n,
            "first_inning_runs_per_game": venue_rate,
            "league_first_inning_runs_per_game": league_rate,
            "park_factor": factor,
            "park_context_feature_eligible": factor is not None,
            "as_of_official_date": str(last["official_date"]),
            "as_of_season": int(last["season"]),
        }
        profiles.append({**core, "feature_hash": _identity(core)})
    profiles.sort(key=lambda p: int(p["venue_id"]))
    return profiles


def terminal_park_projection_bytes(
    profiles: Sequence[Mapping[str, Any]],
) -> bytes:
    return b"".join(canonical_json_bytes(row) for row in profiles)


# --------------------------------------------------------------------------- #
# Full per-(game, side) context feature set (training / replay artifact)
# --------------------------------------------------------------------------- #
def build_context_feature_set(
    rows: Sequence[Mapping[str, Any]],
    venue_reference: Mapping[int, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Strict-prior context snapshot per (game_pk, team_id, is_home)."""
    park = strict_prior_park_factors(rows)
    by_team: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for r in rows:
        by_team[int(r["team_id"])].append(r)
    for team_rows in by_team.values():
        team_rows.sort(
            key=lambda r: (r["official_date"], r["game_number"], r["game_pk"])
        )

    # Starter workload is computed in a single global chronological pass so a
    # traded starter's rest counts his strictly-earlier starts for ANY club
    # (order-independent, immune to per-team iteration order).  Ordering is by
    # official game day (not UTC start) so a west-coast night game whose UTC
    # start rolls past midnight never appears out of calendar order.
    workload_map: dict[tuple[int, int, bool], dict[str, Any]] = {}
    starter_history: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for target in sorted(
        rows,
        key=lambda r: (
            r["official_date"],
            r["game_number"],
            r["game_pk"],
            r["is_home"],
        ),
    ):
        sid = target.get("starter_id")
        if sid is None:
            workload = compute_starter_workload([], target)
        else:
            workload = compute_starter_workload(starter_history[int(sid)], target)
            starter_history[int(sid)].append(target)
        workload_map[
            (int(target["game_pk"]), int(target["team_id"]), bool(target["is_home"]))
        ] = workload

    snapshots: list[dict[str, Any]] = []
    for team_id, team_rows in by_team.items():
        prior: list[Mapping[str, Any]] = []
        for target in team_rows:
            schedule = compute_schedule_travel_features(prior, target, venue_reference)
            workload = workload_map[
                (int(target["game_pk"]), int(team_id), bool(target["is_home"]))
            ]
            park_values = park[int(target["game_pk"])]
            schedule_travel_eligible = bool(
                schedule["has_prior_game"]
                and schedule["venue_known"]
                and schedule["travel_miles"] is not None
            )
            core = {
                "schema_version": "context_feature_snapshot.v1",
                "feature_version": CONTEXT_FEATURE_VERSION,
                "game_pk": int(target["game_pk"]),
                "team_id": int(team_id),
                "is_home": bool(target["is_home"]),
                "official_date": str(target["official_date"]),
                "prediction_cutoff": str(target["prediction_cutoff"]),
                "venue_id": int(target["venue_id"]),
                "park_context_feature_eligible": bool(
                    park_values["park_context_feature_eligible"]
                ),
                "schedule_travel_feature_eligible": schedule_travel_eligible,
                "workload_feature_eligible": bool(
                    workload["workload_feature_eligible"]
                ),
                "feature_values": {
                    **schedule,
                    **workload,
                    **park_values,
                },
            }
            snapshots.append({**core, "feature_hash": _identity(core)})
            prior.append(target)
    snapshots.sort(key=lambda r: (r["prediction_cutoff"], r["game_pk"], r["team_id"]))
    return snapshots


def generate(
    multiseason_dir: Path, venue_reference_path: Path, output_dir: Path
) -> dict[str, Any]:
    """Build side schedule log, context snapshots, and terminal park factors."""
    games, cutoffs = load_games(multiseason_dir)
    reference = load_venue_reference(venue_reference_path)
    rows = build_side_schedule_log(games, cutoffs)
    snapshots = build_context_feature_set(rows, reference)
    terminal = build_terminal_park_factors(rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "context_side_schedule.jsonl", rows)
    _write_jsonl(output_dir / "context_features.jsonl", snapshots)
    projection = terminal_park_projection_bytes(terminal)
    (output_dir / "park_terminal_factors.jsonl").write_bytes(projection)
    reference_bytes = venue_reference_path.read_bytes()

    eligible_parks = sum(1 for p in terminal if p["park_context_feature_eligible"])
    coverage = {
        "schema_version": "context_feature_coverage.v1",
        "extraction_version": CONTEXT_EXTRACTION_VERSION,
        "feature_version": CONTEXT_FEATURE_VERSION,
        "terminal_version": PARK_TERMINAL_VERSION,
        "reference_version": VENUE_REFERENCE_VERSION,
        "side_schedule_rows": len(rows),
        "context_snapshots": len(snapshots),
        "distinct_venues": len(terminal),
        "park_eligible_venues": eligible_parks,
        "side_schedule_identity": _identity(rows),
        "features_identity": _identity(snapshots),
        "terminal_identity": _identity(terminal),
        "terminal_projection_sha256": hashlib.sha256(projection).hexdigest(),
        "venue_reference_sha256": hashlib.sha256(reference_bytes).hexdigest(),
        "seasons": sorted({int(r["season"]) for r in rows}),
        "locked_2025_holdout_accessed": False,
    }
    _write_json(output_dir / "context_coverage.json", coverage)
    return coverage


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
