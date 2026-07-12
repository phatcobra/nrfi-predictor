# NRFI/YRFI Walk-Forward Backtest

- Trained at (UTC): 2026-07-12T21:25:09+00:00
- Package version: 1.0.0
- Trainable rows: 19318
- Training window: 2018-03-29 → 2026-07-12
- YRFI base rate in window: 0.4992

Protocol: for each test season Y, the model is fit only on seasons
strictly before Y (features are pre-game only by construction), then
evaluated on Y. Baseline is the rolling league YRFI rate
(climatology). Positive Brier skill score = model beats climatology.

## Per-season metrics

| season   |   n_games |   yrfi_base_rate |   log_loss_model |   log_loss_baseline |   brier_model |   brier_baseline |   brier_skill_score |   roc_auc |   mean_predicted_yrfi |
|:---------|----------:|-----------------:|-----------------:|--------------------:|--------------:|-----------------:|--------------------:|----------:|----------------------:|
| 2021     |      2426 |           0.5037 |           0.6963 |              0.6934 |        0.2515 |           0.2501 |             -0.0056 |    0.5022 |                0.5140 |
| 2022     |      2429 |           0.4817 |           0.6955 |              0.6932 |        0.2508 |           0.2500 |             -0.0031 |    0.5068 |                0.5066 |
| 2023     |      2429 |           0.5019 |           0.6947 |              0.6937 |        0.2507 |           0.2503 |             -0.0018 |    0.5274 |                0.4657 |
| 2024     |      2425 |           0.4672 |           0.6946 |              0.6919 |        0.2504 |           0.2494 |             -0.0040 |    0.5105 |                0.5014 |
| 2025     |      2425 |           0.5014 |           0.6997 |              0.6938 |        0.2528 |           0.2503 |             -0.0100 |    0.5092 |                0.4683 |
| 2026     |      1438 |           0.5125 |           0.6960 |              0.6929 |        0.2509 |           0.2499 |             -0.0040 |    0.5057 |                0.4920 |
| ALL      |     13572 |           0.4934 |           0.6961 |              0.6932 |        0.2512 |           0.2500 |             -0.0048 |    0.5045 |                0.4913 |

## Calibration (pooled test predictions, by predicted decile)

| bin            |   n_games |   mean_predicted |   observed_yrfi_rate |   calibration_gap |
|:---------------|----------:|-----------------:|---------------------:|------------------:|
| (0.019, 0.462] |      2614 |           0.4461 |               0.4836 |            0.0375 |
| (0.462, 0.463] |       454 |           0.4634 |               0.4846 |            0.0212 |
| (0.463, 0.468] |      1072 |           0.4684 |               0.5103 |            0.0418 |
| (0.468, 0.484] |      2131 |           0.4783 |               0.4890 |            0.0106 |
| (0.484, 0.49]  |       530 |           0.4898 |               0.4415 |           -0.0483 |
| (0.49, 0.5]    |      1405 |           0.4987 |               0.5231 |            0.0244 |
| (0.5, 0.502]   |      1422 |           0.5015 |               0.4923 |           -0.0092 |
| (0.502, 0.512] |      1277 |           0.5114 |               0.4941 |           -0.0173 |
| (0.512, 0.541] |      1695 |           0.5300 |               0.4838 |           -0.0463 |
| (0.541, 0.98]  |       972 |           0.5606 |               0.5185 |           -0.0421 |

## Reading guide

- First-inning scoring is a low-signal event (~50/50 base rate).
  Realistic edges show up as small but consistent log-loss/Brier
  improvements over climatology and clean calibration, not high
  headline accuracy.
- `calibration_gap` near 0 across deciles means the probabilities
  can be compared to market-implied probabilities directly.
