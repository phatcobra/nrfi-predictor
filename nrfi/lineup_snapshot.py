"""Normalize official StatsAPI lineup hydration into immutable snapshot rows.

The forward collector fetches the schedule with the ``lineups`` hydration, which
exposes the posted batting order per side once a club announces it.  This module
turns one such response into deterministic, point-in-time lineup snapshot rows
carrying full provenance.  It never invents a publication timestamp: StatsAPI
does not expose when a lineup was posted, so ``source_publication_time`` stays
``None`` and availability is anchored to the verified retrieval time.  Revision
lineage (no lineup -> posted -> changed -> scratched) is preserved because the
collector stores every timestamped capture immutably; selection across those
revisions happens in the admission layer.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence

from nrfi.pregame_snapshot import canonical_json_bytes

LINEUP_SNAPSHOT_SCHEMA_VERSION = "lineup_snapshot.v1"
LOCKED_HOLDOUT_SEASON = 2025

STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"
STATUS_CONFIRMED = "CONFIRMED"
# StatsAPI posts the official batting order; it does not expose a separate
# projected feed or a lineup publication time, so PROJECTED cannot be derived
# from this source and is reserved for a future projection source.
AVAILABILITY_BASIS = "OFFICIAL_STATSAPI_LINEUP_OBSERVED_AT_RETRIEVAL"


class LineupSnapshotError(ValueError):
    """Raised when a lineup snapshot violates its fail-closed contract."""


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _identity(value: object) -> str:
    return _sha256(canonical_json_bytes(value))


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise LineupSnapshotError("required timestamp is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise LineupSnapshotError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _integer(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if not isinstance(value, (str, int, float)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value: object) -> str | None:
    return str(value) if value not in (None, "") else None


def _validate_target_date(target_date: date) -> None:
    if target_date.year == LOCKED_HOLDOUT_SEASON:
        raise LineupSnapshotError("the locked 2025 holdout is prohibited")


def _batting_order_rows(players: object) -> list[dict[str, Any]]:
    """Extract an ordered batting lineup from a StatsAPI lineups player list."""
    if not isinstance(players, list):
        return []
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index, player in enumerate(players, start=1):
        if not isinstance(player, Mapping):
            raise LineupSnapshotError("lineup player entry is malformed")
        player_id = _integer(player.get("id"))
        if player_id is None or player_id in seen:
            raise LineupSnapshotError("lineup has a missing or duplicate player id")
        seen.add(player_id)
        position = player.get("primaryPosition")
        rows.append(
            {
                "batting_order": index,
                "player_id": player_id,
                "player_name": _text(player.get("fullName")),
                "defensive_position": (
                    _text(position.get("abbreviation"))
                    if isinstance(position, Mapping)
                    else None
                ),
            }
        )
    return rows


def build_lineup_snapshot_rows(
    source: Mapping[str, Any], target_date: date
) -> list[dict[str, Any]]:
    """One lineup snapshot row per game side; never invents publication time."""
    _validate_target_date(target_date)
    retrieved_at = _utc_text(_parse_utc(source.get("retrieved_at")))
    response_sha256 = source.get("response_sha256")
    payload = source.get("payload")
    if not isinstance(payload, Mapping) or not isinstance(response_sha256, str):
        raise LineupSnapshotError("source snapshot is incomplete")
    observed = _parse_utc(retrieved_at)
    source_observation_id = _identity(
        {
            "request_parameters": source.get("request_parameters"),
            "retrieved_at": retrieved_at,
            "response_sha256": response_sha256,
        }
    )

    games = [
        game
        for day in payload.get("dates", [])
        if isinstance(day, Mapping)
        for game in day.get("games", [])
        if isinstance(game, Mapping)
    ]
    rows: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for game in sorted(
        games,
        key=lambda item: (
            _text(item.get("gameDate")) or "",
            _integer(item.get("gamePk")) or -1,
        ),
    ):
        if game.get("gameType") != "R":
            continue
        game_pk = _integer(game.get("gamePk"))
        official_date = _text(game.get("officialDate"))
        scheduled_start_at = _text(game.get("gameDate"))
        if game_pk is None or official_date != target_date.isoformat():
            continue
        cutoff = _parse_utc(scheduled_start_at)
        status_block = game.get("status")
        status_code = (
            _text(status_block.get("statusCode"))
            if isinstance(status_block, Mapping)
            else None
        )
        lineups = game.get("lineups")
        lineups = lineups if isinstance(lineups, Mapping) else {}
        teams = game.get("teams")
        teams = teams if isinstance(teams, Mapping) else {}

        for side, players_key in (("away", "awayPlayers"), ("home", "homePlayers")):
            key = (game_pk, side)
            if key in seen:
                raise LineupSnapshotError("duplicate game/side lineup snapshot")
            seen.add(key)
            side_block = teams.get(side)
            team = side_block.get("team") if isinstance(side_block, Mapping) else None
            team_id = _integer(team.get("id")) if isinstance(team, Mapping) else None
            batting_order = _batting_order_rows(lineups.get(players_key))
            status = STATUS_CONFIRMED if batting_order else STATUS_NOT_AVAILABLE
            row = {
                "schema_version": LINEUP_SNAPSHOT_SCHEMA_VERSION,
                "source_observation_id": source_observation_id,
                "game_pk": game_pk,
                "official_date": official_date,
                "scheduled_start_at": _utc_text(cutoff),
                "prediction_cutoff": _utc_text(cutoff),
                "game_status_code": status_code,
                "side": side,
                "team_id": team_id,
                "lineup_status": status,
                "batting_order_length": len(batting_order),
                "batting_order": batting_order,
                "lineup_observed_at": retrieved_at,
                "source_publication_time": None,
                "availability_basis": AVAILABILITY_BASIS,
                "observed_before_cutoff": observed < cutoff,
            }
            row["snapshot_id"] = _identity(row)
            rows.append(row)
    if not rows:
        raise LineupSnapshotError("no regular-season games found for target date")
    rows.sort(key=lambda row: (row["scheduled_start_at"], row["game_pk"], row["side"]))
    return rows


def summarize_lineups(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Coverage counts for a lineup capture."""
    return {
        "game_sides": len(rows),
        "confirmed_lineups": sum(
            1 for row in rows if row["lineup_status"] == STATUS_CONFIRMED
        ),
        "lineups_observed_before_cutoff": sum(
            1 for row in rows if row["observed_before_cutoff"] is True
        ),
    }
