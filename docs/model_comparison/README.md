# Deterministic real-data candidate comparison

This package compares four fixed candidates on the same committed 2021-through-
2024 MLB development evidence and immutable chronological folds:

- raw regularized logistic regression;
- logistic regression with prior-fold-only sigmoid calibration;
- raw deterministic LightGBM;
- LightGBM with prior-fold-only sigmoid calibration.

No candidate was tuned on a test season. The first 2022 fold is intentionally
uncalibrated because no completed prior out-of-fold predictions exist. The 2023
and 2024 calibrators use 2,429 and 4,858 completed prior predictions,
respectively. Every calibrator records its target fold, model family, training-
prediction identity, and content identity. The locked 2025 holdout, market data,
wagering logic, optional data domains, paid services, cloud resources, and
quarantined assets were not used.

## Evidence

Each variant has 7,287 out-of-sample predictions and separate immutable grade
records across the 2022, 2023, and 2024 folds.

| Candidate | Log loss | Brier score | ECE | Decision |
|---|---:|---:|---:|---|
| Logistic raw | 0.693204 | 0.250029 | 0.015694 | Rejected |
| Logistic prior-fold sigmoid | 0.693847 | 0.250345 | 0.003856 | Rejected |
| LightGBM raw | 0.697654 | 0.252208 | 0.032467 | Rejected |
| LightGBM prior-fold sigmoid | 0.695999 | 0.251390 | 0.014366 | Rejected |

Raw logistic improves on expanding overall climatology by only `0.000066` log-
loss and `0.000033` Brier points. The official-date clustered 95% intervals,
`[-0.000898, 0.000962]` and `[-0.000411, 0.000512]`, include zero. Both LightGBM
variants are materially worse than overall climatology. Sigmoid calibration is
rejected for logistic because lower ECE comes with worse log loss and Brier.
LightGBM calibration is accepted only relative to its rejected raw variant.

The required primary conclusion is:

```text
PREDICTIVE SKILL NOT ESTABLISHED
```

This result prohibits predictive-edge, market, wager, promotion, production, or
deployment claims.

## Replay and identities

Producing code commit:
`a3e86f52e62bd8fcfbd47c579822ab5303a29082`

- model artifacts:
  `fbcebb2ffc4e8f76a81b6b5562820196f50c386854a2a9b39a6bf1ec7fb50540`
- predictions:
  `2518ceafbd3eecfc1b27a60b9733b55fe21cb98a4a1b12d90922f6de9fa51a02`
- grades:
  `8acc412ff7aad193d66b133508b793e1e6b9037b85be31988d50154e5d1c23a2`
- evaluation:
  `23428a3f7257f434a6394a8f8a117ae0df3004cade8b8fa47771cb8ba072bfc7`

Two complete derivations produced the same analytical manifest and zero
logistic replay delta. `artifact_manifest.json` records byte hashes and row
counts for all seven machine-readable outputs. Rebuild offline with:

```powershell
.\.venv\Scripts\python.exe -m nrfi.model_comparison --evidence docs\multiseason --output docs\model_comparison --code-commit a3e86f52e62bd8fcfbd47c579822ab5303a29082 --uncertainty-replicates 32 --bootstrap-replicates 2000
```
