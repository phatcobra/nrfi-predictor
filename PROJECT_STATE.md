# NRFI Autopilot Project State

Status date: 2026-07-15

Phase 0: **PASS WITH DOCUMENTED EXCEPTIONS**

Phase 1: **IN PROGRESS**

Current task: **CI release-gate repair**

Current branch: `fix/ci-release-gate-20260715`

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
| Complete local suite after repair | `50 passed, 21 warnings in 5.88s` |
| Controlled-failure GitHub run and diagnostic artifact | Pending |
| Final passing GitHub run and diagnostic artifact | Pending |

## Exact next action

Run targeted import, byte-compile, and complete offline-suite checks. Then add one
temporary controlled failing test on the draft pull request, confirm the repaired
release gate fails while uploading diagnostics, remove only that probe, and confirm
the same gate passes with diagnostics preserved. After the signal is trustworthy,
continue Phase 1 with the reproducible `uv`, `pyproject.toml`, and lockfile
environment foundation.
