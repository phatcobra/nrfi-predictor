# Multi-season NRFI/YRFI development evidence

This package contains normalized derived official MLB StatsAPI evidence for the
complete 2021 through 2024 regular seasons. It is internal development evidence,
not a production, predictive-edge, market, or wagering claim. Raw source
payloads, quarantined assets, optional data domains, and the locked 2025 holdout
were not used or persisted.

## Coverage

- 9,720 unique scheduled regular-season game identities were observed.
- 9,716 finalized games were accepted; four failed closed.
- 9,778 monthly normalized observations reconciled to those unique games.
- 62 byte-equivalent cross-month duplicate game identities were explicitly
  reconciled, primarily around postponed or resumed schedule windows.
- 9,716 games have both postgame actual starters; actual starters are never used
  as unverified pregame pitcher features.
- 9,559 games have eligible strict-prior team and league features (98.38%).
- 9,558 games are evaluation-eligible (98.37%).
- 157 early-history games lack the required prior sample; suspended gamePk
  `716404` is excluded because its recorded label availability precedes the
  source's current scheduled datetime and no original cutoff is invented.
- Pitcher and lineup pregame feature coverage is 0% by policy.

The four rejected identities are explicit in `rejections.jsonl`: two lack a
first-inning linescore and two lack required team or venue identity.

## Chronological evidence

The expanding-window folds train only on labels available before the next
season's first prediction cutoff.

| Test season | Training rows | Predictions | Candidate log loss | Candidate Brier | ECE |
|---|---:|---:|---:|---:|---:|
| 2022 | 2,271 | 2,429 | 0.692869 | 0.249861 | 0.025610 |
| 2023 | 4,700 | 2,429 | 0.692935 | 0.249894 | 0.015373 |
| 2024 | 7,129 | 2,429 | 0.693809 | 0.250330 | 0.029588 |

Pooled evidence covers 7,287 immutable historical-replay predictions with
separate grade records.

| Model or frozen baseline | Log loss | Brier score | ECE |
|---|---:|---:|---:|
| Regularized team/league logistic candidate | 0.693204 | 0.250029 | 0.015694 |
| Expanding overall climatology | 0.693270 | 0.250062 | 0.015646 |
| Prior-season climatology | 0.693741 | 0.250297 | 0.027055 |
| Rolling league-200 climatology | 0.694345 | 0.250588 | 0.022263 |

Candidate improvement over overall climatology is only `0.000066` log-loss
points and `0.000033` Brier points. Official-date clustered 95% bootstrap
intervals include zero: `[-0.000874, 0.001010]` for log loss and
`[-0.000448, 0.000524]` for Brier. The candidate also degrades in 2024. Pooled
calibration slope is `0.437071` and intercept is `-0.064094`.

The required primary conclusion is:

```text
PREDICTIVE SKILL NOT ESTABLISHED
```

This is a valid negative result. It prohibits market evaluation, wager
qualification, model promotion, and production use.

## Deterministic replay

The producing commit is `cd7c332d42d696794d56928ebfbcc4c6b04a8444` and the
dependency-lock SHA-256 is
`83fc3f537893f95b4fbcdd82e37b42b94b20d60ecc75b999d2d0f6da5e6f88ac`.
Two clean derivations from the verified normalization-v2 cache produced
identical analytical manifests and probabilities with zero maximum difference.
Execution timestamps are excluded from analytical identities.

Key identities:

- normalized partition:
  `f7a3a6e1ad7b3fe0567ed1326f12007f98fa0488ed355f69f2aa679ba5d86d2c`
- feature partition:
  `1eb781cd8a48a0ab1babe09865620bd151e6a9206a3859dbc5fae436de770a55`
- fold membership:
  `f3f6af1dfec1c6a3ddc260b0092359a5716a9960baf43ff838b0a3c6c0bd1dc6`
- prediction partition:
  `334f1ff8fce0bdcdcedd2f20cc1e6f090dbf589f24b92bbaf0f93b6e439e2f24`
- grade partition:
  `d9cfe3f01188d55b84cfc808e85ad102643b4df0252cc938716652bca03590c7`
- evaluation:
  `8a4df4874e0179e79d7be7289b55b66512258cd62dc0b2bf392628812e7c8b70`

`artifact_manifest.json` records byte hashes and row counts for all 16
machine-readable outputs. Rebuild without network access using:

```powershell
.\.venv\Scripts\python.exe -m nrfi.multiseason --seasons 2021,2022,2023,2024 --code-commit cd7c332d42d696794d56928ebfbcc4c6b04a8444 --workers 8 --offline
```
