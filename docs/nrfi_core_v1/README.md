# NRFI_CORE_V1 — frozen feature contract + predeclared evaluation

This freezes **NRFI_CORE_V1**: the immutable strict-prior feature contract
(`nrfi.build_features`, feature version `fv3.1`) together with the predeclared
chronological 2022 / 2023 / 2024 walk-forward evaluation and calibration
program (`nrfi.model_comparison`). The freeze is recorded machine-readably in
`frozen_contract.json`.

## What is frozen

- **Target:** first-inning no-run (NRFI) binary label per game.
- **Feature contract:** `fv3.1` — strict-prior pitcher (career / recent /
  first-inning / Statcast / rest), team (season / first-inning / rolling),
  park, weather, lineup top-3, and schedule (season / week / doubleheader)
  families, over the committed `docs/multiseason` evidence and immutable folds.
- **Protocol:** chronological walk-forward on immutable folds 2022, 2023, 2024
  (7,287 out-of-sample predictions per variant); regularized logistic
  (C = 0.25) and deterministic LightGBM, each raw and with
  prior-completed-fold out-of-fold sigmoid calibration; baselines are overall
  and prior-season climatology.
- **Skill gate (predeclared):** skill is declared only if a variant's paired
  improvement over climatology is strictly positive on **every** fold **and**
  the pooled official-date cluster-bootstrap 95% interval excludes zero.

## Result — PREDICTIVE SKILL NOT ESTABLISHED

| Variant | Log loss | Brier | ECE | Decision |
|---|---:|---:|---:|---|
| logistic_raw | 0.693204 | 0.250029 | 0.015694 | not established |
| logistic_temporal_sigmoid | 0.693847 | 0.250345 | 0.003856 | not established |
| lightgbm_raw | 0.697654 | 0.252208 | 0.032467 | not established |
| lightgbm_temporal_sigmoid | 0.695999 | 0.251390 | 0.014366 | not established |

No variant clears the skill gate. Raw logistic improves on expanding
climatology by only ~0.00007 log-loss with a cluster-bootstrap interval that
includes zero; both LightGBM variants are worse than climatology. The locked
2025 holdout, market data, and wagering logic were not used.

```text
PREDICTIVE SKILL NOT ESTABLISHED
NO QUALIFIED WAGER
```

## Bound identities and reproduction

The commit-invariant scientific identity of the frozen evaluation is the
`evaluation.json` content hash:

`23428a3f7257f434a6394a8f8a117ae0df3004cade8b8fa47771cb8ba072bfc7`

Reproducing `nrfi.model_comparison` at the current head regenerated
`evaluation.json` and `fold_evaluation.jsonl` **byte-identically**, with a
logistic replay delta of `0.0`. `predictions.jsonl`, `grades.jsonl`, and
`deterministic_manifest.json` differ only by `code_commit`- and
`grade_time`-stamped provenance fields, which rebind per run; the underlying
predictions, grades, and metrics are identical. `frozen_contract.json` also
binds the original producing partition identities (predictions
`2518ceaf…`, grades `8acc412f…`, model artifacts `fbcebb2f…`) and the base
feature-partition / fold-membership identities.

Rebuild offline:

```powershell
.\.venv\Scripts\python.exe -m nrfi.model_comparison --evidence docs\multiseason `
  --output docs\model_comparison --code-commit <HEAD> `
  --uncertainty-replicates 32 --bootstrap-replicates 2000
```

## Prohibition and forward path

The `PREDICTIVE SKILL NOT ESTABLISHED` conclusion prohibits any
predictive-edge, market, wager, promotion, production, or betting-signal
claim; the `unified_feature_set`, `model_probability`, `market`, and `wager`
gates stay closed.

The newly-built strict-prior domains — pitcher-Statcast 2015–2024, terminal
batter profiles, team first-inning, and Context Foundation V1 park/venue — are
**candidate inputs for a future NRFI_CORE_V2** evaluation under this same
frozen protocol (walk-forward 2022/2023/2024, climatology baselines,
cluster-bootstrap skill gate). They are **not** part of NRFI_CORE_V1 and do not
change its conclusion. Any future skill claim must clear the same predeclared
gate on out-of-sample folds before any downstream gate may open.
