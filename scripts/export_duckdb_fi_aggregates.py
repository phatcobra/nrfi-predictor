"""Export first-inning aggregates from the mlb-model DuckDB warehouse
(7.7M Statcast pitches) to Parquet for Snowflake COPY INTO.

Correct PA-level math (the old advanced_features.py used pitch counts as
PA/IP denominators - wrong by ~4x):
  - PAs      = rows where events IS NOT NULL (final pitch of each PA)
  - FI outs  = post_outs - outs at PA level within inning 1
  - FI runs  = post_bat_score - bat_score summed over inning-1 PAs
Usage:
  python scripts/export_duckdb_fi_aggregates.py --db /path/mlb.duckdb --out ./exports
Then (human, with Snowflake creds):
  COPY INTO NRFI_DB.RAW.PITCHER_INNING_LOGS FROM @stage/pitcher_fi.parquet ...
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nrfi._obs import logger  # noqa: E402

PITCHER_FI_SQL = """
COPY (
  WITH pa AS (
    SELECT pitcher AS pitcher_id, game_pk, game_date,
           events, post_bat_score - bat_score AS runs_on_pa,
           CASE WHEN events IN ('single','double','triple','home_run') THEN 1 ELSE 0 END AS hit,
           CASE WHEN events IN ('walk','hit_by_pitch') THEN 1 ELSE 0 END AS walk,
           CASE WHEN events = 'strikeout' THEN 1 ELSE 0 END AS k
    FROM statcast_pitches_all
    WHERE inning = 1 AND events IS NOT NULL
  )
  SELECT pitcher_id, game_date, 1 AS inning,
         SUM(runs_on_pa) AS first_inning_runs,
         SUM(hit)        AS first_inning_hits,
         SUM(walk)       AS first_inning_walks,
         SUM(k)          AS first_inning_strikeouts,
         COUNT(*)        AS first_inning_pa
  FROM pa
  GROUP BY pitcher_id, game_date
) TO '{out}/pitcher_fi.parquet' (FORMAT PARQUET)
"""

STATCAST_PITCHER_DAILY_SQL = """
COPY (
  SELECT pitcher AS pitcher_id, game_date,
         SUM(CASE WHEN launch_speed IS NOT NULL THEN launch_speed ELSE 0 END) AS exit_velocity_sum,
         SUM(CASE WHEN launch_speed IS NOT NULL THEN 1 ELSE 0 END)            AS batted_balls,
         SUM(CASE WHEN barrel = 1 THEN 1 ELSE 0 END)                          AS barrels,
         SUM(CASE WHEN launch_speed >= 95 THEN 1 ELSE 0 END)                  AS hard_hits,
         SUM(CASE WHEN description IN ('swinging_strike','swinging_strike_blocked') THEN 1 ELSE 0 END) AS whiffs,
         SUM(CASE WHEN description LIKE '%swing%' OR description IN ('foul','hit_into_play') THEN 1 ELSE 0 END) AS swings
  FROM statcast_pitches_all
  GROUP BY pitcher, game_date
) TO '{out}/statcast_pitcher_daily.parquet' (FORMAT PARQUET)
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="path to mlb-model DuckDB file")
    ap.add_argument("--out", default="./exports")
    args = ap.parse_args()
    import duckdb
    Path(args.out).mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(args.db, read_only=True)
    for name, sql in (("pitcher_fi", PITCHER_FI_SQL),
                      ("statcast_pitcher_daily", STATCAST_PITCHER_DAILY_SQL)):
        con.execute(sql.format(out=args.out))
        logger.info(f"exported {name}.parquet")
    logger.info("done - COPY INTO Snowflake next (human step, needs creds)")


if __name__ == "__main__":
    main()
