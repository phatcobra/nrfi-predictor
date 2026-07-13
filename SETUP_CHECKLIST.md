# NRFI Model Activation Checklist

A deployment is not a functioning model until every gate below passes in order. Do not skip a gate and do not substitute the model from PR #1; its committed walk-forward results underperformed climatology.

## 1. Prepare the environment

```bash
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# macOS/Linux
# source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Populate `.env` with valid Snowflake credentials, the exact OpticOdds MLB first-inning total 0.5 market ID, an OpticOdds key, and serving security values. Never commit `.env`.

## 2. Initialize Snowflake

```bash
python scripts/init_snowflake.py
```

This applies `sql/000_raw.sql` through `sql/003_ml.sql` in order.

## 3. Backfill authoritative first-inning outcomes

```bash
python -m nrfi.ingest_first_inning_outcomes \
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
python scripts/load_raw_dataset.py \
  --dataset pitcher_innings \
  --file exports/pitcher_innings.parquet \
  --source mlb-model-statcast
```

Repeat for every dataset. The loader rejects missing or unknown columns, invalid numbers or dates, null keys, duplicate keys, and missing source provenance.

The included DuckDB exporter produces only the two datasets it can derive without inventing unavailable statistics:

```bash
python scripts/export_duckdb_fi_aggregates.py \
  --db /absolute/path/to/mlb.duckdb \
  --out exports
```

Do not treat those two exports as the complete training warehouse.

## 5. Pass warehouse readiness

```bash
python -m nrfi.data_readiness
```

Required result:

```text
"ready": true
```

Any missing table, column, row coverage, date coverage, or pre-holdout park-factor violation blocks training.

## 6. Train the candidate

```bash
python -m nrfi.train
```

The candidate uses observed data from April 1, 2015 through November 30, 2024. It must pass purged walk-forward out-of-fold gates before a loadable bundle is written. Failed candidates are registered as `rejected` and cannot be served.

Record the generated version from `models/nrfi_meta_<VERSION>.json`.

## 7. Evaluate the locked 2025 holdout once

```bash
python scripts/evaluate_holdout.py --version <VERSION>
```

The evaluator verifies that training ended before the holdout, compares the model against the frozen pre-holdout climatology baseline, records log loss and Brier score, and marks the candidate rejected unless both minimum improvements pass.

Do not rerun the holdout. `--acknowledge-burn` records the evidence as burned and prevents production promotion.

## 8. Review and promote

Commit the exact candidate bundle, metadata, and evidence report on a reviewed branch. After review:

```bash
python scripts/promote_model.py \
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
uvicorn nrfi.api:app --host 0.0.0.0 --port 8000
```

Check:

```text
GET /v3/health
GET /v3/predictions
GET /v3/metrics/summary
```

A healthy database without an approved production model is intentionally reported as red.

## 10. Deploy scheduled paper-mode cycles

Apply `render.yaml` only after the production artifact is present in the deployed repository and the registry promotion is complete. The blueprint runs:

- finalized outcome ingestion;
- nightly grading;
- warehouse readiness checks;
- daily scoring;
- fresh OpticOdds snapshots;
- monthly audit.

The blueprint does not run the incompatible legacy SportsDataIO staging ingester and does not perform automatic weekly retraining.
