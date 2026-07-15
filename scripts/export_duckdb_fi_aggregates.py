"""Export observed first-inning and Statcast aggregates from mlb-model DuckDB.

The output schemas match ``scripts/load_raw_dataset.py`` exactly. Plate
appearances are final-pitch rows (events IS NOT NULL); runs are score deltas.
No missing statistics are synthesized.

Usage:
    python scripts/export_duckdb_fi_aggregates.py --db /path/mlb.duckdb --out exports
    python scripts/load_raw_dataset.py --dataset pitcher_innings \
        --file exports/pitcher_innings.parquet --source mlb-model-statcast
    python scripts/load_raw_dataset.py --dataset statcast_pitcher_daily \
        --file exports/statcast_pitcher_daily.parquet --source mlb-model-statcast
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nrfi._obs import logger

PITCHER_INNINGS_SQL = """
COPY (
  WITH pa AS (
    SELECT pitcher AS pitcher_id,
           CAST(game_pk AS VARCHAR) AS game_id,
           game_date,
           events,
           post_bat_score - bat_score AS runs_on_pa,
           CASE WHEN events IN ('single','double','triple','home_run') THEN 1 ELSE 0 END AS hit,
           CASE WHEN events IN ('walk','hit_by_pitch') THEN 1 ELSE 0 END AS walk,
           CASE WHEN events = 'strikeout' THEN 1 ELSE 0 END AS strikeout
    FROM statcast_pitches_all
    WHERE inning = 1 AND events IS NOT NULL
  )
  SELECT pitcher_id,
         game_id,
         game_date,
         1 AS inning,
         SUM(runs_on_pa) AS first_inning_runs,
         SUM(hit) AS first_inning_hits,
         SUM(walk) AS first_inning_walks,
         SUM(strikeout) AS first_inning_strikeouts,
         COUNT(*) AS first_inning_pa
  FROM pa
  GROUP BY pitcher_id, game_id, game_date
) TO '{out}/pitcher_innings.parquet' (FORMAT PARQUET)
"""

STATCAST_PITCHER_DAILY_SQL = """
COPY (
  SELECT pitcher AS pitcher_id,
         game_date,
         SUM(CASE WHEN launch_speed IS NOT NULL THEN launch_speed ELSE 0 END)
             AS exit_velocity_sum,
         SUM(CASE WHEN barrel = 1 THEN 1 ELSE 0 END) AS barrels,
         SUM(CASE WHEN launch_speed >= 95 THEN 1 ELSE 0 END) AS hard_hits,
         SUM(CASE WHEN description IN
             ('swinging_strike','swinging_strike_blocked') THEN 1 ELSE 0 END) AS whiffs,
         SUM(CASE WHEN description LIKE '%swing%'
             OR description IN ('foul','hit_into_play') THEN 1 ELSE 0 END) AS swings,
         SUM(CASE WHEN launch_speed IS NOT NULL THEN 1 ELSE 0 END) AS batted_balls
  FROM statcast_pitches_all
  WHERE pitcher IS NOT NULL AND game_date IS NOT NULL
  GROUP BY pitcher, game_date
) TO '{out}/statcast_pitcher_daily.parquet' (FORMAT PARQUET)
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="path to mlb-model DuckDB file")
    parser.add_argument("--out", default="./exports")
    args = parser.parse_args()

    import duckdb

    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(args.db, read_only=True)
    try:
        for name, statement in (
            ("pitcher_innings", PITCHER_INNINGS_SQL),
            ("statcast_pitcher_daily", STATCAST_PITCHER_DAILY_SQL),
        ):
            destination = output / f"{name}.parquet"
            if destination.exists():
                destination.unlink()
            connection.execute(statement.format(out=str(output).replace("'", "''")))
            logger.info(f"exported {destination}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
