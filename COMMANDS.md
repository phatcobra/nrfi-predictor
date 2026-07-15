# NRFI Autopilot Command Reference

Commands in this file are local engineering checks. They do not acquire MLB data,
train a model, evaluate the locked holdout, promote an artifact, deploy a service,
or change an external account.

## Reproduce the environment

Install `uv` 0.11.28, then run one platform-specific bootstrap command:

```powershell
.\scripts\bootstrap.ps1
```

```bash
./scripts/bootstrap.sh
```

Both scripts require the recorded `uv` version and execute `uv sync --frozen`.
They stop if the tool version or lock state differs.

## Validate the repository

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

These gates are offline with respect to MLB, sportsbook, warehouse, model, and
holdout data. Dependency installation may use the configured package index; it
must not create a subscription or transmit repository data.

## Run the local API

Only after creating a private `.env` from `.env.example`:

```bash
uv run --frozen uvicorn nrfi.api:app --host 127.0.0.1 --port 8000
```

An empty `API_BEARER_TOKEN` disables protected POST routes. Missing warehouse or
model prerequisites must remain visible as unavailable or blocked states.

## State-changing operator commands

Data loading, training, the one-time holdout evaluation, promotion, and deployment
are intentionally excluded. They remain separately gated by
[`SETUP_CHECKLIST.md`](SETUP_CHECKLIST.md). Do not run them as environment checks.
