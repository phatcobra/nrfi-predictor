"""Validate the observed-data contract before model training or scoring.

This module does not populate data and never substitutes defaults. It proves
that every table and column consumed by the feature builder exists, contains a
minimum viable number of observed rows, and covers the declared training
window. Callers fail closed when any requirement is unmet.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from nrfi.config import HOLDOUT_START_DATE, TRAIN_END_DATE, TRAIN_START_DATE
from nrfi.snowflake_loader import SnowflakeLoader


@dataclass(frozen=True)
class DatasetContract:
    table: str
    required_columns: frozenset[str]
    date_column: str | None
    minimum_rows: int
    require_full_training_window: bool = True


CONTRACTS: tuple[DatasetContract, ...] = (
    DatasetContract(
        "NRFI_DB.CORE.FIRST_INNING_OUTCOMES",
        frozenset({
            "game_id", "game_date", "away_team", "home_team", "away_sp_id",
            "home_sp_id", "venue_id", "fi_runs_top", "fi_runs_bottom", "yrfi",
        }),
        "game_date",
        5_000,
    ),
    DatasetContract(
        "NRFI_DB.RAW.PITCHER_GAME_LOGS",
        frozenset({
            "pitcher_id", "game_id", "game_date", "opponent_team", "earned_runs",
            "runs_allowed", "hits", "walks", "strikeouts", "innings_pitched",
        }),
        "game_date",
        10_000,
    ),
    DatasetContract(
        "NRFI_DB.RAW.PITCHER_INNING_LOGS",
        frozenset({
            "pitcher_id", "game_id", "game_date", "inning", "first_inning_runs",
            "first_inning_hits", "first_inning_walks",
        }),
        "game_date",
        10_000,
    ),
    DatasetContract(
        "NRFI_DB.RAW.STATCAST_PITCHER_DAILY",
        frozenset({
            "pitcher_id", "game_date", "exit_velocity_sum", "barrels", "hard_hits",
            "whiffs", "swings", "batted_balls",
        }),
        "game_date",
        10_000,
    ),
    DatasetContract(
        "NRFI_DB.RAW.TEAM_GAME_LOGS",
        frozenset({
            "team", "game_id", "game_date", "runs", "hits", "at_bats",
            "total_bases", "times_on_base", "plate_appearances", "woba_num",
            "woba_den",
        }),
        "game_date",
        10_000,
    ),
    DatasetContract(
        "NRFI_DB.RAW.TEAM_INNING_LOGS",
        frozenset({"team", "game_id", "game_date", "inning", "first_inning_runs"}),
        "game_date",
        10_000,
    ),
    DatasetContract(
        "NRFI_DB.RAW.BATTER_GAME_LOGS",
        frozenset({
            "batter_id", "game_id", "game_date", "woba_num", "woba_den",
            "times_on_base", "plate_appearances",
        }),
        "game_date",
        50_000,
    ),
    DatasetContract(
        "NRFI_DB.RAW.PARK_FACTORS",
        frozenset({
            "venue_id", "runs_factor", "hr_factor", "hits_factor",
            "calculated_through", "source",
        }),
        "calculated_through",
        20,
        require_full_training_window=False,
    ),
)


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def evaluate_snapshot(
    snapshot: dict[str, dict[str, Any]],
    train_start: str = TRAIN_START_DATE,
    train_end: str = TRAIN_END_DATE,
    holdout_start: str = HOLDOUT_START_DATE,
) -> dict[str, Any]:
    """Evaluate a warehouse snapshot without performing database I/O."""
    start = date.fromisoformat(train_start)
    end = date.fromisoformat(train_end)
    holdout = date.fromisoformat(holdout_start)
    datasets: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    for contract in CONTRACTS:
        observed = snapshot.get(contract.table)
        item_errors: list[str] = []
        if observed is None:
            item_errors.append("table_missing")
            observed = {}

        columns = {str(value).lower() for value in observed.get("columns", [])}
        missing_columns = sorted(contract.required_columns.difference(columns))
        if missing_columns:
            item_errors.append("missing_columns:" + ",".join(missing_columns))

        try:
            row_count = int(observed.get("row_count", 0) or 0)
        except (TypeError, ValueError):
            row_count = 0
        if row_count < contract.minimum_rows:
            item_errors.append(
                f"row_count_{row_count}_below_{contract.minimum_rows}")

        minimum_date = _as_date(observed.get("minimum_date"))
        maximum_date = _as_date(observed.get("maximum_date"))
        if contract.date_column:
            if minimum_date is None or maximum_date is None:
                item_errors.append("date_coverage_unknown")
            elif contract.require_full_training_window:
                if minimum_date > start:
                    item_errors.append(
                        f"starts_{minimum_date.isoformat()}_after_{start.isoformat()}")
                if maximum_date < end:
                    item_errors.append(
                        f"ends_{maximum_date.isoformat()}_before_{end.isoformat()}")
            elif contract.table.endswith("PARK_FACTORS") and maximum_date >= holdout:
                item_errors.append(
                    f"park_factors_use_locked_or_future_data_through_{maximum_date.isoformat()}")

        datasets[contract.table] = {
            "ready": not item_errors,
            "row_count": row_count,
            "minimum_date": minimum_date.isoformat() if minimum_date else None,
            "maximum_date": maximum_date.isoformat() if maximum_date else None,
            "missing_columns": missing_columns,
            "errors": item_errors,
        }
        errors.extend(f"{contract.table}:{error}" for error in item_errors)

    return {
        "ready": not errors,
        "training_window": {"start": train_start, "end": train_end},
        "locked_holdout_start": holdout_start,
        "datasets": datasets,
        "errors": errors,
    }


def inspect_warehouse(loader: SnowflakeLoader | None = None) -> dict[str, Any]:
    """Read table schemas/counts/date ranges and return a readiness report."""
    warehouse = loader or SnowflakeLoader()
    snapshot: dict[str, dict[str, Any]] = {}

    for contract in CONTRACTS:
        database, schema, table = contract.table.split(".")
        columns = warehouse.execute_query(
            f"""
            SELECT LOWER(column_name) AS column_name
            FROM {database}.INFORMATION_SCHEMA.COLUMNS
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
            """,
            [schema.upper(), table.upper()],
        )
        if not columns:
            snapshot[contract.table] = {
                "columns": [], "row_count": 0,
                "minimum_date": None, "maximum_date": None,
            }
            continue

        date_expression = contract.date_column or "NULL"
        statistics = warehouse.execute_query(
            f"""
            SELECT COUNT(*) AS row_count,
                   MIN({date_expression}) AS minimum_date,
                   MAX({date_expression}) AS maximum_date
            FROM {contract.table}
            """
        )
        row = statistics[0] if statistics else {}
        snapshot[contract.table] = {
            "columns": [item["column_name"] for item in columns],
            "row_count": row.get("row_count", 0),
            "minimum_date": row.get("minimum_date"),
            "maximum_date": row.get("maximum_date"),
        }

    return evaluate_snapshot(snapshot)


def require_warehouse_ready(loader: SnowflakeLoader | None = None) -> dict[str, Any]:
    report = inspect_warehouse(loader)
    if not report["ready"]:
        raise RuntimeError(
            "warehouse data contract failed; training/scoring refused:\n"
            + json.dumps(report, indent=2, default=str)
        )
    return report


def main() -> None:
    report = inspect_warehouse()
    print(json.dumps(report, indent=2, default=str))
    if not report["ready"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
