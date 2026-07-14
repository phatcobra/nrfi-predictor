# Repository Operating Standard

This file governs all human- and agent-authored changes in this repository. Apply it together with the fail-closed data, modeling, registry, serving, and audit controls documented in `README.md` and `SETUP_CHECKLIST.md`. When instructions conflict, preserve data integrity, temporal validity, reproducibility, security, and the existing release gates.

## Objective

Build and operate the MLB NRFI/YRFI prediction system with the strongest practical combination of prediction quality, automation, validation, reproducibility, traceability, maintainability, scalability, and operational reliability.

Use advanced tools only when they reduce implementation or operational complexity without weakening analytical depth, exposing hidden decision logic, or bypassing required gates.

## Non-negotiable system invariants

- Preserve fail-closed behavior. Missing, malformed, future-dated, stale, incomplete, or unverified inputs must never be replaced with fabricated, random, or silent fallback values.
- Preserve strict chronology. Features for a game may use only information available before that game's decision time. Same-day or future leakage is prohibited.
- Use the same versioned feature definitions for training and serving.
- Keep the 2025 holdout locked. Do not rerun or tune against it except through the repository's explicit burned-evidence mechanism.
- Do not promote a model without passing purged walk-forward out-of-fold gates, the locked holdout gate, artifact integrity checks, and explicit human promotion.
- Do not claim model skill from unit tests, in-sample metrics, isolated examples, or unrecorded experiments.
- Serving may load only the registry-approved production model and must refuse scoring when required evidence or dependencies are absent.
- Preserve immutable prediction, grading, provenance, and promotion evidence.
- Keep the API diagnostic and paper-mode only. Do not add picks, staking instructions, action language, or fabricated market edges.

## Tool-leverage admission standard

A new tool, service, framework, dependency, platform, managed integration, or automation is admissible only when it provides at least one measurable contribution:

1. Removes meaningful manual work.
2. Reduces a specific and material failure risk.
3. Improves data-quality, leakage, security, testing, deployment, or model-validation controls.
4. Increases reproducibility, determinism, lineage, or auditability.
5. Enables analysis, simulation, storage, computation, training, or inference that is otherwise impractical.
6. Improves debugging, observability, incident response, rollback, recovery, or root-cause analysis.
7. Shortens the path from an idea to a correctly validated and reproducible result.
8. Replaces a weaker component without introducing greater operational risk.
9. Produces measurable gains in cost, latency, throughput, reliability, maintainability, or scalability.

Reject a tool when it:

- duplicates an existing capability without sufficient incremental value;
- hides critical data, feature, model, validation, promotion, or decision logic;
- weakens temporal validation, reproducibility, security, testing, deployment controls, or fail-closed behavior;
- introduces unjustified vendor lock-in, recurring manual cleanup, configuration drift, or incompatible sources of truth;
- makes failures harder to detect, diagnose, reproduce, recover from, or audit;
- adds more architectural or maintenance burden than operational benefit;
- accelerates output by bypassing required validation gates.

Do not adopt a tool merely because it is newer, popular, convenient, or already available.

## Required tool decision record

Every change that adds, replaces, or materially expands a tool or dependency must document all of the following in the pull request:

- **Role:** the exact responsibility assigned to the tool.
- **Integration point:** the files, processes, data contracts, jobs, or runtime boundaries it touches.
- **Expected benefit:** a measurable target or a falsifiable qualitative improvement.
- **Failure modes:** expected technical, data, security, vendor, quota, cost, and operational failures.
- **Owner:** who maintains configuration, credentials, upgrades, and incident response.
- **Validation:** how correctness, reliability, and non-regression will be demonstrated.
- **Exit path:** how the tool can be disabled, replaced, or removed without losing authoritative data or breaking the wider system.
- **Analytical-sophistication check:** evidence that the tool does not weaken feature logic, model comparison, temporal validation, calibration, or release controls.

A tool change without this record is incomplete.

## Change workflow

1. Inspect the current implementation, tests, schemas, workflows, and documentation before editing. Do not infer repository state from task wording alone.
2. State the objective, affected contracts, invariants, failure modes, and validation plan before making a high-risk change.
3. Make the smallest coherent change that solves the identified problem. Avoid parallel sources of truth and speculative abstractions.
4. Keep critical logic explicit and reviewable. Configuration must not conceal feature definitions, data filters, model gates, promotion rules, or failure behavior.
5. Add or update tests for the changed behavior, including negative and dependency-failure paths.
6. Run the strongest validation available for the affected scope before changing tools, models, or architecture again.
7. Stop when a required gate fails. Diagnose the failure; do not weaken or bypass the gate to obtain a passing result.
8. Report what changed, what was validated, what failed, residual risks, rollback steps, and any unvalidated assumptions.

## Data and feature requirements

- Treat source provenance, event time, ingestion time, effective time, schema version, and feature version as first-class data.
- Reject unknown columns, invalid values, null keys, duplicate keys, ambiguous entity mappings, and incomplete source coverage at ingestion boundaries.
- Prefer idempotent, restartable, deterministic pipelines with explicit checkpoints and reconciliation.
- Preserve raw observed data. Derived tables and feature stores must be rebuildable from authoritative inputs.
- Require point-in-time correctness for joins, rolling windows, starter attribution, park factors, odds snapshots, and any externally sourced statistic.
- Add data-quality assertions at the earliest boundary that can identify the defect accurately.
- Never permit a data tool to silently coerce, impute, truncate, deduplicate, or discard records that affect labels or model features.

## Modeling and validation requirements

- Compare candidates against frozen, relevant baselines such as climatology and the current production model.
- Use purged, chronological out-of-sample evaluation. Random cross-validation is not acceptable for release evidence.
- Evaluate discrimination and probability quality, including Brier score, log loss, calibration, coverage, stability, and subgroup behavior.
- Record seeds, package versions, feature versions, data cutoffs, split definitions, hyperparameters, artifacts, and evaluation outputs.
- Keep model selection, calibration, thresholding, and promotion criteria separate and explicit.
- Treat external research and automated experimentation as hypothesis generation, not validation.
- Do not optimize against the locked holdout or repeatedly inspect it during development.
- A faster or more automated training tool is unacceptable if it weakens reproducibility, temporal controls, calibration, interpretability of failure, or artifact traceability.

## Testing and release gates

For changes that can affect production behavior, run the repository release gate from a clean environment:

```bash
pip install -r requirements.txt
python -m py_compile nrfi/*.py scripts/*.py
pytest -q
```

Also run the narrowest relevant integration or operational checks for changed components. Database-, vendor-, and credential-dependent validation must fail clearly when dependencies are unavailable; do not simulate a pass.

Changes affecting data schemas, feature generation, training, calibration, holdout evaluation, registry promotion, scoring, odds ingestion, grading, API authorization, or scheduled jobs require explicit regression coverage for their fail-closed paths.

Do not merge when:

- required tests or release gates fail;
- model or data evidence is missing, stale, irreproducible, or contaminated;
- a new tool lacks the required decision record;
- rollback or replacement is undefined for a material integration;
- implementation and documentation disagree about authoritative behavior.

## Security and external services

- Never commit credentials, tokens, private keys, connection strings, or raw secret-bearing logs.
- Use least-privilege credentials, bounded timeouts, explicit retries, rate-limit handling, and circuit-breaking or fail-closed behavior where appropriate.
- Validate external responses at the boundary and preserve source timestamps and provenance.
- External services must not become an untracked source of truth. Authoritative data and artifacts must remain exportable and auditable.
- A managed service must have a documented outage behavior, cost boundary, data-retention posture, and replacement path.

## Documentation and final report

Update documentation when contracts, commands, schemas, dependencies, operational procedures, failure behavior, or release gates change.

Every substantial pull request must report:

- objective and scope;
- files and contracts changed;
- validation performed and exact results;
- data, leakage, model, security, and operational risks considered;
- tool decision record when applicable;
- known limitations or unvalidated dependencies;
- rollback or disable procedure.

## Governing principle

Maximize useful tool leverage. Minimize manual work, implementation complexity, technical debt, and operational friction. Preserve full analytical sophistication and fail-closed controls. Require every tool and every release claim to prove measurable engineering value.