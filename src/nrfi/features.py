"""Leakage-safe feature engineering for first-inning prediction.

Design principles:

1. **Pre-game information set only.** Features for every game on date D are
   computed from games strictly before D (a day-grouped pass), exactly the
   information available when the daily prediction job runs in the morning.
   Starters are attributed via probable pitchers, matching what is knowable
   pre-game.

2. **One code path for training and serving.** ``FeatureBuilder`` replays
   history to build the training matrix and the same object then produces
   features for a live slate, eliminating training/serving skew.

3. **Empirical-Bayes shrinkage.** Every rate is shrunk toward the running
   league rate with pseudo-count strength m:

       shrunk = (sum + m * league_rate) / (n + m)

   so a pitcher with 2 career starts is pulled almost entirely to league
   average while a 200-start veteran keeps his own rate.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from nrfi.config import FeatureConfig
from nrfi.labels import attach_labels

# Cold-start priors used only before any league history accumulates.
PRIOR_HALF_INNING_YRFI = 0.29  # P(>=1 run in a half inning 1)
PRIOR_HALF_INNING_RUNS = 0.54  # mean runs per team in inning 1
PRIOR_FULL_INNING_YRFI = 0.51  # P(>=1 run in full inning 1)
PRIOR_FULL_INNING_RUNS = 1.08
LEAGUE_PRIOR_STRENGTH = 500.0

FEATURE_COLUMNS = [
    "hp_fi_runs_allowed_shrunk",
    "hp_fi_yrfi_allowed_shrunk",
    "hp_recent_fi_runs_allowed",
    "hp_starts_tracked",
    "hp_days_rest",
    "ap_fi_runs_allowed_shrunk",
    "ap_fi_yrfi_allowed_shrunk",
    "ap_recent_fi_runs_allowed",
    "ap_starts_tracked",
    "ap_days_rest",
    "hto_fi_runs_shrunk",
    "hto_fi_yrfi_shrunk",
    "hto_recent_fi_runs",
    "ato_fi_runs_shrunk",
    "ato_fi_yrfi_shrunk",
    "ato_recent_fi_runs",
    "venue_fi_runs_shrunk",
    "league_yrfi_rate",
    "league_fi_runs_rate",
    "is_night_game",
    "month",
    "season",
]

WEATHER_FEATURES = ["temperature_c", "wind_speed_kmh", "is_indoor_park"]

META_COLUMNS = [
    "game_pk",
    "game_date",
    "season",
    "home_team_name",
    "away_team_name",
    "home_probable_pitcher_id",
    "away_probable_pitcher_id",
]


@dataclass
class _RollingRate:
    n: float = 0.0
    total: float = 0.0

    def add(self, value: float) -> None:
        self.n += 1
        self.total += value

    def shrunk(self, prior: float, strength: float) -> float:
        return (self.total + strength * prior) / (self.n + strength)


@dataclass
class _PitcherState:
    runs: _RollingRate = field(default_factory=_RollingRate)
    yrfi: _RollingRate = field(default_factory=_RollingRate)
    recent_runs: deque = field(default_factory=deque)
    last_start: pd.Timestamp | None = None


@dataclass
class _TeamState:
    runs: _RollingRate = field(default_factory=_RollingRate)
    yrfi: _RollingRate = field(default_factory=_RollingRate)
    recent_runs: deque = field(default_factory=deque)


class FeatureBuilder:
    """Chronological state machine producing pre-game features."""

    def __init__(self, config: FeatureConfig | None = None):
        self.cfg = config or FeatureConfig()
        self.pitchers: dict[int, _PitcherState] = defaultdict(_PitcherState)
        self.teams: dict[int, _TeamState] = defaultdict(_TeamState)
        self.venues: dict[int, _RollingRate] = defaultdict(_RollingRate)
        self.league_half_yrfi = _RollingRate()
        self.league_half_runs = _RollingRate()
        self.league_full_yrfi_window: deque = deque()  # (date, yrfi)
        self.league_full_runs_window: deque = deque()  # (date, runs)

    # ------------------------------------------------------------------
    # League regime helpers
    # ------------------------------------------------------------------
    def _league_half_yrfi_rate(self) -> float:
        return self.league_half_yrfi.shrunk(PRIOR_HALF_INNING_YRFI, LEAGUE_PRIOR_STRENGTH)

    def _league_half_runs_rate(self) -> float:
        return self.league_half_runs.shrunk(PRIOR_HALF_INNING_RUNS, LEAGUE_PRIOR_STRENGTH)

    def _trim_league_windows(self, as_of: pd.Timestamp) -> None:
        cutoff = as_of - pd.Timedelta(days=self.cfg.league_window_days)
        for window in (self.league_full_yrfi_window, self.league_full_runs_window):
            while window and window[0][0] < cutoff:
                window.popleft()

    def _league_regime(self, as_of: pd.Timestamp) -> tuple[float, float]:
        self._trim_league_windows(as_of)
        if len(self.league_full_yrfi_window) >= 200:
            yrfi = float(np.mean([v for _, v in self.league_full_yrfi_window]))
            runs = float(np.mean([v for _, v in self.league_full_runs_window]))
            return yrfi, runs
        return PRIOR_FULL_INNING_YRFI, PRIOR_FULL_INNING_RUNS

    # ------------------------------------------------------------------
    # Feature extraction (must be called BEFORE update for the same game)
    # ------------------------------------------------------------------
    def features_for(self, game: dict[str, Any]) -> dict[str, Any]:
        cfg = self.cfg
        date = pd.Timestamp(str(game["game_date"]))
        league_yrfi, league_runs = self._league_regime(date)
        half_yrfi_prior = self._league_half_yrfi_rate()
        half_runs_prior = self._league_half_runs_rate()

        def pitcher_block(pid: object) -> dict[str, float]:
            if pid is None or (isinstance(pid, float) and np.isnan(pid)):
                return {
                    "fi_runs_allowed_shrunk": np.nan,
                    "fi_yrfi_allowed_shrunk": np.nan,
                    "recent_fi_runs_allowed": np.nan,
                    "starts_tracked": np.nan,
                    "days_rest": np.nan,
                }
            state = self.pitchers[int(pid)]
            recent = (
                float(np.mean(state.recent_runs))
                if len(state.recent_runs) >= cfg.pitcher_min_starts_for_recent
                else np.nan
            )
            rest = np.nan
            if state.last_start is not None:
                rest = min(float((date - state.last_start).days), cfg.max_days_rest)
            return {
                "fi_runs_allowed_shrunk": state.runs.shrunk(half_runs_prior, cfg.shrinkage_strength_pitcher),
                "fi_yrfi_allowed_shrunk": state.yrfi.shrunk(half_yrfi_prior, cfg.shrinkage_strength_pitcher),
                "recent_fi_runs_allowed": recent,
                "starts_tracked": float(state.runs.n),
                "days_rest": rest,
            }

        def team_block(tid: object) -> dict[str, float]:
            if tid is None or (isinstance(tid, float) and np.isnan(tid)):
                return {"fi_runs_shrunk": np.nan, "fi_yrfi_shrunk": np.nan, "recent_fi_runs": np.nan}
            state = self.teams[int(tid)]
            recent = _RollingRate(n=len(state.recent_runs), total=float(sum(state.recent_runs)))
            return {
                "fi_runs_shrunk": state.runs.shrunk(half_runs_prior, cfg.shrinkage_strength_team),
                "fi_yrfi_shrunk": state.yrfi.shrunk(half_yrfi_prior, cfg.shrinkage_strength_team),
                "recent_fi_runs": recent.shrunk(half_runs_prior, cfg.shrinkage_strength_team / 2),
            }

        hp = pitcher_block(game.get("home_probable_pitcher_id"))
        ap = pitcher_block(game.get("away_probable_pitcher_id"))
        hto = team_block(game.get("home_team_id"))
        ato = team_block(game.get("away_team_id"))

        venue_id = game.get("venue_id")
        if venue_id is None or (isinstance(venue_id, float) and np.isnan(venue_id)):
            venue_rate = np.nan
        else:
            venue_rate = self.venues[int(venue_id)].shrunk(
                2 * half_runs_prior, self.cfg.shrinkage_strength_park
            )

        day_night = str(game.get("day_night") or "").lower()

        return {
            "hp_fi_runs_allowed_shrunk": hp["fi_runs_allowed_shrunk"],
            "hp_fi_yrfi_allowed_shrunk": hp["fi_yrfi_allowed_shrunk"],
            "hp_recent_fi_runs_allowed": hp["recent_fi_runs_allowed"],
            "hp_starts_tracked": hp["starts_tracked"],
            "hp_days_rest": hp["days_rest"],
            "ap_fi_runs_allowed_shrunk": ap["fi_runs_allowed_shrunk"],
            "ap_fi_yrfi_allowed_shrunk": ap["fi_yrfi_allowed_shrunk"],
            "ap_recent_fi_runs_allowed": ap["recent_fi_runs_allowed"],
            "ap_starts_tracked": ap["starts_tracked"],
            "ap_days_rest": ap["days_rest"],
            "hto_fi_runs_shrunk": hto["fi_runs_shrunk"],
            "hto_fi_yrfi_shrunk": hto["fi_yrfi_shrunk"],
            "hto_recent_fi_runs": hto["recent_fi_runs"],
            "ato_fi_runs_shrunk": ato["fi_runs_shrunk"],
            "ato_fi_yrfi_shrunk": ato["fi_yrfi_shrunk"],
            "ato_recent_fi_runs": ato["recent_fi_runs"],
            "venue_fi_runs_shrunk": venue_rate,
            "league_yrfi_rate": league_yrfi,
            "league_fi_runs_rate": league_runs,
            "is_night_game": 1.0 if day_night == "night" else 0.0,
            "month": float(date.month),
            "season": float(game.get("season") or date.year),
        }

    # ------------------------------------------------------------------
    # State update with a completed game's outcome
    # ------------------------------------------------------------------
    def update(self, game: dict[str, Any]) -> None:
        date = pd.Timestamp(str(game["game_date"]))
        fi_away = _num(game.get("first_inning_runs_away"))
        fi_home = _num(game.get("first_inning_runs_home"))

        # Home pitcher faces the away offense in the top of the 1st;
        # away pitcher faces the home offense in the bottom.
        self._update_pitcher(game.get("home_probable_pitcher_id"), fi_away, date)
        self._update_pitcher(game.get("away_probable_pitcher_id"), fi_home, date)
        self._update_team(game.get("away_team_id"), fi_away)
        self._update_team(game.get("home_team_id"), fi_home)

        if fi_away is not None:
            self.league_half_runs.add(fi_away)
            self.league_half_yrfi.add(1.0 if fi_away >= 1 else 0.0)
        if fi_home is not None:
            self.league_half_runs.add(fi_home)
            self.league_half_yrfi.add(1.0 if fi_home >= 1 else 0.0)

        if fi_away is not None and fi_home is not None:
            total = fi_away + fi_home
            venue_id = game.get("venue_id")
            if venue_id is not None and not (isinstance(venue_id, float) and np.isnan(venue_id)):
                self.venues[int(venue_id)].add(total)
            self.league_full_yrfi_window.append((date, 1.0 if total >= 1 else 0.0))
            self.league_full_runs_window.append((date, float(total)))

    def _update_pitcher(self, pid: object, runs_allowed: float | None, date: pd.Timestamp) -> None:
        if pid is None or (isinstance(pid, float) and np.isnan(pid)):
            return
        state = self.pitchers[int(pid)]
        # Rest tracking uses every attributed start, even without a linescore.
        state.last_start = date
        if runs_allowed is None:
            return
        state.runs.add(runs_allowed)
        state.yrfi.add(1.0 if runs_allowed >= 1 else 0.0)
        state.recent_runs.append(runs_allowed)
        while len(state.recent_runs) > self.cfg.pitcher_window_starts:
            state.recent_runs.popleft()

    def _update_team(self, tid: object, runs_scored: float | None) -> None:
        if tid is None or (isinstance(tid, float) and np.isnan(tid)) or runs_scored is None:
            return
        state = self.teams[int(tid)]
        state.runs.add(runs_scored)
        state.yrfi.add(1.0 if runs_scored >= 1 else 0.0)
        state.recent_runs.append(runs_scored)
        while len(state.recent_runs) > self.cfg.team_window_games:
            state.recent_runs.popleft()


def _num(value: object) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------
# Frame-level entry points
# ----------------------------------------------------------------------
def build_training_frame(
    games: pd.DataFrame,
    weather: pd.DataFrame | None = None,
    config: FeatureConfig | None = None,
) -> pd.DataFrame:
    """Day-grouped pass over history: features first, updates after.

    Every game on date D sees state from dates < D only — never from
    same-day games, which may be in progress when predictions are made.
    """
    labelled = attach_labels(games)
    builder = FeatureBuilder(config)
    records: list[dict[str, Any]] = []

    for _, day_games in labelled.groupby("game_date", sort=True):
        day_rows = day_games.to_dict("records")
        for row in day_rows:
            feats = builder.features_for(row)
            feats.update({col: row.get(col) for col in META_COLUMNS if col != "season"})
            feats["yrfi"] = row.get("yrfi")
            feats["label_valid"] = bool(row.get("label_valid"))
            records.append(feats)
        for row in day_rows:
            builder.update(row)

    frame = pd.DataFrame.from_records(records)
    return _attach_weather(frame, weather)


def build_slate_features(
    history: pd.DataFrame,
    slate: pd.DataFrame,
    weather: pd.DataFrame | None = None,
    config: FeatureConfig | None = None,
) -> pd.DataFrame:
    """Replay history, then produce features for an upcoming slate.

    History rows on or after the earliest slate date are excluded from the
    replay so a re-run later in the day cannot leak same-day results.
    """
    builder = FeatureBuilder(config)
    slate_dates = pd.to_datetime(slate["game_date"].astype(str))
    cutoff = slate_dates.min()
    hist = history.copy()
    hist_dates = pd.to_datetime(hist["game_date"].astype(str))
    hist = hist[hist_dates < cutoff]
    hist = hist.sort_values(["game_date", "game_datetime_utc", "game_pk"], kind="stable")
    for row in hist.to_dict("records"):
        builder.update(row)

    records = []
    for row in slate.to_dict("records"):
        feats = builder.features_for(row)
        feats.update({col: row.get(col) for col in META_COLUMNS if col != "season"})
        records.append(feats)
    frame = pd.DataFrame.from_records(records)
    return _attach_weather(frame, weather)


def _attach_weather(frame: pd.DataFrame, weather: pd.DataFrame | None) -> pd.DataFrame:
    if weather is not None and not weather.empty and not frame.empty:
        frame = frame.merge(
            weather[["game_pk"] + WEATHER_FEATURES].drop_duplicates("game_pk"),
            on="game_pk",
            how="left",
        )
    else:
        for col in WEATHER_FEATURES:
            frame[col] = np.nan
    return frame
