# NRFI_CORE_V2_2_ADMISSIBLE — the historically promotion-admissible core

The starter-identity audit (`docs/nrfi_core_v2_1/starter_identity_audit.json`)
and its supplement (`docs/nrfi_core_v2_1/discrepancies_supplement.json`) show
that **both** the pitcher **and** the starter-workload domains depend on the
selected starter identity, which historically is only the **postgame actual
starter** (cutoff-known probable starters are unavailable for all 22,761
committed games). Any pitcher- or workload-inclusive historical variant is
therefore **inadmissible** for a promotion claim.

`NRFI_CORE_V2_2_ADMISSIBLE` (`frozen_contract.json`, sha256 `8af8e4d5…`) is the
**predeclared** admissible core, frozen before any V2.2 result. It uses **only
starter-independent** historical domains:

- strict-prior **team** first-inning context (`team-first-inning-strict-prior-v1`);
- effective-dated **park** context;
- team-level **schedule / travel** context.

It **excludes from promotion**: pitcher profile, starter workload, actual
starter identity, postgame attribution, confirmed lineup, batter profile,
realized weather, untimed umpire identity, market data, and 2025.

Predeclared program: candidates logistic-L2 / spline-GAM / constrained LightGBM
× calibrations raw / sigmoid / isotonic / beta × the 7 team/park/schedule
ablations, against pooled / expanding / prior-season climatology and
NRFI_CORE_V1 (on paired common rows). Calibrators fit **only** on immutable
**raw** OOF predictions from predeclared calibration-seed folds strictly before
2022 (predict 2019/2020/2021), which never count as promotion folds and never
allow fitting on the evaluated fold or on already-calibrated predictions.
Primary analysis on admissible-eligible rows (identical rows for model and
baseline); secondary on all rows with train-fold-only imputation + missingness
indicators. Family-wise Bonferroni multiplicity (predeclared). Official-date
cluster bootstrap via the audited seeded `nrfi.deterministic_resampling`.
Effective-dated IANA time zones (`tzdata==2026.3`). Two byte-identical runs +
the full release gate, then AWS Batch local/CI/Batch equality.

V1/V2/V2.1 artifacts and identities are preserved unchanged.
`model_probability_eligible`, `market_eligible`, `wager_eligible` stay **false**.

```text
PREDICTIVE SKILL NOT ESTABLISHED
NO QUALIFIED WAGER
```
