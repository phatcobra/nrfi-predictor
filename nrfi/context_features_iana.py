"""Versioned IANA (V2.2) context: DST-aware timezones + availability-safe priors.

This is the ``timezone_mode = iana`` context path for NRFI_CORE_V2_2_ADMISSIBLE
ONLY. The ``standard_offset`` path in ``nrfi.context_features`` (used by V1/V2
replay) is left completely untouched, so existing artifact identities do not
change.

Two things are repaired relative to the standard-offset path:

1. Effective-dated IANA venue time zones (via ``zoneinfo`` + the pinned
   ``tzdata==2026.3`` package) for day/night, local hour, UTC offset, DST flag,
   and time-zone movement - instead of fixed standard offsets.
2. Availability-safe prior-game selection: a prior game is admitted only when
   ``source.game_pk != target.game_pk`` AND
   ``source.label_available_at <= target.prediction_cutoff`` (never ordered
   solely by ``official_date``). The SAME admitted-prior set feeds rest,
   congestion, travel, prior venue, prior day/night, night->day turnaround, and
   trip position; and the strict-prior park factor explicitly excludes the
   target game.

The artifact is starter-INDEPENDENT: it never contains starter identity,
pitcher, workload, lineup, batter, weather, umpire, or market fields.

Timezone isolation is applied ONLY inside the offline build entry point
(``generate_iana``) - never at module import - so importing this module does not
mutate global timezone state.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import sys
import zoneinfo
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from nrfi.context_features import (
    ADMITTED_MAX_SEASON,
    ADMITTED_MIN_SEASON,
    DAY_NIGHT_CUTOFF_HOUR,
    PARK_MINIMUM_PRIOR_GAMES,
    ContextFeatureError,
    haversine_miles,
    load_games,
    load_venue_reference,
)
from nrfi.pregame_snapshot import canonical_json_bytes

CONTEXT_IANA_FEATURE_VERSION = "context-foundation-iana-strict-prior-v2_2"
CONTEXT_IANA_SCHEMA = "context_feature_snapshot_iana.v1"
CONTEXT_IANA_EXTRACTION_VERSION = "context-foundation-iana-2015-2024-v2_2"
TIMEZONE_IMPLEMENTATION_VERSION = "iana-tzdata-pinned-v1"
CONGESTION_WINDOWS_DAYS: tuple[int, ...] = (3, 7)

PRIOR_SELF_INCLUSION = "TARGET_ENTERED_OWN_PRIOR_HISTORY"

_FORBIDDEN_KEYS = (
    "starter",
    "pitcher",
    "workload",
    "lineup",
    "batter",
    "weather",
    "umpire",
    "market",
)


def _identity(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


# --------------------------------------------------------------------------- #
# Timezone isolation (offline build only) + IANA feature helpers
# --------------------------------------------------------------------------- #
def force_tzdata_only() -> list[str]:
    """Configure zoneinfo to use ONLY the packaged tzdata, then clear the cache.

    Call this only inside an isolated offline build/reproduce process. It never
    runs at import time. Returns the effective (empty) TZ search path.
    """
    zoneinfo.reset_tzpath(to=[])
    ZoneInfo.clear_cache()
    return list(zoneinfo.TZPATH)


def _zone(tz_label: str) -> ZoneInfo:
    return ZoneInfo(str(tz_label))


def iana_local_time(scheduled_start_at: str, tz_label: str) -> datetime:
    return _parse_utc(scheduled_start_at).astimezone(_zone(tz_label))


def iana_local_hour(scheduled_start_at: str, tz_label: str) -> int:
    return iana_local_time(scheduled_start_at, tz_label).hour


def iana_day_night(scheduled_start_at: str, tz_label: str) -> str:
    return (
        "day"
        if iana_local_hour(scheduled_start_at, tz_label) < DAY_NIGHT_CUTOFF_HOUR
        else "night"
    )


def iana_utc_offset_hours(scheduled_start_at: str, tz_label: str) -> float:
    offset = iana_local_time(scheduled_start_at, tz_label).utcoffset()
    return round(offset.total_seconds() / 3600.0, 4) if offset is not None else 0.0


def iana_dst_active(scheduled_start_at: str, tz_label: str) -> bool:
    dst = iana_local_time(scheduled_start_at, tz_label).dst()
    return bool(dst) and dst.total_seconds() != 0.0


# --------------------------------------------------------------------------- #
# Starter-independent side schedule log
# --------------------------------------------------------------------------- #
def build_iana_side_log(
    games: Sequence[Mapping[str, Any]], cutoffs: Mapping[int, str]
) -> list[dict[str, Any]]:
    """Two starter-INDEPENDENT club-side rows per completed regular-season game."""
    rows: list[dict[str, Any]] = []
    for game in games:
        if game.get("game_type") != "R":
            continue
        first = game.get("first_inning") or {}
        if not first.get("completed"):
            continue
        game_pk = int(game["game_pk"])
        official_date = str(game["official_date"])
        season = int(official_date[:4])
        if season < ADMITTED_MIN_SEASON or season > ADMITTED_MAX_SEASON:
            continue
        cutoff = cutoffs.get(game_pk)
        if cutoff is None:
            continue
        venue_id = int(game["venue"]["venue_id"])
        start_at = str(game["scheduled_start_at"])
        label_at = str(game["time_semantics"]["label_available_at"])
        dh_code = str(game.get("doubleheader_code", "N"))
        game_number = int(game.get("game_number", 1))
        away_runs = int(first["away_runs"])
        home_runs = int(first["home_runs"])
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


def _prior_sort_key(row: Mapping[str, Any]) -> tuple[str, str, int, int]:
    return (
        str(row["label_available_at"]),
        str(row["scheduled_start_at"]),
        int(row["game_number"]),
        int(row["game_pk"]),
    )


def admitted_prior_games(
    team_games: Sequence[Mapping[str, Any]], target: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Availability-safe prior set for one target row + a census.

    Admits games of the SAME team with a different game_pk whose label became
    available at or before the target's prediction cutoff. Hard-fails if the
    target ever enters its own prior history.
    """
    cutoff = str(target["prediction_cutoff"])
    target_gp = int(target["game_pk"])
    target_date = datetime.fromisoformat(str(target["official_date"])).date()
    admitted: list[dict[str, Any]] = []
    candidate = 0
    rejected_after_cutoff = 0
    same_day = 0
    self_exclusions = 0
    for row in team_games:
        candidate += 1
        gp = int(row["game_pk"])
        if gp == target_gp:
            self_exclusions += 1
            continue
        if str(row["label_available_at"]) <= cutoff:
            admitted.append(dict(row))
            if datetime.fromisoformat(str(row["official_date"])).date() == target_date:
                same_day += 1
        else:
            rejected_after_cutoff += 1
    admitted.sort(key=_prior_sort_key)
    if any(int(r["game_pk"]) == target_gp for r in admitted):
        raise ContextFeatureError(PRIOR_SELF_INCLUSION)
    census = {
        "prior_candidate_count": candidate,
        "prior_admitted_count": len(admitted),
        "prior_rejected_after_cutoff_count": rejected_after_cutoff,
        "prior_same_day_admitted_count": same_day,
        "target_self_exclusion_count": self_exclusions,
        "latest_admitted_prior_game_pk": (
            int(admitted[-1]["game_pk"]) if admitted else None
        ),
        "latest_admitted_label_available_at": (
            str(admitted[-1]["label_available_at"]) if admitted else None
        ),
    }
    return admitted, census


# --------------------------------------------------------------------------- #
# IANA schedule / travel features (from the admitted-prior set)
# --------------------------------------------------------------------------- #
def compute_iana_schedule_travel(
    admitted_prior: Sequence[Mapping[str, Any]],
    target: Mapping[str, Any],
    venue_reference: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    tgt_venue = venue_reference.get(int(target["venue_id"]))
    values: dict[str, Any] = {
        "is_home": bool(target["is_home"]),
        "doubleheader": str(target.get("doubleheader_code", "N")) != "N",
        "doubleheader_code": str(target.get("doubleheader_code", "N")),
        "doubleheader_game_number": int(target.get("game_number", 1)),
        "venue_known": tgt_venue is not None,
    }
    if tgt_venue is not None:
        tz = str(tgt_venue["tz_label"])
        start = str(target["scheduled_start_at"])
        values["day_night"] = iana_day_night(start, tz)
        values["local_scheduled_hour"] = iana_local_hour(start, tz)
        values["current_utc_offset_hours"] = iana_utc_offset_hours(start, tz)
        values["dst_active"] = iana_dst_active(start, tz)
        values["altitude_ft"] = int(tgt_venue["altitude_ft"])
    else:
        values.update(
            {
                "day_night": None,
                "local_scheduled_hour": None,
                "current_utc_offset_hours": None,
                "dst_active": None,
                "altitude_ft": None,
            }
        )

    tdate = datetime.fromisoformat(str(target["official_date"])).date()
    streak = 1
    for prev in reversed(admitted_prior):
        if bool(prev["is_home"]) == bool(target["is_home"]):
            streak += 1
        else:
            break
    values["trip_game_index"] = streak
    values["trip_is_first_game"] = streak == 1
    values["trip_kind"] = "home_stand" if target["is_home"] else "road_trip"

    for win in CONGESTION_WINDOWS_DAYS:
        lo = tdate - timedelta(days=win)
        values[f"games_prior_{win}d"] = sum(
            1
            for prev in admitted_prior
            if lo <= datetime.fromisoformat(str(prev["official_date"])).date() < tdate
        )

    if not admitted_prior:
        values.update(
            {
                "has_prior_game": False,
                "rest_days": None,
                "travel_miles": None,
                "tz_shift_hours": None,
                "prior_utc_offset_hours": None,
                "prior_day_night": None,
                "prior_dst_active": None,
                "night_to_day_turnaround": None,
                "prior_venue_id": None,
                "prior_official_date": None,
            }
        )
        return values

    prev = admitted_prior[-1]
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
        ptz = str(prev_venue["tz_label"])
        pstart = str(prev["scheduled_start_at"])
        prior_offset = iana_utc_offset_hours(pstart, ptz)
        values["prior_utc_offset_hours"] = prior_offset
        values["tz_shift_hours"] = round(
            float(values["current_utc_offset_hours"]) - prior_offset, 4
        )
        prior_dn = iana_day_night(pstart, ptz)
        values["prior_day_night"] = prior_dn
        values["prior_dst_active"] = iana_dst_active(pstart, ptz)
        values["night_to_day_turnaround"] = (
            prior_dn == "night"
            and values["day_night"] == "day"
            and values["rest_days"] <= 1
        )
    else:
        values.update(
            {
                "travel_miles": None,
                "tz_shift_hours": None,
                "prior_utc_offset_hours": None,
                "prior_day_night": None,
                "prior_dst_active": None,
                "night_to_day_turnaround": None,
            }
        )
    return values


# --------------------------------------------------------------------------- #
# Strict-prior park factors with EXPLICIT target self-exclusion
# --------------------------------------------------------------------------- #
def _game_level(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[int, dict[str, Any]] = {}
    for r in rows:
        gp = int(r["game_pk"])
        if gp in seen:
            continue
        seen[gp] = {
            "game_pk": gp,
            "venue_id": int(r["venue_id"]),
            "label_available_at": r["label_available_at"],
            "prediction_cutoff": r["prediction_cutoff"],
            "official_date": r["official_date"],
            "season": int(r["season"]),
            "first_inning_total_runs": int(r["first_inning_runs_for"])
            + int(r["first_inning_runs_against"]),
        }
    return list(seen.values())


def strict_prior_park_factors_safe(
    rows: Sequence[Mapping[str, Any]],
) -> dict[int, dict[str, Any]]:
    """Per game_pk strict-prior venue vs league first-inning run rate.

    Explicitly enforces source.game_pk != target.game_pk in addition to
    label_available_at <= prediction_cutoff, so a malformed target whose label
    is available before its own cutoff still cannot see itself.
    """
    games = _game_level(rows)

    def _rate(num: int, den: int) -> float | None:
        return float(num) / den if den else None

    # Two-pointer sweep (O(n log n)): admit sources by label_available_at as each
    # target's cutoff is reached, then EXPLICITLY subtract the target's own game
    # if its label happened to be available at/before its own cutoff (malformed).
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
            vid_s = int(s["venue_id"])
            runs_s = int(s["first_inning_total_runs"])
            venue_runs[vid_s] += runs_s
            venue_games[vid_s] += 1
            league_runs += runs_s
            league_games += 1
            ptr += 1
        target_gp = int(tgt["game_pk"])
        vid = int(tgt["venue_id"])
        v_runs, v_games = venue_runs[vid], venue_games[vid]
        l_runs, l_games = league_runs, league_games
        if str(tgt["label_available_at"]) <= str(cutoff):
            # explicit self-exclusion (independent of normal timing)
            self_runs = int(tgt["first_inning_total_runs"])
            v_runs -= self_runs
            v_games -= 1
            l_runs -= self_runs
            l_games -= 1
        venue_rate = _rate(v_runs, v_games)
        league_rate = _rate(l_runs, l_games)
        factor: float | None = None
        if (
            venue_rate is not None
            and league_rate is not None
            and league_rate != 0
            and v_games >= PARK_MINIMUM_PRIOR_GAMES
        ):
            factor = round(venue_rate / league_rate, 6)
        out[target_gp] = {
            "park_prior_games_at_venue": v_games,
            "park_first_inning_runs_per_game": venue_rate,
            "league_first_inning_runs_per_game": league_rate,
            "park_factor": factor,
            "park_context_feature_eligible": factor is not None,
        }
    return out


# --------------------------------------------------------------------------- #
# Full IANA context feature set
# --------------------------------------------------------------------------- #
def build_iana_context_feature_set(
    rows: Sequence[Mapping[str, Any]],
    venue_reference: Mapping[int, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    park = strict_prior_park_factors_safe(rows)
    by_team: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for r in rows:
        by_team[int(r["team_id"])].append(r)
    for team_rows in by_team.values():
        team_rows.sort(
            key=lambda r: (r["official_date"], r["game_number"], r["game_pk"])
        )

    snapshots: list[dict[str, Any]] = []
    for team_id, team_rows in by_team.items():
        for target in team_rows:
            admitted, census = admitted_prior_games(team_rows, target)
            schedule = compute_iana_schedule_travel(admitted, target, venue_reference)
            park_values = park[int(target["game_pk"])]
            schedule_travel_eligible = bool(
                schedule["has_prior_game"]
                and schedule["venue_known"]
                and schedule["travel_miles"] is not None
            )
            feature_values = {**schedule, **park_values}
            _assert_starter_independent(feature_values)
            core = {
                "schema_version": CONTEXT_IANA_SCHEMA,
                "feature_version": CONTEXT_IANA_FEATURE_VERSION,
                "timezone_mode": "iana",
                "timezone_implementation_version": TIMEZONE_IMPLEMENTATION_VERSION,
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
                "prior_game_census": census,
                "feature_values": feature_values,
            }
            snapshots.append({**core, "feature_hash": _identity(core)})
    snapshots.sort(key=lambda r: (r["prediction_cutoff"], r["game_pk"], r["team_id"]))
    return snapshots


def _assert_starter_independent(feature_values: Mapping[str, Any]) -> None:
    for key in feature_values:
        low = str(key).lower()
        for banned in _FORBIDDEN_KEYS:
            if banned in low:
                raise ContextFeatureError(
                    f"starter-dependent key leaked into IANA context: {key}"
                )


def _timezone_provenance(
    venue_reference: Mapping[int, Mapping[str, Any]],
    reference_path: Path,
    effective_tzpath: list[str],
    lock_sha256: str,
) -> dict[str, Any]:
    sample = {
        int(vid): iana_utc_offset_hours("2019-07-01T23:00:00Z", str(v["tz_label"]))
        for vid, v in sorted(venue_reference.items())
    }
    return {
        "timezone_implementation_version": TIMEZONE_IMPLEMENTATION_VERSION,
        "timezone_source_strategy": "packaged_tzdata_only",
        "tzdata_version": importlib.metadata.version("tzdata"),
        "python_version": platform.python_version(),
        "dependency_lock_sha256": lock_sha256,
        "effective_tz_search_path": effective_tzpath,
        "venue_reference_sha256": hashlib.sha256(
            reference_path.read_bytes()
        ).hexdigest(),
        "sample_summer_utc_offset_by_venue": sample,
    }


def generate_iana(
    multiseason_dir: Path,
    venue_reference_path: Path,
    output_dir: Path,
    lock_path: Path,
) -> dict[str, Any]:
    """Isolated offline IANA context build (forces tzdata-only, records provenance)."""
    effective_tzpath = force_tzdata_only()
    games, cutoffs = load_games(multiseason_dir)
    reference = load_venue_reference(venue_reference_path)
    rows = build_iana_side_log(games, cutoffs)
    snapshots = build_iana_context_feature_set(rows, reference)
    lock_sha = hashlib.sha256(lock_path.read_bytes()).hexdigest()
    tz_prov = _timezone_provenance(
        reference, venue_reference_path, effective_tzpath, lock_sha
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "context_iana_features.jsonl").open("wb") as handle:
        for row in snapshots:
            handle.write(canonical_json_bytes(row))
    features_identity = _identity(snapshots)
    scientific_identity = _identity(
        {"features_identity": features_identity, "timezone_provenance": tz_prov}
    )
    coverage = {
        "schema_version": "context_iana_coverage.v1",
        "extraction_version": CONTEXT_IANA_EXTRACTION_VERSION,
        "feature_version": CONTEXT_IANA_FEATURE_VERSION,
        "timezone_mode": "iana",
        "context_snapshots": len(snapshots),
        "side_log_rows": len(rows),
        "features_identity": features_identity,
        "scientific_identity": scientific_identity,
        "timezone_provenance": tz_prov,
        "seasons": sorted({int(r["season"]) for r in rows}),
        "starter_independent": True,
        "locked_2025_holdout_accessed": False,
    }
    (output_dir / "context_iana_coverage.json").write_bytes(
        canonical_json_bytes(coverage)
    )
    return coverage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--multiseason-dir", type=Path, required=True)
    parser.add_argument("--venue-reference", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--lock", type=Path, default=Path("uv.lock"))
    args = parser.parse_args(argv)
    coverage = generate_iana(
        args.multiseason_dir, args.venue_reference, args.output_dir, args.lock
    )
    print(json.dumps(coverage, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
