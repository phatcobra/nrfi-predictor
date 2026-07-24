"""Tests for strict-prior team first-inning features."""

from __future__ import annotations

from typing import Any

import pytest

from nrfi import team_features as tf


def _game(
    pk: int, date: str, away_id: int, home_id: int, away_runs: int, home_runs: int
) -> dict[str, Any]:
    return {
        "game_type": "R",
        "game_pk": pk,
        "official_date": date,
        "scheduled_start_at": f"{date}T23:05:00Z",
        "time_semantics": {"label_available_at": f"{date}T23:59:00Z"},
        "away_team": {"team_id": away_id},
        "home_team": {"team_id": home_id},
        "first_inning": {
            "completed": True,
            "away_runs": away_runs,
            "home_runs": home_runs,
        },
    }


def _cut(*pks: int) -> dict[int, str]:
    return {pk: "2024-04-01T22:00:00Z" for pk in pks}


def test_two_records_per_game() -> None:
    games = [_game(1, "2024-04-01", 100, 200, 1, 0)]
    cutoffs = {1: "2024-04-01T22:00:00Z"}
    recs = tf.build_team_game_records(games, cutoffs)
    assert len(recs) == 2
    away = next(r for r in recs if r["team_id"] == 100)
    home = next(r for r in recs if r["team_id"] == 200)
    assert away["runs_scored"] == 1 and away["runs_allowed"] == 0
    assert away["scored"] == 1 and away["off_scoreless"] == 0
    assert home["runs_scored"] == 0 and home["runs_allowed"] == 1
    assert home["def_scoreless"] == 0 and home["off_scoreless"] == 1
    assert home["is_home"] is True and away["is_home"] is False


def _team100_history(n: int) -> list[dict[str, Any]]:
    games = [_game(i, f"2024-04-{i:02d}", 100, 300 + i, 1, 0) for i in range(1, n + 1)]
    cutoffs = {i: f"2024-04-{i:02d}T22:00:00Z" for i in range(1, n + 1)}
    return tf.build_team_game_records(games, cutoffs)


def test_strict_prior_excludes_current_game() -> None:
    recs = _team100_history(3)
    snaps = {
        s["game_pk"]: s
        for s in tf.build_team_feature_snapshots(recs)
        if s["team_id"] == 100
    }
    assert snaps[1]["prior_games"] == 0
    assert snaps[2]["prior_games"] == 1
    assert snaps[3]["prior_games"] == 2
    # team 100 scored in every prior game -> prior scored_rate_career == 1.0
    assert snaps[3]["feature_values"]["first_inning_scored_rate_career"] == 1.0


def test_minimum_history_gate() -> None:
    recs = _team100_history(25)
    snaps = [s for s in tf.build_team_feature_snapshots(recs) if s["team_id"] == 100]
    early = next(s for s in snaps if s["prior_games"] == 5)
    late = next(s for s in snaps if s["prior_games"] == 24)
    assert early["team_context_feature_eligible"] is False
    assert late["team_context_feature_eligible"] is True


def test_terminal_one_per_team_and_deterministic() -> None:
    recs = _team100_history(30)
    a = tf.build_terminal_team_profiles(recs)
    b = tf.build_terminal_team_profiles(recs)
    assert a == b
    # team 100 plays 30 games; each opponent (301..330) appears once.
    team100 = next(p for p in a if p["team_id"] == 100)
    assert team100["career_games"] == 30
    assert team100["team_context_feature_eligible"] is True
    # profiles sorted by team_id, one row per distinct team
    assert [p["team_id"] for p in a] == sorted(p["team_id"] for p in a)
    assert len({p["team_id"] for p in a}) == len(a)


def test_snapshots_deterministic() -> None:
    recs = _team100_history(20)
    assert tf.build_team_feature_snapshots(recs) == tf.build_team_feature_snapshots(
        recs
    )


def test_refuses_locked_2025_terminal() -> None:
    games = [_game(1, "2025-04-01", 100, 200, 1, 0)]
    # 2025 games are excluded by season filter in build_team_game_records, so
    # forge a record directly to exercise the terminal guard.
    recs = tf.build_team_game_records(games, {1: "2025-04-01T22:00:00Z"})
    assert recs == []  # season filter drops 2025
    forged = [
        {
            "team_id": 100,
            "season": 2025,
            "game_pk": 1,
            "official_date": "2025-04-01",
            "scheduled_start_at": "2025-04-01T23:05:00Z",
            "is_home": True,
            "runs_scored": 1,
            "runs_allowed": 0,
            "scored": 1,
            "allowed": 0,
            "off_scoreless": 0,
            "def_scoreless": 1,
        }
    ]
    with pytest.raises(tf.TeamFeatureError):
        tf.build_terminal_team_profiles(forged)


def test_load_refuses_2025(tmp_path: Any) -> None:
    (tmp_path / "features.jsonl").write_text(
        '{"game_pk": 1, "prediction_cutoff": "2025-04-01T22:00:00Z"}\n',
        encoding="utf-8",
    )
    (tmp_path / "normalized_games.jsonl").write_text(
        '{"game_pk": 1, "official_date": "2025-04-01"}\n', encoding="utf-8"
    )
    with pytest.raises(tf.TeamFeatureError):
        tf.load_games(tmp_path)
