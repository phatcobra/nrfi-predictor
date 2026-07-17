# Real MLB vertical slice

This development-only slice contains normalized derived records from official
MLB StatsAPI responses for regular-season games from 2024-04-01 through
2024-05-31. Raw responses are not stored or redistributed. Quarantined local
assets and the locked 2025 holdout were not accessed.

## Coverage

- 826 finalized games accepted; 0 rejected.
- 30 team identities and 31 venue identities.
- 1,652 actual-starter records; 100% two-starter game coverage.
- 671 games with eligible strict-prior team/league features (81.23%).
- Pitcher pregame feature coverage is 0%; actual starters are postgame
  attribution only.
- 452 chronological training games and 219 out-of-sample test games using a
  2024-05-16 split.

## Probability evidence

| Metric | Team/league logistic baseline | Frozen train climatology |
|---|---:|---:|
| Log loss | 0.682488 | 0.683897 |
| Brier score | 0.244692 | 0.245386 |
| Expected calibration error | 0.014686 | n/a |

The observed improvements are 0.001408 log-loss points and 0.000694 Brier
points on this bounded renewable test period. This is development evidence, not
a production, market-edge, wagering, or locked-holdout claim.

Rebuild with:

```text
python -m nrfi.real_vertical_slice --output docs/vertical_slice \
  --start 2024-04-01 --end 2024-05-31 --split 2024-05-16 --workers 4
```

`artifact_manifest.json` records the byte count, row count, and SHA-256 of each
machine-readable derived artifact.
