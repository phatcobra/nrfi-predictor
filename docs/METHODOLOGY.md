# Methodology — First-Inning (NRFI/YRFI) Prediction

This document specifies exactly how the model is built so every number it
produces can be audited. Nothing here is aspirational; every mechanism is
implemented in `src/nrfi/` and enforced by tests.

## 1. Prediction target

**YRFI** = at least one run scores in the first inning (both halves
combined). **NRFI** = zero runs. The model outputs a calibrated
`P(YRFI)`; `P(NRFI) = 1 − P(YRFI)`.

Label validity rules (`src/nrfi/labels.py`):

- Game must be Final.
- Any first-inning run recorded for either side ⇒ label 1 (the event
  occurred, whatever happened later).
- Label 0 requires both halves recorded scoreless **and** ≥ 5 recorded
  innings, so a truncated linescore can never manufacture a false NRFI.
- Everything else is excluded. Labels are never inferred.

## 2. Data

Single authoritative source: the public **MLB StatsAPI**
(`/schedule` hydrated with `linescore` and `probablePitcher`), regular
season only, seasons 2011 → present (~2,430 games/season). Optional
weather enrichment via **Open-Meteo** (archive for history, forecast for
the live slate), joined at the stadium coordinates published by the
StatsAPI `venues` endpoint. All processed data is committed as
per-season CSVs under `data/processed/` for reproducible retrains.

Starter attribution uses the **probable pitcher**, deliberately: it is the
same information the live predictor has on the morning of a game, so the
training information set matches the serving information set exactly.
Occasional late scratches are noise in both regimes, not a bias.

## 3. Leakage control (the load-bearing design)

Features for every game on date *D* are computed from games **strictly
before D** — a day-grouped pass in `build_training_frame`
(`src/nrfi/features.py`). Same-day games never see each other's results,
because at prediction time (morning) none of them have happened yet.

One `FeatureBuilder` code path serves both training (replay history,
features-then-update per day) and prediction (replay history through
yesterday, featurize today), eliminating training/serving skew. A unit
test (`test_features_use_only_prior_days_never_same_day`) locks this in.

## 4. Features

All rates are empirical-Bayes shrunk toward the running league rate with
pseudo-count strength *m*:

```
shrunk_rate = (sum + m · league_rate) / (n + m)
```

A 2-start rookie is pulled almost entirely to league average; a 200-start
veteran keeps his own rate. League rates themselves are running values
(with fixed cold-start priors that only matter for the first weeks of
2011, before ~500 half-innings accumulate).

| Group | Features |
|---|---|
| Home/away starter | career-to-date first-inning runs-allowed rate (m=25), first-inning YRFI-allowed rate, last-10-starts mean runs allowed, starts tracked, days rest (capped 30) |
| Home/away offense | first-inning runs-scored rate (m=40), first-inning YRFI-scored rate, recent-30-games scoring rate |
| Park | first-inning total-runs factor per venue (m=120) |
| Regime | rolling 365-day league YRFI rate and first-inning runs rate |
| Context | night game, month, season |
| Weather | game-hour temperature, wind speed, indoor-park flag (NaN-tolerant; domes get neutral indoor values) |

The half-inning attribution is exact: the home starter is charged with
the away team's first-inning runs and vice versa (the starter always
pitches the first inning).

## 5. Model

`HistGradientBoostingClassifier` (log-loss objective) configured for a
low-signal target: ≤15 leaf nodes, ≥200 samples/leaf, L2 = 5, learning
rate 0.04, early stopping. Native NaN handling means missing pitcher
history, missing weather, and cold starts are modeled rather than
imputed away.

**Calibration:** the final ~15% of the training window (chronological) is
withheld from fitting and used to train an isotonic regression on the raw
scores. Probabilities are then clipped to [0.02, 0.98] — this market
never justifies certainty.

## 6. Evaluation protocol

**Walk-forward by season** (`src/nrfi/backtest.py`): for each test season
*Y*, fit only on seasons < *Y*, predict *Y*. No test season ever touches
its own model. Reported per season and pooled:

- **Log loss** and **Brier score**, against a **climatology baseline**
  (the rolling league YRFI rate — the strongest naive forecast).
- **Brier skill score** `1 − Brier_model / Brier_climatology`; positive
  means real predictive information.
- **ROC AUC** (discrimination).
- **Calibration table** by predicted-probability decile: observed vs
  predicted YRFI rate; near-zero gaps mean the outputs can be compared
  directly to market-implied probabilities.

## 7. Honest expectations

First-inning scoring is close to a coin flip (league YRFI rate ≈ 51–53%).
A good model here shows **small but consistent** skill: Brier skill score
in the low single-digit percent, AUC roughly 0.58–0.62, and clean
calibration. Any pipeline claiming dramatically more is leaking. The
economic value of such a model lives entirely in calibration quality and
price comparison, which is handled by a separate price-aware research
layer — this repository produces probabilities, never betting picks.

## 8. Roadmap (not yet implemented)

- Umpire and catcher framing effects (requires per-game boxscore ingest).
- Confirmed lineups for the top-3 batters instead of team-level offense.
- Statcast pitch-quality priors for starters with thin MLB history.
- First-inning-specific pitcher splits vs. full-game proxies.
