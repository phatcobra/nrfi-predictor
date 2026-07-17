"""Offline tests for the normalized warehouse readiness gate."""

from __future__ import annotations

from nrfi.data_readiness import CONTRACTS, evaluate_snapshot


def _ready_snapshot():
    snapshot = {}
    for contract in CONTRACTS:
        snapshot[contract.table] = {
            "columns": sorted(contract.required_columns),
            "row_count": contract.minimum_rows,
            "minimum_date": (
                "2015-04-01" if contract.require_full_training_window else "2024-10-01"
            ),
            "maximum_date": (
                "2024-11-30" if contract.require_full_training_window else "2024-11-30"
            ),
        }
    return snapshot


def test_complete_observed_snapshot_is_ready():
    report = evaluate_snapshot(_ready_snapshot())
    assert report["ready"] is True
    assert report["errors"] == []
    assert all(item["ready"] for item in report["datasets"].values())


def test_missing_table_fails_closed():
    snapshot = _ready_snapshot()
    missing_table = CONTRACTS[1].table
    del snapshot[missing_table]
    report = evaluate_snapshot(snapshot)
    assert report["ready"] is False
    assert any(
        error.startswith(f"{missing_table}:table_missing") for error in report["errors"]
    )


def test_missing_required_column_is_reported():
    snapshot = _ready_snapshot()
    contract = CONTRACTS[0]
    snapshot[contract.table]["columns"].remove("game_id")
    report = evaluate_snapshot(snapshot)
    assert report["ready"] is False
    assert "missing_columns:game_id" in report["datasets"][contract.table]["errors"]


def test_insufficient_rows_are_rejected():
    snapshot = _ready_snapshot()
    contract = CONTRACTS[2]
    snapshot[contract.table]["row_count"] = contract.minimum_rows - 1
    report = evaluate_snapshot(snapshot)
    assert report["ready"] is False
    assert any(
        error.startswith("row_count_")
        for error in report["datasets"][contract.table]["errors"]
    )


def test_incomplete_training_date_coverage_is_rejected():
    snapshot = _ready_snapshot()
    contract = next(item for item in CONTRACTS if item.require_full_training_window)
    snapshot[contract.table]["minimum_date"] = "2018-04-01"
    snapshot[contract.table]["maximum_date"] = "2023-11-30"
    report = evaluate_snapshot(snapshot)
    errors = report["datasets"][contract.table]["errors"]
    assert report["ready"] is False
    assert any(error.startswith("starts_2018-04-01_after_") for error in errors)
    assert any(error.startswith("ends_2023-11-30_before_") for error in errors)


def test_park_factors_cannot_use_locked_holdout_data():
    snapshot = _ready_snapshot()
    contract = next(item for item in CONTRACTS if item.table.endswith("PARK_FACTORS"))
    snapshot[contract.table]["maximum_date"] = "2025-06-01"
    report = evaluate_snapshot(snapshot)
    assert report["ready"] is False
    assert any(
        error.startswith("park_factors_use_locked_or_future_data")
        for error in report["datasets"][contract.table]["errors"]
    )
