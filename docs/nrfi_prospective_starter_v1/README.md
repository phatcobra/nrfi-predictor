# NRFI_PROSPECTIVE_STARTER_V1 — forward starter-revision evidence contract

A frozen **definition** (`frozen_contract.json`, sha256 `e05a87b2…`) for
capturing immutable **forward, point-in-time** starter evidence so that
starter-dependent features (pitcher, workload) can eventually be built from the
**cutoff-known probable starter** rather than the postgame actual starter.

**Hard rule:** postgame actual starters must never be used as historical
pregame replacements; starter-workload features must be tied to the exact
selected starter snapshot observed strictly before the prediction cutoff.

Per game and per starter revision the ledger records: `game_pk`, `side`,
`player_id`, `starter_status` (probable/confirmed/withdrawn/scratched),
`probable_vs_confirmed`, `source`, `source_publication_time` (null when the
source supplies none), `observed_at` (collector time — never treated as
publication time), `prediction_cutoff`, `observed_before_cutoff`,
`superseded_by`, `withdrawn_at`, `actual_starter_after_grading` (postgame, for
divergence audit only), `probable_to_actual_match`, `revision_count`, and
`revision_latency_seconds`.

Until a cutoff-known probable-starter history exists, historical pitcher and
workload features remain **research diagnostics only**; no pitcher- or
workload-dependent historical model may be promoted. The live collector already
captures forward probable-starter snapshots; this contract formalizes the
append-only revision ledger and probable-to-actual divergence monitoring for
future starter-uncertainty modelling.

```text
PREDICTIVE SKILL NOT ESTABLISHED
NO QUALIFIED WAGER
```
