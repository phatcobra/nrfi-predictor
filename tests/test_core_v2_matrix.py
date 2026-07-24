"""Tests for the NRFI_CORE_V2 canonical historical matrix builder."""

from __future__ import annotations

from pathlib import Path

import pytest

from nrfi import core_v2_matrix as m


def test_numeric_features_flatten_and_null() -> None:
    out = m._numeric_features(
        {"a": 1, "b": None, "c": True, "d": False, "e": "night", "f": 2.5}, "away_p_"
    )
    assert out["away_p_a"] == 1.0
    assert out["away_p_b"] is None
    assert out["away_p_c"] == 1.0
    assert out["away_p_d"] == 0.0
    assert out["away_p_f"] == 2.5
    assert "away_p_e" not in out  # strings dropped from the numeric matrix


def _write_multiseason(tmp: Path, games: list[str], features: list[str]) -> Path:
    (tmp / "normalized_games.jsonl").write_text(
        "\n".join(games) + "\n", encoding="utf-8"
    )
    (tmp / "features.jsonl").write_text("\n".join(features) + "\n", encoding="utf-8")
    return tmp


def _game(
    pk: int, date: str, away_runs: int, home_runs: int, completed: bool = True
) -> str:
    import json

    return json.dumps(
        {
            "game_type": "R",
            "game_pk": pk,
            "official_date": date,
            "game_number": 1,
            "doubleheader_code": "N",
            "scheduled_start_at": f"{date}T23:05:00Z",
            "time_semantics": {"label_available_at": f"{date}T23:59:00Z"},
            "venue": {"venue_id": 3},
            "away_team": {"team_id": 100},
            "home_team": {"team_id": 200},
            "first_inning": {
                "completed": completed,
                "away_runs": away_runs,
                "home_runs": home_runs,
            },
        }
    )


def _feat(pk: int, date: str) -> str:
    import json

    return json.dumps({"game_pk": pk, "prediction_cutoff": f"{date}T22:00:00Z"})


def test_target_rows_nrfi_yrfi_and_exclusions(tmp_path: Path) -> None:
    games = [
        _game(1, "2024-04-01", 0, 0),  # NRFI
        _game(2, "2024-04-02", 1, 0),  # YRFI
        _game(3, "2024-04-03", 0, 0, completed=False),  # excluded, incomplete
        _game(4, "2024-04-04", 0, 0),  # excluded, no cutoff in features
    ]
    features = [_feat(1, "2024-04-01"), _feat(2, "2024-04-02"), _feat(3, "2024-04-03")]
    _write_multiseason(tmp_path, games, features)
    targets, meta = m._target_rows(tmp_path)
    by_pk = {t["game_pk"]: t for t in targets}
    assert by_pk[1]["nrfi"] == 1 and by_pk[1]["yrfi"] == 0
    assert by_pk[2]["yrfi"] == 1 and by_pk[2]["nrfi"] == 0
    assert 3 not in by_pk and 4 not in by_pk
    reasons = {r["game_pk"]: r["reason"] for r in meta["rejections"]}
    assert reasons[3] == m.NO_COMPLETED_FIRST_INNING
    assert reasons[4] == m.LABEL_UNAVAILABLE


def test_target_rows_refuses_2025(tmp_path: Path) -> None:
    _write_multiseason(
        tmp_path, [_game(1, "2025-04-01", 0, 0)], [_feat(1, "2025-04-01")]
    )
    with pytest.raises(m.CoreV2MatrixError):
        m._target_rows(tmp_path)


def test_duplicate_game_pk_excluded(tmp_path: Path) -> None:
    games = [_game(1, "2024-04-01", 0, 0), _game(1, "2024-04-01", 1, 1)]
    features = [_feat(1, "2024-04-01")]
    _write_multiseason(tmp_path, games, features)
    targets, meta = m._target_rows(tmp_path)
    assert len(targets) == 1
    assert any(
        r["game_pk"] == 1 and r["reason"] == m.AMBIGUOUS_GAME_IDENTITY
        for r in meta["rejections"]
    )
