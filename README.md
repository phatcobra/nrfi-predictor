# nrfi-predictor

Autonomous MLB **first-inning over/under 0.5 runs** (NRFI/YRFI) prediction
system. It ingests every regular-season game since 2011 from the public
MLB StatsAPI, builds leakage-safe pre-game features, trains a calibrated
gradient-boosted model, validates it with season-by-season walk-forward
backtests, and publishes daily slate probabilities — all continuously and
unattended via GitHub Actions.

## What it produces

- `predictions/<date>.csv` + `predictions/latest.md` — calibrated
  `P(YRFI)` / `P(NRFI)` for every game on the slate with announced
  probable pitchers, refreshed every morning before first pitch.
- `predictions/<date>.json` + `predictions/index.json` — the same
  predictions plus a manifest (model metadata + walk-forward backtest
  summary + calibration) that the dashboard renders. See
  `predictions_dashboard.html` and [docs/AUTONOMOUS_OPERATIONS.md](docs/AUTONOMOUS_OPERATIONS.md#dashboard).
- `reports/backtest.md` — walk-forward log-loss/Brier/AUC vs. a
  climatology baseline plus a calibration table, refreshed on every
  retrain.
- `reports/data_coverage.md` — per-season data health.
- `models/nrfi_model.joblib` — the current calibrated model, with full
  training metadata alongside.

## How it works

| Layer | Where | Summary |
|---|---|---|
| Ingestion | `src/nrfi/data/` | Bulk StatsAPI schedule + linescore + probable pitchers; venue metadata; optional Open-Meteo weather. Committed as per-season CSVs. |
| Labels | `src/nrfi/labels.py` | Strict YRFI/NRFI rules; truncated linescores can never fake an NRFI. |
| Features | `src/nrfi/features.py` | Single chronological pass, pre-game information only; empirical-Bayes-shrunk pitcher/offense/park/regime rates; one code path for training and serving. |
| Model | `src/nrfi/model.py` | HistGradientBoosting + isotonic calibration on a held-out chronological tail. |
| Validation | `src/nrfi/backtest.py` | Walk-forward by season; skill measured against climatology. |
| Serving | `src/nrfi/predict.py` | Daily slate with forecast weather; explicit no-prediction for unannounced probables. |
| Autonomy | `.github/workflows/` | CI on push, weekly full retrain, daily predictions — all self-committing. |

Full details: [docs/METHODOLOGY.md](docs/METHODOLOGY.md) and
[docs/AUTONOMOUS_OPERATIONS.md](docs/AUTONOMOUS_OPERATIONS.md).

## Run it yourself

```bash
pip install -r requirements-model.txt
python -m nrfi.cli ingest --start-season 2011 --weather
python -m nrfi.cli train
python -m nrfi.cli predict
```

Tests and lint (no network, fixtures only):

```bash
python -m pytest tests/ -q
python -m ruff check src/nrfi tests
```

## Scope and honesty

This repository outputs **probabilities, not picks**. First-inning
scoring is a ~51–53% base-rate event; genuine skill here is a small,
consistently positive Brier skill score and clean calibration — anything
that looks dramatically better is leaking future information. Price-aware
market evaluation belongs to a separate research layer.

## Legacy prototype

`src/*.py` (flat modules: SportsDataIO/OpticOdds/Snowflake/Flask
scaffolding) and `app.py`, `terraform/`, `scripts/` predate the
autonomous pipeline, require paid API keys, and are not exercised by CI.
The `src/nrfi/` package is self-contained and does not depend on them.
