"""Central configuration for the NRFI pipeline.

Everything tunable lives here so workflows and CLI share one source of truth.
Environment variables override defaults so GitHub Actions can switch between
quick verification runs and full historical retrains without code changes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

STATSAPI_BASE = "https://statsapi.mlb.com/api/v1"
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"

# Regular-season games only. Spring training / postseason have different
# run environments and starter usage patterns.
GAME_TYPE = "R"
SPORT_ID = 1

# Earliest season with reliable linescore + probable pitcher hydration.
DEFAULT_START_SEASON = 2011


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def _root() -> Path:
    """Repo root by default; NRFI_REPO_ROOT redirects all artifacts (tests)."""
    override = os.environ.get("NRFI_REPO_ROOT", "").strip()
    return Path(override) if override else REPO_ROOT


@dataclass(frozen=True)
class Paths:
    root: Path = field(default_factory=_root)
    data_dir: Path = field(default_factory=lambda: _root() / "data" / "processed")
    models_dir: Path = field(default_factory=lambda: _root() / "models")
    reports_dir: Path = field(default_factory=lambda: _root() / "reports")
    predictions_dir: Path = field(default_factory=lambda: _root() / "predictions")

    def ensure(self) -> Paths:
        for p in (self.data_dir, self.models_dir, self.reports_dir, self.predictions_dir):
            p.mkdir(parents=True, exist_ok=True)
        return self


@dataclass(frozen=True)
class FeatureConfig:
    """Knobs for the leakage-safe feature builder.

    shrinkage_strength_* are the pseudo-count priors (m) in the
    empirical-Bayes shrinkage estimate  (n * rate + m * league) / (n + m).
    """

    pitcher_window_starts: int = 10
    pitcher_min_starts_for_recent: int = 3
    team_window_games: int = 30
    league_window_days: int = 365
    shrinkage_strength_pitcher: float = 25.0
    shrinkage_strength_team: float = 40.0
    shrinkage_strength_park: float = 120.0
    max_days_rest: float = 30.0


@dataclass(frozen=True)
class TrainConfig:
    start_season: int = field(default_factory=lambda: _int_env("NRFI_START_SEASON", DEFAULT_START_SEASON))
    end_season: int = field(default_factory=lambda: _int_env("NRFI_END_SEASON", 0))  # 0 => latest available
    backtest_first_season: int = field(default_factory=lambda: _int_env("NRFI_BACKTEST_FIRST_SEASON", 0))
    random_state: int = 20260712
    # HistGradientBoosting hyperparameters chosen for a low-signal binary
    # target: shallow trees, strong regularisation, early stopping.
    learning_rate: float = 0.04
    max_leaf_nodes: int = 15
    min_samples_leaf: int = 200
    l2_regularization: float = 5.0
    max_iter: int = 600
    early_stopping_fraction: float = 0.15


REQUEST_TIMEOUT = 60
REQUEST_RETRIES = 4
REQUEST_BACKOFF_SECONDS = 2.0

MISSING_PROBABLE_NOTE = "NO PREDICTION — probable pitcher not announced"
