# NRFI Autopilot Project State

Status date: 2026-07-16

Phase 0: **PASS WITH DOCUMENTED EXCEPTIONS**

Phase 1: **PASS WITH DOCUMENTED EXCEPTIONS**

Phase 2: **PASS WITH DOCUMENTED EXCEPTIONS**

Current task: **real historical prediction API and browser display**

Current branch: `chore/phase1-environment-foundation-20260715`

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
| GitHub authentication and SSH connectivity | Restored for account `phatcobra`; remote mutation remains limited to the existing PR #6 branch and pull request |
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

## Model-evidence integrity

The canonical probability path is now meta -> temporal Venn-Abers -> one final
clip; venue shrinkage remains quarantined pending separate temporal evidence.
SQL registry columns, evidence-contract preflight, fail-closed holdout burn
recording, candidate-status enforcement, and stale-calibrator clearing were
corrected without reading real data, the locked holdout, a model artifact, or a
production system.

The isolated model-evidence branch passed `72 passed, 21 warnings`,
repository-wide Ruff lint and formatting, byte compilation, Pyright (`0 errors,
0 warnings, 0 informations`), and `git diff --check` before its atomic commit was
integrated locally.

## Phase 2 contract evidence

The Phase 2 package is documentation and machine-readable policy only; it
admits no real asset. It contains 12 asset records, 19 contracts, 25 required
asset attributes, 18 open gaps, 2 resolved evidence gaps, and 7 acquisition
proposals. All assets remain unadmitted, quarantined, or rejected, and every
acquisition proposal remains unauthorized with network, credential, payment,
and subscription actions prohibited.

The catalog was reconciled to the preserved Phase 0 scan summary and checksum
sidecar: scan ID, 6,670 files, 1,455,407,592 bytes, content and observation
trees, parameters, generator, manifest, and summary identities all match. No
asset scan, quarantined-database access, data acquisition, locked-holdout
inspection, training, promotion, or deployment occurred. Validation passed:
all seven JSON files parse; catalog/report IDs and provenance identities match;
required attribute, time-role, gap, disposition, and acquisition invariants
pass; public-path/secret checks pass; Ruff passes; Pyright reports `0 errors,
0 warnings, 0 informations`; and the complete offline suite reports `63 passed,
21 warnings`.

## Local integration consolidation evidence

The existing PR #6 integration branch now contains the locally committed
model-evidence integrity, Phase 2 data-contract, and immutable-lineage
foundation changes in that order. Their source commits were integrated as
`0d59ef6`, `52b86b6`, and `ab50a07`. CI-repair head `85f81a3` remains an
ancestor, proving that all PR #5 commits are retained.

The optional synthetic market-decision audit remains isolated as local commit
`577bbd9` and is not on the critical path. A read-only three-way merge preview
identified overlaps in `PROJECT_STATE.md` and `README.md`, so the audit was not
integrated under the no-conflict/no-delay condition. The later unvalidated
observed-lifecycle additions remain uncommitted and preserved in their source
worktree.

The consolidated branch passed Ruff lint; Ruff format (`41 files already
formatted`); Pyright (`0 errors, 0 warnings, 0 informations`); byte compilation;
parsing of 14 tracked JSON files, four YAML files, `pyproject.toml`, and both
public JSON schemas; and the complete offline suite (`100 passed, 1 skipped, 22
warnings`). The skip is the documented unavailable Windows directory-symlink
privilege. Warnings comprise 20 upstream scikit-learn deprecations, one Sentry
SDK deprecation, and one denied pytest-cache write; the cache warning did not
affect test collection or execution. No scan, acquisition, network request,
quarantined-repository mutation, real-data access, locked-holdout access,
training, promotion, deployment, push, or pull-request mutation occurred.

## Published integration evidence

Draft pull request <https://github.com/phatcobra/nrfi-predictor/pull/6> now targets
`main` at head `e628f5fd521e2e778c6245ee8b47e5f38f231cf6`. It contains every
PR #5 commit and changed path. PRs #1, #3, and #5 are closed with their remote
branches preserved. GitHub Actions run `29544833916` completed successfully and
the `release-gate` check reported `SUCCESS`.

## Bounded real-data slice authorization

The semantic boundary is resolved only for an internal, development-only MLB
StatsAPI slice covering 2024-04-01 through 2024-05-31. Unauthenticated official
StatsAPI GET requests and storage of normalized derived records, checksums,
source references, and timestamps are authorized. Raw-payload redistribution,
paid or credentialed providers, AWS, production deployment, sportsbook and
market data, wagering, weather, umpire, lineup, and injury inputs remain
prohibited. Quarantined pybaseball and MLB-model assets remain closed, and the
locked 2025 holdout remains inaccessible.

## Real-data vertical-slice evidence

Official MLB StatsAPI data for 2024-04-01 through 2024-05-31 was retrieved with
unauthenticated read-only GET requests. Raw responses remained in memory and
were not stored or redistributed. The normalized derived package in
`docs/vertical_slice/` contains 826 finalized regular-season games, 30 teams,
31 venues, 1,652 postgame actual-starter records, 826 finalized first-inning
outcomes, 827 request-provenance records, 826 feature rows, and 219 real
out-of-sample predictions. All 826 scheduled games were accepted; two-starter
and label coverage are 100%.

Strict-prior team and league features are eligible for 671 games (81.23%).
Pitcher pregame feature coverage is explicitly 0% and actual starters are not
backfilled. The chronological split uses MLB official date: 452 eligible games
before 2024-05-16 train the simple logistic baseline and 219 games from
2024-05-16 through 2024-05-31 form the renewable out-of-sample period.

Out-of-sample log loss is `0.682488` versus `0.683897` for frozen training
climatology; Brier score is `0.244692` versus `0.245386`; expected calibration
error is `0.014686`. The differences are development evidence only and do not
qualify a production model, market edge, or wager.

Independent verification passed every artifact checksum and row count,
official-date split membership, probability-complement invariant, strict
StatsAPI endpoint restriction, provenance reference, locked-holdout exclusion,
and private-path scan. Repository validation passed Ruff lint and formatting
(`43 files`), byte compilation, Pyright (`0 errors, 0 warnings, 0
informations`), and the complete offline suite (`105 passed, 1 skipped, 22
warnings`). The existing Windows symlink skip and dependency/cache warnings are
unchanged.

## Exact next action

Expose one committed real historical prediction through a read-only API route
that does not require Snowflake, and display the same response in a minimal
browser page. Keep market, wagering, deployment, and additional data domains
out of scope.
