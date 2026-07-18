# NRFI Autopilot Project State

Status date: 2026-07-17

Phase 0: **PASS WITH DOCUMENTED EXCEPTIONS**

Phase 1: **PASS WITH DOCUMENTED EXCEPTIONS**

Phase 2: **PASS WITH DOCUMENTED EXCEPTIONS**

AWS platform: **STAGE 3 IN PROGRESS — IAM-AUTHENTICATED PROBABILITY API LIVE**

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
