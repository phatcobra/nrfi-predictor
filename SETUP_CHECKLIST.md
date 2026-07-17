# NRFI Model Activation Checklist

A deployment is not a functioning model until every gate below passes in order. Do not skip a gate and do not substitute the model from PR #1; its committed walk-forward results underperformed climatology.

## Operator-only authorization gate

**Stop:** this checklist changes warehouse, data, model, registry, or deployment
state. It is not a developer bootstrap, CI procedure, or Phase 1 environment
check. Before continuing, an authorized operator must verify and record that:

- the exact operation, target, rollback boundary, and audit destination were
  approved;
- the target repository is clean and reviewed, while every dirty external
  repository (including `mlb-model`) remains read-only and quarantined;
- credentials belong to dedicated least-privilege identities, never Snowflake
  `ACCOUNTADMIN`, `SECURITYADMIN`, or `SYSADMIN`;
- every external account already exists, has approved cost controls, and requires
  no new subscription;
- all inputs are approved, provenance-bearing observed data, and private paths or
  records will not enter commits, logs, issues, pull requests, or artifacts;
- the locked 2025 holdout has not been opened or burned, and its one-time use is
  separately authorized; and
- missing GitHub protection, billing, or account-setting verification is recorded
  as an operational risk rather than treated as permission to bypass a gate.

If any statement is false or unverified, stop before the state-changing action.

## 1. Prepare the environment

```powershell
.\scripts\bootstrap.ps1
Copy-Item .env.example .env
```

```bash
./scripts/bootstrap.sh
cp .env.example .env
```

Both bootstrap scripts require `uv` 0.11.28 and run `uv sync --frozen`.
Populate `.env` with approved least-privilege Snowflake credentials, the exact
OpticOdds MLB first-inning total 0.5 market ID, an existing approved OpticOdds
key, and serving security values. Never commit `.env` or expose its values.

## 2. Initialize Snowflake

```bash
uv run --frozen python scripts/init_snowflake.py
```

This applies `sql/000_raw.sql` through `sql/003_ml.sql` in order.

## 3. Backfill authoritative first-inning outcomes

```bash
uv run --frozen python -m nrfi.ingest_first_inning_outcomes \
  --from 2015-04-01 \
  --to 2025-11-30
```

The label ingester uses finalized linescores and finalized actual starters. Ambiguous starters remain null.

## 4. Load normalized observed feature sources

The training feature builder requires all seven normalized source datasets:

| Loader dataset | Snowflake table |
|---|---|
| `pitcher_games` | `NRFI_DB.RAW.PITCHER_GAME_LOGS` |
| `pitcher_innings` | `NRFI_DB.RAW.PITCHER_INNING_LOGS` |
| `statcast_pitcher_daily` | `NRFI_DB.RAW.STATCAST_PITCHER_DAILY` |
| `team_games` | `NRFI_DB.RAW.TEAM_GAME_LOGS` |
| `team_innings` | `NRFI_DB.RAW.TEAM_INNING_LOGS` |
| `batter_games` | `NRFI_DB.RAW.BATTER_GAME_LOGS` |
| `park_factors` | `NRFI_DB.RAW.PARK_FACTORS` |

Load only observed CSV or Parquet files through the validator:

```bash
uv run --frozen python scripts/load_raw_dataset.py \
  --dataset pitcher_innings \
  --file "$APPROVED_INPUT_FILE" \
  --source "$APPROVED_SOURCE_ID"
```

Repeat for every dataset. The loader rejects missing or unknown columns, invalid numbers or dates, null keys, duplicate keys, and missing source provenance.

Do not point the loader at a dirty quarantined repository or an unclassified
workstation file. Use only an approved private path, and keep that path and its
records out of command transcripts, commits, issues, pull requests, and CI
artifacts.

The included DuckDB exporter produces only the two datasets it can derive without inventing unavailable statistics:

```bash
uv run --frozen python scripts/export_duckdb_fi_aggregates.py \
  --db "$PRIVATE_DUCKDB_PATH" \
  --out "$PRIVATE_EXPORT_DIR"
```

Do not treat those two exports as the complete training warehouse.

## 5. Pass warehouse readiness

```bash
uv run --frozen python -m nrfi.data_readiness
```

Required result:

```text
"ready": true
```

Any missing table, column, row coverage, date coverage, or pre-holdout park-factor violation blocks training.

## 6. Train the candidate

```bash
uv run --frozen python -m nrfi.train
```

The candidate uses observed data from April 1, 2015 through November 30, 2024. It must pass purged walk-forward out-of-fold gates before a loadable bundle is written. Failed candidates are registered as `rejected` and cannot be served.

Record the generated version from `models/nrfi_meta_<VERSION>.json`.

## 7. Evaluate the locked 2025 holdout once

```bash
uv run --frozen python scripts/evaluate_holdout.py --version <VERSION>
```

The evaluator verifies that training ended before the holdout, compares the model against the frozen pre-holdout climatology baseline, records log loss and Brier score, and marks the candidate rejected unless both minimum improvements pass.

Do not rerun the holdout. `--acknowledge-burn` records the evidence as burned and prevents production promotion.

## 8. Review and promote

Commit the exact candidate bundle, metadata, and evidence report on a reviewed branch. After review:

```bash
uv run --frozen python scripts/promote_model.py \
  --version <VERSION> \
  --confirm PROMOTE
```

Promotion requires all of the following in the registry:

- `status = candidate`
- `gates_passed = true`
- `holdout_passed = true`
- `holdout_burned_rerun = false`
- matching local bundle and metadata

The previous production model is retired atomically. Daily scoring loads only the registry-approved production version.

## 9. Validate serving

```bash
uv run --frozen uvicorn nrfi.api:app --host 127.0.0.1 --port 8000
```

Check:

```text
GET /v3/health
GET /v3/predictions
GET /v3/metrics/summary
```

A healthy database without an approved production model is intentionally reported as red.

## 10. Deploy scheduled paper-mode cycles

Apply `render.yaml` only to an existing, explicitly approved environment after
cost, access, protection, rollback, and secret controls have been verified, the
production artifact is present in the deployed repository, and registry
promotion is complete. Do not create a service or subscription from this
checklist. The blueprint runs:

- finalized outcome ingestion;
- nightly grading;
- warehouse readiness checks;
- daily scoring;
- fresh OpticOdds snapshots;
- monthly audit.

The blueprint does not run the incompatible legacy SportsDataIO staging ingester and does not perform automatic weekly retraining.
