"""NRFI/YRFI first-inning prediction system.

Self-contained pipeline: MLB StatsAPI ingestion -> leakage-safe feature
engineering -> calibrated gradient-boosted model -> walk-forward backtest ->
daily slate predictions. Designed to run autonomously in GitHub Actions.
"""

__version__ = "1.0.0"
