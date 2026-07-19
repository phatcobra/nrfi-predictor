# Historical asset reconciliation - 2026-07-19

Read-only inventory across the authoritative repository, local caches, the
quarantined `mlb-model` repository, Codex worktrees, and AWS. No source asset
was modified. The machine-readable ledger is `inventory.json`; classifications
follow the eight-class admission taxonomy. AWS raw/evidence/audit bucket
enumeration is recorded as PENDING because the operator console session signed
out mid-inventory; the lake bucket contents were verified earlier the same day.

## Season x domain coverage (verified this inventory)

| Domain | Verified coverage | Source | Status |
| --- | --- | --- | --- |
| Schedules, game identities, venues | 2015-2024 | MLB StatsAPI normalized v2 cache (2015-2020 acquisition completing in this session) | ADMITTED_STATIC_OR_POSTGAME_LABEL |
| First-inning outcomes | 2015-2024 | same | ADMITTED_STATIC_OR_POSTGAME_LABEL |
| Actual starters (postgame labels) | 2015-2024 | same | ADMITTED_STATIC_OR_POSTGAME_LABEL (never substitutable for probables) |
| Statcast pitch-level | 2015-2024 present locally | mlb-model `data/statcast_days/` (2,584 daily parquet, 1.23 GB, 2015-2025) and `mlb.duckdb` (3.78 GB) | CANDIDATE: per-file/per-slice admission via extraction contract; 2025-dated members HOLDOUT_BLOCKED |
| Strict-prior pitcher profiles | 2021-2024 | AWS lake parquet + JSONL projection | ADMITTED (canonical); full-history rebuild pending Statcast extraction |
| Probable starters (point-in-time) | 2026-07-18 onward only | forward collector captures (observation-timestamped) | ADMITTED_POINT_IN_TIME / FORWARD_ONLY |
| Lineups, batting orders, play-by-play, umpires | candidate only | mlb-model `data/retrosheet/` (3.1 MB) + retrosheet tables inside mlb.duckdb; coverage unverified | CANDIDATE pending extraction contract + coverage verification |
| Player/team identity mappings | 2015-2024 partial | StatsAPI ids (canonical); Lahman fragment (4 KB) negligible | StatsAPI ADMITTED; Lahman fragment recorded |
| Rosters and injuries | none found | - | ABSENT (no lawful historical asset located) |
| Park factors | derivable 2015-2024 | admitted venues + outcomes | DERIVABLE |
| Weather (historical pregame forecasts) | none found | - | ABSENT |
| Rest, travel, doubleheaders, workload | derivable 2015-2024 | admitted schedules | DERIVABLE |
| Sportsbook prices w/ timestamps | none found locally | legacy `ingest_opticodds.py` module exists; no local price data located | ABSENT (module only) |

## Quarantine and holdout notes

- `C:\Users\ameis\mlb-model` remains read-only and quarantined as a whole:
  it contains 2025 Statcast (daily files, monthly parquets,
  `statcast_pitches_2025` = 713,036 rows per its own invariant) and
  2025-holdout backtest outputs. Its `outputs/` and `models/` are
  holdout-contaminated for this project's purposes and stay QUARANTINED.
- Admission of its 2015-2024 content requires a controlled extraction that
  provably excludes season 2025 (season predicate, per-export checksums, row
  counts, provenance) - defined as the next data operation; not yet executed.
- No 2025 object exists in the project lake; the locked holdout was not
  listed, loaded, or computed against during this inventory.

## Precise 2026 assembly rejection census (directive #15)

Sample: the committed 2026-07-19 local pregame package (30 sides) and the
deployed 2026-07-19 assembly run (32 sides, 30 snapshot-eligible), both under
feature schema v1:

- 1 side: PROBABLE_STARTER_MISSING (no announced starter yet - true absence);
- 7 sides: NO_STRICT_PRIOR_STATCAST_PROFILE (pitcher absent from the
  2021-2024 profile table - true data gap: debut/no qualifying starts in
  window; expected to shrink after the 2015-2024 profile rebuild);
- 2 sides: PROFILE_MINIMUM_PRIOR_STARTS_NOT_MET (true threshold gap);
- 20 sides: PROFILE_MISSING_INTERVENING_SEASON_HISTORY - an unnecessary
  2025 requirement: valid 2021-2024 career history was being erased because
  locked-2025 history cannot exist. No frozen model contract requires 2025.
  Corrected in feature schema v2: the gap is now the explicit fields
  `profile_history_gap_seasons` / `profile_recent_history_missing` and no
  longer blocks pitcher-feature eligibility. Probability eligibility remains
  fail-closed behind model approval regardless.
- 0 sides: player identity mismatch, stale profile table read, feature-table
  omission, or cutoff-logic error (all selections used latest admissible
  pre-cutoff observations; identities joined deterministically by MLBAM id).
