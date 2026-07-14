# NRFI/YRFI Predictor

Fail-closed MLB first-inning probability system. It estimates `P(YRFI)` and `P(NRFI)`, compares the estimate with fresh de-vigged sportsbook consensus, and stores auditable paper-mode outputs. It does not create picks, staking instructions, or fabricated fallback values.

## Current state

The repository contains a tested model pipeline, warehouse schema, validation gates, API, and scheduled paper-mode jobs. A production model exists only after observed raw data is loaded and one candidate passes both the purged walk-forward gates and the locked 2025 holdout. The service refuses scoring when the registry has no approved production model.

Do not use the model artifact from PR #1. Its committed walk-forward report was worse than climatology in every reported season and failed the basic skill requirement.

## System flow

```text
Observed sources
  -> normalized Snowflake RAW tables
  -> strict warehouse readiness gate
  -> one leakage-safe FeatureBuilder for train and serve
  -> deterministic LightGBM + ElasticNet stack
  -> out-of-fold calibration
  -> candidate registry entry
  -> locked 2025 holdout
  -> explicit human promotion
  -> registry-approved production scoring
  -> immutable grading and audit
```

## Non-negotiable behavior

- Missing data remains missing; no league-average or random fallback statistics.
- Historical windows use only rows strictly before the game date.
- Training stops November 30, 2024; the 2025 season is locked release evidence.
- Failed candidates are registered as `rejected` and are not saved as loadable bundles.
- Serving loads only a registry row with `production`, OOF pass, holdout pass, and unburned holdout evidence.
- Unknown, malformed, future-dated, or stale odds hide market fields and degrade the game.
- Missing probable pitchers, feature errors, low feature coverage, or invalid probabilities block the game.
- The API exposes probabilities and diagnostic market differences only.

## Main components

| Component | Purpose |
|---|---|
| `sql/000_raw.sql` | Normalized observed feature-source tables |
| `sql/001_core.sql` | Authoritative outcomes and odds snapshots |
| `sql/002_features.sql` | Versioned feature store |
| `sql/003_ml.sql` | Model registry, predictions, and grades |
| `nrfi/data_readiness.py` | Table, column, row, date, and leakage readiness gate |
| `nrfi/raw_loader.py` | Strict CSV/Parquet validation and idempotent loading |
| `nrfi/build_features.py` | Set-based, chronology-safe feature construction |
| `nrfi/ensemble.py` | Deterministic purged walk-forward stacked model |
| `nrfi/venn_abers.py` | Out-of-fold probability calibration |
| `nrfi/train.py` | Candidate training, evidence gates, and persistence |
| `scripts/evaluate_holdout.py` | One-time locked holdout release gate |
| `nrfi/model_registry.py` | Approved production selection and guarded promotion |
| `nrfi/predict_daily.py` | Fail-closed daily scoring |
| `nrfi/ingest_opticodds.py` | Exact-market, per-book no-vig odds snapshots |
| `nrfi/grade_nightly.py` | Brier, log-loss, calibration, and market diagnostics |
| `nrfi/api.py` | FastAPI paper-mode service |

## Installation

```bash
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

On macOS/Linux, activate with `source .venv/bin/activate` and copy with `cp .env.example .env`.

## Activation

Follow [`SETUP_CHECKLIST.md`](SETUP_CHECKLIST.md) in order. The abbreviated sequence is:

```bash
python scripts/init_snowflake.py
python -m nrfi.ingest_first_inning_outcomes --from 2015-04-01 --to 2025-11-30
python scripts/load_raw_dataset.py --dataset <DATASET> --file <FILE> --source <SOURCE>
python -m nrfi.data_readiness
python -m nrfi.train
python scripts/evaluate_holdout.py --version <VERSION>
python scripts/promote_model.py --version <VERSION> --confirm PROMOTE
uvicorn nrfi.api:app --host 0.0.0.0 --port 8000
```

Loading only first-inning labels is insufficient. The readiness gate requires all normalized pitcher, team, batter, Statcast, and park-factor sources.

## API

Primary endpoints:

```text
GET  /v3/health
GET  /v3/predictions?date=YYYY-MM-DD
GET  /v3/metrics/summary
GET  /v3/metrics/calibration
POST /v3/jobs/predict
POST /v3/jobs/grade
POST /v3/jobs/ingest_odds
```

POST routes require `API_BEARER_TOKEN`; an empty token disables them.

## Validation

GitHub Actions performs a clean dependency install, byte-compiles the package and scripts, runs the complete offline test suite, uploads the full pytest log, and fails the branch when any gate fails.

Core test coverage includes:

- unresolved imports and legacy package references;
- fabricated-data and action-language redlines;
- ratio-of-sums feature math;
- strict chronology and same-day leakage isolation;
- missing-value and coverage behavior;
- deterministic ensemble training and persistence;
- game-day dependency failure simulation;
- normalized warehouse readiness;
- raw-loader schema and key validation;
- actual-starter attribution;
- registry-authoritative production selection.

Offline tests prove code behavior, not model skill. Model skill is established only by the recorded OOF and locked-holdout evidence generated from the populated observed warehouse.

## Repository governance

[`AGENTS.md`](AGENTS.md) is the canonical operating standard for human- and agent-authored changes. It preserves the repository's fail-closed and temporal-validation controls and requires every adopted tool, service, framework, dependency, or automation to document its role, integration point, measurable benefit, failure modes, owner, validation method, exit path, and effect on analytical sophistication.

The pull-request template turns those requirements into merge-review gates. A tool or dependency change without the required decision record is incomplete, and a change must not be merged when required validation, rollback behavior, or authoritative documentation is missing.

## Deployment

`render.yaml` defines the FastAPI service and only the supported normalized cycles: finalized outcome ingestion, grading, readiness, scoring, odds refresh, and monthly audit. Automatic weekly retraining is intentionally disabled until a new post-2025 out-of-time evaluation protocol is defined.