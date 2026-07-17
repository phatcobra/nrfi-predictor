# NRFI/YRFI Predictor

Fail-closed MLB first-inning probability system. It estimates `P(YRFI)` and `P(NRFI)`, compares the estimate with fresh de-vigged sportsbook consensus, and stores auditable paper-mode outputs. It does not create picks, staking instructions, or fabricated fallback values.

## Current state

The repository contains a tested model pipeline, warehouse schema, validation gates, API, and scheduled paper-mode jobs. A production model exists only after observed raw data is loaded and one candidate passes both the purged walk-forward gates and the locked 2025 holdout. The service refuses scoring when the registry has no approved production model.

The sole deployable probability path is the temporally cross-fitted ensemble
score, followed by Venn-Abers calibration and one final bounds clip. Venue
shrinkage remains a quarantined research utility and is not applied in serving;
it requires separately predeclared temporal evidence before reconsideration.

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

## Security and evidence boundary

- Offline development does not require production credentials, private MLB data,
  external account access, or a new subscription.
- Never commit populated environment files, private workstation paths, raw or
  derived local datasets, database files, model bundles, or Terraform state.
- Treat any dirty external repository, including a local `mlb-model` checkout, as
  read-only and quarantined. Do not reset, clean, stash, commit, or copy from it
  until its changes have been classified safely.
- The 2025 holdout is locked release evidence. Development and CI must not open,
  modify, copy, or rerun it.
- Missing protection, billing, or account-setting verification is an operational
  risk, not permission to weaken local gates or access private data.

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
| `nrfi/lineage.py` | Immutable lineage envelopes, deterministic input manifests, and local append-only fallback |
| `nrfi/lifecycle.py` | Fail-closed lifecycle envelope factories; metadata construction only |
| `schemas/` | Versioned public lineage-envelope and input-manifest schemas |
| `nrfi/api.py` | FastAPI paper-mode service |

## Offline developer setup

Use Python 3.11 and `uv` 0.11.28. The checked-in Python version, project metadata,
and lockfile define the reproducible environment. No `.env`, data acquisition,
warehouse connection, training, or model artifact is required for these checks.

Run the platform-specific bootstrap from the repository root:

```powershell
.\scripts\bootstrap.ps1
```

```bash
./scripts/bootstrap.sh
```

The scripts require exactly `uv` 0.11.28 and execute `uv sync --frozen`. Then run
the offline repository gates:

```bash
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen pyright
uv run --frozen python -m compileall -q nrfi scripts tests
uv run --frozen python -m pytest tests/ -q
```

See [`COMMANDS.md`](COMMANDS.md) for the full local command reference and
[`CONTRIBUTING.md`](CONTRIBUTING.md) for change and evidence requirements.

## Multi-season development engine

The authorized development engine uses unauthenticated read-only official MLB
StatsAPI requests for the complete 2021 through 2024 regular seasons. It writes
only normalized derived records, maintains a resumable ignored local cache,
keeps prediction-time records separate from postgame grades, and rejects any
request that includes the locked 2025 season.

After committing the engine code, build and deterministically replay the package
with that producing commit identity:

```powershell
$commit = git rev-parse HEAD
.\.venv\Scripts\python.exe -m nrfi.multiseason --seasons 2021,2022,2023,2024 --code-commit $commit --workers 8
```

The command emits expanding-window chronological predictions, frozen baseline
comparisons, calibration and subgroup evidence, clustered bootstrap intervals,
separate immutable grades, stable analytical identities, and a byte manifest in
`docs/multiseason/`. It does not use market data, wagering logic, optional data
domains, quarantined assets, or the locked holdout.

The fixed logistic/LightGBM and prior-fold sigmoid comparison can be replayed
without network access from that committed evidence:

```powershell
.\.venv\Scripts\python.exe -m nrfi.model_comparison --evidence docs\multiseason --output docs\model_comparison --code-commit a3e86f52e62bd8fcfbd47c579822ab5303a29082 --uncertainty-replicates 32 --bootstrap-replicates 2000
```

The comparison retains model artifacts, uncertainty, separate prediction and
grade ledgers, and exact replay identities. Its conclusion is
`PREDICTIVE SKILL NOT ESTABLISHED`; it does not authorize market or wager work.

## Operator activation

Warehouse initialization, source loading, training, locked-holdout evaluation,
promotion, and deployment are state-changing operator actions. They are not
developer bootstrap steps. Use the fail-closed
[`SETUP_CHECKLIST.md`](SETUP_CHECKLIST.md) only with explicit authorization and
approved existing accounts. Loading only first-inning labels is insufficient;
readiness requires all normalized pitcher, team, batter, Statcast, and
park-factor sources.

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

GitHub Actions installs the locked environment, checks formatting, lint, and
types, byte-compiles the package and scripts, runs the complete offline test
suite, uploads the full pytest log, and fails the branch when any gate fails.

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

## Deployment

`render.yaml` defines the FastAPI service and only the supported normalized cycles: finalized outcome ingestion, grading, readiness, scoring, odds refresh, and monthly audit. Automatic weekly retraining is intentionally disabled until a new post-2025 out-of-time evaluation protocol is defined.
