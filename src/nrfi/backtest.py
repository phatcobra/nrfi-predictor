"""Walk-forward, season-by-season backtesting with honest baselines.

For each test season Y: fit on all seasons < Y, evaluate on Y. No test
season ever influences its own model. The skill baseline is the rolling
league YRFI rate (climatology), which any useful model must beat.

Metrics: log loss, Brier score, Brier skill score vs climatology, ROC AUC,
and a calibration table by predicted-probability decile.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from nrfi.config import TrainConfig
from nrfi.model import fit_model, trainable_rows

MIN_TRAIN_SEASONS = 3


def walk_forward_backtest(
    features_frame: pd.DataFrame,
    cfg: TrainConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Returns (per_season_metrics, pooled_predictions, calibration_table)."""
    cfg = cfg or TrainConfig()
    rows = trainable_rows(features_frame)
    seasons = sorted(int(s) for s in rows["season"].dropna().unique())
    if len(seasons) <= MIN_TRAIN_SEASONS:
        raise ValueError(
            f"need more than {MIN_TRAIN_SEASONS} seasons for walk-forward backtest, have {seasons}"
        )

    first_test = cfg.backtest_first_season or seasons[MIN_TRAIN_SEASONS]
    test_seasons = [s for s in seasons if s >= first_test]

    metric_rows = []
    prediction_frames = []
    for test_season in test_seasons:
        train = rows[rows["season"] < test_season]
        test = rows[rows["season"] == test_season]
        if train["season"].nunique() < MIN_TRAIN_SEASONS or len(test) < 100:
            continue
        model = fit_model(train, cfg)
        probs = model.predict_yrfi_proba(test)
        y = test["yrfi"].to_numpy(dtype=float)
        baseline = test["league_yrfi_rate"].to_numpy(dtype=float)

        preds = test[["game_pk", "game_date", "season"]].copy()
        preds["yrfi"] = y
        preds["p_yrfi"] = probs
        preds["p_baseline"] = baseline
        prediction_frames.append(preds)

        metric_rows.append(_season_metrics(test_season, y, probs, baseline))

    if not prediction_frames:
        raise ValueError("walk-forward backtest produced no test seasons")

    pooled = pd.concat(prediction_frames, ignore_index=True)
    metric_rows.append(
        _season_metrics(
            "ALL",
            pooled["yrfi"].to_numpy(dtype=float),
            pooled["p_yrfi"].to_numpy(dtype=float),
            pooled["p_baseline"].to_numpy(dtype=float),
        )
    )
    metrics = pd.DataFrame(metric_rows)
    calibration = calibration_table(pooled["yrfi"].to_numpy(dtype=float), pooled["p_yrfi"].to_numpy(dtype=float))
    return metrics, pooled, calibration


def _season_metrics(season: object, y: np.ndarray, p: np.ndarray, baseline: np.ndarray) -> dict:
    eps = 1e-6
    p_clip = np.clip(p, eps, 1 - eps)
    base_clip = np.clip(baseline, eps, 1 - eps)
    brier_model = brier_score_loss(y, p_clip)
    brier_base = brier_score_loss(y, base_clip)
    return {
        "season": season,
        "n_games": int(len(y)),
        "yrfi_base_rate": float(np.mean(y)),
        "log_loss_model": float(log_loss(y, p_clip)),
        "log_loss_baseline": float(log_loss(y, base_clip)),
        "brier_model": float(brier_model),
        "brier_baseline": float(brier_base),
        "brier_skill_score": float(1.0 - brier_model / brier_base) if brier_base > 0 else np.nan,
        "roc_auc": float(roc_auc_score(y, p_clip)) if len(np.unique(y)) > 1 else np.nan,
        "mean_predicted_yrfi": float(np.mean(p_clip)),
    }


def calibration_table(y: np.ndarray, p: np.ndarray, n_bins: int = 10) -> pd.DataFrame:
    """Observed vs predicted YRFI rate by predicted-probability decile."""
    frame = pd.DataFrame({"y": y, "p": p})
    try:
        frame["bin"] = pd.qcut(frame["p"], q=n_bins, duplicates="drop")
    except ValueError:
        frame["bin"] = pd.cut(frame["p"], bins=n_bins)
    grouped = frame.groupby("bin", observed=True)
    table = grouped.agg(
        n_games=("y", "size"),
        mean_predicted=("p", "mean"),
        observed_yrfi_rate=("y", "mean"),
    ).reset_index()
    table["bin"] = table["bin"].astype(str)
    table["calibration_gap"] = table["observed_yrfi_rate"] - table["mean_predicted"]
    return table


def render_backtest_report(
    metrics: pd.DataFrame,
    calibration: pd.DataFrame,
    metadata: dict,
) -> str:
    """Markdown backtest report committed to the repo by the train workflow."""
    lines = [
        "# NRFI/YRFI Walk-Forward Backtest",
        "",
        f"- Trained at (UTC): {metadata.get('trained_at_utc', 'n/a')}",
        f"- Package version: {metadata.get('package_version', 'n/a')}",
        f"- Trainable rows: {metadata.get('n_trainable_rows', 'n/a')}",
        f"- Training window: {metadata.get('train_date_min', '?')} → {metadata.get('train_date_max', '?')}",
        f"- YRFI base rate in window: {metadata.get('base_rate_yrfi', float('nan')):.4f}",
        "",
        "Protocol: for each test season Y, the model is fit only on seasons",
        "strictly before Y (features are pre-game only by construction), then",
        "evaluated on Y. Baseline is the rolling league YRFI rate",
        "(climatology). Positive Brier skill score = model beats climatology.",
        "",
        "## Per-season metrics",
        "",
        metrics.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## Calibration (pooled test predictions, by predicted decile)",
        "",
        calibration.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## Reading guide",
        "",
        "- First-inning scoring is a low-signal event (~50/50 base rate).",
        "  Realistic edges show up as small but consistent log-loss/Brier",
        "  improvements over climatology and clean calibration, not high",
        "  headline accuracy.",
        "- `calibration_gap` near 0 across deciles means the probabilities",
        "  can be compared to market-implied probabilities directly.",
        "",
    ]
    return "\n".join(lines)
