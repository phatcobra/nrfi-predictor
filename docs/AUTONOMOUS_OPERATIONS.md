# Autonomous Operations

The system runs itself through three GitHub Actions workflows. No human
step is required between "code merged" and "daily predictions appear".

## The loop

```
           ┌────────────────────────────────────────────────┐
           │  ci.yml — every code push / PR                 │
           │  ruff + pytest (fixtures only, no live APIs)   │
           └────────────────────────────────────────────────┘

           ┌────────────────────────────────────────────────┐
           │  train.yml — Mondays 06:00 UTC on main,        │
           │  on demand, and on pipeline changes to         │
           │  claude/** branches (quick verification mode)  │
           │                                                │
           │  ingest 2011→present (StatsAPI + weather)      │
           │  → walk-forward backtest → fit + calibrate     │
           │  → commit data/, models/, reports/             │
           └────────────────────────────────────────────────┘

           ┌────────────────────────────────────────────────┐
           │  predict.yml — daily 11:00 UTC (≈07:00 ET)     │
           │                                                │
           │  refresh current season → fetch today's slate  │
           │  + probables + forecast weather → predict      │
           │  → commit predictions/<date>.csv + latest.md   │
           └────────────────────────────────────────────────┘
```

## Proof gates

- CI must be green for a merge; tests include leakage guards, label edge
  cases, model round-trips, and a full synthetic end-to-end `train` run.
- Every retrain publishes its walk-forward backtest to
  `reports/backtest.md` and the run summary — regressions are visible in
  the diff of a bot commit, not hidden in a log.
- `reports/data_coverage.md` shows per-season ingest coverage (games,
  probable-pitcher coverage, trainable rows, YRFI base rate) so silent
  data decay is caught by inspection.

## Failure behavior

- StatsAPI requests retry 5× with exponential backoff; a failed ingest
  fails the run loudly (no partial silent data).
- Weather is strictly fail-soft: any Open-Meteo failure produces missing
  values, which the model handles natively. A weather outage can never
  block training or predictions.
- Bot commits use `[skip ci]` and rebase-with-retry pushes, so scheduled
  jobs cannot trigger loops or race each other (`concurrency` groups
  serialize per-ref runs).
- `predict.yml` refuses to run without a committed trained model, and
  games without an announced probable pitcher are emitted with an
  explicit no-prediction note rather than a guessed probability.

## Operating it anyway (manual overrides)

Everything the robots do is one CLI:

```bash
pip install -r requirements-model.txt
python -m nrfi.cli ingest --start-season 2011 --weather   # full history
python -m nrfi.cli train                                  # backtest + fit + save
python -m nrfi.cli predict --date 2026-07-12 --weather    # any slate
```

`workflow_dispatch` on either workflow does the same from the Actions tab
(train accepts `start_season`; predict accepts `date`).
