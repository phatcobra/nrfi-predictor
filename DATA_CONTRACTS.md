# NRFI Autopilot Data Contracts

Status date: 2026-07-15

Phase 2 status: **PASS WITH DOCUMENTED EXCEPTIONS**

This document defines the storage-neutral contracts and admission gates for the
NRFI Autopilot data layer. It uses only the public-safe metadata produced by the
two completed Phase 0 scans. No cache was rescanned, no quarantined database was
opened, no data was acquired, and no locked evaluation evidence was inspected.

Passing this documentation gate does not admit any real data asset. Every real
candidate remains unavailable to training, evaluation, or production until its
own authority, license, provenance, timing, schema, key, quality, and corruption
gates pass.

## Evidence boundary

The preserved Phase 0 evidence describes 6,670 files totaling 1,455,407,592
bytes. Its scan ID is
`0f3f19aa1d72525577f460a2fcb9692f81c835ec110c3674a720096c6a23c111`.
The two deterministic executions produced byte-identical manifest, summary,
and checksum outputs.

| Evidence | Recorded identity |
|---|---|
| Content tree | SHA-256 `40a53f6ec231c1a0a21f1c9ecfca5f606db7948e27636c205c0192d8a73ee6cb` |
| Observation tree | SHA-256 `74feb2dae3e9549b8238f580bfcf34613b771ad06bc85ee6311574df7956eb07` |
| Scan parameters | SHA-256 `c52e984983c40edb5b6db8d256c86e8a111ee27e1ea88bba3ea81a784b276924` |
| Canonical selection | 2,173 records; SHA-256 `b3e3f19c10e0e1504ecc31c2b46b71aa250d1b0f9a2078e0615c69e42579a9ac` |
| Per-file manifest | 6,670 records; 13,068,963 bytes; SHA-256 `4ab2f5e74b61743a81152096416a09e8c0b13c121fe045174208af93cfa29fbc` |
| Scan summary | SHA-256 `6342b5503474a036ce1bab56b7ee1fb6dca3cb024a550ee5108e6f90d2c9d032` |
| Inventory generator | SHA-256 `b14387e57919b3b857e8a0b9105ca24f4860c2cca1a87ade63e903be73f8f4f6` |
| Checksum sidecar | SHA-256 `bf9270797084ee58c2f46bf0d51ec2d8e49833f891dec84edd2930d893b2a496` |

The Phase 0 artifacts remain on the unpublished documentation branch. Phase 2
references their logical repository paths and recorded hashes; it does not copy
the 13 MB JSONL manifest. Publication order is operational backlog and does not
change the recorded evidence or admit an asset.

Coverage claims use one of four explicit scopes:

- `physical_inventory`: every inventoried file, regardless of readability;
- `footer_declared`: Parquet footer metadata, including an unreadable payload;
- `canonical_readable_subset`: the deterministic canonical selection after
  excluding unreadable and byte-identical duplicate physical partitions;
- `complete_source`: a claim about the complete source, allowed only when every
  relevant partition is readable and reconciled.

The current evidence does not support a `complete_source` uniqueness or
missingness claim because one partition is unreadable.

## Asset dispositions

| Asset ID | Evidence-supported role | Phase 2 disposition |
|---|---|---|
| `pybaseball-cache-root` | Physical cache inventory | Candidate cache; unadmitted |
| `pybaseball-statcast-parquet` | Statcast partitions and schema metadata | Candidate cache; unadmitted |
| `pybaseball-chadwick-parquet` | Chadwick lookup partition | Candidate reference; unadmitted |
| `pybaseball-cache-json` | Cache metadata, including truncated files | Candidate metadata; unadmitted |
| `pybaseball-corrupt-2015-05-21` | Identified unreadable partition | Quarantined |
| `pybaseball-duplicate-date-queries` | 36 byte-identical requested-date pairs | Reconciled physical duplicates; not authoritative data |
| `pybaseball-canonical-scan` | Derived inventory evidence | Evidence only; not a data source |
| `mlb-model-duckdb` | Local rebuildable database candidate | Read-only quarantine; never opened in Phase 2 |
| `nrfi-pr1-processed-csvs` | Historical branch artifacts | Candidate historical data; unadmitted |
| `nrfi-pr1-rejected-model` | Underperforming historical model | Rejected; never champion evidence |
| `market-research-contracts` | Market semantics and safety rules | Authoritative only for stated semantics; contains no admitted prices |
| `nrfi-actions-artifacts` | Retained workflow diagnostics | Diagnostic evidence only; not data or release authority |

Every directive-required asset attribute is represented in
`docs/phase2/data_contracts.json` as exactly one of:

- `known`, with value, scope, and evidence;
- `unknown`, with a reason and admission consequence; or
- `not_applicable`, with a reason.

Filesystem modification times and cache expiry metadata are not source,
retrieval, or availability times. Git object IDs are labeled as Git identities,
not SHA-256 checksums.

## Admission policy

An asset is admitted only if all applicable gates pass:

1. source authority and use terms are verified;
2. source-record and producing-code provenance are reproducible;
3. event, source, availability, retrieval, and ingestion timing are separated;
4. schema, non-null keys, uniqueness, entity mapping, and correction rules pass;
5. coverage, continuity, season completeness, missingness, and row counts are
   validated at the stated scope;
6. corrupt and duplicate partitions have deterministic dispositions;
7. checksums and rebuildability are recorded; and
8. use cannot expose private paths, records, credentials, or locked evidence.

Unknown authority, license, provenance, availability timing, required
schema/key semantics, checksum, or corruption status fails closed. `ingested_at`
is a load timestamp only and cannot substitute for any earlier time role.

## Contract catalog

The catalog declares intended immutable identity and required time lineage. A
`partial`, `missing`, or `unsafe_partial` implementation state is not an
admission decision.

| Contract ID | Intended immutable key | Current evidence state |
|---|---|---|
| `core.first_inning_outcomes.v1` | `game_id`, `outcome_version` | Partial; label finalization and correction semantics unresolved |
| `core.game_schedule.v1` | `game_id`, `retrieval_time` | Ephemeral adapter only; no immutable snapshots |
| `reference.teams.v1` | `team_id`, `valid_from` | Missing effective-dated identity map |
| `core.probable_pitchers.v1` | `game_id`, `side`, `retrieval_time` | Ephemeral only; no announcement history |
| `core.actual_starters.v1` | `game_id`, `side`, `outcome_version` | Partial postgame extraction; persisted coverage unproved |
| `raw.pitcher_game_logs.v1` | `pitcher_id`, `game_id` | Declared loader/table only; no admitted producer |
| `raw.pitcher_inning_logs.v1` | `pitcher_id`, `game_id`, `inning` | Declared loader/table only; source quarantined |
| `raw.statcast_pitcher_daily.v1` | `pitcher_id`, `game_date` | Declared loader/table; candidate source unadmitted |
| `raw.team_game_logs.v1` | `team`, `game_id` | Declared loader/table; stable team mapping missing |
| `raw.team_inning_logs.v1` | `team`, `game_id`, `inning` | Declared loader/table; stable team mapping missing |
| `raw.batter_game_logs.v1` | `batter_id`, `game_id` | Declared loader/table only; no admitted producer |
| `raw.park_factors.v1` | `venue_id`, `calculated_through`, `source` | Unsafe partial; current storage key is not point-in-time safe |
| `raw.weather_snapshots.v1` | `game_id`, `forecast_for`, `source_time`, `source` | Consumer-only; source timing and license unknown |
| `raw.umpire_assignments.v1` | `game_id`, `role`, `source_time`, `source` | Missing point-in-time contract materialization |
| `derived.travel_rest.v1` | `game_id`, `entity_type`, `entity_id`, `as_of`, `definition_version` | Partial pitcher rest only; travel definition missing |
| `derived.bullpen_workload.v1` | `game_id`, `team_id`, `as_of`, `definition_version` | Missing |
| `core.market_prices.v1` | `snapshot_id` | Semantics only; prices and entitlement absent |
| `ml.predictions.v1` | `game_id`, `predicted_at` | Partial; cutoff, manifest, feature, model, and code lineage incomplete |
| `ml.grades.v1` | `game_id`, `predicted_at`, `grade_version` | Unsafe partial; current mutable key loses prediction/correction identity |

The catalog's column records distinguish required contract fields from current
adapter projections. A proposed key is not permission to migrate storage, and
this phase makes no label, feature, normalization, or correction decision.

## Point-in-time and provenance rules

Records must preserve applicable time roles independently:

- `event_time`: when the baseball or market event occurs;
- `source_time`: when the source created or revised the record;
- `availability_time`: earliest time the record was legitimately knowable;
- `retrieval_time`: when the adapter observed it;
- `ingestion_time`: when local storage accepted it;
- `cutoff_time`: latest admissible availability for a prediction or feature;
- `computed_time`: when a deterministic derived record was produced; and
- `finalized_time`: when an outcome became gradeable.

Every non-null time or provenance role must name a declared non-null column.
Every unavailable role carries a gap code; it is never inferred. Pregame inputs
must satisfy `availability_time <= cutoff_time < scheduled_start_at`. Grades must
join immutable prediction identity to a finalized, versioned outcome.

Minimum provenance includes source and source-record identity, adapter/version,
validation result, input manifest/checksum, and producing code commit where
applicable. Existing loaders record only caller-supplied source and load-time
ingestion, so their outputs remain unadmitted.

## Preserved quality evidence

The Statcast inventory contains 2,209 Parquet files totaling 1,452,930,951
bytes and 7,884,065 footer-declared rows. The canonical readable subset contains
7,735,266 rows, covering actual game dates 2015-04-05 through 2025-09-30,
2,172 distinct dates, 26,497 games, and 896,978 first-inning rows. The readable
subset has no duplicate audited pitch-key group and no null or invalid value in
the eight audited key fields.

Those subset results do not erase the unreadable 569,600-byte, 3,394-row-footer
partition. The 36 requested-date duplicate pairs are byte-identical and exclude
145,405 physical rows from canonical selection. Statcast has 119 columns, 75
logical schema variants, and eight recorded type-drift fields. Future-game,
post-score, event/outcome, and win-expectancy fields are leakage-sensitive raw
observations and are prohibited from pregame features without separate,
availability-safe contracts.

## Reuse, rejection, and acquisition

Reuse is evaluated before acquisition. Current proposals are limited to:

- existing StatsAPI adapters as implementation evidence for schedules, teams,
  probable pitchers, actual starters, and outcomes;
- preserved Statcast metadata for a future admitted transformation;
- current SQL, loader, and readiness declarations as draft adapter projections;
- market-research rules for market semantics only.

The dirty MLB-model repository and its database remain read-only quarantined.
The rejected historical model cannot become a champion, baseline substitute,
or admission credential. Workflow diagnostics cannot become data authority.

`docs/phase2/acquisition_plan.json` is a gap-limited proposal record. Every item
is `authorized: false`; no network call, subscription, credential use, payment,
download, or entitlement activation is approved. A proposal can advance only
after reuse is exhausted and source authority, terms, point-in-time lineage,
zero-overage status, and a storage/provenance design are approved.

## Authorized bounded development vertical slice

One development-only carve-out is authorized for the fixed 2024-04-01 through
2024-05-31 MLB sample. It may use read-only controlled repository assets and
unauthenticated HTTP GET requests to official MLB StatsAPI endpoints. It may
store normalized derived records, source references, request parameters,
retrieval and normalization timestamps, and checksums. Raw StatsAPI payloads
must not be committed or redistributed.

The slice is limited to game, team, venue, actual-starter, finalized
first-inning-outcome, provenance, rolling team/league feature, chronological
baseline, prediction, coverage, and evaluation records. Park identity may be
used, but unverified historical park-factor values may not. Weather, umpire,
lineup, injury, market-price, wagering, paid API, credentialed provider, AWS,
subscription, and production-deployment work remain unauthorized. Pybaseball
and the dirty MLB-model repository remain quarantined and must not be opened.

For this slice, MLB `gamePk` is the primary game identity. Official date, home
team, away team, doubleheader indicator, and game number are reconciliation
attributes; team and date alone never identify a game. Cancelled games are
excluded. Postponed games receive no outcome until played under an official
game identity. Suspended or resumed games retain their original identity and
scheduled-first-pitch context, use only the finalized official first-inning
result for grading, and are rejected when first-inning chronology is unclear.

`YRFI = 1` only when the finalized official record contains at least one run in
inning 1. `YRFI = 0` and `NRFI = 1` only when inning 1 is complete and both teams
have zero runs. Missing, incomplete, ambiguous, or non-final linescores are
rejected; NRFI is never inferred from missing data. Official corrections must
regrade or invalidate affected records.

Probable starter, probable-starter announcement time, prediction cutoff, actual
starter, and actual-starter confirmation time remain distinct. Actual starters
are postgame attribution only and cannot become pregame features unless a
separate recorded probable-starter snapshot proves availability before cutoff.
This initial slice omits pitcher-specific pregame features and reports that
coverage rather than backfilling actual starters.

Event, source update when supplied, retrieval, normalization, and correction
times are recorded separately. Missing publication times remain missing.
Postgame facts enter historical features only after finalized availability.
Unreadable, corrupt, duplicate, or irreconcilable records are rejected with a
reason and coverage loss; no value is fabricated. The known corrupt pybaseball
partition is outside this slice. The locked 2025 holdout remains inaccessible.

This authorization is internal technical approval, not a legal opinion. Stop if
an applicable source term explicitly prohibits the intended internal use. The
authorization does not change any other asset admission or acquisition status.

## Unresolved semantic stop boundaries

Except for the bounded slice above, do not materialize, normalize, train,
evaluate, or score an affected real-data domain until its applicable decision
is resolved:

- finalized first-inning label, correction, suspended-game, and resumed-game
  rules;
- doubleheader-safe game identity and scheduled-first-pitch identity;
- probable versus actual starter definitions and announcement cutoff;
- event, source, availability, retrieval, and correction-time semantics;
- schema-drift normalization and numeric coercion;
- park-factor cutoff and weather forecast-observation semantics;
- corrupt-partition replacement or omission policy;
- source authority, licensing, redistribution, and market entitlement;
- exact market freshness, paired-price, future-timestamp, and duplicate rules;
- any use or inspection of locked evaluation evidence.

Safe follow-on work is limited to storage-neutral schemas, immutable path
conventions, metadata-only lineage, fail-closed status handling, and synthetic
fixtures that do not encode unresolved baseball or market semantics.

## Machine-readable outputs

- `docs/phase2/data_contracts.json`
- `docs/phase2/coverage_report.json`
- `docs/phase2/schema_report.json`
- `docs/phase2/data_gap_report.json`
- `docs/phase2/reuse_plan.json`
- `docs/phase2/rejected_assets_report.json`
- `docs/phase2/acquisition_plan.json`

`tests/test_phase2_contracts.py` enforces exact IDs, required asset attributes,
explicit unknowns, evidence reconciliation, fail-closed admission, report
cross-references, acquisition authorization, and public-path/secret rules.

## Phase gate

Phase 2 passes with documented exceptions when the catalog and reports parse,
the exact 12 assets and 19 contracts reconcile, all unresolved evidence is
explicit, every candidate remains fail-closed, privacy and secret checks pass,
targeted contract tests and the complete offline suite pass, and the reviewed
package is published as a draft pull request.

This gate completes data inventory and contract governance only. It does not
make quarantined or missing data production-ready. Phase 3 real-asset
materialization remains blocked; synthetic metadata and storage-contract work
may proceed independently without touching quarantined or locked evidence.
