"""Leakage-safe set-based feature construction used by training and serving.

Every source table is loaded once. Per-game windows use only rows strictly before
``game_date``. Missing observations remain missing; they are never converted into
zero-valued outcomes or included in rate denominators.
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
PITCHER_GS_WINDOW = 30
WEATHER_KEYS = frozenset({"temp_f", "wind_speed", "humidity", "wind_out_component"})


def _missing(value: object) -> bool:
    return value is None or bool(pd.isna(value))


def coverage(features: Dict[str, float]) -> float:
    """Return the observed share of applicable non-flag features."""
    dome = features.get("is_dome") == 1.0
    values = [
        value
        for name, value in features.items()
        if not name.endswith("_missing") and not (dome and name in WEATHER_KEYS)
    ]
    if not values:
        return 0.0
    return sum(not _missing(value) for value in values) / len(values)


class _Cum:
    """Per-key date-sorted cumulative sums and non-null observation counts."""

    def __init__(
        self,
        frame: pd.DataFrame,
        key: str,
        date_col: str,
        sum_cols: Sequence[str],
    ) -> None:
        self.sum_cols = list(sum_cols)
        self.data: dict = {}
        if frame is None or frame.empty:
            return

        clean = frame.dropna(subset=[key, date_col]).sort_values([key, date_col])
        for group_key, group in clean.groupby(key, sort=False):
            dates = group[date_col].to_numpy(dtype="datetime64[ns]")
            sums: dict[str, np.ndarray] = {}
            counts: dict[str, np.ndarray] = {}
            for column in self.sum_cols:
                numeric = pd.to_numeric(group[column], errors="coerce")
                sums[column] = np.concatenate(
                    [[0.0], np.cumsum(numeric.fillna(0.0).to_numpy(dtype=float))]
                )
                counts[column] = np.concatenate(
                    [[0.0], np.cumsum(numeric.notna().to_numpy(dtype=float))]
                )
            self.data[group_key] = (dates, sums, counts)

    def window(
        self,
        key: object,
        as_of: np.datetime64,
        days: Optional[int] = None,
        last_n: Optional[int] = None,
    ) -> Optional[Dict[str, float]]:
        """Aggregate rows strictly before ``as_of`` inside the requested window."""
        entry = self.data.get(key)
        if entry is None:
            return None
        dates, sums, counts = entry
        high = int(np.searchsorted(dates, as_of, side="left"))
        if high == 0:
            return None
        if days is not None:
            low_date = as_of - np.timedelta64(days, "D")
            low = int(np.searchsorted(dates, low_date, side="left"))
        elif last_n is not None:
            low = max(0, high - last_n)
        else:
            low = 0
        if high <= low:
            return None

        result = {
            column: float(sums[column][high] - sums[column][low])
            for column in self.sum_cols
        }
        result["_rows"] = float(high - low)
        for column in self.sum_cols:
            result[f"_n_{column}"] = float(counts[column][high] - counts[column][low])
        return result


def _ratio(
    window: Optional[dict],
    numerator: str,
    denominator: str,
    scale: float = 1.0,
) -> float:
    if window is None:
        return NAN
    denominator_value = window.get(denominator, 0.0)
    if not denominator_value:
        return NAN
    return float(scale * window[numerator] / denominator_value)


def _per_observation(window: Optional[dict], column: str) -> float:
    """Mean over observed values only; null rows never enter the denominator."""
    if window is None:
        return NAN
    observed = float(window.get(f"_n_{column}", 0.0))
    if observed <= 0:
        return NAN
    return float(window[column] / observed)


def _count(window: Optional[dict], column: Optional[str] = None) -> float:
    if window is None:
        return NAN
    if column is None:
        return float(window.get("_rows", NAN))
    return float(window.get(f"_n_{column}", NAN))


def _family_missing(features: Dict[str, float], prefix: str) -> float:
    values = [
        value
        for name, value in features.items()
        if name.startswith(prefix) and not name.endswith("_missing")
    ]
    return 1.0 if not values or all(_missing(value) for value in values) else 0.0


class FeatureBuilder:
    """Bulk-load source frames once, then build chronological game features."""

    def __init__(
        self,
        sf: Optional[SnowflakeLoader] = None,
        raw_frames: Optional[Dict[str, pd.DataFrame]] = None,
    ) -> None:
        self.sf = sf
        self._frames = raw_frames
        self._prepared = False

    def _bulk(self, query: str, params: list) -> pd.DataFrame:
        if self.sf is None:
            raise RuntimeError(
                "Snowflake loader is required when raw_frames are absent"
            )
        return pd.DataFrame(self.sf.execute_query(query, params))

    def prepare(self, max_date: str) -> None:
        """Load each source once; per-game leakage is blocked inside ``window``."""
        if self._frames is None:
            params = [max_date]
            self._frames = {
                "pitcher_games": self._bulk(
                    "SELECT pitcher_id, game_date, earned_runs, runs_allowed, hits, walks, "
                    "strikeouts, innings_pitched, opponent_team "
                    "FROM NRFI_DB.RAW.PITCHER_GAME_LOGS WHERE game_date < %s",
                    params,
                ),
                "pitcher_fi": self._bulk(
                    "SELECT pitcher_id, game_date, first_inning_runs, first_inning_hits, "
                    "first_inning_walks FROM NRFI_DB.RAW.PITCHER_INNING_LOGS "
                    "WHERE inning = 1 AND game_date < %s",
                    params,
                ),
                "statcast_pitcher": self._bulk(
                    "SELECT pitcher_id, game_date, exit_velocity_sum, barrels, hard_hits, "
                    "whiffs, swings, batted_balls "
                    "FROM NRFI_DB.RAW.STATCAST_PITCHER_DAILY WHERE game_date < %s",
                    params,
                ),
                "team_games": self._bulk(
                    "SELECT team, game_date, runs, hits, at_bats, total_bases, "
                    "times_on_base, plate_appearances, woba_num, woba_den "
                    "FROM NRFI_DB.RAW.TEAM_GAME_LOGS WHERE game_date < %s",
                    params,
                ),
                "team_fi": self._bulk(
                    "SELECT team, game_date, first_inning_runs "
                    "FROM NRFI_DB.RAW.TEAM_INNING_LOGS "
                    "WHERE inning = 1 AND game_date < %s",
                    params,
                ),
                "batters": self._bulk(
                    "SELECT batter_id, game_date, woba_num, woba_den, times_on_base, "
                    "plate_appearances FROM NRFI_DB.RAW.BATTER_GAME_LOGS "
                    "WHERE game_date < %s",
                    params,
                ),
                "parks": self._bulk(
                    "SELECT venue_id, runs_factor, hr_factor, hits_factor "
                    "FROM NRFI_DB.RAW.PARK_FACTORS",
                    [],
                ),
            }

        frames = self._frames
        for name in (
            "pitcher_games",
            "pitcher_fi",
            "statcast_pitcher",
            "team_games",
            "team_fi",
            "batters",
        ):
            frame = frames.get(name)
            if frame is not None and not frame.empty:
                frame["game_date"] = pd.to_datetime(frame["game_date"], errors="raise")

        self.pg = _Cum(
            frames.get("pitcher_games"),
            "pitcher_id",
            "game_date",
            [
                "earned_runs",
                "runs_allowed",
                "hits",
                "walks",
                "strikeouts",
                "innings_pitched",
            ],
        )
        self.pfi = _Cum(
            frames.get("pitcher_fi"),
            "pitcher_id",
            "game_date",
            ["first_inning_runs", "first_inning_hits", "first_inning_walks"],
        )

        pitcher_fi = frames.get("pitcher_fi")
        if pitcher_fi is not None and not pitcher_fi.empty:
            pitcher_fi = pitcher_fi.copy()
            runs = pd.to_numeric(pitcher_fi["first_inning_runs"], errors="coerce")
            pitcher_fi["fi_zero"] = np.where(
                runs.isna(), np.nan, (runs == 0).astype(float)
            )
            self.pfi_nrfi = _Cum(pitcher_fi, "pitcher_id", "game_date", ["fi_zero"])
        else:
            self.pfi_nrfi = _Cum(pd.DataFrame(), "pitcher_id", "game_date", ["fi_zero"])

        self.scp = _Cum(
            frames.get("statcast_pitcher"),
            "pitcher_id",
            "game_date",
            [
                "exit_velocity_sum",
                "barrels",
                "hard_hits",
                "whiffs",
                "swings",
                "batted_balls",
            ],
        )
        self.tg = _Cum(
            frames.get("team_games"),
            "team",
            "game_date",
            [
                "runs",
                "hits",
                "at_bats",
                "total_bases",
                "times_on_base",
                "plate_appearances",
                "woba_num",
                "woba_den",
            ],
        )

        team_fi = frames.get("team_fi")
        if team_fi is not None and not team_fi.empty:
            team_fi = team_fi.copy()
            runs = pd.to_numeric(team_fi["first_inning_runs"], errors="coerce")
            team_fi["fi_scored"] = np.where(
                runs.isna(), np.nan, (runs > 0).astype(float)
            )
            self.tfi = _Cum(
                team_fi, "team", "game_date", ["first_inning_runs", "fi_scored"]
            )
        else:
            self.tfi = _Cum(
                pd.DataFrame(), "team", "game_date", ["first_inning_runs", "fi_scored"]
            )

        self.bat = _Cum(
            frames.get("batters"),
            "batter_id",
            "game_date",
            ["woba_num", "woba_den", "times_on_base", "plate_appearances"],
        )
        parks = frames.get("parks")
        self.parks = (
            {}
            if parks is None or parks.empty
            else parks.set_index("venue_id").to_dict("index")
        )
        self._prepared = True

    def build_game(self, game: Dict) -> Dict[str, float]:
        if not self._prepared:
            raise RuntimeError("call prepare(max_date) first")
        as_of = np.datetime64(pd.to_datetime(game["game_date"], errors="raise"))
        features: Dict[str, float] = {}
        for side, pitcher_key, team_key in (
            ("away", "away_pitcher_id", "away_team"),
            ("home", "home_pitcher_id", "home_team"),
        ):
            features.update(self._pitcher(game.get(pitcher_key), side, as_of))
            features.update(self._team(game.get(team_key), side, as_of))
        features.update(self._park(game.get("venue_id")))
        features.update(self._weather(game))
        features.update(self._lineups(game.get("lineups"), as_of))
        game_date = pd.to_datetime(game["game_date"], errors="raise")
        features["season"] = float(game_date.year)
        features["season_week"] = float(int(game_date.strftime("%V")))
        features["is_doubleheader"] = 1.0 if game.get("is_doubleheader") else 0.0
        return features

    def build_games(self, games: List[Dict]) -> Dict[str, Dict[str, float]]:
        return {str(game["game_id"]): self.build_game(game) for game in games}

    def _pitcher(
        self, pitcher_id: object, side: str, as_of: np.datetime64
    ) -> Dict[str, float]:
        features: Dict[str, float] = {}
        if _missing(pitcher_id):
            features[f"{side}_p_missing"] = 1.0
            return features

        career = self.pg.window(pitcher_id, as_of)
        features[f"{side}_p_career_era"] = _ratio(
            career, "earned_runs", "innings_pitched", 9.0
        )
        features[f"{side}_p_career_whip"] = (
            NAN
            if career is None
            else _ratio(
                {
                    "hw": career["hits"] + career["walks"],
                    "ip": career["innings_pitched"],
                },
                "hw",
                "ip",
            )
        )
        features[f"{side}_p_career_k9"] = _ratio(
            career, "strikeouts", "innings_pitched", 9.0
        )
        features[f"{side}_p_career_bb9"] = _ratio(
            career, "walks", "innings_pitched", 9.0
        )
        features[f"{side}_p_career_ip"] = (
            NAN if career is None else float(career["innings_pitched"])
        )

        recent_starts = self.pg.window(pitcher_id, as_of, last_n=PITCHER_GS_WINDOW)
        features[f"{side}_p_30gs_era"] = _ratio(
            recent_starts, "earned_runs", "innings_pitched", 9.0
        )
        features[f"{side}_p_30gs_k9"] = _ratio(
            recent_starts, "strikeouts", "innings_pitched", 9.0
        )

        first_inning = self.pfi.window(pitcher_id, as_of)
        features[f"{side}_p_fi_ra9"] = (
            _per_observation(first_inning, "first_inning_runs") * 9.0
        )
        features[f"{side}_p_fi_whip"] = (
            NAN
            if first_inning is None
            or first_inning.get("_n_first_inning_hits", 0.0) <= 0
            or first_inning.get("_n_first_inning_walks", 0.0) <= 0
            else float(
                (first_inning["first_inning_hits"] + first_inning["first_inning_walks"])
                / min(
                    first_inning["_n_first_inning_hits"],
                    first_inning["_n_first_inning_walks"],
                )
            )
        )
        features[f"{side}_p_fi_runs_rate"] = _per_observation(
            first_inning, "first_inning_runs"
        )
        first_inning_nrfi = self.pfi_nrfi.window(pitcher_id, as_of)
        features[f"{side}_p_fi_nrfi_rate"] = _per_observation(
            first_inning_nrfi, "fi_zero"
        )
        features[f"{side}_p_fi_games"] = _count(first_inning, "first_inning_runs")

        for days in PITCHER_DAY_WINDOWS:
            window = self.pg.window(pitcher_id, as_of, days=days)
            features[f"{side}_p_{days}d_era"] = _ratio(
                window, "earned_runs", "innings_pitched", 9.0
            )
            features[f"{side}_p_{days}d_whip"] = (
                NAN
                if window is None
                else _ratio(
                    {
                        "hw": window["hits"] + window["walks"],
                        "ip": window["innings_pitched"],
                    },
                    "hw",
                    "ip",
                )
            )
            features[f"{side}_p_{days}d_starts"] = _count(window)

        entry = self.pg.data.get(pitcher_id)
        if entry is None:
            features[f"{side}_p_rest_days"] = NAN
        else:
            dates = entry[0]
            high = int(np.searchsorted(dates, as_of, side="left"))
            features[f"{side}_p_rest_days"] = (
                float((as_of - dates[high - 1]) / np.timedelta64(1, "D"))
                if high > 0
                else NAN
            )

        statcast = self.scp.window(pitcher_id, as_of, days=30)
        features[f"{side}_p_avg_exit_velo"] = _ratio(
            statcast, "exit_velocity_sum", "batted_balls"
        )
        features[f"{side}_p_barrel_pct"] = _ratio(
            statcast, "barrels", "batted_balls", 100.0
        )
        features[f"{side}_p_hard_hit_pct"] = _ratio(
            statcast, "hard_hits", "batted_balls", 100.0
        )
        features[f"{side}_p_whiff_pct"] = _ratio(statcast, "whiffs", "swings", 100.0)
        features[f"{side}_p_missing"] = _family_missing(features, f"{side}_p_")
        return features

    def _team(self, team: object, side: str, as_of: np.datetime64) -> Dict[str, float]:
        features: Dict[str, float] = {}
        if _missing(team) or not str(team):
            features[f"{side}_t_missing"] = 1.0
            return features

        season = self.tg.window(team, as_of, days=365)
        features[f"{side}_t_season_avg"] = _ratio(season, "hits", "at_bats")
        features[f"{side}_t_season_obp"] = _ratio(
            season, "times_on_base", "plate_appearances"
        )
        features[f"{side}_t_season_slg"] = _ratio(season, "total_bases", "at_bats")
        features[f"{side}_t_season_woba"] = _ratio(season, "woba_num", "woba_den")
        features[f"{side}_t_season_rpg"] = _per_observation(season, "runs")

        first_inning = self.tfi.window(team, as_of, days=365)
        features[f"{side}_t_fi_rpg"] = _per_observation(
            first_inning, "first_inning_runs"
        )
        features[f"{side}_t_fi_scoring_pct"] = _per_observation(
            first_inning, "fi_scored"
        )

        for days in TEAM_DAY_WINDOWS:
            window = self.tg.window(team, as_of, days=days)
            features[f"{side}_t_{days}d_rpg"] = _per_observation(window, "runs")
            features[f"{side}_t_{days}d_woba"] = _ratio(window, "woba_num", "woba_den")
        features[f"{side}_t_missing"] = _family_missing(features, f"{side}_t_")
        return features

    def _park(self, venue_id: object) -> Dict[str, float]:
        row = None if _missing(venue_id) else self.parks.get(venue_id)
        features = {
            "park_runs_factor": NAN
            if row is None
            else float(row.get("runs_factor", NAN)),
            "park_hr_factor": NAN if row is None else float(row.get("hr_factor", NAN)),
            "park_hits_factor": NAN
            if row is None
            else float(row.get("hits_factor", NAN)),
        }
        features["park_missing"] = _family_missing(features, "park_")
        return features

    @staticmethod
    def _weather(game: Dict) -> Dict[str, float]:
        weather = game.get("weather") or {}
        dome = bool(game.get("is_dome", False))

        def number(value: object) -> float:
            try:
                return float(value) if value is not None else NAN
            except (TypeError, ValueError):
                return NAN

        features = {
            "temp_f": number(weather.get("temperature")),
            "wind_speed": number(weather.get("wind_speed")),
            "humidity": number(weather.get("humidity")),
            "is_dome": 1.0 if dome else 0.0,
        }
        wind_direction = weather.get("wind_dir_deg")
        center_field = game.get("cf_azimuth_deg")
        if (
            wind_direction is not None
            and center_field is not None
            and not _missing(features["wind_speed"])
        ):
            features["wind_out_component"] = features["wind_speed"] * float(
                np.cos(np.radians(float(wind_direction) - float(center_field)))
            )
        else:
            features["wind_out_component"] = NAN
        features["weather_missing"] = (
            0.0
            if dome
            else 1.0
            if _missing(features["temp_f"]) or _missing(features["wind_speed"])
            else 0.0
        )
        return features

    def _lineups(self, lineups: object, as_of: np.datetime64) -> Dict[str, float]:
        features: Dict[str, float] = {}
        lineup_map = lineups if isinstance(lineups, dict) else {}
        for side in ("away", "home"):
            batters = lineup_map.get(side) or []
            wobas: list[float] = []
            obps: list[float] = []
            for batter_id in batters[:3]:
                window = self.bat.window(batter_id, as_of, days=30)
                if window is not None:
                    wobas.append(_ratio(window, "woba_num", "woba_den"))
                    obps.append(_ratio(window, "times_on_base", "plate_appearances"))
            valid = (
                len(wobas) == 3
                and len(obps) == 3
                and not any(_missing(value) for value in wobas + obps)
            )
            features[f"{side}_lineup_top3_woba"] = (
                float(np.mean(wobas)) if valid else NAN
            )
            features[f"{side}_lineup_top3_obp"] = float(np.mean(obps)) if valid else NAN
            features[f"{side}_lineup_missing"] = 0.0 if valid else 1.0
        return features

    def persist(
        self,
        games: List[Dict],
        feature_version: str = FEATURE_VERSION,
    ) -> int:
        """Upsert versioned JSON feature rows into Snowflake."""
        rows = []
        computed_at = datetime.now(timezone.utc).isoformat()
        for game in games:
            features = self.build_game(game)
            serializable = {
                name: None if _missing(value) else float(value)
                for name, value in features.items()
            }
            rows.append(
                {
                    "game_id": str(game["game_id"]),
                    "feature_version": feature_version,
                    "computed_at": computed_at,
                    "as_of": pd.to_datetime(
                        game["game_date"], errors="raise"
                    ).isoformat(),
                    "f": json.dumps(serializable),
                    "missing_ct": sum(value is None for value in serializable.values()),
                    "coverage": coverage(features),
                }
            )
        if self.sf is not None and rows:
            self.sf.merge_upsert(
                "NRFI_DB.FEATURES.GAME_FEATURES",
                rows,
                key_cols=["game_id", "feature_version"],
            )
        return len(rows)
