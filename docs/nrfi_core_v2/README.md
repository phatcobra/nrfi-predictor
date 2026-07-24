# NRFI_CORE_V2 — predeclared frozen contract

This is the **predeclared, frozen** contract for the active scientific mainline
`NRFI_CORE_V2`, recorded machine-readably in `frozen_contract.json`
(sha256 `5133dda94f525bdec6739e82246a430e178a10fe47a1d7eb6cff7337d73947aa`).
It is frozen **before** the canonical matrix is built or any model result is
inspected. A material change requires a new contract version, a documented
rationale, a new deterministic build, and a full re-evaluation.

## What V2 is (and is not)

V2 is a **new** canonical, historically backtestable production-core candidate
built from the newly engineered strict-prior artifacts — it is **not** a rename
of the legacy `fv3.1` matrix. Its feature domains are:

- **pitcher** (`pitcher-statcast-strict-prior-v1`) — career/recent first-inning
  prevention, traffic, contact quality (exit velo, hard-hit, barrel, whiff),
  K/BB rates, recent form, days since previous start, min-history + recency;
- **team** (`team-first-inning-strict-prior-v1`, identity `5124bebb…`) —
  strict-prior first-inning scoring/prevention over last-10/25/50/career +
  season-to-date + home/away splits;
- **park** (`context-foundation-strict-prior-v1`, park terminal `3dacfdb5…`,
  venue reference `d7b9c606…`) — effective-dated venue identity, strict-prior
  first-inning park factor, altitude;
- **workload** — starter rest days, starts in trailing 30 days, prior starts;
- **schedule/travel** — rest, congestion (3d/7d), doubleheaders, travel miles,
  time-zone movement, day/night transitions, road-trip/home-stand position.

All five domains are strict-prior (prior games only, `label_available_at <=`
prediction cutoff, target game excluded) and reconstructable point-in-time. The
matrix joins the three artifacts' 45,522 aligned per-(game, side) snapshots into
22,761 game rows carrying the first-inning NRFI target.

## What is excluded from V2

Confirmed batting orders, top-of-order batter profiles, platoon interactions,
scratches/injuries, timestamped weather/umpire, and any market/closing-odds
feature are **excluded** — they belong to the separate prospective enrichment
contract `NRFI_PROSPECTIVE_ENRICHED_V1` and must never be back-filled with
postgame information into historical V2.

## Predeclared evaluation and gate

Chronological walk-forward on immutable folds (train ≤2021 → 2022, ≤2022 →
2023, ≤2023 → 2024); candidates logistic-L2, spline-GAM logistic, and a
deterministic constrained LightGBM, raw and with prior-completed-fold OOF
calibration (sigmoid / isotonic / beta); baselines pooled/expanding/prior-season
climatology and `NRFI_CORE_V1`; primary metrics log loss, Brier, calibration
intercept/slope, with official-date clustered bootstrap intervals; the full
13-cell domain ablation program.

**Promotion gate (all required):** strictly positive improvement over the
designated baseline on *every* promotion fold **and** a pooled paired 95%
interval excluding zero, with calibration intercept in `[-0.15, 0.15]`, slope in
`[0.8, 1.2]`, no subgroup collapse, adequate coverage, passing deterministic
replay, and no leakage / no 2025 access. If no candidate passes, the outcome is
**PREDICTIVE SKILL NOT ESTABLISHED** — a valid result; the gate is not weakened.

The 2025 season stays locked. Required standing output until the gate passes:

```text
PREDICTIVE SKILL NOT ESTABLISHED
NO QUALIFIED WAGER
```
