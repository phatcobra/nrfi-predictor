"""Boundary tests for the <=2024 Statcast day-cache extraction contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from nrfi import statcast_extraction as sx


def _touch(root: Path, rel: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"parquet-placeholder")
    return path


def _seed_cache(root: Path) -> None:
    _touch(root, "2015/04/statcast_2015_04_06.parquet")
    _touch(root, "2024/09/statcast_2024_09_30.parquet")
    _touch(root, "2020/07/statcast_2020_07_24.parquet")
    # rejects that must never be opened
    _touch(root, "2025/03/statcast_2025_03_28.parquet")
    _touch(root, "2024/06/statcast_2024_06_15.parquet.corrupt_20260622t220355")
    _touch(root, "2024/13/statcast_2024_13_01.parquet")
    _touch(root, "2024/09/statcast_2023_09_30.parquet")
    _touch(root, "2024/09/notes.txt")


def test_ledger_admits_only_in_range_and_never_lists_2025(tmp_path: Path) -> None:
    _seed_cache(tmp_path)

    ledger = sx.build_source_ledger(tmp_path)

    admitted = {row["relative_path"] for row in ledger["admitted"]}
    assert admitted == {
        "2015/04/statcast_2015_04_06.parquet",
        "2020/07/statcast_2020_07_24.parquet",
        "2024/09/statcast_2024_09_30.parquet",
    }
    assert all(not row["opened"] for row in ledger["admitted"])
    assert all(
        not str(row["game_date"]).startswith("2025") for row in ledger["admitted"]
    )

    reasons = {row["relative_path"]: row["reason"] for row in ledger["rejected"]}
    # the 2025 season directory is rejected as a whole and never traversed
    assert reasons["2025"] == "LOCKED_2025_SEASON_DIRECTORY_NOT_TRAVERSED"
    assert not any(
        row["relative_path"].startswith("2025/") for row in ledger["rejected"]
    )
    assert (
        reasons["2024/06/statcast_2024_06_15.parquet.corrupt_20260622t220355"]
        == "FILENAME_NOT_ADMITTED_PARQUET"
    )
    assert (
        reasons["2024/13/statcast_2024_13_01.parquet"] == "UNRESOLVABLE_CALENDAR_DATE"
    )
    assert (
        reasons["2024/09/statcast_2023_09_30.parquet"]
        == "FILENAME_SEASON_DIRECTORY_MISMATCH"
    )
    assert reasons["2024/09/notes.txt"] == "FILENAME_NOT_ADMITTED_PARQUET"


def test_ledger_is_deterministic(tmp_path: Path) -> None:
    _seed_cache(tmp_path)

    first = sx.build_source_ledger(tmp_path)
    second = sx.build_source_ledger(tmp_path)

    assert first == second


def test_open_history_refuses_a_2025_dated_entry(tmp_path: Path) -> None:
    _seed_cache(tmp_path)
    poisoned = [
        {
            "relative_path": "2025/03/statcast_2025_03_28.parquet",
            "reason": "IN_RANGE_STATCAST_DAY_FILE",
            "game_date": "2025-03-28",
        }
    ]
    with pytest.raises(sx.StatcastExtractionError, match="locked-2025"):
        sx.build_pitcher_game_history_from_daycache(tmp_path, poisoned, [])


def test_generate_rejects_seasons_touching_2025(tmp_path: Path) -> None:
    with pytest.raises(sx.StatcastExtractionError):
        sx.generate_expanded_pitcher_statcast_package(
            day_cache_dir=tmp_path,
            multiseason_dir=tmp_path,
            output_dir=tmp_path / "out",
            producing_commit="a" * 40,
            seasons=[2024, 2025],
        )


def test_empty_admitted_history_produces_no_open(tmp_path: Path) -> None:
    (tmp_path / "2019").mkdir()

    ledger = sx.build_source_ledger(tmp_path)
    history, rejections, opened = sx.build_pitcher_game_history_from_daycache(
        tmp_path, ledger["admitted"], []
    )

    assert history == []
    assert rejections == []
    assert opened == []
