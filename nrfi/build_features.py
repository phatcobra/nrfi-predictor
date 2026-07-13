"""Set-based feature builder - THE single feature code path (train == serve).

Efficiency contract (SYSTEM_DESIGN_V3 SS6.3/SS10):
  - Each raw table is pulled ONCE per build (bulk query), then every game's
    trailing windows are answered in-memory via per-key cumulative sums +
    binary search. A 24K-game backfill is ~7 bulk queries, not ~450K.

Correctness contract:
  - Leakage guard: every window is strictly `date < as_of` (searchsorted
    side='left' on the game's as_of).
  - Rate stats are ratio-of-sums.
  - Missing => NaN + family missing flag. No defaults, no randomness.
  - Coverage = share of non-missing feature values; callers block below
    FEATURE_COVERAGE_MIN.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from nrfi.snowflake_loader import SnowflakeLoader

logger = logging.getLogger(__name__)

NAN = float("nan")
FEATURE_VERSION = "fv3.1"
PITCHER_DAY_WINDOWS = [7, 14, 30, 90, 365]
TEAM_DAY_WINDOWS = [7, 14, 30]
PITCHER_GS_WINDOW = 30  # trailing 30 games started (spec)


WEATHER_KEYS = frozenset(
    {"temp_f", "wind_speed", "humidity", "wind_out_component"})


def coverage(features: Dict[str, float]) -> float:
    """Share of non-missing values (missing flags excluded from the base).

    Dome games: weather fields are NOT APPLICABLE rather than missing, so
    they leave the denominator instead of dragging coverage down. This is
    denominator logic, not imputation - the values stay NaN."""
    dome = features.get("is_dome") == 1.0
    vals = [v for k, v in features.items()
            if not k.endswith("_missing")
            and not (dome and k in WEATHER_KEYS)]
    if not vals:
        return 0.0
    present = sum(
        0 if (v is None or (isinstance(v, float) and np.isnan(v))) else 1
        for v in vals
    )
    return present / len(vals)


class _Cum:
    """Per-key date-sorted cumulative sums; O(log n) leakage-safe windows."""

    def __init__(self, df: pd.DataFrame, key: str, date_col: str,
                 sum_cols: Sequence[str]):
        self.sum_cols = list(sum_cols)
        self.data: dict = {}
        if df is None or df.empty:
            return
        df = df.dropna(subset=[key, date_col]).sort_values([key, date_col])
        for k, g in df.groupby(key, sort=False):
            dates = g[date_col].to_numpy(dtype="datetime64[ns]")
            cums = {}
            for c in self.sum_cols:
                v = pd.to_numeric(g[c], errors="coerce").fillna(0.0).to_numpy()
                cums[c] = np.concatenate([[0.0], np.cumsum(v)])
            # count of non-null observations per col (for "did we have data")
            cnts = {}
            for c in self.sum_cols:
                nn = (~pd.to_numeric(g[c], errors="coerce").isna()).astype(float).to_numpy()
                cnts[c] = np.concatenate([[0.0], np.cumsum(nn)])
            self.data[k] = (dates, cums, cnts)

    def window(self, key, as_of: np.datetime64, days: Optional[int] = None,
               last_n: Optional[int] = None) -> Optional[Dict[str, float]]:
        """Sums + row count for rows with date < as_of (and >= as_of-days,
        or the last_n rows). None when the key has no prior rows."""
        entry = self.data.get(key)
        if entry is None:
            return None
        dates, cums, cnts = entry
        hi = int(np.searchsorted(dates, as_of, side="left"))  # strictly before
        if hi == 0:
            return None
        if days is not None:
            lo_date = as_of - np.timedelta64(days, "D")
            lo = int(np.searchsorted(dates, lo_date, side="left"))
        elif last_n is not None:
            lo = max(0, hi - last_n)
        else:
            lo = 0
        if hi <= lo:
            return None
        out = {c: cums[c][hi] - cums[c][lo] for c in self.sum_cols}
        out["_rows"] = float(hi - lo)
        for c in self.sum_cols:
            out[f"_n_{c}"] = cnts[c][hi] - cnts[c][lo]
        return out


def _ratio(w: Optional[dict], num: str, den: str, scale: float = 1.0) -> float:
    if w is None:
        return NAN
    d = w.get(den, 0.0)
    if not d:
        return NAN
    return scale * w[num] / d


def _per_row(w: Optional[dict], col: str) -> float:
    if w is None or not w.get("_rows"):
        return NAN
    if w.get(f"_n_{col}", 0.0) == 0.0:
        return NAN  # rows existed but this column was never observed
    return w[col] / w["_rows"]


def _count(w: Optional[dict]) -> float:
    return NAN if w is None else w.get("_rows", NAN)


def _family_missing(f: Dict[str, float], prefix: str) -> float:
    vals = [v for k, v in f.items()
            if k.startswith(prefix) and not k.endswith("_missing")]
    if not vals:
        return 1.0
    return 1.0 if all(isinstance(v, float) and np.isnan(v) for v in vals) else 0.0


class FeatureBuilder:
    """Bulk-load raw tables once, then answer per-game feature vectors."""

    def __init__(self, sf: Optional[SnowflakeLoader] = None,
                 raw_frames: Optional[Dict[str, pd.DataFrame]] = None):
        """raw_frames lets tests (and the DuckDB export) inject data directly;
        otherwise frames are bulk-queried from Snowflake at prepare()."""
        self.sf = sf
        self._frames = raw_frames
        self._prepared = False

    # ------------------------------------------------------------ loading

    def _bulk(self, query: str, params: list) -> pd.DataFrame:
        rows = self.sf.execute_query(query, params)
        return pd.DataFrame(rows)

    def prepare(self, max_date: str) -> None:
        """One bulk query per raw table (7 total). max_date bounds the pull;
        per-game leakage is enforced by the < as_of window, not here."""
        if self._frames is None:
            p = [max_date]
            self._frames = {
                "pitcher_games": self._bulk(
                    "SELECT pitcher_id, game_date, earned_runs, runs_allowed, hits, walks, "
                    "strikeouts, innings_pitched, opponent_team "
                    "FROM NRFI_DB.RAW.PITCHER_GAME_LOGS WHERE game_date < %s", p),
                "pitcher_fi": self._bulk(
                    "SELECT pitcher_id, game_date, first_inning_runs, first_inning_hits, "
                    "first_inning_walks FROM NRFI_DB.RAW.PITCHER_INNING_LOGS "
                    "WHERE inning = 1 AND game_date < %s", p),
                "statcast_pitcher": self._bulk(
                    "SELECT pitcher_id, game_date, exit_velocity_sum, barrels, hard_hits, "
                    "whiffs, swings, batted_balls FROM NRFI_DB.RAW.STATCAST_PITCHER_DAILY "
                    "WHERE game_date < %s", p),
                "team_games": self._bulk(
                    "SELECT team, game_date, runs, hits, at_bats, total_bases, "
                    "times_on_base, plate_appearances, woba_num, woba_den "
                    "FROM NRFI_DB.RAW.TEAM_GAME_LOGS WHERE game_date < %s", p),
                "team_fi": self._bulk(
                    "SELECT team, game_date, first_inning_runs "
                    "FROM NRFI_DB.RAW.TEAM_INNING_LOGS WHERE inning = 1 AND game_date < %s", p),
                "batters": self._bulk(
                    "SELECT batter_id, game_date, woba_num, woba_den, times_on_base, "
                    "plate_appearances FROM NRFI_DB.RAW.BATTER_GAME_LOGS "
                    "WHERE game_date < %s", p),
                "parks": self._bulk(
                    "SELECT venue_id, runs_factor, hr_factor, hits_factor "
                    "FROM NRFI_DB.RAW.PARK_FACTORS", []),
            }

        fr = self._frames
        for name in ("pitcher_games", "pitcher_fi", "statcast_pitcher",
                     "team_games", "team_fi", "batters"):
            df = fr.get(name)
            if df is not None and not df.empty:
                df["game_date"] = pd.to_datetime(df["game_date"])

        self.pg = _Cum(fr.get("pitcher_games"), "pitcher_id", "game_date",
                       ["earned_runs", "runs_allowed", "hits", "walks",
                        "strikeouts", "innings_pitched"])
        self.pfi = _Cum(fr.get("pitcher_fi"), "pitcher_id", "game_date",
                        ["first_inning_runs", "first_inning_hits", "first_inning_walks"])
        # nrfi indicator needs a derived column
        pfi_df = fr.get("pitcher_fi")
        if pfi_df is not None and not pfi_df.empty:
            pfi_df = pfi_df.copy()
            pfi_df["fi_zero"] = (pd.to_numeric(
                pfi_df["first_inning_runs"], errors="coerce") == 0).astype(float)
            self.pfi_nrfi = _Cum(pfi_df, "pitcher_id", "game_date", ["fi_zero"])
        else:
            self.pfi_nrfi = _Cum(pd.DataFrame(), "pitcher_id", "game_date", ["fi_zero"])
        self.scp = _Cum(fr.get("statcast_pitcher"), "pitcher_id", "game_date",
                        ["exit_velocity_sum", "barrels", "hard_hits",
                         "whiffs", "swings", "batted_balls"])
        self.tg = _Cum(fr.get("team_games"), "team", "game_date",
                       ["runs", "hits", "at_bats", "total_bases", "times_on_base",
                        "plate_appearances", "woba_num", "woba_den"])
        tfi_df = fr.get("team_fi")
        if tfi_df is not None and not tfi_df.empty:
            tfi_df = tfi_df.copy()
            tfi_df["fi_scored"] = (pd.to_numeric(
                tfi_df["first_inning_runs"], errors="coerce") > 0).astype(float)
            self.tfi = _Cum(tfi_df, "team", "game_date",
                            ["first_inning_runs", "fi_scored"])
        else:
            self.tfi = _Cum(pd.DataFrame(), "team", "game_date",
                            ["first_inning_runs", "fi_scored"])
        self.bat = _Cum(fr.get("batters"), "batter_id", "game_date",
                        ["woba_num", "woba_den", "times_on_base", "plate_appearances"])
        parks = fr.get("parks")
        self.parks = ({} if parks is None or parks.empty else
                      parks.set_index("venue_id").to_dict("index"))
        self._prepared = True

    # ------------------------------------------------------------ features

    def build_game(self, game: Dict) -> Dict[str, float]:
        assert self._prepared, "call prepare(max_date) first"
        as_of = np.datetime64(pd.to_datetime(game["game_date"]))
        f: Dict[str, float] = {}
        for side, pid_key, team_key, opp_key in (
            ("away", "away_pitcher_id", "away_team", "home_team"),
            ("home", "home_pitcher_id", "home_team", "away_team"),
        ):
            f.update(self._pitcher(game.get(pid_key), side, as_of))
            f.update(self._team(game.get(team_key), side, as_of))
        f.update(self._park(game.get("venue_id")))
        f.update(self._weather(game))
        f.update(self._lineups(game.get("lineups"), as_of))
        d = pd.to_datetime(game["game_date"])
        f["season"] = float(d.year)
        f["season_week"] = float(int(d.strftime("%V")))
        f["is_doubleheader"] = 1.0 if game.get("is_doubleheader") else 0.0
        return f

    def build_games(self, games: List[Dict]) -> Dict[str, Dict[str, float]]:
        return {str(g["game_id"]): self.build_game(g) for g in games}

    def _pitcher(self, pid, side: str, as_of) -> Dict[str, float]:
        f: Dict[str, float] = {}
        if pid is None:
            f[f"{side}_p_missing"] = 1.0
            return f
        career = self.pg.window(pid, as_of)
        f[f"{side}_p_career_era"] = _ratio(career, "earned_runs", "innings_pitched", 9.0)
        f[f"{side}_p_career_whip"] = (
            NAN if career is None else
            _ratio({"hw": career["hits"] + career["walks"],
                    "ip": career["innings_pitched"]}, "hw", "ip"))
        f[f"{side}_p_career_k9"] = _ratio(career, "strikeouts", "innings_pitched", 9.0)
        f[f"{side}_p_career_bb9"] = _ratio(career, "walks", "innings_pitched", 9.0)
        f[f"{side}_p_career_ip"] = NAN if career is None else career["innings_pitched"]

        # trailing 30 GS (spec window)
        g30 = self.pg.window(pid, as_of, last_n=PITCHER_GS_WINDOW)
        f[f"{side}_p_30gs_era"] = _ratio(g30, "earned_runs", "innings_pitched", 9.0)
        f[f"{side}_p_30gs_k9"] = _ratio(g30, "strikeouts", "innings_pitched", 9.0)

        fi = self.pfi.window(pid, as_of)
        f[f"{side}_p_fi_ra9"] = _ratio(fi, "first_inning_runs", "_rows", 9.0)
        f[f"{side}_p_fi_whip"] = (
            NAN if fi is None else
            (fi["first_inning_hits"] + fi["first_inning_walks"]) / fi["_rows"])
        f[f"{side}_p_fi_runs_rate"] = _per_row(fi, "first_inning_runs")
        fi_nrfi = self.pfi_nrfi.window(pid, as_of)
        f[f"{side}_p_fi_nrfi_rate"] = _per_row(fi_nrfi, "fi_zero")
        f[f"{side}_p_fi_games"] = _count(fi)

        for days in PITCHER_DAY_WINDOWS:
            w = self.pg.window(pid, as_of, days=days)
            f[f"{side}_p_{days}d_era"] = _ratio(w, "earned_runs", "innings_pitched", 9.0)
            f[f"{side}_p_{days}d_whip"] = (
                NAN if w is None else
                _ratio({"hw": w["hits"] + w["walks"],
                        "ip": w["innings_pitched"]}, "hw", "ip"))
            f[f"{side}_p_{days}d_starts"] = _count(w)

        # rest days: gap since previous start
        entry = self.pg.data.get(pid)
        if entry is not None:
            dates = entry[0]
            hi = int(np.searchsorted(dates, as_of, side="left"))
            f[f"{side}_p_rest_days"] = (
                float((as_of - dates[hi - 1]) / np.timedelta64(1, "D"))
                if hi > 0 else NAN)
        else:
            f[f"{side}_p_rest_days"] = NAN

        sc = self.scp.window(pid, as_of, days=30)
        f[f"{side}_p_avg_exit_velo"] = _ratio(sc, "exit_velocity_sum", "batted_balls")
        f[f"{side}_p_barrel_pct"] = _ratio(sc, "barrels", "batted_balls", 100.0)
        f[f"{side}_p_hard_hit_pct"] = _ratio(sc, "hard_hits", "batted_balls", 100.0)
        f[f"{side}_p_whiff_pct"] = _ratio(sc, "whiffs", "swings", 100.0)

        f[f"{side}_p_missing"] = _family_missing(f, f"{side}_p_")
        return f

    def _team(self, team, side: str, as_of) -> Dict[str, float]:
        f: Dict[str, float] = {}
        if not team:
            f[f"{side}_t_missing"] = 1.0
            return f
        season = self.tg.window(team, as_of, days=365)
        f[f"{side}_t_season_avg"] = _ratio(season, "hits", "at_bats")
        f[f"{side}_t_season_obp"] = _ratio(season, "times_on_base", "plate_appearances")
        f[f"{side}_t_season_slg"] = _ratio(season, "total_bases", "at_bats")
        f[f"{side}_t_season_woba"] = _ratio(season, "woba_num", "woba_den")
        f[f"{side}_t_season_rpg"] = _per_row(season, "runs")

        fi = self.tfi.window(team, as_of, days=365)
        f[f"{side}_t_fi_rpg"] = _per_row(fi, "first_inning_runs")
        f[f"{side}_t_fi_scoring_pct"] = _per_row(fi, "fi_scored")

        for days in TEAM_DAY_WINDOWS:
            w = self.tg.window(team, as_of, days=days)
            f[f"{side}_t_{days}d_rpg"] = _per_row(w, "runs")
            f[f"{side}_t_{days}d_woba"] = _ratio(w, "woba_num", "woba_den")
        f[f"{side}_t_missing"] = _family_missing(f, f"{side}_t_")
        return f

    def _park(self, venue_id) -> Dict[str, float]:
        row = self.parks.get(venue_id) if venue_id is not None else None
        f = {
            "park_runs_factor": NAN if row is None else float(row.get("runs_factor", NAN)),
            "park_hr_factor": NAN if row is None else float(row.get("hr_factor", NAN)),
            "park_hits_factor": NAN if row is None else float(row.get("hits_factor", NAN)),
        }
        f["park_missing"] = _family_missing(f, "park_")
        return f

    @staticmethod
    def _weather(game: Dict) -> Dict[str, float]:
        w = game.get("weather") or {}
        is_dome = bool(game.get("is_dome", False))

        def num(v):
            try:
                return float(v) if v is not None else NAN
            except (TypeError, ValueError):
                return NAN

        f = {
            "temp_f": num(w.get("temperature")),
            "wind_speed": num(w.get("wind_speed")),
            "humidity": num(w.get("humidity")),
            "is_dome": 1.0 if is_dome else 0.0,
        }
        wd, cf = w.get("wind_dir_deg"), game.get("cf_azimuth_deg")
        if wd is not None and cf is not None and not np.isnan(f["wind_speed"]):
            f["wind_out_component"] = f["wind_speed"] * float(
                np.cos(np.radians(float(wd) - float(cf))))
        else:
            f["wind_out_component"] = NAN
        if is_dome:
            f["weather_missing"] = 0.0
        else:
            f["weather_missing"] = (
                1.0 if any(np.isnan(v) for v in (f["temp_f"], f["wind_speed"]))
                else 0.0)
        return f

    def _lineups(self, lineups, as_of) -> Dict[str, float]:
        f: Dict[str, float] = {}
        for side in ("away", "home"):
            batters = (lineups or {}).get(side) or []
            wobas, obps = [], []
            for b in batters[:3]:
                w = self.bat.window(b, as_of, days=30)
                if w is not None:
                    wobas.append(_ratio(w, "woba_num", "woba_den"))
                    obps.append(_ratio(w, "times_on_base", "plate_appearances"))
            if len(wobas) == 3 and not any(np.isnan(v) for v in wobas):
                f[f"{side}_lineup_top3_woba"] = float(np.mean(wobas))
                f[f"{side}_lineup_top3_obp"] = float(np.mean(obps))
                f[f"{side}_lineup_missing"] = 0.0
            else:
                f[f"{side}_lineup_top3_woba"] = NAN
                f[f"{side}_lineup_top3_obp"] = NAN
                f[f"{side}_lineup_missing"] = 1.0
        return f

    # ------------------------------------------------------------ persist

    def persist(self, games: List[Dict], feature_version: str = FEATURE_VERSION) -> int:
        """Backfill/append FEATURES.GAME_FEATURES (f stored as JSON text)."""
        rows = []
        now = datetime.now(timezone.utc).isoformat()
        for g in games:
            f = self.build_game(g)
            miss = sum(1 for k, v in f.items()
                       if not k.endswith("_missing")
                       and isinstance(v, float) and np.isnan(v))
            rows.append({
                "game_id": str(g["game_id"]),
                "feature_version": feature_version,
                "computed_at": now,
                "as_of": pd.to_datetime(g["game_date"]).isoformat(),
                "f": json.dumps({k: (None if isinstance(v, float) and np.isnan(v) else v)
                                 for k, v in f.items()}),
                "missing_ct": miss,
                "coverage": coverage(f),
            })
        if self.sf is not None and rows:
            self.sf.merge_upsert("NRFI_DB.FEATURES.GAME_FEATURES", rows,
                                 key_cols=["game_id", "feature_version"])
        return len(rows)
