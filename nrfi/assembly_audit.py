"""Read-only, exact per-side audit of an immutable pregame assembly package.

Pure over the package document -- it NEVER invokes the collector or touches the
network.  It separates game-level eligibility counters from side-level evidence,
counts every lineup / batter / team / pitcher rejection reason at the side grain,
resolves the BATTER_PROFILE_MISSING vs BATTER_HISTORY_INSUFFICIENT split from the
per-side top-of-order coverage, explains why pitcher_profile_eligible collapses,
and verifies that every batter-eligible game used a CONFIRMED/UPDATED pre-cutoff
lineup and a verified terminal batter profile.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SIDES = ("away", "home")
CONFIRMED_STATUSES = ("CONFIRMED", "UPDATED")


def _counter_to_sorted(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items()))


def audit_package(package: dict[str, Any]) -> dict[str, Any]:
    """Produce the exact per-side + per-game census for one assembly package."""
    games = package.get("games", [])

    # --- game-level counters (recomputed from each game's eligibility) ---
    def _games_with(stage: str) -> int:
        return sum(1 for g in games if g.get("eligibility", {}).get(stage) is True)

    game_level = {
        "games": len(games),
        "pitcher_profile_eligible_games": _games_with("pitcher_profile_eligible"),
        "probable_starter_eligible_games": _games_with("probable_starter_eligible"),
        "lineup_feature_eligible_games": _games_with("lineup_feature_eligible"),
        "batter_feature_eligible_games": _games_with("batter_feature_eligible"),
        "team_context_eligible_games": _games_with("team_context_eligible"),
        "unified_feature_set_eligible_games": _games_with(
            "unified_feature_set_eligible"
        ),
        "games_before_prediction_cutoff": sum(
            1 for g in games if g.get("before_prediction_cutoff") is True
        ),
        "games_snapshot_fresh": sum(
            1 for g in games if g.get("snapshot_fresh") is True
        ),
    }

    # --- side-level tallies ---
    total_sides = 0
    pitcher_selection = Counter[str]()
    pitcher_feature_status = Counter[str]()
    pitcher_feature_reason = Counter[str]()
    lineup_status = Counter[str]()
    lineup_side_eligible = Counter[str]()
    lineup_reason = Counter[str]()
    batter_side_eligible = Counter[str]()
    batter_reason = Counter[str]()
    team_side_eligible = Counter[str]()
    team_reason = Counter[str]()
    # exact split evidence
    batter_missing_profile_sides = 0
    batter_history_insufficient_sides = 0

    for game in games:
        sides = game.get("sides", {})
        for side in SIDES:
            s = sides.get(side)
            if not isinstance(s, dict):
                continue
            total_sides += 1
            pitcher_selection[str(s.get("selection_status"))] += 1
            pitcher_feature_status[str(s.get("feature_status"))] += 1
            if s.get("feature_status_reason"):
                pitcher_feature_reason[str(s.get("feature_status_reason"))] += 1

            lineup_status[str(s.get("lineup_status"))] += 1
            lineup_side_eligible[str(bool(s.get("lineup_feature_eligible")))] += 1
            batter_side_eligible[str(bool(s.get("batter_feature_eligible")))] += 1
            team_side_eligible[str(bool(s.get("team_context_eligible")))] += 1

            for reason in s.get("batter_stage_reasons", []) or []:
                if reason.startswith("LINEUP_"):
                    lineup_reason[reason] += 1
                else:
                    batter_reason[reason] += 1
            for reason in s.get("team_context_reasons", []) or []:
                team_reason[reason] += 1

            # Resolve the exact PROFILE_MISSING vs HISTORY_INSUFFICIENT split from
            # the side's own top-of-order coverage (authoritative, not just the
            # reason string): missing profile -> MISSING; present-but-ineligible
            # -> HISTORY_INSUFFICIENT.
            toe = s.get("top_of_order")
            if (
                bool(s.get("lineup_feature_eligible"))
                and not bool(s.get("batter_feature_eligible"))
                and isinstance(toe, dict)
            ):
                if int(toe.get("missing_profile_count", 0)) > 0:
                    batter_missing_profile_sides += 1
                elif int(toe.get("profile_eligible_count", 0)) < int(
                    toe.get("top_of_order_size", 0)
                ):
                    batter_history_insufficient_sides += 1

    # --- verify the batter-eligible games end to end ---
    batter_eligible_games: list[dict[str, Any]] = []
    for game in games:
        if game.get("eligibility", {}).get("batter_feature_eligible") is not True:
            continue
        detail: dict[str, Any] = {"game_pk": game.get("game_pk"), "sides": {}}
        ok = True
        for side in SIDES:
            s = game.get("sides", {}).get(side, {})
            toe = s.get("top_of_order") or {}
            confirmed = str(s.get("lineup_status")) in CONFIRMED_STATUSES
            coverage = float(toe.get("profile_coverage") or 0.0)
            missing = int(toe.get("missing_profile_count", 0))
            side_ok = (
                confirmed
                and bool(s.get("lineup_feature_eligible"))
                and bool(s.get("batter_feature_eligible"))
                and bool(s.get("team_context_eligible"))
                and coverage == 1.0
                and missing == 0
            )
            ok = ok and side_ok
            detail["sides"][side] = {
                "team_id": s.get("team_id"),
                "lineup_status": s.get("lineup_status"),
                "lineup_snapshot_id": s.get("lineup_snapshot_id"),
                "lineup_observed_at": s.get("lineup_observed_at"),
                "lineup_age_at_cutoff_seconds": s.get("lineup_age_at_cutoff_seconds"),
                "first_three_batter_ids": toe.get("first_three_batter_ids"),
                "first_four_batter_ids": toe.get("first_four_batter_ids"),
                "profile_coverage": toe.get("profile_coverage"),
                "missing_profile_count": toe.get("missing_profile_count"),
                "confirmed_pre_cutoff": confirmed
                and s.get("lineup_age_at_cutoff_seconds") is not None
                and int(s.get("lineup_age_at_cutoff_seconds") or -1) >= 0,
            }
        detail["fully_verified"] = ok
        batter_eligible_games.append(detail)

    # --- pitcher_profile_eligible=0 explanation ---
    pitcher_zero = {
        "pitcher_profile_eligible_games": game_level["pitcher_profile_eligible_games"],
        "games_before_prediction_cutoff": game_level["games_before_prediction_cutoff"],
        "prediction_cutoff_passed_games": sum(
            1
            for g in games
            if any(
                str(r).endswith("PREDICTION_CUTOFF_PASSED")
                for r in g.get("rejection_reasons", [])
            )
        ),
        "snapshot_stale_games": sum(
            1
            for g in games
            if any(
                str(r).endswith("SNAPSHOT_STALE")
                for r in g.get("rejection_reasons", [])
            )
        ),
        "sides_selected": pitcher_selection.get("SELECTED", 0),
        "sides_feature_ready": pitcher_feature_status.get("READY", 0),
    }

    return {
        "schema_version": "assembly_audit_census.v1",
        "official_date": package.get("official_date"),
        "package_id": package.get("package_id"),
        "generated_at": package.get("generated_at"),
        "profiles_status": package.get("profiles_status"),
        "batter_profiles_status": package.get("batter_profiles_status"),
        "batter_profile_identity": package.get("batter_profile_identity"),
        "team_profiles_status": package.get("team_profiles_status"),
        "team_profile_identity": package.get("team_profile_identity"),
        "game_level": game_level,
        "side_level": {
            "total_sides": total_sides,
            "pitcher_selection_status": _counter_to_sorted(pitcher_selection),
            "pitcher_feature_status": _counter_to_sorted(pitcher_feature_status),
            "pitcher_feature_reason": _counter_to_sorted(pitcher_feature_reason),
            "lineup_status": _counter_to_sorted(lineup_status),
            "lineup_side_eligible": _counter_to_sorted(lineup_side_eligible),
            "lineup_reason": _counter_to_sorted(lineup_reason),
            "batter_side_eligible": _counter_to_sorted(batter_side_eligible),
            "batter_reason": _counter_to_sorted(batter_reason),
            "batter_missing_profile_sides": batter_missing_profile_sides,
            "batter_history_insufficient_sides": batter_history_insufficient_sides,
            "team_side_eligible": _counter_to_sorted(team_side_eligible),
            "team_reason": _counter_to_sorted(team_reason),
        },
        "pitcher_zero_explanation": pitcher_zero,
        "batter_eligible_games": batter_eligible_games,
        "unified_feature_set_eligible": game_level["unified_feature_set_eligible_games"]
        > 0,
        "wager_decision": package.get("wager_decision"),
    }


def select_confirmed_package(packages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the package with the most batter-eligible games (tie: latest)."""
    scored = [
        (
            sum(
                1
                for g in p.get("games", [])
                if g.get("eligibility", {}).get("batter_feature_eligible") is True
            ),
            str(p.get("generated_at") or ""),
            p,
        )
        for p in packages
    ]
    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1]))
    return scored[-1][2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, help="single package JSON to audit")
    parser.add_argument(
        "--select-dir",
        type=Path,
        help="directory of package JSON files; audits the max-batter-eligible one",
    )
    args = parser.parse_args(argv)
    if args.select_dir:
        packages = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(args.select_dir.glob("*.json"))
        ]
        chosen = select_confirmed_package(packages)
        if chosen is None:
            raise SystemExit("no packages found in --select-dir")
        print(json.dumps(audit_package(chosen), sort_keys=True))
        return 0
    if not args.package:
        raise SystemExit("--package or --select-dir is required")
    package = json.loads(args.package.read_text(encoding="utf-8"))
    print(json.dumps(audit_package(package), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
