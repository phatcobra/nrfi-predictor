# NRFI_CORE_V2_1 — admissibility repair of the V2 program

The NRFI_CORE_V2 result is **provisional**: the implementation did not fully
match its frozen contract. All V2 artifacts under `docs/nrfi_core_v2/` are
**preserved unchanged**. `NRFI_CORE_V2_1` re-specifies and (in a later step)
re-runs the program with every discrepancy fixed. This directory holds the
recorded discrepancies (`discrepancies.json`) and the new **predeclared** frozen
contract (`frozen_contract.json`, sha256 `215984be…`), frozen before any V2.1
result.

## Recorded V2 discrepancies (see `discrepancies.json`)

1. Only logistic + LightGBM ran; **spline-GAM** was predeclared but not executed.
2. Only **sigmoid** calibration ran; isotonic and beta were predeclared.
3. Only **expanding** climatology baseline; pooled, prior-season, and
   NRFI_CORE_V1 were predeclared.
4. The Bonferroni family-wise correction was **post-hoc for V2** (added after
   the first result); it is legitimately **predeclared in V2.1**.
5. The evaluator used **all rows**; `core_model_feature_eligible` was not
   enforced for the primary promotion analysis.
6. The temporal calibrator stored **calibrated** predictions back into the
   prior-fold pool, so later calibrators trained on a mixture of raw and
   already-calibrated probabilities (OOF contamination).
7. The historical pitcher artifact uses **postgame actual-starter attribution**,
   which is not guaranteed equal to the cutoff-known probable starter
   (potential training-serving skew).
8. Schedule/travel local-time features used **fixed standard UTC offsets**
   without historical DST (not effective-dated).

## What V2.1 predeclares

Candidates logistic-L2 / spline-GAM / constrained LightGBM × calibrations
raw / sigmoid / isotonic / beta × the 13-cell ablation program, against four
baselines (pooled, expanding, prior-season climatology, NRFI_CORE_V1). Primary
promotion analysis on `core_model_feature_eligible == true`; secondary
robustness on all rows with train-fold-only imputation + missingness indicators
(coverage and rejection reasons reported for both). Calibrators fit **only** on
immutable prior-fold **raw** OOF predictions. Family-wise Bonferroni multiplicity
(predeclared here). Official-date cluster bootstrap via the audited seeded
`nrfi.deterministic_resampling` module (2,000 replicates, seed 20260722).
Calibration bands intercept `[-0.15, 0.15]`, slope `[0.8, 1.2]`. Effective-dated
IANA time zones with `tzdata==2026.3`.

**Starter-identity admissibility:** because the historical pitcher domain is
postgame-attributed, no predictive-skill claim is admissible until the
cutoff-known-vs-actual starter divergence is audited and resolved
(restrict-to-confirmed, rebuild-with-cutoff-known, or model starter
uncertainty). Two byte-identical evaluations and the full release gate are
required, then AWS Batch local/CI/Batch equality.

`model_probability_eligible`, `market_eligible`, `wager_eligible` stay **false**.

```text
PREDICTIVE SKILL NOT ESTABLISHED
NO QUALIFIED WAGER
```
