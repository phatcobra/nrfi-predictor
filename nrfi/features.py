"""Feature engineering for NRFI/YRFI prediction (fail-closed).

Contract (Phase 1):
  - A feature that cannot be computed is NaN. Never a default, never random.
  - Every family emits a `<family>_missing` indicator (0.0/1.0).
  - Rate stats are ratio-of-sums (SUM(er)*9/SUM(ip)), never AVG of per-game
    ratios.
  - All queries are strictly `game_date < as_of` (leakage guard).
  - First-inning run rate is labeled RA9 (runs allowed), not ERA.
  - Betting odds are NOT model features: the market is the comparator for
    diagnostic edge, and 2015-2024 training data has no NRFI odds.

Phase 2 replaces the per-game queries below with set-based feature builds
persisted to FEATURES.GAME_FEATURES; the NaN/missing-flag contract is
already the one that pipeline will keep.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from nrfi.snowflake_loader import SnowflakeLoader

logger = logging.getLogger(__name__)

NAN = float("nan")


class NFRIFeatureEngineer:
    """Generate fail-closed features for one game."""

    def __init__(self, snowflake_loader: Optional[SnowflakeLoader] = None):
        self.sf = snowflake_loader or SnowflakeLoader()
        self.lookback_days = [7, 14, 30, 90, 365]

    # ------------------------------------------------------------------ api

    def generate_game_features(self, game_data: Dict) -> Dict:
        """Return {feature: value} for one game. Missing => NaN + flag."""
        as_of = pd.to_datetime(game_data["game_date"])
        features: Dict[str, float] = {}

        features.update(self._pitcher_features(game_data.get("away_pitcher_id"), "away", as_of))
        features.update(self._pitcher_features(game_data.get("home_pitcher_id"), "home", as_of))
        features.update(self._team_offense_features(game_data.get("away_team"), "away", as_of))
        features.update(self._team_offense_features(game_data.get("home_team"), "home", as_of))
        features.update(self._matchup_features(game_data.get("away_pitcher_id"),
                                               game_data.get("home_team"), "away", as_of))
        features.update(self._matchup_features(game_data.get("home_pitcher_id"),
                                               game_data.get("away_team"), "home", as_of))
        features.update(self._park_features(game_data.get("venue_id")))
        features.update(self._weather_features(game_data))
        features.update(self._lineup_features(game_data.get("lineups"), as_of))

        features["season"] = float(as_of.year)
        features["season_week"] = float(int(as_of.strftime("%V")))
        return features

    @staticmethod
    def coverage(features: Dict[str, float]) -> float:
        """Share of non-missing feature values (missing flags excluded)."""
        vals = [v for k, v in features.items() if not k.endswith("_missing")]
        if not vals:
            return 0.0
        present = sum(0 if (v is None or (isinstance(v, float) and np.isnan(v))) else 1
                      for v in vals)
        return present / len(vals)

    # ------------------------------------------------------------- families

    def _pitcher_features(self, pitcher_id, side: str, as_of: datetime) -> Dict:
        f: Dict[str, float] = {}
        if pitcher_id is None:
            # No probable pitcher: the whole family is missing.
            f[f"{side}_p_missing"] = 1.0
            return f

        career = self._q_pitcher_agg(pitcher_id, None, as_of)
        f[f"{side}_p_career_era"]  = _num(career, "era")
        f[f"{side}_p_career_whip"] = _num(career, "whip")
        f[f"{side}_p_career_k9"]   = _num(career, "k_per_9")
        f[f"{side}_p_career_bb9"]  = _num(career, "bb_per_9")
        f[f"{side}_p_career_ip"]   = _num(career, "total_ip")

        fi = self._q_pitcher_first_inning(pitcher_id, as_of)
        f[f"{side}_p_fi_ra9"]       = _num(fi, "fi_ra9")
        f[f"{side}_p_fi_whip"]      = _num(fi, "fi_whip")
        f[f"{side}_p_fi_runs_rate"] = _num(fi, "runs_per_game")
        f[f"{side}_p_fi_nrfi_rate"] = _num(fi, "nrfi_pct")
        f[f"{side}_p_fi_games"]     = _num(fi, "fi_games")

        for days in self.lookback_days:
            recent = self._q_pitcher_agg(pitcher_id, as_of - timedelta(days=days), as_of)
            f[f"{side}_p_{days}d_era"]    = _num(recent, "era")
            f[f"{side}_p_{days}d_whip"]   = _num(recent, "whip")
            f[f"{side}_p_{days}d_starts"] = _num(recent, "games_started")

        sc = self._q_statcast_pitcher(pitcher_id, as_of)
        f[f"{side}_p_avg_exit_velo"] = _num(sc, "avg_exit_velocity")
        f[f"{side}_p_barrel_pct"]    = _num(sc, "barrel_pct")
        f[f"{side}_p_hard_hit_pct"]  = _num(sc, "hard_hit_pct")
        f[f"{side}_p_whiff_pct"]     = _num(sc, "whiff_pct")

        f[f"{side}_p_missing"] = _family_missing(f, f"{side}_p_")
        return f

    def _team_offense_features(self, team, side: str, as_of: datetime) -> Dict:
        f: Dict[str, float] = {}
        if not team:
            f[f"{side}_t_missing"] = 1.0
            return f

        season = self._q_team_offense(team, None, as_of)
        f[f"{side}_t_season_avg"]  = _num(season, "batting_avg")
        f[f"{side}_t_season_obp"]  = _num(season, "obp")
        f[f"{side}_t_season_slg"]  = _num(season, "slg")
        f[f"{side}_t_season_woba"] = _num(season, "woba")
        f[f"{side}_t_season_rpg"]  = _num(season, "runs_per_game")

        fi = self._q_team_first_inning(team, as_of)
        f[f"{side}_t_fi_rpg"]         = _num(fi, "runs_per_game")
        f[f"{side}_t_fi_scoring_pct"] = _num(fi, "scoring_pct")

        for days in [7, 14, 30]:
            recent = self._q_team_offense(team, as_of - timedelta(days=days), as_of)
            f[f"{side}_t_{days}d_rpg"]  = _num(recent, "runs_per_game")
            f[f"{side}_t_{days}d_woba"] = _num(recent, "woba")

        f[f"{side}_t_missing"] = _family_missing(f, f"{side}_t_")
        return f

    def _matchup_features(self, pitcher_id, opp_team, side: str, as_of: datetime) -> Dict:
        f: Dict[str, float] = {}
        row = None
        if pitcher_id is not None and opp_team:
            row = self._q_pitcher_vs_team(pitcher_id, opp_team, as_of)
        f[f"{side}_matchup_games"] = _num(row, "games")
        f[f"{side}_matchup_ra9"]   = _num(row, "ra9")
        f[f"{side}_matchup_missing"] = _family_missing(f, f"{side}_matchup_")
        return f

    def _park_features(self, venue_id) -> Dict:
        row = self._q_park_factors(venue_id) if venue_id is not None else None
        f = {
            "park_runs_factor": _num(row, "runs_factor"),
            "park_hr_factor":   _num(row, "hr_factor"),
            "park_hits_factor": _num(row, "hits_factor"),
        }
        f["park_missing"] = _family_missing(f, "park_")
        return f

    def _weather_features(self, game_data: Dict) -> Dict:
        """NaN when unknown. A dome zeroes weather relevance, not the data."""
        w = game_data.get("weather") or {}
        is_dome = bool(game_data.get("is_dome", False))
        f = {
            "temp_f":     _maybe(w.get("temperature")),
            "wind_speed": _maybe(w.get("wind_speed")),
            "humidity":   _maybe(w.get("humidity")),
            "is_dome":    1.0 if is_dome else 0.0,
        }
        # Wind component toward CF: wind_mph * cos(wind_dir - cf_azimuth).
        wd, cf = w.get("wind_dir_deg"), game_data.get("cf_azimuth_deg")
        if wd is not None and cf is not None and f["wind_speed"] == f["wind_speed"]:
            f["wind_out_component"] = f["wind_speed"] * float(
                np.cos(np.radians(float(wd) - float(cf)))
            )
        else:
            f["wind_out_component"] = NAN
        if is_dome:
            f["weather_missing"] = 0.0
        else:
            f["weather_missing"] = (
                1.0 if any(np.isnan(v) for v in (f["temp_f"], f["wind_speed"])) else 0.0
            )
        return f

    def _lineup_features(self, lineups, as_of: datetime) -> Dict:
        f: Dict[str, float] = {}
        for side in ["away", "home"]:
            batters = (lineups or {}).get(side) or []
            top3 = batters[:3]
            stats = [s for s in (self._q_batter(b, as_of) for b in top3) if s]
            if len(stats) == 3:
                f[f"{side}_lineup_top3_woba"] = float(np.mean([_num(s, "woba") for s in stats]))
                f[f"{side}_lineup_top3_obp"]  = float(np.mean([_num(s, "obp") for s in stats]))
                f[f"{side}_lineup_missing"] = 0.0
            else:
                f[f"{side}_lineup_top3_woba"] = NAN
                f[f"{side}_lineup_top3_obp"]  = NAN
                f[f"{side}_lineup_missing"] = 1.0
        return f

    # ------------------------------------------------------------- queries
    # Ratio-of-sums everywhere; strict `game_date < as_of`.

    def _q(self, query: str, params: list) -> Optional[dict]:
        try:
            rows = self.sf.execute_query(query, params)
            return rows[0] if rows else None
        except Exception as e:  # fail closed: caller records NaN + flag
            logger.error(f"feature query failed: {e}")
            return None

    def _q_pitcher_agg(self, pid, start, end) -> Optional[dict]:
        q = """
        SELECT SUM(earned_runs) * 9.0 / NULLIF(SUM(innings_pitched), 0)  AS era,
               (SUM(hits) + SUM(walks)) / NULLIF(SUM(innings_pitched), 0) AS whip,
               SUM(strikeouts) * 9.0 / NULLIF(SUM(innings_pitched), 0)  AS k_per_9,
               SUM(walks) * 9.0 / NULLIF(SUM(innings_pitched), 0)       AS bb_per_9,
               SUM(innings_pitched) AS total_ip,
               COUNT(*)             AS games_started
        FROM NRFI_DB.RAW.PITCHER_GAME_LOGS
        WHERE pitcher_id = %s AND game_date < %s
        """
        params = [pid, end]
        if start is not None:
            q += " AND game_date >= %s"
            params.append(start)
        return self._q(q, params)

    def _q_pitcher_first_inning(self, pid, end) -> Optional[dict]:
        q = """
        SELECT SUM(first_inning_runs) * 9.0 / NULLIF(COUNT(*), 0) AS fi_ra9,
               (SUM(first_inning_hits) + SUM(first_inning_walks))
                   / NULLIF(COUNT(*), 0)                          AS fi_whip,
               AVG(first_inning_runs)                             AS runs_per_game,
               AVG(CASE WHEN first_inning_runs = 0 THEN 1.0 ELSE 0.0 END) AS nrfi_pct,
               COUNT(*)                                           AS fi_games
        FROM NRFI_DB.RAW.PITCHER_INNING_LOGS
        WHERE pitcher_id = %s AND inning = 1 AND game_date < %s
        """
        return self._q(q, [pid, end])

    def _q_statcast_pitcher(self, pid, end) -> Optional[dict]:
        q = """
        SELECT AVG(exit_velocity) AS avg_exit_velocity,
               AVG(CASE WHEN barrel = 1 THEN 100.0 ELSE 0.0 END)          AS barrel_pct,
               AVG(CASE WHEN exit_velocity >= 95 THEN 100.0 ELSE 0.0 END) AS hard_hit_pct,
               AVG(CASE WHEN swing = 1 AND contact = 0 THEN 100.0 ELSE 0.0 END) AS whiff_pct
        FROM NRFI_DB.RAW.STATCAST_PITCHER
        WHERE pitcher_id = %s AND game_date < %s AND game_date >= %s
        """
        return self._q(q, [pid, end, end - timedelta(days=30)])

    def _q_team_offense(self, team, start, end) -> Optional[dict]:
        q = """
        SELECT SUM(hits) / NULLIF(SUM(at_bats), 0)              AS batting_avg,
               SUM(times_on_base) / NULLIF(SUM(plate_appearances), 0) AS obp,
               SUM(total_bases) / NULLIF(SUM(at_bats), 0)       AS slg,
               AVG(woba)                                        AS woba,
               SUM(runs) / NULLIF(COUNT(*), 0)                  AS runs_per_game
        FROM NRFI_DB.RAW.TEAM_GAME_LOGS
        WHERE team = %s AND game_date < %s
        """
        params = [team, end]
        if start is not None:
            q += " AND game_date >= %s"
            params.append(start)
        return self._q(q, params)

    def _q_team_first_inning(self, team, end) -> Optional[dict]:
        q = """
        SELECT AVG(first_inning_runs) AS runs_per_game,
               AVG(CASE WHEN first_inning_runs > 0 THEN 1.0 ELSE 0.0 END) AS scoring_pct
        FROM NRFI_DB.RAW.TEAM_INNING_LOGS
        WHERE team = %s AND inning = 1 AND game_date < %s
        """
        return self._q(q, [team, end])

    def _q_pitcher_vs_team(self, pid, team, end) -> Optional[dict]:
        q = """
        SELECT COUNT(*) AS games,
               SUM(runs_allowed) * 9.0 / NULLIF(SUM(innings_pitched), 0) AS ra9
        FROM NRFI_DB.RAW.PITCHER_GAME_LOGS
        WHERE pitcher_id = %s AND opponent_team = %s AND game_date < %s
        """
        return self._q(q, [pid, team, end])

    def _q_park_factors(self, venue_id) -> Optional[dict]:
        q = """
        SELECT runs_factor, hr_factor, hits_factor
        FROM NRFI_DB.RAW.PARK_FACTORS
        WHERE venue_id = %s
        """
        return self._q(q, [venue_id])

    def _q_batter(self, batter_id, end) -> Optional[dict]:
        q = """
        SELECT AVG(woba) AS woba,
               SUM(times_on_base) / NULLIF(SUM(plate_appearances), 0) AS obp
        FROM NRFI_DB.RAW.BATTER_GAME_LOGS
        WHERE batter_id = %s AND game_date < %s AND game_date >= %s
        """
        return self._q(q, [batter_id, end, end - timedelta(days=30)])


# ---------------------------------------------------------------- helpers

def _num(row: Optional[dict], key: str) -> float:
    """NaN-safe numeric extraction. No default values, ever."""
    if row is None:
        return NAN
    v = row.get(key)
    if v is None:
        return NAN
    try:
        return float(v)
    except (TypeError, ValueError):
        return NAN


def _maybe(v) -> float:
    try:
        return float(v) if v is not None else NAN
    except (TypeError, ValueError):
        return NAN


def _family_missing(f: Dict[str, float], prefix: str) -> float:
    vals = [v for k, v in f.items() if k.startswith(prefix) and not k.endswith("_missing")]
    if not vals:
        return 1.0
    return 1.0 if all(isinstance(v, float) and np.isnan(v) for v in vals) else 0.0
