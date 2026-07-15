"""Schema-validated loading of observed raw datasets into Snowflake.

The loader accepts CSV or Parquet, rejects missing/unknown columns, null or
duplicate keys, invalid dates, and invalid numeric values, then performs an
idempotent Snowflake MERGE. Source provenance and ingestion time are added by
the loader; no statistical values are inferred or imputed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from nrfi.snowflake_loader import SnowflakeLoader


@dataclass(frozen=True)
class LoadSpec:
    table: str
    key_columns: tuple[str, ...]
    required_columns: frozenset[str]
    allowed_columns: frozenset[str]
    date_columns: tuple[str, ...] = ("game_date",)
    numeric_columns: tuple[str, ...] = ()


SPECS: dict[str, LoadSpec] = {
    "pitcher_games": LoadSpec(
        table="NRFI_DB.RAW.PITCHER_GAME_LOGS",
        key_columns=("pitcher_id", "game_id"),
        required_columns=frozenset(
            {
                "pitcher_id",
                "game_id",
                "game_date",
                "opponent_team",
                "earned_runs",
                "runs_allowed",
                "hits",
                "walks",
                "strikeouts",
                "innings_pitched",
            }
        ),
        allowed_columns=frozenset(
            {
                "pitcher_id",
                "game_id",
                "game_date",
                "opponent_team",
                "earned_runs",
                "runs_allowed",
                "hits",
                "walks",
                "strikeouts",
                "innings_pitched",
            }
        ),
        numeric_columns=(
            "pitcher_id",
            "earned_runs",
            "runs_allowed",
            "hits",
            "walks",
            "strikeouts",
            "innings_pitched",
        ),
    ),
    "pitcher_innings": LoadSpec(
        table="NRFI_DB.RAW.PITCHER_INNING_LOGS",
        key_columns=("pitcher_id", "game_id", "inning"),
        required_columns=frozenset(
            {
                "pitcher_id",
                "game_id",
                "game_date",
                "inning",
                "first_inning_runs",
                "first_inning_hits",
                "first_inning_walks",
            }
        ),
        allowed_columns=frozenset(
            {
                "pitcher_id",
                "game_id",
                "game_date",
                "inning",
                "first_inning_runs",
                "first_inning_hits",
                "first_inning_walks",
                "first_inning_strikeouts",
                "first_inning_pa",
            }
        ),
        numeric_columns=(
            "pitcher_id",
            "inning",
            "first_inning_runs",
            "first_inning_hits",
            "first_inning_walks",
            "first_inning_strikeouts",
            "first_inning_pa",
        ),
    ),
    "statcast_pitcher_daily": LoadSpec(
        table="NRFI_DB.RAW.STATCAST_PITCHER_DAILY",
        key_columns=("pitcher_id", "game_date"),
        required_columns=frozenset(
            {
                "pitcher_id",
                "game_date",
                "exit_velocity_sum",
                "barrels",
                "hard_hits",
                "whiffs",
                "swings",
                "batted_balls",
            }
        ),
        allowed_columns=frozenset(
            {
                "pitcher_id",
                "game_date",
                "exit_velocity_sum",
                "barrels",
                "hard_hits",
                "whiffs",
                "swings",
                "batted_balls",
            }
        ),
        numeric_columns=(
            "pitcher_id",
            "exit_velocity_sum",
            "barrels",
            "hard_hits",
            "whiffs",
            "swings",
            "batted_balls",
        ),
    ),
    "team_games": LoadSpec(
        table="NRFI_DB.RAW.TEAM_GAME_LOGS",
        key_columns=("team", "game_id"),
        required_columns=frozenset(
            {
                "team",
                "game_id",
                "game_date",
                "runs",
                "hits",
                "at_bats",
                "total_bases",
                "times_on_base",
                "plate_appearances",
                "woba_num",
                "woba_den",
            }
        ),
        allowed_columns=frozenset(
            {
                "team",
                "game_id",
                "game_date",
                "runs",
                "hits",
                "at_bats",
                "total_bases",
                "times_on_base",
                "plate_appearances",
                "woba_num",
                "woba_den",
            }
        ),
        numeric_columns=(
            "runs",
            "hits",
            "at_bats",
            "total_bases",
            "times_on_base",
            "plate_appearances",
            "woba_num",
            "woba_den",
        ),
    ),
    "team_innings": LoadSpec(
        table="NRFI_DB.RAW.TEAM_INNING_LOGS",
        key_columns=("team", "game_id", "inning"),
        required_columns=frozenset(
            {
                "team",
                "game_id",
                "game_date",
                "inning",
                "first_inning_runs",
            }
        ),
        allowed_columns=frozenset(
            {
                "team",
                "game_id",
                "game_date",
                "inning",
                "first_inning_runs",
            }
        ),
        numeric_columns=("inning", "first_inning_runs"),
    ),
    "batter_games": LoadSpec(
        table="NRFI_DB.RAW.BATTER_GAME_LOGS",
        key_columns=("batter_id", "game_id"),
        required_columns=frozenset(
            {
                "batter_id",
                "game_id",
                "game_date",
                "woba_num",
                "woba_den",
                "times_on_base",
                "plate_appearances",
            }
        ),
        allowed_columns=frozenset(
            {
                "batter_id",
                "game_id",
                "game_date",
                "woba_num",
                "woba_den",
                "times_on_base",
                "plate_appearances",
            }
        ),
        numeric_columns=(
            "batter_id",
            "woba_num",
            "woba_den",
            "times_on_base",
            "plate_appearances",
        ),
    ),
    "park_factors": LoadSpec(
        table="NRFI_DB.RAW.PARK_FACTORS",
        key_columns=("venue_id",),
        required_columns=frozenset(
            {
                "venue_id",
                "runs_factor",
                "hr_factor",
                "hits_factor",
                "calculated_through",
            }
        ),
        allowed_columns=frozenset(
            {
                "venue_id",
                "runs_factor",
                "hr_factor",
                "hits_factor",
                "calculated_through",
            }
        ),
        date_columns=("calculated_through",),
        numeric_columns=("venue_id", "runs_factor", "hr_factor", "hits_factor"),
    ),
}


def read_dataset(path: str | Path) -> pd.DataFrame:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(file_path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(file_path)
    raise ValueError("input must be CSV or Parquet")


def _normalize_columns(columns: Iterable[object]) -> list[str]:
    normalized = [str(column).strip().lower() for column in columns]
    if len(normalized) != len(set(normalized)):
        raise ValueError("input has duplicate columns after lower-case normalization")
    return normalized


def validate_frame(frame: pd.DataFrame, dataset: str, source: str) -> pd.DataFrame:
    if dataset not in SPECS:
        raise ValueError(f"unknown dataset {dataset!r}; choose from {sorted(SPECS)}")
    if not source or not source.strip():
        raise ValueError("source provenance is required")
    if frame is None or frame.empty:
        raise ValueError("input dataset is empty")

    spec = SPECS[dataset]
    result = frame.copy()
    result.columns = _normalize_columns(result.columns)
    columns = set(result.columns)
    missing = sorted(spec.required_columns.difference(columns))
    unknown = sorted(columns.difference(spec.allowed_columns))
    if missing:
        raise ValueError(f"missing required columns: {missing}")
    if unknown:
        raise ValueError(f"unknown columns are not allowed: {unknown}")

    result = result.loc[:, sorted(spec.allowed_columns.intersection(columns))]
    for column in spec.date_columns:
        parsed = pd.to_datetime(result[column], errors="raise", utc=True)
        result[column] = parsed.dt.date
    for column in spec.numeric_columns:
        if column in result.columns:
            result[column] = pd.to_numeric(result[column], errors="raise")

    if result.loc[:, list(spec.key_columns)].isna().any().any():
        raise ValueError(f"null values found in key columns {spec.key_columns}")
    duplicate_mask = result.duplicated(subset=list(spec.key_columns), keep=False)
    if duplicate_mask.any():
        examples = result.loc[duplicate_mask, list(spec.key_columns)].head(5)
        raise ValueError(
            "duplicate dataset keys found: " + examples.to_dict("records").__repr__()
        )

    result["source"] = source.strip()
    result["ingested_at"] = datetime.now(timezone.utc).isoformat()
    return result


def load_dataset(
    dataset: str, path: str | Path, source: str, loader: SnowflakeLoader | None = None
) -> int:
    validated = validate_frame(read_dataset(path), dataset, source)
    spec = SPECS[dataset]
    warehouse = loader or SnowflakeLoader()
    warehouse.merge_upsert(
        spec.table,
        validated.to_dict("records"),
        key_cols=list(spec.key_columns),
    )
    return len(validated)
