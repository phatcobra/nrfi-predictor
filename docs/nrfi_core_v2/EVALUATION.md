# NRFI_CORE_V2 — chronological evaluation result

Executed under the frozen contract (`frozen_contract.json`) on the canonical
historical matrix (identity `83003ad4…`, verified). Harness:
`nrfi.core_v2_evaluation`. Full machine-readable record: `evaluation.json`.

```text
PREDICTIVE SKILL NOT ESTABLISHED
NO QUALIFIED WAGER
```

## Setup

Target: YRFI (`P_FIRST_INNING_RUN`); `P_NRFI = 1 − P_YRFI`. Walk-forward folds
train≤2021→2022, ≤2022→2023, ≤2023→2024 (2,429 / 2,430 / 2,429 test games).
Baseline: expanding climatology (first-inning run base rate ≈ 0.51). Candidates
evaluated: logistic-L2 and constrained LightGBM, each raw and with
prior-completed-fold out-of-fold sigmoid calibration, across the 13 predeclared
domain ablations — **52 variants**. Scores use official-date cluster-bootstrap
(2,000 replicates). The predeclared spline-GAM candidate is staged for the AWS
Batch productionization run; adding it only enlarges the variant family and
therefore tightens the multiple-comparison correction — it cannot change the
conclusion below.

## Why no skill is established

The predeclared full-contract variants do not beat climatology out-of-sample:

| variant | mean Δlog-loss | raw 95% CI | +every fold | calib bands | skill |
|---|---:|---|:--:|:--:|:--:|
| full_v2 · logistic | −0.00145 | [−0.00406, +0.00140] | no | no | no |
| full_v2 · logistic+sigmoid | +0.00007 | [−0.00199, +0.00209] | no | no | no |
| full_v2 · lightgbm | +0.00070 | [−0.00096, +0.00232] | no | no | no |
| full_v2 · lightgbm+sigmoid | +0.00046 | [−0.00134, +0.00221] | no | no | no |
| **best of 52** (pitcher_park · lightgbm) | +0.00182 | [+0.00023, +0.00343] | yes | **no** | **no** |

The only variant whose *raw* 95% interval excludes zero is the cherry-picked
best of 52. Under the predeclared family-wise (Bonferroni) correction its
interval is `[−0.00039, +0.00430]` — it **includes zero** — and its calibration
bands fail. No variant clears the frozen gate (`positive on every fold` **and**
`family-corrected CI excludes zero` **and** `calibration slope ∈ [0.8, 1.2]` and
`intercept ∈ [−0.15, 0.15]` on every fold), so
`any_variant_established_skill = false`.

Calibration collapses out-of-sample even for the strongest full model: the
LightGBM calibration slope falls 0.90 (2022) → 0.52 (2023) → 0.11 (2024). The
tiny in-fold gains do not persist and the probabilities are not reliably
calibrated forward.

## Consequence

`PREDICTIVE SKILL NOT ESTABLISHED` — a valid, predeclared outcome. It prohibits
any predictive-edge, market, wager, promotion, production-model, or
deployment-of-a-signal claim; `unified_feature_set`, `model_probability`,
`market`, and `wager` gates stay closed. The 2025 holdout was never accessed
(`market_data_used = false`, `locked_2025_holdout_accessed = false`). The gate
was not weakened; a tiny, uncertain, uncalibrated improvement is not skill.

Determinism: fixed seeds (`random_state=0`, `deterministic=True` LightGBM,
`n_jobs=1`, bootstrap seed `20260722`), canonical serialization, no wall-clock
stamps in the scientific record; the evaluation reproduces byte-identically and
is re-verified in the release gate / Batch run.
