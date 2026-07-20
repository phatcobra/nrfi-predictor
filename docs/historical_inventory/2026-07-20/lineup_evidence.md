# Historical lineup and batting-order evidence reconciliation - 2026-07-20

Read-only classification of lawful historical lineup evidence through 2024. No
source was modified; the locked 2025 season was not inspected.

## Sources and classification

| Source | Coverage | Lineup nature | Publication/observation time | Corrections | Known before cutoff? | Classification |
| --- | --- | --- | --- | --- | --- | --- |
| MLB StatsAPI `lineups` hydration | 2026 forward (live) | Official posted batting order | Not exposed by the API; only the retrieval time is verifiable | Captured as immutable timestamped revisions by the forward collector | Yes, when observed before first pitch | ADMITTED_POINT_IN_TIME / FORWARD_ONLY |
| MLB StatsAPI boxscore/live feed (historical) | 2015-2024 | Batting order as recorded during/after the game | No pregame publication timestamp; reflects the order once the game is under way | Not a pregame feed | No | ADMITTED_STATIC_OR_POSTGAME_LABEL |
| Retrosheet event/game files | 1915-2024 (mlb-model data/retrosheet, 3.1 MB + duckdb tables) | Postgame reconstructed batting order | Postgame; no pregame publication time | Retrosheet corrections are release-versioned, not per-game pregame | No | ADMITTED_STATIC_OR_POSTGAME_LABEL (Retrosheet licence: free, attribution notice required) |
| Lahman | seasonal | Season aggregates, no per-game lineup | n/a | n/a | n/a | DUPLICATE / not lineup-relevant |

## Determination

Timestamp-verifiable historical pregame lineups (with proof the batting order
was published before the prediction cutoff) are UNAVAILABLE for 2015-2024.
Every located historical batting-order source is postgame or in-game
attribution without a pregame publication time. Postgame actual batting orders
are never treated as pregame evidence.

## Consequence (reflected in the platform)

1. Production inference uses forward-only lineup snapshots
   (signals/pregame/official-statsapi/lineups/), now live, preserving the full
   not-available -> confirmed -> revised progression with verified retrieval
   timestamps and immutable versioned storage.
2. Model development uses lineup-independent strict-prior batter aggregations
   built from lawful 2015-2024 pitch/plate-appearance event data (each batter's
   own prior-to-cutoff history), which require no historical pregame lineup.
3. Historical lineup availability is represented as explicit missingness;
   lineup_feature_eligible stays false for historical folds and true only when
   a fresh pre-cutoff forward lineup snapshot exists.

No historical lineup timestamp is fabricated. The 2025 season is not inspected.
