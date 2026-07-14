## Objective

Describe the problem, the intended outcome, and why this change is necessary.

## Scope and authoritative contracts

List the files, schemas, APIs, jobs, artifacts, or operational procedures changed. Identify the authoritative source of truth after this pull request.

## System invariants

- [ ] Fail-closed behavior is preserved.
- [ ] Point-in-time chronology and leakage controls are preserved.
- [ ] Training and serving feature definitions remain aligned.
- [ ] The locked holdout has not been reused, tuned against, or silently rerun.
- [ ] Registry, promotion, artifact-integrity, and audit controls remain authoritative.
- [ ] No picks, staking instructions, action language, or fabricated fallback values were added.
- [ ] Not applicable items are explained below rather than checked without evidence.

## Tool or dependency decision record

Complete this section for any new, replaced, or materially expanded tool, dependency, service, framework, managed integration, or automation. Otherwise state `Not applicable` and explain why.

- **Role:**
- **Integration point:**
- **Expected measurable benefit:**
- **Failure modes:**
- **Owner and maintenance responsibility:**
- **Validation method:**
- **Exit or replacement path:**
- **Evidence analytical sophistication and controls are not weakened:**
- **Existing alternatives considered and rejection reason:**

## Data and model safety

Describe effects on source provenance, schemas, labels, feature time semantics, missing-data behavior, coverage, calibration, baselines, model selection, or promotion evidence.

## Validation performed

Provide exact commands and results. Do not report a check as passed when a required external dependency, credential, dataset, or service was unavailable.

```text
pip install -r requirements.txt
python -m py_compile nrfi/*.py scripts/*.py
pytest -q
```

Additional integration, migration, data-quality, model-evidence, security, or operational checks:

```text
<commands and results>
```

- [ ] Negative and dependency-failure paths were tested for changed behavior.
- [ ] Documentation matches the implemented authoritative behavior.
- [ ] Generated artifacts, reports, and logs needed for review are attached or reproducibly generated.

## Failure behavior and rollback

State how the change fails, how operators detect the failure, and the exact disable, rollback, migration-reversal, or replacement procedure.

## Residual risk and limitations

List unvalidated assumptions, unavailable dependencies, known limitations, follow-up work, and explicit stop conditions.

## Final report

Summarize what changed, what was proven, what was not proven, and whether the pull request is safe to merge.