"""Synthetic StatsAPI-shaped payloads for parser tests.

Deliberately fictional teams, players, venues, and IDs — these mirror the
schedule schema, not any real game. No test in this repo touches a live API.
"""

from __future__ import annotations

from typing import Any

TEAM_ALPHA = {"id": 9001, "name": "Testville Alphas"}
TEAM_BETA = {"id": 9002, "name": "Mockington Betas"}
VENUE = {"id": 7001, "name": "Fixture Park"}
PITCHER_A = {"id": 500001, "fullName": "Test Pitcher Alpha"}
PITCHER_B = {"id": 500002, "fullName": "Test Pitcher Beta"}


def innings(first_away: int, first_home: int | None, count: int = 9) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for num in range(1, count + 1):
        if num == 1:
            home_half: dict[str, Any] = {} if first_home is None else {"runs": first_home}
            out.append({"num": num, "away": {"runs": first_away}, "home": home_half})
        else:
            out.append({"num": num, "away": {"runs": 0}, "home": {"runs": 0}})
    return out


def game(
    game_pk: int,
    date: str,
    status: str = "Final",
    first_away: int | None = 0,
    first_home: int | None = 0,
    innings_count: int = 9,
    game_type: str = "R",
    day_night: str = "night",
    home_pitcher: dict | None = PITCHER_A,
    away_pitcher: dict | None = PITCHER_B,
    home_team: dict | None = None,
    away_team: dict | None = None,
    venue: dict | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "gamePk": game_pk,
        "gameType": game_type,
        "season": date[:4],
        "gameDate": f"{date}T23:05:00Z",
        "officialDate": date,
        "status": {"abstractGameState": status, "detailedState": status},
        "dayNight": day_night,
        "doubleHeader": "N",
        "venue": venue or VENUE,
        "teams": {
            "away": {"team": away_team or TEAM_BETA},
            "home": {"team": home_team or TEAM_ALPHA},
        },
    }
    if home_pitcher is not None:
        body["teams"]["home"]["probablePitcher"] = home_pitcher
    if away_pitcher is not None:
        body["teams"]["away"]["probablePitcher"] = away_pitcher
    if first_away is not None and status == "Final":
        body["linescore"] = {"currentInning": innings_count, "innings": innings(first_away, first_home, innings_count)}
    return body


def schedule_payload(games: list[dict[str, Any]]) -> dict[str, Any]:
    by_date: dict[str, list[dict[str, Any]]] = {}
    for g in games:
        by_date.setdefault(g["officialDate"], []).append(g)
    return {
        "totalGames": len(games),
        "dates": [{"date": d, "games": gs} for d, gs in sorted(by_date.items())],
    }


def venues_payload() -> dict[str, Any]:
    return {
        "venues": [
            {
                "id": 7001,
                "name": "Fixture Park",
                "location": {"defaultCoordinates": {"latitude": 41.0, "longitude": -87.0}},
                "fieldInfo": {"roofType": "Open"},
            },
            {
                "id": 7002,
                "name": "Fixture Dome",
                "location": {"defaultCoordinates": {"latitude": 27.0, "longitude": -82.0}},
                "fieldInfo": {"roofType": "Dome"},
            },
            {"id": 7003, "name": "No-Coordinates Grounds"},
        ]
    }
