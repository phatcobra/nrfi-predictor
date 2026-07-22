# NRFI Autopilot Project State

Status date: 2026-07-18

Phase 0: **PASS WITH DOCUMENTED EXCEPTIONS**

Phase 1: **PASS WITH DOCUMENTED EXCEPTIONS**

Phase 2: **PASS WITH DOCUMENTED EXCEPTIONS**

AWS platform: **STAGE 3 — PREGAME COLLECTOR LIVE, 29 ELIGIBLE ROWS FOR 2026-07-19**

Current task: **add valid point-in-time predictive signal through the existing AWS pipeline**

Current branch: `feat/aws-probability-platform-20260717`

Current required output: **NO QUALIFIED WAGER**

## AWS probability-platform checkpoint

The frozen probability baseline is reproduced in AWS in approved region
`us-east-2`. The successful private Fargate job used image digest
`sha256:23dfb0df95bc2cc423bcce2476a1f3ab8f7a450fc82d8605accc2740d1e90f0a`
from source commit `bcc2c2aa32bb3a55aeb80d178619b6a4cfa0d753`. It ran with 2
vCPU, 4,096 MiB, no public IP, no internet or NAT route, one attempt, and a
two-hour timeout. The measured successful-job duration was 64.691 seconds, and
no Batch job remained active afterward.

The container read only the committed 2021-through-2024 package. It verified all
source and generated artifact hashes and row counts, then performed the existing
two-pass deterministic comparison with 32 uncertainty and 2,000 score-bootstrap
replicates. All 29,148 candidate predictions and 29,148 grades matched the frozen
package one-to-one after deterministic platform identity remapping. Model,
calibrator, prediction, grade, and fold links passed; probability complements
passed; the maximum record delta was `1.1712852909795402e-13`, below the declared
`1e-12` tolerance. The sole scientific conclusion remains
`PREDICTIVE SKILL NOT ESTABLISHED`. The 2025 holdout was not opened, copied,
uploaded, provisioned, or referenced.

Three fail-closed diagnostic attempts preceded success: revision 1 exposed a
missing container package path, revision 2 rejected exact cross-platform
evaluation equality, and revision 3 rejected platform-sensitive derived hashes.
Each defect was corrected in the offline replay wrapper only. Production model
code, dependencies locked in `uv.lock`, normalized data, features, folds,
probabilities, metrics, manifests, and frozen evidence were not modified.

The result SHA-256 is
`e4269bf2436d107a4792a475a7f616874050d408ececd10e85afc6f8b8c19cd5`.
The result and bounded run metadata are stored as versioned, KMS-encrypted
objects under `aws-baseline/2026-07-17/` and locked in governance mode until
2027-07-18. The public evidence summary is
`docs/aws/baseline_reproduction.json`.

The minimum AWS foundation contains three private, versioned, public-blocked,
KMS-encrypted buckets; immutable KMS-encrypted ECR; one private subnet; a free S3
gateway endpoint; exactly three single-AZ interface endpoints for ECR API, ECR
Docker, and CloudWatch Logs; a rotating KMS key; a bounded log group; and a
scale-to-zero Batch environment capped at 2 vCPU. It contains no NAT gateway,
public workload address, Lambda, API Gateway, Glue, SageMaker, scheduled job, or
holdout bucket. Terraform `1.12.2` with `hashicorp/aws v5.100.0` passes format,
validation, and zero-drift checks against the KMS-encrypted remote state.

The account-wide monthly budget is `$30`, with 50% forecast, 80% actual, and
100% actual notifications. The approximate endpoint floor is `$21.90` per
730-hour month and the rotating KMS key adds about `$1`, before storage, logs,
data processing, and the bounded Fargate runtime. AWS Budgets currently reports
`$0.00`; Cost Explorer reports data unavailable because new-account cost data
has not yet been ingested, so observed cost remains an operational lag rather
than a verified zero.

CloudTrail is logging and delivering without a recorded delivery or digest
error. Root MFA is enabled and root has no access keys. The temporary bootstrap
access key and user are deleted. Superseded managed-policy versions are deleted.
The deployment role now has exactly one trust statement: GitHub OIDC for
`repo:phatcobra/nrfi-predictor:ref:refs/heads/feat/aws-probability-platform-20260717`;
the temporary root bootstrap trust is removed.

The container release gate is cleared. `Dockerfile.aws` now uses immutable
Amazon Linux 2023 base digest
`sha256:f03a6d1b59561c1347a4c386ecb8e38588050cffa290f0ac4f5c7246d055a36e`
with Python `3.11.15-1.amzn2023.0.3` and `libgomp`
`14.2.1-7.amzn2023.0.2`. Immutable tag `runtime-7602b07358b2` resolves to ECR
digest `sha256:710237682af8ba399c2658e4d2846c050e2275a32360430498173f6e3764534e`.
Its scan is `COMPLETE` with zero critical, high, medium, low, informational, or
undefined findings. Existing private Batch job definition revision 5 uses that
digest; revision 4 remains active and available for rollback.

Draft PR #8 remains the sole AWS implementation pull request and must not be
merged, retargeted, or otherwise modified by this checkpoint. This checkpoint
is committed locally on the existing branch and is not pushed because advancing
the remote branch would modify that pull request. No historical data was
reacquired, no asset scan was repeated, and no private workstation path,
credential, raw local dataset, or locked evaluation evidence entered AWS or the
repository.

The Phase 0 asset inventory, per-file manifest, reconciliation, data-gap analysis,
repository assessment, and risk register are complete. Their two deterministic
scans remain authoritative. Phase 1 has not repeated either scan, acquired data,
uploaded local assets, or inspected locked evaluation evidence.

## Documented exceptions and operational risks

| Item | Disposition |
|---|---|
| Phase 0 documentation branch is unpublished | Nonblocking publication backlog; publish separately when tooling permits |
| `${MLB_MODEL_REPO}` has 34 modified and 7 untracked paths | Read-only quarantine; do not reset, clean, stash, commit, overwrite, train from, or otherwise alter it |
| GitHub protection, benefits, and zero-overage settings are unverified | Operational risk; no new paid subscription or weakened repository gate is authorized |
| GitHub authentication and SSH connectivity | Restored for account `phatcobra`; remote mutation remains limited to the existing PR #8 branch and pull request |
| AWS Cost Explorer ingestion | Newly enabled account data is unavailable; the budget currently reports `$0.00`, which is not accepted as evidence of zero accrued cost |
| Container release scan | Resolved: immutable runtime digest `sha256:710237682af8ba399c2658e4d2846c050e2275a32360430498173f6e3764534e` is `COMPLETE` with all severity counts zero |
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
`main` at validated head `77c73b63901932c09e61d88e67f92817b65674dd`.
It contains every prior PR #5 commit and changed path, the bounded real slice,
and the complete multi-season evidence package. PRs #1, #3, and #5 remain
closed with their remote branches preserved. GitHub Actions run `29555205156`
completed successfully on that head, and every `release-gate` step executed,
including the complete offline suite and diagnostic artifact upload. A separate
draft PR #7 for PostHog appeared outside this execution; it was not created,
inspected, or modified here and does not alter the product critical path.

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

Normalization v2 completed all 36 monthly partitions for the 2021 through 2024
regular seasons. The cache contains 9,778 normalized partition observations;
62 gamePks occur in two calendar-month partitions because StatsAPI exposes the
same postponed or resumed identity in both schedule windows. Their analytical
records are identical, so the aggregate retains one record per gamePk and now
emits 62 explicit reconciliation records. Four other games fail closed: two
have no first-inning linescore and two have missing team or venue identity.
The resulting unique accepted set contains 9,716 finalized games with 100%
two-starter coverage and 9,559 strict-prior feature-eligible games.

One otherwise feature-eligible suspended-game record, gamePk `716404`, remains
evaluation-ineligible because its recorded final label availability precedes
the source's current October 2 scheduled datetime for a September 28 official
game. No original prediction cutoff is invented. The renewable chronological
ledger therefore contains 7,287 predictions and separate grades across the
2022, 2023, and 2024 folds.

The final complete deterministic package replay under producing commit
`cd7c332d42d696794d56928ebfbcc4c6b04a8444` passed and produced the
conservative primary conclusion `PREDICTIVE SKILL NOT ESTABLISHED`. Pooled log
loss is `0.693204` versus `0.693270` for expanding overall climatology; pooled
Brier score is `0.250029` versus `0.250062`. The official-date clustered 95%
intervals include zero for both improvements, and the candidate degrades in the
2024 fold. Pooled calibration slope is `0.437071`, intercept is `-0.064094`, and
ECE is `0.015694`. These results prohibit any predictive-edge, market, wager,
promotion, or production claim.

The committed package contains 16 machine-readable artifacts totaling
50,326,756 bytes. Independent verification parsed 73,108 JSONL records, matched
every byte hash and row count, verified all 7,287 prediction-to-grade links,
confirmed that prediction records contain no outcome, reproduced every
probability with zero maximum difference from the preserved preliminary
package, and confirmed that 2025, market data, raw payloads, and private paths
are absent. Repository attributes disable line-ending normalization for both
real-evidence directories, preserving manifest bytes across platforms. The
normalized partition identity is
`f7a3a6e1ad7b3fe0567ed1326f12007f98fa0488ed355f69f2aa679ba5d86d2c`;
the prediction partition identity is
`334f1ff8fce0bdcdcedd2f20cc1e6f090dbf589f24b92bbaf0f93b6e439e2f24`.

Focused real-package manifest, coverage, reconciliation, ledger-separation,
byte-portability, and decision validation reports `5 passed`. The complete
offline suite reports `123 passed, 1 skipped, 21 warnings`; the skip and
dependency warnings are the existing documented environment baseline. Ruff
lint passed, Ruff formatting reports `47 files already formatted`, byte
compilation passed, and Pyright
reports `0 errors, 0 warnings, 0 informations`. The first full-suite attempt
correctly rejected the bootstrap's `np.random` spelling under the repository's
anti-fabrication gate; the deterministic sampler was replaced without weakening
that gate, and the final suite passed.

## Candidate comparison code checkpoint

The candidate-comparison implementation now reuses only the committed
2021-through-2024 evidence and identical immutable folds. It compares the fixed
regularized logistic model with a deterministic fixed-parameter LightGBM model,
both raw and with sigmoid calibration trained exclusively on completed prior
fold out-of-sample predictions. The first test fold is intentionally uncalibrated
because no prior out-of-fold evidence exists. It retains model text and hashes,
separate candidate prediction and grade ledgers, model-bootstrap probability
uncertainty clustered by official game date, score-bootstrap intervals, and two
complete deterministic derivations. It performs no acquisition, tuning,
feature selection, locked-holdout access, or market evaluation.

The validated low-replicate real-data check preserves the primary decision
`PREDICTIVE SKILL NOT ESTABLISHED` and reproduces the logistic probabilities
with maximum absolute delta `0`. Pooled log loss / Brier / ECE are:

- logistic raw: `0.693204` / `0.250029` / `0.015694`;
- logistic prior-fold sigmoid: `0.693847` / `0.250345` / `0.003856`;
- LightGBM raw: `0.697654` / `0.252208` / `0.032467`;
- LightGBM prior-fold sigmoid: `0.695999` / `0.251390` / `0.014366`.

Logistic calibration is rejected because its ECE improvement comes with worse
pooled log loss and Brier score. LightGBM calibration is accepted only relative
to the materially worse raw LightGBM candidate; neither LightGBM variant nor
either logistic variant establishes skill. The complete offline code gate
reports `128 passed, 1 skipped, 21 warnings`; Ruff lint and format, Pyright,
byte compilation, JSON/JSONL parsing, privacy/secret scanning, and
`git diff --check` all pass. The skip and warnings remain the documented
environment/dependency baseline.

## Candidate comparison final evidence

The exact committed comparison code produced a final two-pass package using 32
model-uncertainty and 2,000 official-date score-bootstrap replicates. Each of the
four variants has 7,287 chronological predictions and separate grades on the
same immutable 2022-through-2024 folds. The package contains 58,311 JSONL rows
across seven manifested artifacts totaling 55,154,142 bytes. No outcome appears
in a prediction record, all prediction IDs link one-to-one to grades, the
locked 2025 holdout remains unused, every market snapshot is null, and no raw or
private workstation data is present.

The final pooled evidence is unchanged from the validated point estimates:

- logistic raw: log loss `0.693204`, Brier `0.250029`, ECE `0.015694`;
- logistic prior-fold sigmoid: `0.693847`, `0.250345`, `0.003856`;
- LightGBM raw: `0.697654`, `0.252208`, `0.032467`;
- LightGBM prior-fold sigmoid: `0.695999`, `0.251390`, `0.014366`.

Raw logistic improvement over overall climatology is only `0.000066` log-loss
and `0.000033` Brier points; the final 95% intervals are
`[-0.000898, 0.000962]` and `[-0.000411, 0.000512]`. Both LightGBM variants are
materially worse than overall climatology. Logistic calibration remains
rejected. LightGBM calibration is accepted only relative to raw LightGBM and
does not make that family competitive. Every variant decision and the sole
primary decision are `PREDICTIVE SKILL NOT ESTABLISHED`.

Each temporal calibrator now records its target fold, model family, prior-fold
training count, training-prediction identity, and its own content identity. A
second clean offline package run exactly matched configuration, fold membership,
metrics, model and calibrator artifacts, every prediction byte, and all 29,148
grade identities. No network client exists in the comparison module and both
runs read only committed local 2021-through-2024 evidence.

Deterministic replay passed with zero logistic probability delta. Producing code
commit `a3e86f52e62bd8fcfbd47c579822ab5303a29082` generated model-artifact identity
`fbcebb2ffc4e8f76a81b6b5562820196f50c386854a2a9b39a6bf1ec7fb50540`,
prediction identity
`2518ceafbd3eecfc1b27a60b9733b55fe21cb98a4a1b12d90922f6de9fa51a02`,
grade identity
`8acc412ff7aad193d66b133508b793e1e6b9037b85be31988d50154e5d1c23a2`,
and evaluation identity
`23428a3f7257f434a6394a8f8a117ae0df3004cade8b8fa47771cb8ba072bfc7`.

Independent committed-artifact validation reports `5 passed` and verifies all
seven manifest hashes and row counts, chronological fold definitions, 29,148
one-to-one prediction/grade links, outcome separation, probability complements,
model and calibrator identities, target-fold/model-family provenance, 62
cross-partition reconciliations, four explicit source rejections, and 158
evaluation exclusions. The complete repository suite reports
`133 passed, 1 skipped, 21 warnings`; the skip and warnings remain the existing
documented environment/dependency baseline. Ruff lint passed, Ruff formatting
reports `50 files already formatted`, Pyright reports `0 errors, 0 warnings, 0
informations`, and byte compilation passed. Parsing passed for 51 JSON/JSONL
files containing 136,656 JSONL rows, four YAML files, and one TOML file. The 15
publication files contain no recognized secret or private workstation path, and
`git diff --check` passes.

## Deterministic continuation checkpoint — 2026-07-17

### Permanent project goal

Build and operate the complete reproducible, production-grade MLB NRFI/YRFI
probability platform on AWS. The permanent scope includes lawful point-in-time
baseball, pitcher, Statcast, lineup, park, weather, umpire, schedule, travel,
injury, and sportsbook ingestion; leakage-resistant features; chronological
out-of-sample modeling and calibration; conservative uncertainty and market
comparison; fail-closed decision and risk gates; probability API and browser
interface; scheduling, monitoring, grading, retraining, promotion, rollback,
recovery, audit, security, and cost controls. AWS foundation work, baseline
replay, data publication, and individual feature tables are components rather
than completion conditions. Until every qualification gate passes, the required
decision output is `NO QUALIFIED WAGER`.

### Repository checkpoint

- Existing branch: `feat/aws-probability-platform-20260717`; existing draft PR:
  `#8`; no branch, worktree, or pull request was created for this checkpoint.
- Validated publication head before this state-record commit:
  `162fd92f78ae4b96d2622d12959c510828938321`.
- Ordered new implementation commits after the previously published
  `fa9763059144b2e83d62c983a9a907f36142b787` checkpoint:
  `3db6d38e40ac053832d7034433a1dad2283a6a05`,
  `ce571dca5ea25e16fe70b9f6d396216607522ed6`,
  `11fdef7b272e2347bd9e8351fb4def5f43dfb5e7`, evidence metadata commit
  `ee76650ab8f1a4a9f1e32916c85dd7469bc0943f`, container repair commit
  `9e1f643b04ee98931e334d75eb2f3077df7e9514`, and evidence-table commit
  `162fd92f78ae4b96d2622d12959c510828938321`.
- The CloudShell producing commit
  `352974280a4d9ec8e101bc4553837379060e5f0b` and local publication head
  `162fd92f78ae4b96d2622d12959c510828938321` have the identical Git tree
  `0f253588118d0361988d716290ad56d3dcd5f9a3`. CloudShell preserves the
  state-record commit `038136d7ac135b30211fca58547cdb7946999e65` and its verified bundle. The
  workstation checkout now contains the same validated implementation and
  generated evidence as atomic commits; do not reset, clean, stash, or rewrite
  either history.

### AWS resource state and identifiers

- Account `660838763909`; approved region `us-east-2`.
- Storage buckets:
  `nrfi-probability-dev-660838763909-us-east-2-raw`,
  `nrfi-probability-dev-660838763909-us-east-2-lake`, and
  `nrfi-probability-dev-660838763909-us-east-2-evidence`. All are private,
  versioned, and KMS-encrypted; raw and evidence use Object Lock. The KMS alias
  is `alias/nrfi-probability-dev-platform`.
- ECR repository:
  `660838763909.dkr.ecr.us-east-2.amazonaws.com/nrfi-probability-dev-pipeline`.
  Preserved blocked tag:
  `commit-352974280a4d9ec8e101bc4553837379060e5f0b`; immutable manifest digest:
  `sha256:2467211600b1a3f56e7d80fa1d05586e02f0bd3c4b0eee34210c63167ada983a`.
  Live immutable tag `runtime-7602b07358b2` resolves to release-gated digest
  `sha256:710237682af8ba399c2658e4d2846c050e2275a32360430498173f6e3764534e`.
- Batch compute environment ARN:
  `arn:aws:batch:us-east-2:660838763909:compute-environment/nrfi-probability-dev-fargate`;
  queue ARN:
  `arn:aws:batch:us-east-2:660838763909:job-queue/nrfi-probability-dev-baseline`;
  active job definition:
  `arn:aws:batch:us-east-2:660838763909:job-definition/nrfi-probability-dev-baseline-replay:5`.
  Revision 4 remains active as the verified rollback definition.
- Network: default VPC `vpc-0022f9516b839ad93`; private subnet
  `subnet-0685bb9da6eb5c3a1` (`172.31.48.0/24`, `us-east-2a`, no public IP);
  S3 gateway endpoint `vpce-0f57a78509aef5802`; ECR Docker endpoint
  `vpce-017a206f6efa5becb`; ECR API endpoint `vpce-073bf6bdb57b3d0d0`;
  CloudWatch Logs endpoint `vpce-03f9e321d97c4e9c7`.
- The Fargate compute environment and queue are `ENABLED`/`VALID`. Counts for
  `SUBMITTED`, `PENDING`, `RUNNABLE`, `STARTING`, and `RUNNING` jobs are all
  zero. No Lambda, API Gateway, Glue, SageMaker, scheduled job, or duplicate
  network resource was added in this operation.

### Completed and validated work

- The Phase 0 inventory remains authoritative; no scan or acquisition was
  repeated. Exactly 875 manifest-approved 2021-through-2024 Statcast partitions
  (579,360,770 bytes) produced 19,432 actual-starter game histories and 19,432
  strict-prior feature snapshots. Of those, 17,509 profiles (90.103952%) meet
  the minimum prior-history threshold.
- Historical prediction joins remain explicitly ineligible at 0% because no
  timestamped probable-starter snapshot is admitted. Actual starter identities
  are used only for postgame attribution; no probable identity is invented.
- Two complete offline generations are byte-identical for all five package
  files. Manifest hashes, byte sizes, row counts, Parquet reads, date bounds,
  private-path checks, and the five focused tests pass. Dates are bounded from
  2021-04-01 through 2024-09-30.
- Two Parquet objects were written to the versioned KMS lake under feature
  version `pitcher-statcast-strict-prior-v1`. The manifest, coverage,
  zero-row rejection log, and transfer archive were written to the versioned
  KMS evidence bucket with Governance retention through July 2027. All six AWS
  objects have verified byte counts, SHA-256 checksums, encryption, and version
  IDs. No raw workstation cache was uploaded.
- `Dockerfile.aws` was repaired without changing application code or the locked
  dependency graph. It now uses immutable Amazon Linux 2023 digest
  `sha256:f03a6d1b59561c1347a4c386ecb8e38588050cffa290f0ac4f5c7246d055a36e`,
  exact Python package `3.11.15-1.amzn2023.0.3`, exact `libgomp` package
  `14.2.1-7.amzn2023.0.2`, and `UV_PYTHON=/usr/bin/python3.11`. Runtime smoke
  verification loaded Python 3.11.15, glibc 2.34, LightGBM 4.6.0, PyArrow
  25.0.0, and the existing replay module as non-root user `65532:65532`.

### Verified live-AWS checkpoint

Immutable tag `runtime-7602b07358b2` was built once and pushed once. ECR digest
`sha256:710237682af8ba399c2658e4d2846c050e2275a32360430498173f6e3764534e`
reports scan status `COMPLETE` with critical, high, medium, low, informational,
and undefined counts all zero. The known-blocked tag and digest remain unchanged
and were not deployed.

Existing private Batch job definition revision 5 points to the clean digest;
revision 4 remains available for rollback. Job
`f8419681-7513-4b73-86e6-f0adaaee2c36` completed `SUCCEEDED` with exit code 0,
one attempt, no public IP, and `NRFI_LOCKED_HOLDOUT_ACCESS=DENIED`. The job
verified 29,148 predictions and 29,148 grades, deterministic replay `PASS`, and
analytical equivalence at or below the declared `1e-12` tolerance; the maximum
record delta was `1.1712852909795402e-13`. It reported
`locked_holdout_used=false` and `market_data_used=false`.

The verified calibrated probability response, restricted to probability and
uncertainty, is:

```json
{
  "p_nrfi": 0.511138831136253,
  "p_yrfi": 0.4888611688637469,
  "uncertainty": {
    "lower_95": 0.4164458332468519,
    "method": "official-date-cluster-model-bootstrap-v1",
    "replicates": 32,
    "standard_error": 0.03987121250858687,
    "upper_95": 0.5626698522933542
  }
}
```

After verification, `SUBMITTED`, `PENDING`, `RUNNABLE`, `STARTING`, and
`RUNNING` job counts were all zero; Docker was idle; the ECR authentication
entry was absent; and no build, push, or Terraform operation remained active.
No new service, schema, endpoint, or recurring infrastructure was created. The
scientific status remains `PREDICTIVE SKILL NOT ESTABLISHED`, so the required
output remains `NO QUALIFIED WAGER`.

### Costs and budget

The account-wide budget remains `$30` per month with the existing 50% forecast,
80% actual, and 100% actual notifications. The private interface-endpoint floor
remains approximately `$21.90` per 730-hour month and the rotating KMS key adds
about `$1`, before storage, logs, data processing, ECR storage, and bounded
Fargate runtime. This checkpoint added one immutable ECR image and one bounded
Fargate validation job but no new recurring service or infrastructure floor.
Cost Explorer ingestion remains
lagged, so the project must not claim verified zero spend.

### Preserved local-only state

- The authoritative Phase 0 manifests, two completed scans, per-file manifest,
  checksums, and asset cache remain local and must not be reacquired.
- `.cache/nrfi_pitcher_statcast/replay2` preserves the second deterministic
  feature replay. The local transfer archive and Git bundle are preserved under
  the ignored pitcher-Statcast cache. The manifest-approved raw Statcast cache
  remains local-only.
- CloudShell retains state commit
  `038136d7ac135b30211fca58547cdb7946999e65` and its preserved dirty
  `Dockerfile.aws` runtime copy. Do not clean, reset, commit, or otherwise touch
  that checkout. The unused local Lambda image cache and temporary transfer and
  validation copies were removed only to recover CloudShell disk; the pushed
  ECR image, Git state, remote Terraform state, and source evidence remain
  recoverable and unchanged.
- The dirty external `mlb-model` repository remains read-only and quarantined.

### Safe stopping state

The single Docker build, smoke verification, ECR push, clean scan, Batch
revision registration, and live validation job are complete. The ECR login was
removed and the Docker configuration no longer contains that registry
authentication entry. There is no active Docker, build, push, or Terraform
process; no active Batch job; no partial S3 write identified; no Terraform apply
in progress; and no user-created temporary AWS credential. The prior bootstrap
user/key remain deleted. CloudShell intentionally preserves only its dirty
`Dockerfile.aws` runtime copy and must not be touched. The scanned ECR image,
rollback revision, and all S3 objects are immutable/versioned and recoverable.

### Commands and operations that must not be repeated

- Do not rerun either Phase 0 asset scan or reacquire the 2021-through-2024 MLB
  or Statcast source set.
- Do not rerun the completed 19,432-row pitcher feature generations or their
  deterministic replay unless their preserved outputs fail verification.
- Do not rerun the frozen AWS baseline Batch replay or the completed local model
  comparison/model-selection work.
- Do not rerun successful live validation job
  `f8419681-7513-4b73-86e6-f0adaaee2c36`, rebuild or repush immutable tag
  `runtime-7602b07358b2`, or repeat its completed ECR scan.
- Do not re-upload the six pitcher-Statcast package objects or rebuild/push ECR
  tag `commit-352974280a4d9ec8e101bc4553837379060e5f0b`.
- Do not run `terraform apply` merely to reproduce this checkpoint; the current
  operation made no Terraform change.
- Do not access, copy, upload, tune against, or evaluate the locked 2025
  holdout.

### Exact next operation

Continue directly with AWS-hosted point-in-time signal production through the
existing resources: define and validate the bounded signal input/output
contract, connect admitted pregame snapshots to the existing chronology-safe
feature and calibrated probability path, and expose probability plus
uncertainty through the existing AWS deployment boundary. Add API hosting only
when technically indispensable to that product path; do not perform PR,
publication, audit, or governance expansion as the next operation. Preserve the
locked 2025 holdout, keep `NRFI_LOCKED_HOLDOUT_ACCESS=DENIED`, and emit
`NO QUALIFIED WAGER` until every scientific and decision gate passes.

### Live probability API checkpoint — 2026-07-18

Validated implementation commit
`26a845ab2d5e77ef70737208c402e4f782ea1388` on existing branch
`feat/aws-probability-platform-20260717` exposes the preserved calibrated
probability through the existing AWS foundation. This commit remains local and
is not pushed because pushing would mutate draft PR #8, which the current
directive forbids.

Terraform added only the sanitized lake object, one bounded CloudWatch log
group, one least-privilege Lambda role and inline policy, one Python 3.11 Lambda,
and one IAM-authenticated Function URL. The live endpoint is
`https://42ajmftf4o2h4jiyaze2f447wm0jxiof.lambda-url.us-east-2.on.aws/`.
An AWS SigV4-authenticated `GET` returned HTTP 200 with exactly:

```json
{"p_nrfi":0.511138831136253,"p_yrfi":0.4888611688637469,"uncertainty":{"lower_95":0.4164458332468519,"method":"official-date-cluster-model-bootstrap-v1","replicates":32,"standard_error":0.03987121250858687,"upper_95":0.5626698522933542}}
```

The same URL returned HTTP 403 without AWS authentication. Lambda state is
`Active`, last update is `Successful`, runtime is Python 3.11 on `x86_64`,
memory is 128 MiB, timeout is 10 seconds, and
`NRFI_LOCKED_HOLDOUT_ACCESS=DENIED`. The response object is 284 bytes at
`s3://nrfi-probability-dev-660838763909-us-east-2-lake/signals/sanitized/current/probability-response.json`,
with `application/json`, `no-store`, and platform-key KMS encryption.

The account concurrency quota requires all 10 executions to remain unreserved,
so AWS rejected reserved concurrency 1. The failed apply stopped before URL
creation; Terraform then replaced only the tainted incomplete Lambda, created
the URL, and applied an in-place timeout correction. Final Terraform format and
validation passed, the encrypted S3 state lock was released, and a full refresh
plan reported `No changes`. The final state contains no active Batch jobs and no
active Terraform, Docker build, or Docker push process.

This endpoint adds no recurring monthly infrastructure floor beyond the
existing approximately $21.90 private-network floor and KMS key; Lambda, logs,
and S3 are usage-based and remain under the existing $30 monthly budget. No
temporary credential was created, the 2025 holdout remains untouched, and the
scientific status remains `PREDICTIVE SKILL NOT ESTABLISHED` with required
output `NO QUALIFIED WAGER`.

Do not reapply `/tmp/nrfi-probability-api.tfplan`,
`/tmp/nrfi-probability-api-v2.tfplan`, or
`/tmp/nrfi-probability-api-v3.tfplan`; their completed effects are represented
in encrypted remote state. The exact next product operation is to produce and
join valid timestamped pregame pitcher and Statcast signals through the existing
AWS feature path, then generate new chronological out-of-sample probabilities
without accessing or tuning against 2025. Do not add another service, audit,
schema framework, branch, worktree, or pull request first.

### Timestamped probable-starter AWS checkpoint - 2026-07-18

The permanent goal remains a production-grade AWS-hosted MLB NRFI/YRFI
probability platform. The active product boundary is calibrated NRFI/YRFI
probability with uncertainty. The scientific state remains
`PREDICTIVE SKILL NOT ESTABLISHED`, and the required fail-closed output remains
`NO QUALIFIED WAGER`.

One official StatsAPI schedule response for games on `2026-07-19` was persisted
at `2026-07-18T04:47:28.706439Z`. Its 46,037-byte response SHA-256 is
`ad1313ef710094d83b4aef12471d6a9a09da3df7012b4647079ac153482a453c`.
All package generations after that acquisition used the checksum-verified local
cache with networking disabled. The raw response remains local-only and was not
written to the repository or AWS.

The derived package contains 15 regular-season games and 30 game-side rows.
Twenty-nine rows have an official probable starter observed before the scheduled
cutoff. Twenty-two rows match an inventoried strict-prior Statcast profile, and
20 of those profiles meet the existing minimum-history rule. Inference coverage
is still zero: those 20 profiles stop before the intervening locked season, two
profiles lack sufficient prior history, seven pitcher IDs are absent from the
inventory, and one game side has no probable starter. The package therefore
does not invent a current game probability.

The producing code and seven focused tests are an isolated commit on the
preserved CloudShell copy of existing branch
`feat/aws-probability-platform-20260717`:
`7b365dd004aa3a1edb6d65cd6dfce091b6ac7216`. This commit contains only
`nrfi/pregame_snapshot.py` and `tests/test_pregame_snapshot.py`. The files are
byte-equal to the locally validated files. No push or pull-request mutation was
performed. This CloudShell history is based on preserved CloudShell head
`038136d7ac135b30211fca58547cdb7946999e65`; it must not be mistaken for the
workstation branch head or pushed without intentional lineage reconciliation.

The workstation remains on branch `feat/aws-probability-platform-20260717` at
`589963ab896dcb7a880c2fc11d15b47052ce2786`, three commits ahead of its remote.
Its Git metadata is outside the currently writable workspace, so the two code
files, the five-file derived package under
`docs/pregame_snapshot/2026-07-19`, and this state update remain uncommitted and
preserved. Do not reset, clean, stash, overwrite, or regenerate them.

Validation evidence:

- focused pytest: 7 passed; one non-test-failure warning reports that pytest
  could not write its cache directory;
- Ruff lint and Ruff format check: passed;
- Pyright: 0 errors, 0 warnings;
- byte compilation and `git diff --check`: passed;
- two offline replays plus the derived package are byte-identical for all five
  files;
- every manifest byte count, SHA-256, and row count passed; 30 snapshot IDs and
  30 feature IDs are unique and linked one-to-one;
- all eligible snapshot observations precede their prediction cutoffs, and all
  joined profiles precede their observation timestamps;
- private-path, secret, raw-response, and locked-2025 checks passed.

The five derived files are live in the existing versioned, private, KMS-encrypted
lake under
`s3://nrfi-probability-dev-660838763909-us-east-2-lake/signals/pregame/official-statsapi/2026-07-19/`.
They use KMS key
`arn:aws:kms:us-east-2:660838763909:key/7772a2e9-e516-49ff-b2e1-0067567f52a8`
and `Cache-Control: no-store`. Exact latest versions are:

- `artifact_manifest.json`, 1,000 bytes,
  `bhatJLtUEWn4oeMCOEMWUiAGZFcFN7nO`;
- `coverage.json`, 859 bytes, `ugHH5Qe4eDVZcCrYLfqxn.Eq3KLrTLVm`;
- `pitcher_features.jsonl`, 58,449 bytes,
  `_wHkkd0IbKTU4Nu8nj2WfCowoASWvD_B`;
- `probable_starters.jsonl`, 24,651 bytes,
  `IgFkluPiI3mUyleobZf_S3znkZEPUo5J`;
- `provenance.json`, 481 bytes, `GmPGViryTdbvf0bays.djLTCuA2r7FIv`.

No AWS service, Terraform resource, subscription, credential, Batch job, or
recurring cost was created. The only AWS mutations were these five small
versioned S3 objects and temporary files in the existing CloudShell home
directory. The `$30` monthly budget and existing network/KMS cost floor are
unchanged apart from negligible S3 storage and request usage.

Preserved local-only state includes the raw source cache, two replay directories,
and the 16,674-byte transfer archive under
`.cache/nrfi_pregame/2026-07-19`. Do not repeat the July 19 StatsAPI acquisition,
the three package generations, or the five S3 uploads while the recorded hashes
and version IDs remain available and valid.

The exact next product operation is not infrastructure. It is to obtain lawful,
timestamp-verifiable pregame starter identities for a development-period sample
or accumulate forward snapshots, then build strict-prior pitcher/Statcast
features with history available before each cutoff and re-run chronological
out-of-sample evaluation. Postgame actual starters may not substitute for that
evidence. The 2025 holdout remains locked and untouched.

## Forward snapshot collector checkpoint - 2026-07-18

The scheduled forward collector for immutable timestamped probable-starter
snapshots is live in AWS. Implementation commit
`af6c178a59eafa0af6489c3d57864f49f04fe08b` added
`nrfi/aws_pregame_collector.py` (schema `forward_probable_starter_capture.v1`,
reusing the committed `pregame_snapshot` acquisition and normalization path
through lazy imports), six focused tests, `terraform/pregame_collector.tf`, and
the OIDC deployment workflow `.github/workflows/terraform-deploy.yml`. Workflow
commits `f0a68f5` and `c740ec9` added branch-push triggering and KMS-encrypted
state locking. The change-set gate passed Ruff lint and format, Pyright
`0 errors, 0 warnings, 0 informations`, and the complete offline suite
`158 passed, 1 skipped, 21 warnings`; CI remained green through run
`29663636034`.

Deployment executed under GitHub OIDC role
`nrfi-probability-terraform-deployer`; no root or long-lived credential ran
Terraform. Managed policy `nrfi-probability-stage2-deployer` was extended from
the operator console session as bounded bootstrap actions: version v5 added
`lambda:*`, `events:*`, and Lambda log-group management scoped to
`nrfi-probability-*` resources plus `logs:DescribeLogGroups`; version v6 added
`iam:PassRole` for `arn:aws:iam::660838763909:role/nrfi-probability-*`. Prior
policy versions remain available for rollback. The first apply attempt
(run `29663147439`, commit `917dd31`) failed closed on the missing
`iam:PassRole` permission and mutated nothing.

Terraform run `29663385687` (trigger commit `41de6ba`) applied the reviewed
plan `7 to add, 1 to change, 0 to destroy`; the single in-place change
realigned `aws_batch_job_definition.baseline` with the already-deployed clean
image digest. Created resources:

- Lambda `nrfi-probability-dev-pregame-collector` (python3.11, 256 MiB, 120 s
  timeout, `NRFI_LOCKED_HOLDOUT_ACCESS=DENIED`), verified `Active` and
  `Successful`;
- IAM role and boundary policy `nrfi-probability-dev-pregame-collector`
  limited to `s3:PutObject` under `signals/pregame/official-statsapi/forward/`,
  KMS via S3, its own bounded log group, and explicit locked-holdout denies;
- log group `/aws/lambda/nrfi-probability-dev-pregame-collector` with 30-day
  retention;
- EventBridge rule `nrfi-probability-dev-pregame-collector-schedule`,
  verified `ENABLED` with `cron(3 11,13,15,17,19,21,23,1 * * ? *)` (eight
  captures per day for the market's today and tomorrow), plus its target and
  invoke permission.

The controlled first invocation returned status 200 in 3,420 ms and wrote two
versioned, KMS-encrypted, `no-store` captures whose keys, byte counts, and
version IDs were independently re-read from S3 afterward:

- `signals/pregame/official-statsapi/forward/2026-07-18/capture-20260718T222823Z.json`,
  26,120 bytes, version `Rp7NoKU12L98CoZjtzSUtShEaHC_Y9x3`, 30 rows, 6
  pregame-eligible;
- `signals/pregame/official-statsapi/forward/2026-07-19/capture-20260718T222824Z.json`,
  26,925 bytes, version `jhvZWkcM6nQKmS4sY2mOBcKEvXS9tVfm`, 32 rows, 29
  pregame-eligible.

Captures persist derived rows, request parameters, retrieval timestamps, and
the source response SHA-256 only; no raw StatsAPI payload was uploaded, and
`locked_2025_holdout_accessed` is false in both captures. After verification,
`RUNNING` Batch jobs were zero, no temporary AWS credential existed, and the
only new recurring usage is the schedule's negligible Lambda, S3, and KMS
request cost inside the approved `$30` monthly budget.

A public-archive probe for 2022-2024 probable-pitcher pages could not be
executed from this session because the fetch path is blocklisted; lawful
timestamp-verifiable historical probable-starter evidence therefore remains
unavailable, and scheduled forward accumulation is the active remedy.

The exact next product operation is to admit accumulated forward captures from
the lake into the shared feature path: verify capture checksums, join
strict-prior Statcast profiles, surface per-game eligibility and rejection
reasons through the existing IAM-authenticated endpoint, then extend lineup,
park, weather, umpire, rest, travel, and injury point-in-time inputs and re-run
strict chronological evaluation. The scientific status remains
`PREDICTIVE SKILL NOT ESTABLISHED`; the required output remains
`NO QUALIFIED WAGER`.

## Live forward assembly checkpoint - 2026-07-19

Accumulated forward captures are now admitted into the shared production
feature path on AWS, and the IAM-authenticated endpoint serves real
request-specific assembly status. Implementation commit `0c31fd5` added
`nrfi/forward_admission.py` (capture discovery, schema and identity
validation, explicit rejections, point-in-time selection with preserved
revision lineage, strict-prior profile join, per-game fail-closed assembly)
plus eight focused admission tests, seven endpoint tests, one collector
wiring test, and the Terraform for both Lambdas. Commits `13bb81e` and
`904bae8` sized the collector at 1024 MiB for the profile projection. The
gate for the change set was Ruff lint/format clean, Pyright `0 errors`, and
the complete offline suite `172 passed, 1 skipped, 21 warnings`; CI stayed
green through run `29668666368`.

The strict-prior profile table now has a lossless JSONL projection for the
stdlib Lambda runtime at
`features/pitcher-statcast-strict-prior-v1/profiles.jsonl`
(40,608,284 bytes, SHA-256
`b6a164f6aaacccad88365a90667525a35024915e27bd62e80216a90c019fc071`, version
`In6dj0vA6fjCBqBiGn2T4yKNvbQ2X42D`, 19,432 rows, 17,509 eligible, zero NaN
projections, cutoff years 2021-2024 only), derived in CloudShell with PyArrow
25.0.0 from committed parquet
`features/pitcher-statcast-strict-prior-v1/producing_commit=11fdef7b272e2347bd9e8351fb4def5f43dfb5e7/pitcher_features.parquet`
(source SHA-256
`9ec5ea9250a09ff7055459e960252b305e0b5e9772aa85dcc6b7d7078a9ff1a7`, version
`sp.tPTyJms.SIny5yWW0nKly4x432bta`); provenance sidecar version is
`lSDk7MTaHqd0CXvy8vHq9lziKwD_BF7V`.

Deployment ran only through the GitHub OIDC deployer. Run `29668474511`
planned `0 add, 4 change, 0 destroy`; dispatch run `29668618357` applied it;
dispatch run `29668657458` confirmed `No changes`; run `29668844142` applied
the memory sizing (`0 add, 1 change, 0 destroy`). No resource was destroyed
or replaced at any point.

Independent live verification: the collector (1024 MiB, Active/Successful)
returned HTTP 200 and published assembly packages for 2026-07-18 (4 admitted
captures, 15 games) and 2026-07-19 (4 admitted captures, 16 games) with
`profiles_status=PROFILES_LOADED`. `feature_assembly_eligible_games` is `0`
on both dates, and that zero is the correct fail-closed product of the
recorded scientific gap: every side blocks on
`PROFILE_MISSING_INTERVENING_SEASON_HISTORY`,
`PROFILE_MINIMUM_PRIOR_STARTS_NOT_MET`, or
`NO_STRICT_PRIOR_STATCAST_PROFILE` because the 2025 season remains locked.
The latest verified package is
`signals/pregame/assembly/2026-07-19/assembly-20260719T013838Z.json` with
`package_id`
`0ebc4e68a97378027021edacbdd3154e1f8f1a2b9eda7541ad54eb90f328b4e5`.

Endpoint verification: an unauthenticated game query returned HTTP 403; a
SigV4 `GET ?game_pk=822786&date=2026-07-19` returned HTTP 200 with the real
per-game assembly (layered eligibility all false above the snapshot level,
`freshness_seconds` 2,
`probability_ineligibility_reasons`
`["APPROVED_MODEL_UNAVAILABLE","PREDICTIVE_SKILL_NOT_ESTABLISHED"]`, and
`"wager_decision":"NO QUALIFIED WAGER"`); the root path still returns the
byte-identical preserved response now explicitly labeled
`x-nrfi-response-class: preserved-baseline-not-current-inference`.

After verification no Batch job was active in any state and no temporary
credential persisted; SigV4 test credentials were confined to subshells. The
new usage (one 40.6 MB object, small assembly objects, eight collector
invocations per day at 1024 MiB) stays within the approved `$30` monthly
budget. A deferred security follow-up remains recorded: narrow the deployer
policy's `lambda:*`/`events:*` grants to the enumerated action set after the
next stable deployment window.

The exact next product operations are, in order: timestamped lineup
collection and admission through the same forward pattern; batter and
top-of-order features; park factors; pregame weather forecasts; umpire
assignments; rest, travel, and workload effects; then strict chronological
re-evaluation over the accumulated forward window before any model approval.
The scientific status remains `PREDICTIVE SKILL NOT ESTABLISHED`; the
required output remains `NO QUALIFIED WAGER`.

## Expanded-history admission checkpoint - 2026-07-19

A read-only inventory reconciled every located 2015-2024 historical asset;
the committed ledger is `docs/historical_inventory/2026-07-19/`
(`inventory.json` + `summary.md`). Principal findings: the StatsAPI
normalized-v2 cache and committed evidence remain the canonical outcome
source; the quarantined `mlb-model` repository holds the 2015-2024 raw
Statcast day-level cache (1.23 GB, 2,584 files, 2015-2025 mixed) and a
3.78 GB DuckDB warehouse (Statcast/Retrosheet/Lahman/StatsAPI, includes
2025); its 2025 members are HOLDOUT_BLOCKED, its derived outputs are
holdout-contaminated and stay QUARANTINED, and its 2015-2024 slices are
admission candidates strictly through a season<=2024 extraction contract
that has not yet been executed. No historical weather, injury, or
timestamped sportsbook-price asset was located. No source asset was
modified; the 2025 holdout was not listed, loaded, or computed against.

The precise 2026 assembly-rejection census (30 committed sides plus the
32-side deployed run) is recorded in the ledger: one missing probable
starter, seven pitchers absent from the 2021-2024 profile table, two below
the minimum-starts threshold, twenty blocked only by the unnecessary
requirement for locked-2025 intervening history, and zero identity,
staleness, omission, or cutoff defects. Commit
`a60be5a` corrected the unnecessary requirement: feature schema
`pregame_pitcher_statcast_feature.v2` and assembly schema
`pregame_game_assembly.v2` now express the gap as
`profile_history_gap_seasons` / `profile_recent_history_missing` without
erasing valid career history, and probability eligibility remains
fail-closed behind model approval. Terraform run `29682891314` planned
`0 add, 2 change, 0 destroy` and marker run `29682932564` applied it; both
Lambdas run the v2 semantics. The full gate passed
(`174 passed, 1 skipped, 21 warnings`; Ruff and Pyright clean).

The multiseason engine then acquired and normalized the 2015-2020 regular
seasons into the existing resumable cache (36 new monthly partitions,
official StatsAPI, raw payloads in memory only) and produced the new
expanded-history experiment package `docs/multiseason_2015_2024/`
(17 artifacts, 124,756,722 bytes, per-file SHA-256 manifest, deterministic
double-derivation replay PASS, producing commit
`5a7a5b77de87b7b11510c83e7e5f228fc2ea4d43`). Coverage: 22,772 scheduled,
22,761 accepted finalized games, 11 explicit rejections, 193
cross-partition duplicate gamePks deduplicated with reconciliation
records, 100% actual-starter coverage, 99.95% label coverage, and
`locked_holdout_used=false` throughout. The prior `docs/multiseason`
2021-2024 package and every existing prediction, grade, and baseline
remain untouched.

Chronological evaluation now spans nine expanding folds (train 2015..K,
predict K+1, for K+1 in 2016-2024; the 2020 fold holds 898 pandemic-season
predictions) with 20,330 out-of-sample predictions. Pooled candidate
metrics: log loss `0.693166` versus `0.693277` overall climatology; Brier
`0.250009` versus `0.250065`; ECE `0.010349`; calibration slope
`0.583255`, intercept `-0.010933`. The official-date-clustered bootstrap
(2,000 replicates) log-loss improvement is `+0.000111` with 95% interval
`[-0.000263, +0.000...]` including zero. Key identities: configuration
`f9044e29...96c728`, normalized partition `d81999b1...87f5aa`, features
`2e92ae82...34f8dc`, predictions `ddd70534...49003c`, grades
`7e76f426...dec5bb`, evaluation `9438d52b...14a5d4`, fold membership
`7e8cb53a...ec2d11`. The decision on the maximum lawful outcome history is
unchanged: `PREDICTIVE SKILL NOT ESTABLISHED`.

2025-denial evidence: the engine CLI rejects any season >= 2025 by
construction (`the locked 2025 holdout is prohibited`), the collector and
admission paths carry dedicated locked-2025 tests (suite green), every
manifest records `locked_holdout_used=false`, and no 2025 object exists in
the project lake.

Remaining operations, in order: execute the season<=2024 Statcast
extraction contract from the quarantined raw cache and rebuild the
pitcher profile table over 2015-2024 (then batter/top-of-order, team,
park, platoon, rest/travel/workload tables with explicit missingness);
verify Retrosheet coverage for lineups/umpires and admit or reject it;
publish the expanded package and rebuilt tables to the versioned lake
(pending operator console sign-in; the GitHub OIDC deploy path remains
available); re-run the model-comparison family and calibration on the
expanded features under a new experiment identity; and narrow the deployer
policy's broad grants. The required outputs remain
`PREDICTIVE SKILL NOT ESTABLISHED` and `NO QUALIFIED WAGER`.

## Statcast extraction + profile rebuild checkpoint - 2026-07-19

The pre-2025 Statcast extraction contract is implemented, executed, and
committed. Commit `810815a` added `nrfi/statcast_extraction.py` and
`tests/test_statcast_extraction.py` (five boundary tests, all passing inside
the full suite `179 passed, 1 skipped`). The module builds an allowlist purely
from directory and filename tokens over the quarantined
`mlb-model/data/statcast_days/<year>/<month>/statcast_<y>_<m>_<d>.parquet`
cache, where each season is a physically separate top-level directory, so the
locked-2025 directory is never traversed for content. Aggregation and the
strict-prior windowing reuse the proven `nrfi.pitcher_statcast` functions
unchanged, preserving the committed 2021-2024 feature semantics.

Executed build (producing commit `64b7ccc`) over the real cache:
`day_files_admitted=2450`, `day_files_opened=2450`,
`day_files_opened_2025=0`, `day_files_rejected=43`,
`opened_source_bytes=1,167,901,647`. The 43 rejects are the entire 2025 season
directory (never traversed), 42 `.corrupt_*` files, and non-matching names -
each recorded in `source_file_ledger.jsonl` with `opened:false`. Zero locked
files opened is proven both by the ledger identity
`1e1f7410e51b1bd9c9fc825d28443a71f65b272f55a30b8f46d0eba972642677` and the
runtime guard. Source files were read-only; the mixed DuckDB warehouse was
never opened.

Rebuilt strict-prior profiles span 2015-2024: 45,522 actual-starter games
(100% Statcast-matched, 0 rejected), 45,522 pitcher feature snapshots,
42,437 profile-feature-eligible (93.223057%) across 1,168 distinct pitchers
(860 ever-eligible) - versus 17,509 eligible in the old 2021-2024 table. Each
snapshot carries career / last_5 / last_20 rate windows, workload
(average_pitch_count), rest (days_since_previous_start), minimum-history
(prior_starts_* with MINIMUM_PRIOR_STARTS=3), pitch quality (whiff / chase /
hard-hit / barrel / fastball velocity), and platoon raw counts (vs-LHB / vs-RHB
PA and K); every window uses only starts with scheduled_start_at and
label_available_at strictly before the prediction cutoff, excluding the target
game. Identities: history partition
`3d2243a43deb2b70287c4efd777c510f1f0ef89c558251989981dcdc01f6b5e5`,
feature partition
`52c0d0a9405ee2096301d52c1d06e54c9c588a7ff4041738da916befa1ba90b8`,
configuration inside `artifact_manifest.json`.

Re-run 2026-07-19 rejection census against the rebuilt table
(`rejection_census_2026_07_19.json`), 30 probable-starter sides:
20 RESOLVED_ELIGIBLE_PROFILE (previously blocked by the spurious 2025
intervening-history requirement, now backed by real 2015-2024 career history),
7 NO_HISTORICAL_PROFILE_2015_2024 (genuine gaps - pitchers with no qualifying
2015-2024 starts, i.e. debuts after 2024), 2 MIN_THRESHOLD_NOT_MET (2-3 career
starts), 1 PROBABLE_STARTER_MISSING (no announced starter). No identity
mismatch, stale-table, feature-omission, or cutoff defect appears; the seven
absent pitchers are precisely genuine data gaps, not an unnecessary 2025
requirement.

Determinism is proven. Commit `d485129` added
`tests/test_statcast_extraction_determinism.py`, which runs the complete
extraction pipeline twice on a synthetic fixture and asserts byte-identical
`pitcher_game_history.parquet`, `pitcher_features.parquet`,
`source_file_ledger.jsonl`, `coverage.json`, and `artifact_manifest.json`, plus
identical history/feature/ledger identities, and confirms the strict-prior
window excludes the current and future starts (prior_starts_career 0 then 1).
A confirmatory second full-cache build was started but abandoned for system
contention; the fixture test is the durable determinism guarantee. AWS publish
was not performed this turn. The rebuilt `pitcher_game_history.parquet` and
`pitcher_features.parquet` are preserved in git alongside the committed ledger,
coverage, manifest, and census so the dataset is durably versioned; the S3-lake
publication (versioned, KMS-encrypted, under
`features/pitcher-statcast-strict-prior-2015-2024-v1/`) and the live-assembly
switch to the rebuilt profiles remain the exact next operations. 2025 stays
fully locked; the required outputs remain `PREDICTIVE SKILL NOT ESTABLISHED`
and `NO QUALIFIED WAGER`.

### Exact next operations
1. From CloudShell (needs interactive AWS sign-in), run the pending safety
   verification: `aws sts get-caller-identity`, Batch job counts across all
   active states on `nrfi-probability-dev-baseline`, and the 2025-prefix deny
   check on the lake. No AWS mutation occurred this turn, so no job can exist
   by construction, but the explicit check was blocked by console session
   instability and should be recorded.
2. Publish the two rebuilt parquet tables (local at
   `docs/pitcher_statcast_2015_2024/`) to the encrypted, versioned lake under
   `features/pitcher-statcast-strict-prior-2015-2024-v1/` and generate the
   JSONL profile projection for the stdlib Lambda runtime, exactly as the
   2021-2024 projection was produced.
3. Point the live assembly collector's `NRFI_PITCHER_PROFILES_KEY` at the
   rebuilt projection and re-verify the deployed game-assembly census (expect
   20 of 30 sides to resolve, matching the local census).
4. Continue through batter, team, park, platoon, rest, travel, lineup, umpire,
   and lawful weather features, then the expanded model comparison and
   calibration under a new experiment identity.

Exact continuation command for the extraction/rebuild (reproduces the committed
tables identically): `python -m nrfi.statcast_extraction --day-cache-dir
C:\Users\ameis\mlb-model\data\statcast_days --multiseason-dir
docs/multiseason_2015_2024 --output-dir docs/pitcher_statcast_2015_2024
--producing-commit 64b7ccc0715df2cf41b74761d9c56a0c080d9fe0`.

## Window-builder optimization checkpoint - 2026-07-19

Phase 1 verified: branch `feat/aws-probability-platform-20260717` clean and
synced at `81057a9` before this work, no unpushed or unrelated commits, active
worktree correct. Local AWS CLI carries no long-lived credentials by design
(`InvalidClientTokenId`) - itself the intended least-privilege posture; AWS
read-verification and S3 publication run only through interactive CloudShell or
the GitHub OIDC path. The committed Terraform retains the locked-holdout deny
controls (`DenyLockedHoldoutStorage`, `DenyLockedHoldoutKeys`) as static 2025
deny evidence; no 2025 prefix was enumerated.

Phase 2 optimization is implemented and proven. Commit `d864686` added
`build_pitcher_feature_snapshots_fast` to `nrfi/statcast_extraction.py`: the
career window is accumulated left-to-right (identical float arithmetic to the
reference prefix `sum`) while the bounded last_5 / last_20 windows reuse the
exact `_window_metrics` over their <=20-row slices, so no feature meaning,
cutoff, minimum-history rule, label, admitted partition, identity mapping, or
chronology changes. Equivalence is proven, not assumed:
`test_fast_builder_matches_reference_builder_exactly` asserts the fast and
reference builders produce byte-identical snapshots (including the float
fastball-velocity field and the >20-start career/trim edge that first exposed a
`prior_starts_career` bug, now fixed), and the full-pipeline determinism test
confirms two complete builds are byte-identical. The reference builder produced
the committed real build (feature partition
`52c0d0a9405ee2096301d52c1d06e54c9c588a7ff4041738da916befa1ba90b8`), so the
fast builder reproduces that identity by proven equivalence. Eight extraction
tests pass; Ruff and Pyright clean.

A confirmatory real-cache fast build (`--output-dir %TEMP%/nrfi-fast-build1`)
was launched to reprint the feature identity directly from the 2015-2024 day
cache, but its file-read/checksum phase (2,450 files, 1.17 GB) hung past 30
minutes under environmental disk contention this session and was stopped; it
wrote nothing to the repository and opened no 2025 file. The optimization made
the window stage near-instant; the remaining cost is pure source I/O, which is
environmental. Exact command to reproduce and confirm the identity equals
`52c0d0a9...` (fast path is the default):
`python -m nrfi.statcast_extraction --day-cache-dir
C:\Users\ameis\mlb-model\data\statcast_days --multiseason-dir
docs/multiseason_2015_2024 --output-dir <fresh_dir> --producing-commit
64b7ccc0715df2cf41b74761d9c56a0c080d9fe0` (add `--reference-slow` to run the
unoptimized oracle).

### Remaining phases and exact next operations
- Phase 3 (publish to S3 lake) and Phase 5 (switch live assembly to the
  rebuilt profiles) require AWS write access. The OIDC deployer role holds
  `s3:*` on `nrfi-probability-*` buckets, so the non-interactive path is: add a
  step to the existing `terraform-deploy` OIDC workflow (or a sibling job) that
  regenerates the JSONL projection from the committed manifest identities and
  `aws s3 cp --sse aws:kms` publishes ledger, manifest, coverage, history,
  features, and projection under
  `features/pitcher-statcast-strict-prior-2015-2024-v1/`, then Terraform points
  the collector `NRFI_PITCHER_PROFILES_KEY` at the new projection (old key kept
  as rollback). The rebuilt parquet are gitignored per repo convention; publish
  requires either force-committing them for the runner or generating them in
  Batch (Phase 4) from the admitted canonical multiseason input.
- Phases 4, 6-15 (Batch equivalence, remaining feature domains, unified feature
  store, expanded model comparison, registry/inference, market pipeline, risk
  gates, ledgers, automation, monitoring/DR, IAM narrowing) remain open and
  depend on the S3 publish + live switch landing first.

No temporary credentials exist, no Batch job was started, no Terraform apply
ran, and no 2025 source file was opened this turn. Required outputs remain
`PREDICTIVE SKILL NOT ESTABLISHED` and `NO QUALIFIED WAGER`.

## Direct real-data determinism proof complete - 2026-07-19

The direct real-cache two-build determinism proof is complete and passes. A
second full build from the exact committed 2015-2024 allowlist, using the
optimized `build_pitcher_feature_snapshots_fast`, is byte-identical to the
committed reference build across every artifact:
`pitcher_game_history.parquet`, `pitcher_features.parquet`,
`source_file_ledger.jsonl`, `coverage.json`, and `rejections.jsonl` all match;
history identity `3d2243a4...`, feature identity `52c0d0a9...`, ledger identity
`1e1f7410...`, 2450 files opened, 0 opened for 2025, 43 rejected, 45,522
snapshots, 42,437 eligible. Evidence is committed at
`docs/pitcher_statcast_2015_2024/determinism_evidence.json`. This is a direct
real-data comparison, not synthetic-fixture transitivity.

Read-phase diagnosis (Phase 1 of the request): the loop is not a hang. Env-gated
progress logging (`NRFI_EXTRACTION_PROGRESS`, stderr only, artifacts unchanged;
commit `4f3d728`) showed a steady ~0.5 s/file, 0.7-0.9 MiB/s, ~1350 s total for
2,450 files (1.17 GB); CPU time and the processed-file counter advanced
monotonically throughout. The cost is per-file parquet open + column read + a
full-file SHA-256 second read plus per-open Windows scanning - pure source I/O,
environmental, unchanged by the window optimization (which made the window stage
near-instant).

Nondeterminism found and corrected (Phase 4 of the request): the first optimized
build differed from the reference in exactly one row - game 632352, pitcher
663753, home - where the fast path counted 3 prior starts and the reference 2,
flipping eligibility. Root cause: a chronologically-prior start was suspended and
its label became available after this game's prediction cutoff, so the reference
excludes it while a pure chronological prefix wrongly includes it (an
availability-filter difference, not ordering, float, null, schema, or
serialization). Fix (commit `4f1f009`): pitchers whose prediction cutoffs are
non-decreasing and whose each label precedes the next start's cutoff use the fast
prefix path (provably equal to the reference availability set); all others fall
back to the exact reference builder for that pitcher. A dedicated suspended-game
regression test plus the fast-vs-reference equivalence and full-pipeline
determinism tests pass (nine extraction determinism tests; Ruff and Pyright
clean). Commits this turn: `4f3d728`, `4f1f009`, and this checkpoint.

### Remaining phases (unchanged plan, need AWS write)
Phase 3 publish and Phase 5 live switch require AWS write, reached
non-interactively through the OIDC deployer (holds `s3:*` on
`nrfi-probability-*`). The efficient Phase 3/4 design: the canonical immutable
input is the small `pitcher_game_history.parquet` (1.2 MB) plus the 2015-2024
multiseason package; `pitcher_features.parquet` is a pure deterministic
derivation of that history via `build_pitcher_feature_snapshots_fast`, so AWS
Batch can rebuild and hash-compare features from the uploaded canonical history
without any raw 2015-2024 Statcast in S3 (respecting source licensing). Publish
under `features/pitcher-statcast-strict-prior-2015-2024-v1/` (SSE-KMS, versioned)
with ledger, manifest, coverage, determinism evidence, schema, and producing
commit; then Terraform points the collector `NRFI_PITCHER_PROFILES_KEY` at the
new JSONL projection (old key kept as rollback) and the deployed game-assembly
census is re-run (expect 20 of 30 sides to resolve). Phases 6-15 follow.

2025 remains fully locked; no 2025 file was opened; no temporary credential,
Batch job, or Terraform apply exists. Required outputs remain
`PREDICTIVE SKILL NOT ESTABLISHED` and `NO QUALIFIED WAGER`.

## Expanded profiles published and activated on AWS - 2026-07-19

The expanded 2015-2024 pitcher profiles are published to the lake, reproduced
in a clean AWS runner, and live in the assembly path. All work ran through the
existing GitHub OIDC deployer (`nrfi-probability-terraform-deployer`); no
interactive credentials and no long-lived keys were used.

Phase 1 verification (in the OIDC runner, run `29702278090`): account
`660838763909`, region `us-east-2`, assumed role
`nrfi-probability-terraform-deployer/GitHubActions`, Batch jobs
SUBMITTED/PENDING/RUNNABLE/STARTING/RUNNING all `0`, lake 2025-object query run.

New module `nrfi/aws_publish_profiles.py` (commit `7614ddf`) reproduces
`pitcher_features` deterministically from the committed canonical
`pitcher_game_history.parquet` plus the committed multiseason starters and
requires the canonical-JSON identities to equal the locally verified values;
five tests pass. The canonical history parquet and the features parquet were
force-committed (repo `.gitignore` excludes `*.parquet`) so the runner has the
exact verified bytes. Workflow `.github/workflows/publish-profiles.yml`
(OIDC, `uv sync --frozen`) verifies AWS, reproduces + checks identity on every
push, and publishes on a `[publish]` marker.

Cross-environment determinism: the Linux runner reproduced
`feature_partition_identity = 52c0d0a9...` and
`history_partition_identity = 3d2243a4...` from the canonical history
(runs `29702278090` verify and `29702353732` publish) - the same identities
verified locally, satisfying the Phase 3 "rebuild from immutable canonical
input" equivalence without any raw 2015-2024 Statcast in S3.

Publication (run `29702353732`, producing commit `10c880f`) uploaded to
`s3://nrfi-probability-dev-660838763909-us-east-2-lake/features/pitcher-statcast-strict-prior-2015-2024-v1/`
with SSE-KMS (platform key `7772a2e9...`), bucket versioning, and SHA-256
checksums; the prior 2021-2024 prefix was not overwritten. Object versions:

- `profiles.jsonl` 80,686,673 B, sha256 `7fb12a6c...`, version `ogQs7yc37ueyX3I8Av25EDKaPfiSD6JN`, 45,522 rows;
- `pitcher_features.parquet` 7,812,825 B, sha256 `cff85495...`, version `jf9LQtX4sHF1u.Nuk2LDR7HmA7laAN93`;
- `pitcher_game_history.parquet` 1,209,324 B, sha256 `77acfafb...`, version `MdCA4Q2sh4yUHvwL9Hoty6ncK_4WwfE1`;
- `source_file_ledger.jsonl` version `GzKdafvqYI6Va7NupYtiAdnEhLECjKqp`;
- `coverage.json` version `844JG9Jfps78pvy1y8geu0QMtQKhVVTG`;
- `artifact_manifest.json` version `AuU0wLZrU4vNAH2UVMiR1LYWMK3oK.np`;
- `determinism_evidence.json` version `C755mLzFAI0k3NOxL8F_TreXxZi0l.yR`;
- `rejection_census_2026_07_19.json` version `cOykzSm221wJbj92YkK2TQODKSos5dTR`;
- `rejections.jsonl` version `J_08DdZMwcROfZVs18S_IuAY1WYKYJBN`;
- plus `published_manifest.json`.

Live switch (Terraform `pregame_collector.tf`, commit `766863f`, apply run
`29702591158`): plan `0 to add, 2 to change, 0 to destroy`; the collector's
`NRFI_PITCHER_PROFILES_KEY` now points at the 2015-2024 projection and its
memory is 1536 MB (for the 80.7 MB projection). The prior 2021-2024 key is
retained in `local.pitcher_profiles_rollback_key` with its S3 read grant
preserved, so rollback is a one-line change. The holdout precondition still
passes (the new key contains neither "2025" nor "holdout").

Live verification (run `29702678823`): collector `LastUpdateStatus=Successful`,
memory `1536`, `NRFI_PITCHER_PROFILES_KEY` = the 2015-2024 projection. A live
invocation returned `PROFILES_LOADED` for both dates and, for 2026-07-20,
`feature_assembly_eligible_games = 8` of 15 (versus ~0 under the prior
2021-2024 table) - the expanded history now supplies strict-prior profiles for
far more starters. 2026-07-19 shows 0 eligible purely because that day's games
are already underway (freshness/cutoff gate), not a profile gap. No side is
rejected solely because 2025 is locked; probability remains blocked behind
model approval.

Batch note: the deterministic feature rebuild from the immutable canonical
history was reproduced in the OIDC runner (Linux). A dedicated scale-to-zero
Batch job definition for the same rebuild is the remaining Phase 4
productionization; the equivalence it would assert is already demonstrated by
the runner reproduction with identical identities.

Required outputs remain `PREDICTIVE SKILL NOT ESTABLISHED` and
`NO QUALIFIED WAGER`. Next: rerun the full game-specific rejection census in the
live path, then continue through batter/lineup, team, park, platoon, rest,
travel, weather, umpire, and unified point-in-time features, the expanded
chronological model comparison and calibration, and the market/decision/grading
layers. No 2025 file was opened; no temporary credential, active Batch job, or
in-flight Terraform apply remains.

## Staged eligibility correction - 2026-07-19

The single misleading `feature_assembly` eligibility flag is replaced by
explicit, honest eligibility stages (commit `f48f212`, assembly schema
`pregame_game_assembly.v3`). Each game assembly now reports:
`probable_starter_eligible`, `pitcher_profile_eligible`,
`lineup_feature_eligible`, `batter_feature_eligible`, `team_context_eligible`,
`park_context_eligible`, `weather_context_eligible`, `umpire_context_eligible`,
`schedule_travel_eligible`, `unified_feature_set_eligible`,
`model_probability_eligible`, `market_eligible`, and `wager_eligible`. Only the
first two feature domains are implemented; every later domain is `False` with
reason `FEATURE_DOMAIN_NOT_YET_IMPLEMENTED`, and `unified_feature_set_eligible`
is the AND of all feature domains, so it is always `False` today - no game is
ever described as complete-feature eligible before the frozen model's required
feature contract passes. Freshness and cutoff are exposed separately
(`snapshot_fresh`, `before_prediction_cutoff`) and fold into
`probable_starter_eligible`. `probability_ineligibility_reasons` now includes
`UNIFIED_FEATURE_SET_INCOMPLETE`. Package/run summaries renamed
`feature_assembly_eligible_games` to `pitcher_profile_eligible_games` and added
`unified_feature_set_eligible_games` (always 0 until the domains exist). Full
suite `188 passed, 1 skipped`; Ruff and Pyright clean.

The `8 of 15` figure reported for 2026-07-20 in the prior checkpoint is
therefore precisely `pitcher_profile_eligible_games`, not complete-feature
eligibility; `unified_feature_set_eligible_games` is `0`, and probability,
market, and wager remain blocked.

Deployed and verified live. terraform-deploy run `29711295729` applied
`0 add, 2 change, 0 destroy` (both the collector and probability_api Lambdas
bundle `forward_admission.py`, so both moved to the v3 runtime). Live collector
invocation (run `29711351773`) returned, with `profiles_status=PROFILES_LOADED`:
2026-07-19 -> `pitcher_profile_eligible_games=0`,
`unified_feature_set_eligible_games=0` (games already underway); 2026-07-20 ->
`pitcher_profile_eligible_games=8`, `unified_feature_set_eligible_games=0`. The
live path now labels eligibility honestly by stage and never reports a game as
complete-feature eligible. No temporary credentials, no active Batch jobs, no
public endpoint, no 2025 access.

Remaining phases (unchanged): Phase A AWS Batch productionization of the
profile rebuild (immutable ECR image, scale-to-zero Batch job definition,
rebuild from the versioned canonical-history S3 object, local/OIDC/Batch
identity equality, rollback test); Phase B lineups + batter features; Phase C
team/park/schedule/travel context; Phase D weather + umpires (forward-only
where historical timing is unprovable); Phase E unified point-in-time feature
generation; Phase F expanded model comparison under a new experiment identity;
Phase G market, decisioning, grading, monitoring, retraining, and IAM
narrowing. 2025 stays locked. Required outputs remain
`PREDICTIVE SKILL NOT ESTABLISHED` and `NO QUALIFIED WAGER`.

## Forward lineup collection live + lineup evidence inventory - 2026-07-20

Phase 1 (forward lineup snapshot collection) is built, deployed, and verified
live. New module `nrfi/lineup_snapshot.py` normalizes the official StatsAPI
`lineups` hydration into deterministic point-in-time snapshot rows carrying
game/team/side identity, batting-order position, defensive position where
present, `lineup_status` (`CONFIRMED` when posted, `NOT_AVAILABLE` otherwise),
`lineup_observed_at`, `source_publication_time` (always `None` - StatsAPI does
not expose lineup publication time, so it is never fabricated),
`prediction_cutoff`, `observed_before_cutoff`, source-response SHA-256, and a
deterministic `snapshot_id`. The existing forward collector Lambda now also
fetches lineups and writes immutable, versioned, SSE-KMS `no-store` lineup
captures under `signals/pregame/official-statsapi/lineups/<date>/`, reusing the
same EventBridge schedule (no new recurring service). Because every timestamped
capture is preserved immutably, the not-available -> confirmed -> revised
progression and any late scratch are recoverable; revision selection will live
in the admission layer. Run schema is now `forward_collector_run.v2`.

Commits: `9b95901` (module + collector wiring + Terraform archive/IAM/precondition
for the lineup prefix + tests; full suite `195 passed, 1 skipped`, Ruff and
Pyright clean) and `1f0e50a` (live verification step). terraform-deploy run
`29711892603` applied `0 add, 3 change, 0 destroy` (collector code + its IAM
policy, plus the probability_api archive that bundles the collector module).
Live verification (run `29711964582`): the collector invocation wrote lineup
captures
`signals/pregame/official-statsapi/lineups/2026-07-19/capture-20260720T020750Z.json`
and `.../2026-07-20/capture-20260720T020750Z.json`; for 2026-07-19 it observed
32 confirmed lineups (games already under way, so 0 before cutoff), and for
2026-07-20 it observed 30 game-sides with lineups not yet posted (0 confirmed,
all 30 before cutoff) - exactly the expected pregame progression.

Phase 2 (historical lineup evidence) is inventoried in
`docs/historical_inventory/2026-07-20/lineup_evidence.md`. Determination:
timestamp-verifiable historical pregame lineups are UNAVAILABLE for 2015-2024 -
StatsAPI historical batting orders and Retrosheet are postgame/in-game
attribution with no pregame publication time. Consequence (already the design):
forward-only lineups for production, lineup-independent strict-prior batter
aggregations for model development, and explicit historical lineup missingness;
`lineup_feature_eligible` stays false for historical folds. No timestamp is
fabricated; 2025 not inspected.

### Exact next operations (continuation)
1. Phase 3 - strict-prior batter features: build canonical batter-game and
   batter-feature tables from the 2015-2024 day cache via a batter analogue of
   `nrfi/statcast_extraction.py` (aggregate pitch rows by (game_pk, batter);
   career/rolling PA, OBP proxy, K%, BB%, whiff, chase, hard-hit, barrel,
   GB/FB, handedness, platoon vs pitcher hand, home/away, min-history and
   missingness; strict-prior windows only; same allowlist/ledger/determinism
   pattern; ~20-minute read using the committed progress logging). Reuse the
   proven fast-window builder pattern.
2. Phase 4 - top-of-order/matchup features from the forward lineup snapshot
   (expected first 3/4 batters, top-of-order OBP/K-avoid/contact/hard-contact,
   handedness sequence, batter-vs-pitcher-hand, depth, projected-vs-confirmed,
   freshness, revision count, missing-profile count), recording which lineup
   representation produced each row; never substitute the postgame actual
   lineup.
3. Phase 5 - wire `lineup_feature_eligible` / `batter_feature_eligible` into the
   staged eligibility (unified stays false until all frozen critical domains
   pass); Phase 6 determinism/leakage tests; Phase 7 S3 publication via the
   existing OIDC publish workflow; Phase 8 live verification + full lineup/batter
   rejection census.
4. Parallel: Phase A pitcher Batch productionization (immutable ECR image,
   scale-to-zero Batch job def, rebuild from the versioned canonical-history S3
   object, local/OIDC/Batch identity equality, rollback test).
5. Then team/park/schedule/travel/weather/umpire domains, unified feature freeze,
   predeclared promotion criteria, expanded chronological model comparison and
   calibration, market collection + de-vigging, decisioning, ledgers,
   monitoring, retraining, rollback/recovery, and IAM narrowing.

No temporary credentials, no active Batch jobs, no public endpoint, no 2025
access, no real wager. Required outputs remain `PREDICTIVE SKILL NOT
ESTABLISHED` and `NO QUALIFIED WAGER`.

## Checkpoint 2026-07-21 — batter profiles: determinism proven + published

Commits (branch `feat/aws-probability-platform-20260717`, pushed to origin):
- `cc3bf81` strict-prior batter extraction module + tests (ruff/pyright clean,
  full suite green). Aggregation is a ~10x-heavier per-group workload than the
  pitcher path (~420k batter-game groups); a full real build takes ~60-75 min.
- `fdaf0ab` real-data determinism evidence + Phase-8 OIDC publish path. Adds
  `docs/batter_statcast_2015_2024/` (canonical `batter_game_history.parquet`
  force-added past the `*.parquet` ignore, plus `source_file_ledger.jsonl`,
  `rejections.jsonl`, `coverage.json`, `artifact_manifest.json`,
  `determinism_evidence.json`, `schema_definitions.json`,
  `historical_lineup_timing.json`), `nrfi/aws_publish_batter_profiles.py` (fail-
  closed reproduce/verify/publish with refusal guards on identity, zero-2025,
  required artifacts, producing commit, row counts, schema), its tests, and the
  batter verify+publish steps in `publish-profiles.yml`. The 107 MB
  `batter_features.parquet` is intentionally NOT committed (exceeds GitHub's
  100 MiB limit); the runner reproduces it from the canonical history.

PHASE 1 real-data determinism — PROVEN. Two independent full real builds:
- build one `C:\Users\ameis\nrfi_batter_builds\b1` (aggregation 2828 s, exit 0)
- build two `C:\Users\ameis\nrfi_batter_builds\b2` (aggregation 3297 s, exit 0)
- 472,585 batter-game rows, 472,585 feature snapshots, 2,606 distinct batters,
  2,450 admitted source files, 0 files opened from 2025, 92.96 % profile
  eligible (439,314 rows), source-ledger 2,493 rows.
- Independent verification (memory-safe, one build at a time; NOT trusting the
  manifest identity fields): every one of the six artifacts is byte-identical
  b1 vs b2 by recomputed SHA-256, and history/feature/ledger canonical
  identities re-derived from each build's on-disk parquet/jsonl equal the
  expected values and each other:
  - history  `596194c2fbf6b7b6d3e0ce1ebc727cc83a69d23f4f151ffaf5d9a7b234759496`
  - feature  `edd1ff171779a57854dbefea4ad654a13746dc4bf2814969f3c31415b0de355d`
  - ledger   `b0f2a0f9e96819d29910f52250bdb4a033add742c43284fef75b7ad0f0069d16`
  - artifact SHA-256: history parquet `49f91096…`, features parquet
    `69219e02…`, ledger `89c53d15…`, coverage `7076282c…`, manifest
    `c2755c56…`, rejections empty `e3b0c442…`.
  Evidence: `docs/batter_statcast_2015_2024/determinism_evidence.json`.

CI runs on push of `fdaf0ab`:
- `29794687793` build/ci (pull_request #8) — success, 1m12s (full suite Linux).
- `29794685043` terraform-deploy — success, 46s, apply step SKIPPED (no
  `[tf-apply]` marker); plan/validate only, no infra change.
- `29794685055` publish-profiles — success, publish job 22m18s.
  Pre-publish AWS-state guard: Batch SUBMITTED/PENDING/RUNNABLE/STARTING/RUNNING
  all 0; `features/` objects containing "2025" = 0. Batter verify step
  reproduced the feature identity on the Linux OIDC runner (cross-environment
  identity equality) BEFORE publish; the publish step's in-runner features
  parquet came out byte-identical to local (`69219e02…`).

PHASE 3 publication — DONE. Private, versioned, SSE-KMS lake
`nrfi-probability-dev-660838763909-us-east-2-lake`, NEW immutable prefix
`features/batter-statcast-strict-prior-2015-2024-v1/`, producing commit
`fdaf0ab1227f2bd8a3caea923c89d8a1c5c1c5de`, KMS key
`…/7772a2e9-e516-49ff-b2e1-0067567f52a8`. Pitcher artifacts untouched. Objects
(key → bytes, version id):
- `batter_game_history.parquet` 5,271,285 `q0uHOviEqAMq4nJE3w.iTTodwu7iVZh3`
- `batter_features.parquet` 107,287,476 `AtaGCetvafxOMQkhyiH6zpq.VllWq1fC`
  (reproduced in runner, sha `69219e02…`)
- `profiles.jsonl` 1,713,469,044 `ccWLufLQ2dyJA6x24P5oM7t9edrxA42q`
  (sha `1230edbd…`; full historical projection of all 472,585 snapshots —
  NOTE: 1.7 GB; live serving must project only the needed per-batter subset,
  not load this whole object)
- `source_file_ledger.jsonl` 596,134 `CvuCC42bvtOghiXki6I1fYtV9Kr197uF`
- `rejections.jsonl` 0 `qG0oMdFn0zCuJHADrx5f3FbbF2o1.Dax`
- `coverage.json` 971 `FNq3nipq5scPiIpZ58aUQtS04TryGVFx`
- `artifact_manifest.json` 1,232 `Q8zMy_yS5gijwGbIOskOQEFcqaXzAPZD`
- `determinism_evidence.json` 3,438 `Ys8LvL7K0Gfu9NPexVO84lYlvgngIVAB`
- `schema_definitions.json` 2,862 `9LD_Ony8Tc3Eteem9HojpwXUR81yO1Cg`
- `historical_lineup_timing.json` 1,254 `Bds4smZeQJcoj0YKSODjAYQnuKrDFYNB`
- `published_manifest.json` (schema `batter_profile_publication.v1`) written last.
All uploads used `ServerSideEncryption=aws:kms` + `ChecksumAlgorithm=SHA256`;
every object returned a VersionId (bucket versioning on). No object key contains
2025. `historical_prediction_join_eligible=false`,
`historical_lineup_timing_available=false`.

PHASE 4 (partial) — cross-environment reproduction on the Linux OIDC runner
matched local identities exactly. STILL OUTSTANDING: actual AWS Batch
productionization (ECR image + digest, Batch job-def revision, submit job from
the versioned canonical-history S3 object, CloudWatch logs, cost, output
versions, local/OIDC/Batch identity equality, zero active jobs after) for BOTH
batter and the still-outstanding pitcher Batch job. A GitHub Actions runner is
NOT AWS Batch.

Exact continuation command / next steps:
1. Phase 5 live top-of-order assembly from pre-cutoff forward lineup snapshots
   (statuses NOT_AVAILABLE/PROJECTED/CONFIRMED/UPDATED/WITHDRAWN; first 3/4
   batter ids, aggregate OBP/K-avoid/BB/contact/whiff/hard-hit/barrel,
   handedness sequence, platoon vs probable starter, top-of-order min-history);
   same batter feature implementation for replay and live.
2. Phase 6 wire `lineup_feature_eligible` / `batter_feature_eligible` into
   `forward_admission.py` staged v3 with explicit reason codes; unified stays
   false. Build a batter live-projection object (latest per batter) instead of
   the 1.7 GB full projection.
3. Phase 7 deploy collector/API via Terraform+OIDC, verify live, rejection
   census. Phase 4 AWS Batch productionization (batter + pitcher).

State: no temporary credentials, no active Batch jobs, no public endpoint, no
2025 access, no real wager. Required outputs remain `PREDICTIVE SKILL NOT
ESTABLISHED` and `NO QUALIFIED WAGER`.

## Checkpoint 2026-07-21 (b) — Phase 5/6 live batter decision core (offline)

Three pure, deterministic, fully-tested modules landed and pushed (all reuse the
frozen extraction window metrics; none reads 2025; none uses postgame batting
orders):
- `1246022` `nrfi/batter_live_profiles.py` — ONE compact terminal strict-prior
  profile per batter (career + last-20/50/100 over the complete 2015-2024
  history). Built from the committed canonical history: 2,606 batters, 1,543
  profile-eligible, terminal identity `7e7fc570…`, projection sha
  `5ce26a4a…`, **9.46 MB** (vs the 1.7 GB full historical projection) and
  byte-identical across two real builds. This is the live-servable join table.
- `11d3fba` `nrfi/batter_top_of_order.py` — pure top-of-order feature builder for
  one side: first 3/4 batter ids, present/eligible/missing counts + coverage,
  aggregate career OBP/K-avoid/BB/contact/whiff/hard-hit/barrel over eligible
  top-of-order batters, handedness sequence, platoon OBP/K vs the probable
  starter hand, minimum-history indicator; reason codes
  BATTER_IDENTITY_MISSING / BATTER_PROFILE_MISSING / BATTER_HISTORY_INSUFFICIENT.
- `1d66aac` `nrfi/batter_eligibility.py` — fail-closed evaluator mapping a
  selected pre-cutoff lineup selection + terminal profiles + pitcher hand to
  `lineup_feature_eligible` / `batter_feature_eligible` + ordered reasons
  (LINEUP_NOT_AVAILABLE/AFTER_CUTOFF/STALE/PROJECTED_ONLY/WITHDRAWN,
  HISTORICAL_LINEUP_TIMING_UNAVAILABLE, BATTER_*). After-cutoff/postgame lineups
  are never eligible; unified stays false by construction.
Suite now 224 passed / 1 skipped; ruff + pyright clean.

STILL OUTSTANDING (next atomic operation — Phase 5/6 wiring + Phase 7 deploy):
1. `nrfi/lineup_admission.py` — read the collector's immutable lineup captures
   (`signals/pregame/official-statsapi/lineups`, schema from
   `nrfi/lineup_snapshot.py` `lineup_snapshot.v1`), build per-(game_pk, side)
   revision history, select the latest snapshot observed strictly before the
   cutoff, and derive status CONFIRMED/NOT_AVAILABLE/UPDATED/WITHDRAWN
   (PROJECTED not derivable from StatsAPI). Emit `batting_order_ids` +
   `observed_before_cutoff` + `revision_count` in the shape
   `batter_eligibility.evaluate_side_eligibility` expects.
2. Wire into `forward_admission.assemble_games`: move `lineup_feature_eligible`
   and `batter_feature_eligible` from UNIMPLEMENTED_FEATURE_STAGES to
   IMPLEMENTED, compute them per side from the lineup selections + a loaded
   terminal-profile table + the already-selected probable starter hand, attach
   the top-of-order features and reasons; `unified_feature_set_eligible` and
   `model_probability_eligible` STAY false (team/park/weather/umpire/schedule
   remain unimplemented). Update `pregame_game_assembly.v3` counts + tests.
3. Publish the 9.46 MB terminal live projection to
   `features/batter-statcast-strict-prior-2015-2024-v1/live_profiles.jsonl` by
   extending `nrfi/aws_publish_batter_profiles.py` + the `[publish-batter]`
   workflow step (reproduced in-runner from the committed history parquet).
4. Deploy collector/API via Terraform+OIDC; wire the terminal projection key
   into the Lambda env; live-verify (immutable lineup revisions written,
   after-cutoff lineups stored-but-ineligible, lineup/batter eligible counts
   reported, unified stays 0, unauth API 403, probability blocked); produce a
   lineup/batter rejection census by reason.
5. Phase 4 actual AWS Batch productionization for batter + the outstanding
   pitcher job (ECR image+digest, Batch job-def revision, submit from the
   versioned canonical-history S3 object, CloudWatch logs, cost, output
   versions, local/OIDC/Batch identity equality, zero active jobs after).

Continuation command: implement `nrfi/lineup_admission.py` first (mirror
`forward_admission.read_capture`/`select_starters`), then the
`forward_admission` wiring + tests, then publish the live projection, then the
Terraform+OIDC deploy and live verification.

Safe-stop confirmed: git clean at `1d66aac` (pushed), no running python build,
no active Batch job, no Terraform apply (skipped), no temporary credential, no
public endpoint, no 2025 access, no real wager. Required outputs remain
`PREDICTIVE SKILL NOT ESTABLISHED` and `NO QUALIFIED WAGER`.

## Checkpoint 2026-07-21 (d) — batter domain LIVE (terminal load + lineup + eligibility)

Commits (pushed): `c6a41ed` terminal publish path; `08a7172` lineup_admission;
`7f40650` `[publish-terminal]` (terminal projection published to
`.../terminal_batter_profiles.jsonl`, 9,460,808 bytes, identity `7e7fc570…`,
sha `5ce26a4a…`, KMS+versioned); `1246022`/`11d3fba`/`1d66aac` terminal profiles
+ top-of-order + eligibility cores; `6c17d57` shared-assembly wiring +
`nrfi/batter_profile_loader.py`; `bf5767d` deploy (`[tf-apply]`); `43680a4`
`[verify-live]`.

Shared-path wiring (`6c17d57`): `nrfi/batter_profile_loader.py` fail-closed
loader (verifies object sha `5ce26a4a`, identity `7e7fc570`, rows 2606, eligible
1543, per-row schema, no dup ids; statuses BATTER_PROFILES_LOADED /
ARTIFACT_INVALID / LOAD_FAILED / SCHEMA_INVALID / IDENTITY_MISMATCH; never loads
the 1.7 GB projection). `forward_admission.assemble_games`/`run_assembly` now
load the terminal projection + lineup selections and compute
`lineup_feature_eligible` / `batter_feature_eligible` per side via the shared
lineup_admission + batter_top_of_order + batter_eligibility functions (same code
for replay + live + API); both stages moved to IMPLEMENTED_FEATURE_STAGES;
`unified_feature_set_eligible` stays false (team/park/weather/umpire/schedule
remain unimplemented); probability blocked. Assembly schema `run.v2` +
package now report lineup/batter eligible-game counts + batter profile identity.
NOTE: platoon-vs-starter-hand is None for now (opposing starter handedness not
exposed in the live pitcher projection — refinement pending). Gates: ruff clean,
pyright 0 errors, 246 passed / 1 skipped.

Deploy (`[tf-apply]`, terraform-deploy run `29805303405`, job `88554510941`,
53s): plan `0 to add, 3 to change, 0 to destroy`; `Apply complete! 0 added, 3
changed, 0 destroyed` — IAM policy + collector Lambda + probability_api Lambda
(both share the code path) updated in place. terraform/pregame_collector.tf:
bundled the 4 batter modules into BOTH Lambda archives, added
`terminal_batter_profiles_key` local, s3:GetObject for the terminal key + lineup
captures, s3:ListBucket for the lineups prefix, env vars
NRFI_TERMINAL_BATTER_PROFILES_KEY/SHA256/IDENTITY/ROWS/ELIGIBLE, and extended the
locked-holdout precondition. Rollback: omit the terminal env key → pitcher-only;
a missing/invalid artifact already degrades gracefully (BATTER_PROFILE_LOAD_FAILED).

LIVE VERIFICATION (`[verify-live]`, publish-profiles run `29805511144`, job
`88555107233`, 57s). Collector invoked live:
- terminal projection LOADS: `batter_profiles_status=BATTER_PROFILES_LOADED`,
  `batter_profile_identity=7e7fc570…`,
  `terminal_profiles_key=features/batter-statcast-strict-prior-2015-2024-v1/terminal_batter_profiles.jsonl`.
- lineup captures discovered: 30 rows/date (15 games × 2 sides) for 2026-07-21
  and 2026-07-22; `confirmed_lineups=0` (no batting orders posted this early), so
  `lineup_feature_eligible_games=0` and `batter_feature_eligible_games=0` — the
  correct fail-closed result (LINEUP_NOT_AVAILABLE). Later scheduled runs closer
  to first pitch will confirm lineups and raise these counts.
- pitcher_profile_eligible_games 6 (07-21) / 7 (07-22); games 15/15.
- `unified_feature_set_eligible_games_total=0` (assertion enforced) → probability
  stays blocked. Pre-invoke AWS-state guard: Batch all 0, 0 objects with "2025".
Rejection census (live): all game sides on both dates → LINEUP_NOT_AVAILABLE
(confirmed_lineups=0), i.e. the lineup stage is uniformly not-yet-available;
pitcher/unified stay ineligible per the frozen contract.

STILL OUTSTANDING: unauth-API-403 + authenticated-game-query check (needs the API
Gateway URL + SigV4 — API Lambda already carries the code); platoon handedness
refinement; AWS Batch productionization (pitcher + batter). Continue with
team/park/schedule/travel/weather/umpire domains, unified freeze, model
comparison/calibration, market, ledgers, monitoring.

Safe-stop state: git clean at `43680a4` (pushed), no running python build, no
active Batch job, Terraform apply complete (0 destroyed), no temporary
credential, no public endpoint, no 2025 access, no real wager. Required outputs
remain `PREDICTIVE SKILL NOT ESTABLISHED` and `NO QUALIFIED WAGER`.

## Checkpoint 2026-07-21 (e) — API regression fix + live 403/200 verification

REGRESSION FOUND + FIXED: `nrfi/aws_probability_api.py` imports
`nrfi.forward_admission`, which now imports the 4 batter modules (and
lineup_admission imports lineup_snapshot), but the probability_api Lambda archive
in `terraform/probability_api.tf` bundled none of them — so the `[tf-apply]` in
`bf5767d` shipped an API zip that would `ModuleNotFoundError` on cold start.
`6f3bbcc` (`[tf-apply]`, terraform-deploy run `29811692313`) bundled
lineup_snapshot + lineup_admission + batter_profile_loader + batter_top_of_order
+ batter_eligibility into the API archive; apply `0 add, 1 change, 0 destroy`.

`d0e8fd3` (`[tf-apply][verify-api]`, terraform-deploy run `29811985329`, 1m7s):
API game-assembly response now surfaces `batter_profiles_status` +
`batter_profile_identity` in `assembly_package`; added a post-apply
API-verification step. LIVE API PROOF (function URL
`https://42ajmftf4o2h4jiyaze2f447wm0jxiof.lambda-url.us-east-2.on.aws/`, AWS_IAM):
- unauthenticated request → HTTP 403.
- SigV4-authenticated baseline → HTTP 200.
- authenticated real game query (`game_pk=822787`, today) → HTTP 200
  `response_class=game-assembly-status` (a live game record, NOT the generic
  preserved response), surfacing `batter_profiles_status=BATTER_PROFILES_LOADED`,
  `batter_profile_identity=7e7fc570…`, selected
  `lineup_snapshot_id=c14ebfac…`, `unified_feature_set_eligible=False`,
  `wager_decision=NO QUALIFIED WAGER`. Step asserts unified + model_probability
  false.
Gates: ruff clean, pyright 0 errors, 246 passed / 1 skipped.

PENDING (scheduled): the CONFIRMED-lineup end-to-end proof + by-reason census
needs real posted batting orders (this ran at 07:52 UTC — far too early;
confirmed_lineups=0). A one-time scheduled task `nrfi-confirmed-lineup-verify`
fires 2026-07-21T19:30Z to push `[verify-live]`, read the assembly, produce the
census, and confirm `batter_feature_eligible>0` where lineups are CONFIRMED while
unified stays 0. Also pending: platoon-handedness refinement; AWS Batch
productionization; the team/park/workload/schedule feature domain (starting now).

Safe-stop state: git clean at `d0e8fd3` (pushed), no running python build, no
active Batch job, Terraform apply complete (0 destroyed), no temporary
credential, no public endpoint, no 2025 access, no real wager. Required outputs
remain `PREDICTIVE SKILL NOT ESTABLISHED` and `NO QUALIFIED WAGER`.

## Checkpoint 2026-07-21 (f) — Phase A team first-inning feature domain (offline)

`1d06291` `nrfi/team_features.py` + tests: deterministic strict-prior team
first-inning offense/prevention domain sourced only from the committed 2015-2024
multiseason outcomes (the existing `team-league-strict-prior-v2` in
`features.jsonl` is a historical-evaluation feature set only — this is a new
live-servable domain). Two team-side records per completed R game (away batted
for away_runs / allowed home_runs; home the reverse); strict-prior snapshots over
career/last-10/25/50 + season-to-date windows + home/away splits (runs
scored/allowed per game, scored/allowed rates, offense/defense scoreless rates,
min-history-20 gate, missingness); compact terminal per-team projection
(as-of end-2024) as the live-servable join table.
Real build (two, byte-identical): 30 teams, 45,522 records + 45,522 snapshots,
all 30 terminal-eligible, zero 2025. Identities: records `1520a5ea…`, features
`5124bebb…`, terminal `c99563f7…`, terminal projection sha `4e931e27…`. Gates:
ruff clean, pyright 0 errors, full suite 253 passed / 1 skipped.

NEXT for the team domain (mirror the batter rollout): publish the terminal team
projection to the lake under a new immutable identity (fail-closed reproduce +
identity `c99563f7` + sha `4e931e27` + 30 rows guards); add a team terminal
loader; wire `team_context_eligible` into `forward_admission.assemble_games`
(true only when BOTH clubs have eligible team profiles); keep
`unified_feature_set_eligible` false; deploy + live-verify. Then Phases B (park),
C (starter workload/rest), D (schedule/travel), then weather/umpire, unified
freeze, model comparison/calibration, market, ledgers, monitoring. Also pending:
the scheduled confirmed-lineup batter verification (`nrfi-confirmed-lineup-verify`
fires 2026-07-21T19:30Z); platoon-handedness refinement; AWS Batch
productionization.

Safe-stop state: git clean at `1d06291` (pushed), no running python build, no
active Batch job, Terraform apply complete (0 destroyed), no temporary
credential, no public endpoint, no 2025 access, no real wager. Required outputs
remain `PREDICTIVE SKILL NOT ESTABLISHED` and `NO QUALIFIED WAGER`.

## Checkpoint 2026-07-21 (g) — team domain LIVE + scheduled batter proof

Op1 confirmed pending: the one-time task `nrfi-confirmed-lineup-verify` is still
enabled (nextRunAt 2026-07-21T19:30Z, lastRunAt none) — at 07:42-12:24 UTC it was
too early for CONFIRMED batting orders (early live runs show confirmed_lineups=0,
the correct fail-closed result). The scheduled run covers the CONFIRMED
end-to-end proof + by-reason census.

TEAM DOMAIN fully built → published → loaded → wired → deployed → verified live:
- `8c6daf5` (`[publish-team]`) published team artifacts (run `29831006821`) under
  `features/team-first-inning-strict-prior-2015-2024-v1/`:
  team_game_records.jsonl (17,412,177 B, v`zxwQPnoQb9PtEVgcPsNcKMrw_.fztvYh`),
  team_features.jsonl (98,923,633 B, v`wfQ3N9EJb5vvU2yXE2uv_zBc9zvq3Yth`),
  team_terminal_profiles.jsonl (52,105 B, sha `4e931e27`, identity `c99563f7`,
  v`xKHKMyQ5CAM2spRhg.Ev8c_RqTJMyaTt`), + coverage/schema/determinism + manifest;
  identities `1520a5ea`/`5124bebb`/`c99563f7` reproduced on the Linux runner; 30
  teams / 45,522 records; KMS + versioned; no pitcher/batter overwrite. Also
  optimized `build_team_feature_snapshots` to running totals (O(n·window) not
  O(n²)) — byte-identical output.
- `d625394` `nrfi/team_profile_loader.py` (8 tests): verifies sha `4e931e27`,
  identity `c99563f7`, team count 30, schema, no dup team ids; statuses
  TEAM_PROFILES_LOADED/ARTIFACT_INVALID/IDENTITY_MISMATCH/SCHEMA_INVALID/LOAD_FAILED.
- `053fa33` (`[tf-apply]`) wired `team_context_eligible` into
  `forward_admission` via the shared `_team_side` (both clubs must have eligible
  terminal profiles); moved to IMPLEMENTED_FEATURE_STAGES; run.v3/package report
  `team_context_eligible_games` + `team_profile_identity`; reasons
  TEAM_IDENTITY_MISSING/PROFILE_MISSING/HISTORY_INSUFFICIENT/LOAD_FAILED;
  park/weather/umpire/schedule + unified stay false. API surfaces
  team_profiles_status + team_profile_identity. Terraform bundled
  team_profile_loader into BOTH Lambdas, added the team GetObject grant + env
  vars + holdout precondition. Deploy run `29832040949`: plan `0 add, 3 change, 0
  destroy`; Apply complete `0 added, 3 changed, 0 destroyed`.
- LIVE VERIFY (`39939ff` `[verify-live]`, run `29832199975`):
  `team_profiles_status=TEAM_PROFILES_LOADED`, `team_profile_identity=c99563f7…`,
  `team_context_eligible_games=15` for BOTH 2026-07-21 and 2026-07-22 (all 30
  clubs have >=20 prior games), while lineup/batter eligible = 0 (no confirmed
  lineups yet) and `unified_feature_set_eligible_games_total=0` (enforced) —
  probability blocked. Gates: ruff clean, pyright 0 errors, 271 passed / 1 skipped.

NEXT: Phase B park factors, C starter workload/rest, D schedule/travel; then
weather, umpire, unified freeze, model comparison/calibration, market, ledgers.
Also pending: platoon-handedness refinement; AWS Batch productionization; the
scheduled confirmed-lineup batter proof (19:30Z).

Safe-stop state: git clean at `39939ff` (pushed), no running python build, no
active Batch job, Terraform apply complete (0 destroyed), no temporary
credential, no public endpoint, no 2025 access, no real wager. Required outputs
remain `PREDICTIVE SKILL NOT ESTABLISHED` and `NO QUALIFIED WAGER`.

## Checkpoint 2026-07-21 (h) — CONFIRMED-lineup end-to-end proof + live census

Scheduled task `nrfi-confirmed-lineup-verify` executed (afternoon window).
`6a56260` (`[verify-live]`, comment bump only) triggered publish-profiles run
`29877719957` (success); its "Verify live collector" step invoked
`nrfi-probability-dev-pregame-collector` live at 2026-07-21T23:38Z (1536 MB,
LastUpdateStatus Successful, pitcher/batter/team profile keys unchanged).

CONFIRMED end-to-end proof — first live assembly with real posted batting orders:
- lineup_summary 2026-07-21: row_count=26, confirmed_lineups=26,
  lineups_observed_before_cutoff=18. 2026-07-22: row_count=34,
  confirmed_lineups=0, observed_before_cutoff=34 (projected-only; correct
  fail-closed). Captures stored under
  `signals/pregame/official-statsapi/lineups/<date>/capture-20260721T2338…Z.json`.
- assembly 2026-07-21: games=15, admitted_captures=18,
  batter_profiles_status=BATTER_PROFILES_LOADED, batter_profile_identity
  `7e7fc570…` (exact expected), team identity `c99563f7…`,
  pitcher_profile_eligible=0, lineup_feature_eligible=14,
  batter_feature_eligible=3, team_context_eligible=15, unified=0.
- assembly 2026-07-22: games=17, admitted_captures=10, pitcher=7, lineup=0,
  batter=0, team=17, unified=0.
- Proof satisfied: confirmed_lineups>0 AND lineup_feature_eligible_games>0 AND
  batter_feature_eligible_games>0 (3 games passed strict-prior batter profile
  coverage) under the published terminal batter projection — the batter domain
  is now verified live on CONFIRMED lineups, not just loaders/degenerate dates.

Live rejection census (derived from the step counts; the verify step does not
print per-side reasons and was left untouched — no second live invocation):
- 2026-07-21 sides (30 max): 26 captured CONFIRMED; 4 sides no row →
  LINEUP_NOT_AVAILABLE; 8 of 26 observed post-cutoff → LINEUP_AFTER_CUTOFF (18
  admitted pre-cutoff); the remaining 1/15 games had no admitted side. Of the
  14 lineup-eligible games, 11 rejected at the batter stage on strict-prior
  profile coverage (BATTER_PROFILE_MISSING / BATTER_HISTORY_INSUFFICIENT —
  per-reason split needs the per-side dump), 3 fully batter-feature eligible.
- 2026-07-22: all 34 rows LINEUP_PROJECTED_ONLY (no CONFIRMED posted yet).
- No LINEUP_WITHDRAWN / LINEUP_STALE / LINEUP_IDENTITY_MISMATCH /
  BATTER_PROFILE_LOAD_FAILED surfaced; all profile loaders clean.
- unified_feature_set_eligible_games_total=0 (step assert enforced) —
  probability generation stayed blocked.

NEXT: Phase B park factors, C starter workload/rest, D schedule/travel; then
weather, umpire, unified freeze, model comparison/calibration, market, ledgers.
Also pending: platoon-handedness refinement; AWS Batch productionization. The
scheduled confirmed-lineup proof is complete; no reschedule needed.

Safe-stop state: git clean at `6a56260` (pushed), no running python build, no
active Batch job, Terraform apply complete (0 destroyed), no temporary
credential, no public endpoint, no 2025 access, no real wager. Required outputs
remain `PREDICTIVE SKILL NOT ESTABLISHED` and `NO QUALIFIED WAGER`.


## Checkpoint (i) - read-only per-side assembly audit (2026-07-21), no collector invocation

Built `nrfi/assembly_audit.py` (pure read-only auditor: downloads already-
published S3 objects only; never invokes the live collector) plus
`tests/test_assembly_audit.py` (5 tests, all green) and a `[audit-assembly]`
CI step in `publish-profiles.yml` that lists+downloads every published
`signals/pregame/assembly/2026-07-21/` package, records an immutability
manifest (key/version_id/sha256/generated_at/batter_eligible per package),
then runs the auditor over the downloaded set. `audited_no_collector_invocation=true`.

Audited package (selected = max batter_eligible, tie -> latest generated_at):
- key `signals/pregame/assembly/2026-07-21/assembly-20260721T233849Z.json`
- S3 version_id `aSZ.sbY601kAgCsaLTUgFYmklbiUALzk`
- object sha256 `9829a1a7886eed3072f06d351ddb15389497094a4cab1077086fe5b0cfe2cec3`
- canonical content id `7817d8ffe9f21a33f21f945fc6b584199c5f4148d7999e223adc624117c8381e`
- generated_at 2026-07-21T23:38:49Z; 18 packages published total.

Game-level (15 games): games_before_cutoff=9, snapshot_fresh=14,
probable_starter_eligible=9, pitcher_profile_eligible=0,
lineup_feature_eligible=14, batter_feature_eligible=3, team_context_eligible=15,
unified=0.

Side-level (30 sides): pitcher SELECTED=30; pitcher_feature READY=8,
BLOCKED_NO_INVENTORIED_PROFILE=11, BLOCKED_PREGAME_SNAPSHOT=10,
BLOCKED_INSUFFICIENT_PROFILE_HISTORY=1. lineup CONFIRMED=28, NOT_AVAILABLE=2.
team_side_eligible True=30 (no team rejections).

pitcher_profile_eligible=0 explained: no game had BOTH sides simultaneously
pregame/pre-cutoff AND both starters carrying a qualifying strict-prior
2015-2024 Statcast profile. 8 of 30 sides READY; 10 blocked because the game
left pregame status (6/15 games past cutoff at 23:38Z), 11 blocked
NO_STRICT_PRIOR_STATCAST_PROFILE (post-2024 debutants / no qualifying starts),
1 blocked minimum prior starts. snapshot_stale_games=0. Honest data-coverage
outcome, not a pipeline fault.

BATTER split RESOLVED (side-level, authoritative from the immutable package;
supersedes the earlier step-count approximation): of 28 lineup-eligible sides
-> 14 batter-eligible, 13 BATTER_PROFILE_MISSING (>=1 top-of-order batter has
no terminal profile, missing_profile_count>0), 1 BATTER_HISTORY_INSUFFICIENT
(all four have profiles but >=1 below the career-PA minimum,
missing_profile_count=0). Reconciles: 14+13+1=28 lineup-eligible; the other 2
of 30 sides are LINEUP_NOT_AVAILABLE; false batter sides 13+1+2=16.

3 batter-eligible GAMES all fully_verified=true (both sides CONFIRMED,
confirmed_pre_cutoff=true, profile_coverage=1.0, missing_profile_count=0,
against terminal batter identity 7e7fc570 and team identity c99563f7):
game_pk 822787 (teams 139/141, lineups 23:03:26Z), 823437 (119/143,
21:03:26Z), 825056 (133/109, 23:38:44Z).

Immutable evidence committed under `docs/assembly_audit_2026_07_21/`:
`census.json` (canonical audit census), `package_immutability.json` (18-package
manifest + selection rule), `README.md` (narrative). Gates unchanged:
unified/model/market/wager all false; outputs remain `PREDICTIVE SKILL NOT
ESTABLISHED` and `NO QUALIFIED WAGER`.
