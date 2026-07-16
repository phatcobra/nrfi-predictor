# NRFI Autopilot Project State

Status date: 2026-07-15

Phase 0: **PASS WITH DOCUMENTED EXCEPTIONS**

Phase 1: **IN PROGRESS**

Phase 2: **IN PROGRESS**

Current task: **model evidence integrity and canonical probability-path repair**

Current branch: `fix/model-evidence-integrity-20260715`

The Phase 0 asset inventory, per-file manifest, reconciliation, data-gap analysis,
repository assessment, and risk register are complete. Their two deterministic
scans remain authoritative. Phase 1 has not repeated either scan, acquired data,
uploaded local assets, or inspected locked evaluation evidence.

## Documented exceptions and operational risks

| Item | Disposition |
|---|---|
| Phase 0 documentation branch is unpublished | Nonblocking publication backlog; publish separately when tooling permits |
| `${MLB_MODEL_REPO}` has 34 modified and 7 untracked paths | Read-only quarantine; do not reset, clean, stash, commit, overwrite, train from, or otherwise alter it |
| Browser and Computer bridges are unavailable | Operational limitation; signed-in account inspection remains unavailable |
| GitHub protection, billing, benefits, and zero-overage settings are unverified | Operational risk; no paid, cloud, subscription, or permission-changing action is authorized |
| GitHub CLI authentication is currently invalid | Use the authenticated GitHub connector only for the explicitly requested branch and draft pull request |
| Some quarantined files remain incompletely inspected | They remain unadmitted and cannot be used for training, evaluation, or production |

These exceptions do not weaken the fail-closed, locked-holdout,
no-new-subscription, cost, security, provenance, or data-reuse requirements.

## CI defect and repair boundary

GitHub Actions run `29274094844` is rejected as release evidence. The test command
exited `2` with eight `ModuleNotFoundError: No module named 'nrfi'` collection
errors, the enforcement step was skipped, and the workflow nevertheless reported
success. Diagnostic artifact `8288619635` was retained.

The repair is limited to:

- invoke the suite as `python -m pytest` so the repository package is importable;
- let the pytest pipeline's nonzero status fail the job directly;
- keep diagnostic upload under `if: always()`;
- remove the stale optional import of deliberately deleted
  `nrfi.retrain_weekly` from the local monthly audit;
- keep the invalid-numeric test compatible with pandas 3 without weakening the
  production validator.

No model, label, feature, holdout, production artifact, or local MLB dataset is in
scope.

## Validation evidence

| Evidence | Result |
|---|---|
| Baseline GitHub run `29274094844` | False green: pytest exit `2`; enforcement skipped; overall workflow succeeded; eight collection errors |
| Targeted static-integrity baseline | `1 failed, 1 passed in 0.38s`; missing `nrfi.retrain_weekly` |
| Complete local baseline in isolated Python 3.13 environment | `2 failed, 48 passed, 21 warnings in 22.48s`; stale import plus pandas 3 test-fixture incompatibility |
| Targeted post-repair regressions | `9 passed in 1.36s`; static integrity and raw-loader validation |
| Byte-compile and audit import smoke checks | Passed |
| Complete local suite after repair | Passed twice: `50 passed, 21 warnings in 5.88s`; after probe removal, `50 passed, 21 warnings in 5.76s` |
| Phase 1 Ruff preflight | Found and corrected a missing `os` import still required by `audit_monthly.main()`; Ruff `F821` passed and the suite remained `50 passed, 21 warnings in 14.98s` |
| Controlled-failure GitHub run `29437200500` | Failed correctly: `1 failed, 50 passed, 21 warnings in 2.56s`; `release-gate` failed with exit `1` |
| Controlled-failure diagnostic artifact | Upload succeeded; artifact `8351893545`, digest `sha256:e9a8cdeda983c9a635d5129c3c56a4c64cd77cc30fd45769a0a69389e75dd500` |
| Passing GitHub run `29437410732` | Succeeded: `50 passed, 21 warnings in 1.87s`; `release-gate` succeeded |
| Passing-run diagnostic artifact | Upload succeeded; artifact `8351977471`, digest `sha256:187f06eeb9b6ae01effbc712fcc1608fe4fd9e1766d9b2fca37659d551fcf851` |
| Final CI-repair GitHub run `29440101407` | Succeeded at head `85f81a3083711c228a7feffda922bbf7827ebdde`; the monthly-audit import regression is fixed |
| Final CI-repair diagnostic artifact | Upload succeeded; artifact `8353062469`, digest `sha256:09814a760becf820311fc3af51d71baab5aef96eb7c34cac83b7ff0452869ad4` |

## Phase 1 environment-foundation evidence

The foundation uses Python 3.11, `uv` 0.11.28, `pyproject.toml`, and the checked-in
lockfile. `pyproject.toml` is the development and CI authority;
`requirements.txt` remains the unchanged legacy deployment manifest until a
separately reviewed deployment migration. DuckDB is development-only and does
not expand the production dependency set.

Published foundation head `0aad0b0c9d1a172369c9d5065a687590299efbed` is on
draft pull request <https://github.com/phatcobra/nrfi-predictor/pull/6>, stacked
on the draft CI repair and intentionally unmerged.

| Evidence | Result |
|---|---|
| Lock validation | `uv lock --check` resolved the recorded 126-package graph |
| Frozen synchronization | `uv sync --frozen` checked 117 installed packages without changing the lock |
| Ruff lint | Passed for the complete repository |
| Ruff format | Passed; 34 Python files are in the recorded format |
| Formatter semantic check | 27 tracked formatter-only Python files retained byte-independent AST equality; AST-changing paths are limited to the documented audit cleanup and Snowflake hardening |
| Pyright | `0 errors, 0 warnings, 0 informations`; basic checking covers all unlisted files, with 12 dynamic legacy files recorded explicitly in `pyproject.toml` as adoption debt |
| Byte compilation | `python -m compileall -q nrfi scripts tests` passed |
| Snowflake fail-closed regression | `8 passed, 1 warning`; every account, identity, database, schema, warehouse, and role setting is required before engine creation |
| Complete offline suite | `58 passed, 21 warnings in 21.76s`; no external data, warehouse, sportsbook, holdout, training, or model operation ran |
| Pre-commit | Ruff lint, Ruff format, Pyright, and the complete offline pytest hook all passed |
| Configuration syntax | Five JSON files, two YAML files, and `pyproject.toml` parsed successfully |
| Privacy and secret review | Added-content scan found no private workstation paths, private keys, or provider-token patterns |
| Foundation GitHub run `29442936672` | Succeeded: 126-package lock verified, Ruff and format passed, Pyright reported zero diagnostics, import smoke passed, and `58 passed, 21 warnings in 4.45s` |
| Foundation diagnostic artifact | Upload succeeded; artifact `8354201900`, digest `sha256:6e71d7978df80146a128e3e255de2e473d9cf62c636517d1c7a8ab55ebb6dae4` |
| Action supply chain | Checkout, Python setup, uv setup, and artifact upload are pinned to the official tag targets' immutable commit SHAs |
| Final pinned-action run `29444056728` | Succeeded at head `7a15878dbef41001cd4e3bcd31ccd48c9517fe3b`: lock, lint, format, Pyright, import smoke, compile, and `58 passed, 21 warnings in 4.12s` |
| Final pinned-action diagnostic artifact | Upload succeeded; artifact `8354654348`, digest `sha256:501e0e07c39421510c9b11de401610e83a8ee012cadfae82468be1dbdf941e23` |

The 21 test warnings are 20 upstream scikit-learn deprecations and one Sentry SDK
deprecation. They are recorded maintenance debt, not suppressed release evidence.
The Dev Container definition is syntax-validated and uses a minimal
`.devcontainer`-only build context. A local build attempt produced no image before
the fixed ten-minute external-image-fetch timeout; no repository data entered the
context. The explicit Pyright legacy baseline and the uncompleted image build
remain reviewable hardening backlog items.

## Exact next action

The current modeling repair is local-only and remains pre-publication: no real
data, locked holdout, model artifact, or production system was accessed. The
canonical path is now meta -> temporal Venn-Abers -> one final clip; venue
shrinkage remains quarantined pending separate temporal evidence. Validation
passed with `72 passed, 21 warnings`, repository-wide Ruff lint and formatting,
byte compilation, Pyright (`0 errors, 0 warnings, 0 informations`), and
`git diff --check`. SQL registry columns, evidence-contract preflight,
fail-closed holdout burn recording, candidate-status enforcement, and
stale-calibrator clearing were corrected locally. The branch is uncommitted and
unpublished pending authenticated GitHub tooling.

Resume validation of the existing `docs/phase2-data-contracts-20260715`
worktree using only the preserved Phase 0 manifests. Do not rescan, acquire data,
inspect the locked holdout, train, promote, or deploy. Keep draft pull requests
`#5` and `#6`
unmerged.
