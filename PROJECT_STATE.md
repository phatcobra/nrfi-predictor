# NRFI Autopilot Project State

Status date: 2026-07-16

Phase 0: **PASS WITH DOCUMENTED EXCEPTIONS**

Phase 1: **PASS WITH DOCUMENTED EXCEPTIONS**

Phase 2: **PASS WITH DOCUMENTED EXCEPTIONS**

Current task: **multi-season official data acquisition and chronological validation**

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
| GitHub-hosted action Node.js 20 runtimes | Nonblocking deprecation warning on the successful release gate; update pinned actions separately before GitHub ends forced Node.js 24 compatibility |
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

Draft pull request <https://github.com/phatcobra/nrfi-predictor/pull/6> targets
`main`. Its validated real-data engineering head is
`295aae96454c198c3e0abaf44019c1eb1ec3ab18`; the ordered slice commits are
`ede5afd` (authorization), `a95230d` (real MLB slice), and `295aae9` (real
prediction API and page). It contains every PR #5 commit and changed path. PRs
#1, #3, and #5 are closed with their remote branches preserved. GitHub Actions
run `29548242775` completed successfully on that head, and every `release-gate`
step executed, including the complete offline suite and diagnostic artifact
upload.

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

## Real-prediction API and browser evidence

The read-only `/v3/vertical-slice/prediction` route now exposes one committed
real out-of-sample prediction without Snowflake or any external request. The
corresponding `/vertical-slice` page fetches and displays that same response
without external browser assets. The checked response is gamePk `745907`, New
York Yankees at Minnesota Twins on 2024-05-16 at Target Field, with Clarke
Schmidt and Joe Ryan recorded separately as postgame actual starters. The
baseline returned NRFI `0.532451` and YRFI `0.467549`; the finalized observed
result was YRFI. The response is explicitly historical development evidence,
not a production or wagering signal.

Focused API and page-contract validation reports `4 passed`; the live local
HTTP checks returned status 200 for both the API and page. The in-app browser
bridge was unavailable, so interactive visual inspection remains a
nonblocking operational gap rather than substituted evidence. The complete
locked suite passed with an explicit worktree-local pytest temp root: `109
passed, 1 skipped, 21 warnings`. The default Windows temp-root attempt first
reported 100 passes and 10 setup errors caused solely by denied access to
pytest's temp directory. Ruff lint passed, Ruff formatting reports `44 files
already formatted`, byte compilation passed, and Pyright reports `0 errors, 0
warnings, 0 informations`. Parsing passed for 21 JSON files, nine JSONL files
containing 5,237 records, four YAML files, and `pyproject.toml`; all 11 vertical
slice artifact hashes and row counts were independently verified. The 22 files
changed from the published PR head contain no private workstation path or
recognized secret pattern, and `git diff --check` passes.

## Multi-season probability-engine foundation

The authorized development boundary now covers the complete 2021 through 2024
regular seasons using only unauthenticated read-only official MLB StatsAPI GET
requests and normalized derived outputs. The locked 2025 holdout, quarantined
assets, probable-starter backfill, pitcher features without historical
availability, lineups, Statcast, weather, umpires, injuries, markets, wagering,
paid services, cloud resources, and production deployment remain closed.

A verified deterministic-replay defect existed in the bounded generator:
retrieval and normalization timestamps participated in byte manifests, and
historical prediction rows contained postgame outcomes. The multi-season engine
now separates execution metadata from stable analytical identities and writes
prediction-time records independently from immutable postgame grade records.
It records source, normalized partition, feature, fold, model, calibrator,
prediction, grade, evaluation, configuration, dependency-lock, and code
identities. Two derivations from the same frozen normalized records must produce
identical analytical manifests and predictions; grade execution time is excluded
from analytical identity.

The engine defines expanding 2021-to-2024 season folds, strict-prior
team/league features, a fixed regularized logistic candidate, frozen overall,
prior-season, and rolling-200 league climatology baselines, calibration slope
and intercept, reliability bins, Brier skill, official-date clustered bootstrap
intervals, probability uncertainty, and season/month/team/venue/probability
subgroups. It issues only one conservative predictive-skill conclusion. Market
and decision work remains prohibited until this evidence exists and qualifies.

One non-persisted probe of already-known gamePk `745907` verified that the
official feed fields projection retains the source timestamp, nine innings, and
both 26-player boxscore maps while reducing the response to 20,133 bytes. No raw
payload was written. The optimized strict-prior feature computation replays the
committed 826-game feature table byte-for-byte at SHA-256
`80c1f00c7410537903985d9509267ec24e8150b8f68bb8f91dcc4fd85a3ac40e`.

The first 2021 acquisition attempt then failed closed on a real StatsAPI
reconciliation defect before training: gamePk `634595` appeared twice in the
April schedule with conflicting doubleheader and game-number attributes. A
targeted official feed check identifies it authoritatively as doubleheader game
2. Normalization now prefers the feed's game metadata, fetches each gamePk once,
deduplicates schedule rows only when their normalized records are identical,
records the source schedule-row count, and rejects any remaining conflict. The
zero-game March checkpoint and conflicting April checkpoint remain preserved
under normalization v1; corrected acquisition uses a separate v2 cache path.

Focused contract, slice, reconciliation, replay, ledger-separation, holdout,
baseline, and uncertainty validation reports `19 passed`. The complete offline
suite reports `118 passed, 1 skipped, 21 warnings`; the skip and dependency
warnings are the existing documented environment baseline. Ruff lint passed, Ruff formatting
reports `46 files already formatted`, byte compilation passed, and Pyright
reports `0 errors, 0 warnings, 0 informations`. The first full-suite attempt
correctly rejected the bootstrap's `np.random` spelling under the repository's
anti-fabrication gate; the deterministic sampler was replaced without weakening
that gate, and the final suite passed.

## Exact next action

Acquire and checkpoint normalized official StatsAPI records for each calendar
month of the complete 2021 through 2024 regular seasons, then generate the
expanding-window chronological prediction and grade ledgers from the committed
engine identity. Keep 2025, optional data domains, markets, wagering, cloud, and
production deployment out of scope.
