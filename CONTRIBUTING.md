# Contributing to NRFI/YRFI Predictor

Changes must be small, auditable, reversible, and supported by repository
evidence. Preserve fail-closed behavior and keep engineering validation separate
from state-changing data, model, and deployment operations.

## Development boundary

- Use Python 3.11, `uv` 0.11.28, `.python-version`, `pyproject.toml`, and the
  checked-in `uv.lock`. Run `uv sync --frozen`; do not update the lockfile as a
  side effect of validation.
- Do not add a dependency, service, account, or subscription without explicit
  approval. Never substitute an unreviewed data source or paid provider.
- Never commit secrets, populated environment files, private workstation paths,
  raw or derived local MLB data, databases, model bundles, evaluation outputs, or
  Terraform state.
- Treat dirty external repositories as read-only quarantines. Do not reset,
  clean, stash, commit, overwrite, or copy their unclassified contents.
- Sanitized fixtures belong under `tests/fixtures/`. They must be minimal,
  synthetic or demonstrably public, free of credentials and private paths, and
  reviewed before commit.

## Model and data controls

- Do not change labels, feature semantics, chronology boundaries, calibration,
  market qualification, risk rules, or promotion gates without an explicit,
  reviewed decision.
- Training may use only observed, provenance-bearing inputs. Missing values must
  remain missing; do not add fabricated, random, or league-average fallbacks.
- Preserve strict pre-game chronology and the November 30, 2024 training cutoff.
- The 2025 holdout is locked release evidence. Do not inspect, modify, copy, or
  rerun it during development or CI. A separately authorized operator process
  governs its one-time use.
- Tests must not connect to Snowflake, sportsbooks, MLB providers, a private
  DuckDB file, or any other external or local production dataset.

## Make and validate a change

Start with the smallest relevant test, then run the complete offline gate before
requesting review:

```bash
uv lock --check
uv sync --frozen
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen pyright
uv run --frozen python -m compileall -q nrfi scripts tests
uv run --frozen python -m pytest tests/ -q
uv run --frozen pre-commit run --all-files
```

Do not weaken a test, suppress an unexplained warning, add `continue-on-error`,
or skip an enforcement step to obtain a green result. CI must propagate every
nonzero validation exit code while preserving diagnostic artifact upload.

## Pull request evidence

Document the exact files and behavior changed, validation commands and results,
known gaps, rollback boundary, and any operational risk. Review the staged diff
for secrets, private paths, generated data or models, locked-holdout material,
and unrelated production changes. Operator actions remain governed by
[`SETUP_CHECKLIST.md`](SETUP_CHECKLIST.md); local engineering commands are in
[`COMMANDS.md`](COMMANDS.md).
