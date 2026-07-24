# Read-only per-side assembly audit — official date 2026-07-21

This is a **read-only** audit of the immutable pregame assembly package for
official date 2026-07-21. The live collector was **not** invoked
(`audited_no_collector_invocation=true`). The audit tool
(`nrfi/assembly_audit.py`, covered by `tests/test_assembly_audit.py`) only
downloads already-published S3 objects and inspects them.

## Audited package (immutable identity)

18 immutable packages were published for 2026-07-21. The audit selected the
package with the most batter-eligible games (tie broken by latest
`generated_at`):

| field | value |
|---|---|
| key | `signals/pregame/assembly/2026-07-21/assembly-20260721T233849Z.json` |
| S3 version_id | `aSZ.sbY601kAgCsaLTUgFYmklbiUALzk` |
| object sha256 | `9829a1a7886eed3072f06d351ddb15389497094a4cab1077086fe5b0cfe2cec3` |
| canonical content id | `7817d8ffe9f21a33f21f945fc6b584199c5f4148d7999e223adc624117c8381e` |
| generated_at | `2026-07-21T23:38:49.172775Z` |
| batter_profiles_status | `BATTER_PROFILES_LOADED` (identity `7e7fc570…`) |
| team_profiles_status | `TEAM_PROFILES_LOADED` (identity `c99563f7…`) |

`package_immutability.json` records all 18 published packages (key,
version_id, sha256, generated_at, batter_eligible_games) so the selection is
reproducible and the audited object cannot be silently swapped.

## Game-level counters (15 games)

| counter | value |
|---|---|
| games | 15 |
| games_before_prediction_cutoff | 9 |
| games_snapshot_fresh | 14 |
| probable_starter_eligible_games | 9 |
| pitcher_profile_eligible_games | **0** |
| lineup_feature_eligible_games | 14 |
| batter_feature_eligible_games | **3** |
| team_context_eligible_games | 15 |
| unified_feature_set_eligible_games | **0** |

## Side-level evidence (30 sides = 15 games × 2)

Pitcher:
- pitcher_selection_status: `SELECTED` 30 (a probable starter was named on every side)
- pitcher_feature_status: `READY` 8 · `BLOCKED_NO_INVENTORIED_PROFILE` 11 · `BLOCKED_PREGAME_SNAPSHOT` 10 · `BLOCKED_INSUFFICIENT_PROFILE_HISTORY` 1
- pitcher_feature_reason: `NO_STRICT_PRIOR_STATCAST_PROFILE` 11 · `GAME_STATUS_NOT_PREGAME_ELIGIBLE` 10 · `PROFILE_MINIMUM_PRIOR_STARTS_NOT_MET` 1

Lineup:
- lineup_status: `CONFIRMED` 28 · `NOT_AVAILABLE` 2
- lineup_side_eligible: True 28 · False 2 (reason `LINEUP_NOT_AVAILABLE` 2)

Batter:
- batter_side_eligible: True 14 · False 16
- batter_reason: `BATTER_PROFILE_MISSING` 13 · `BATTER_HISTORY_INSUFFICIENT` 1

Team:
- team_side_eligible: True 30 · team_reason: none (every side team-eligible)

## Why `pitcher_profile_eligible_games = 0`

A game becomes pitcher-profile-eligible only when it is
probable-starter-eligible (fresh pregame snapshot, before the prediction
cutoff) **and both** starters carry a qualifying strict-prior 2015–2024
Statcast profile. On 2026-07-21 no single game satisfied both simultaneously:

- Of 30 selected sides only **8** reached `READY`.
- **10** sides were blocked `GAME_STATUS_NOT_PREGAME_ELIGIBLE` — the game had
  already left pregame status (6 of 15 games were past their prediction
  cutoff at 23:38Z; `prediction_cutoff_passed_games=1` additionally crossed
  between snapshot and assembly).
- **11** sides were blocked `NO_STRICT_PRIOR_STATCAST_PROFILE` — the named
  starter has no inventoried 2015–2024 profile (post-2024 debutants / no
  qualifying starts).
- **1** side was blocked `PROFILE_MINIMUM_PRIOR_STARTS_NOT_MET`.

`snapshot_stale_games=0`. The zero is an honest data-coverage outcome, not a
pipeline fault. This is expected until the strict-prior pitcher inventory is
extended and more games are audited before their cutoff.

## Exact BATTER_PROFILE_MISSING vs BATTER_HISTORY_INSUFFICIENT split

Of the **28** lineup-eligible sides:
- **14** batter-eligible (full top-of-order coverage, every batter has a
  terminal profile with sufficient career history).
- **13** blocked `BATTER_PROFILE_MISSING` — at least one top-of-order batter
  has **no** terminal profile at all (`missing_profile_count > 0`;
  post-2024 debutant / not in the terminal batter table).
- **1** blocked `BATTER_HISTORY_INSUFFICIENT` — every top-of-order batter
  **has** a profile, but at least one falls below the minimum career-PA
  threshold (`missing_profile_count = 0`, `profile_eligible_count < top_of_order_size`).

Reconciliation: 14 + 13 + 1 = 28 lineup-eligible sides. The remaining 2 of 30
sides are the `LINEUP_NOT_AVAILABLE` sides (blocked upstream at the lineup
stage, not counted against batter reasons). False batter sides = 13 + 1 + 2 = 16. ✓

## The 3 batter-eligible games — verification

All three are `fully_verified = true`: both sides `CONFIRMED`,
`confirmed_pre_cutoff = true`, `profile_coverage = 1.0`,
`missing_profile_count = 0`, evaluated against loaded terminal batter
profiles (identity `7e7fc570…`) and loaded team profiles (identity `c99563f7…`).

| game_pk | away team | away lineup observed | home team | home lineup observed | both pre-cutoff | coverage |
|---|---|---|---|---|---|---|
| 822787 | 139 | 2026-07-21T23:03:26Z | 141 | 2026-07-21T23:03:26Z | yes | 1.0 / 1.0 |
| 823437 | 119 | 2026-07-21T21:03:26Z | 143 | 2026-07-21T21:03:26Z | yes | 1.0 / 1.0 |
| 825056 | 133 | 2026-07-21T23:38:44Z | 109 | 2026-07-21T23:38:44Z | yes | 1.0 / 1.0 |

Each side records the confirmed first-four batter ids and the lineup snapshot
id used, so the evidence is traceable to the exact pre-cutoff CONFIRMED lineup
snapshot. Full per-side detail is in `census.json`.

## Gate status unchanged

`unified_feature_set_eligible = 0`, `model_probability_eligible`,
`market_eligible`, `wager_eligible` all remain **false**. Required outputs
still stand: **PREDICTIVE SKILL NOT ESTABLISHED** and **NO QUALIFIED WAGER**.
