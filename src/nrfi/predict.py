"""Daily slate prediction.

Fetches the day's schedule with probable pitchers, replays stored history
through yesterday to build pre-game features, and emits calibrated
P(YRFI)/P(NRFI) per game. Games without an announced probable pitcher get
an explicit no-prediction note — pitcher identity is core signal and is
never inferred.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from nrfi.config import GAME_TYPE, MISSING_PROBABLE_NOTE, SPORT_ID, STATSAPI_BASE
from nrfi.data.statsapi import _get_json, parse_schedule_payload
from nrfi.features import build_slate_features
from nrfi.model import NRFIModel

log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

PREDICTION_COLUMNS = [
    "game_pk",
    "game_date",
    "game_datetime_utc",
    "away_team_name",
    "home_team_name",
    "away_probable_pitcher_name",
    "home_probable_pitcher_name",
    "venue_name",
    "p_yrfi",
    "p_nrfi",
    "model_version",
    "note",
]


def today_et() -> str:
    return dt.datetime.now(tz=ET).date().isoformat()


def fetch_slate(date: str, session: requests.Session | None = None) -> pd.DataFrame:
    sess = session or requests.Session()
    payload = _get_json(
        sess,
        f"{STATSAPI_BASE}/schedule",
        params={
            "sportId": SPORT_ID,
            "gameType": GAME_TYPE,
            "date": date,
            "hydrate": "probablePitcher",
        },
    )
    rows = parse_schedule_payload(payload)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    # Predict only games that have not started; never emit a "prediction"
    # for a game already in progress or finished.
    return frame[frame["status"] == "Preview"].reset_index(drop=True)


def predict_slate(
    history: pd.DataFrame,
    slate: pd.DataFrame,
    model: NRFIModel,
    weather: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if slate.empty:
        return pd.DataFrame(columns=PREDICTION_COLUMNS)

    feats = build_slate_features(history, slate, weather=weather)
    version = model.metadata.get("trained_at_utc", "unknown")

    out = slate[
        [
            "game_pk",
            "game_date",
            "game_datetime_utc",
            "away_team_name",
            "home_team_name",
            "away_probable_pitcher_name",
            "home_probable_pitcher_name",
            "venue_name",
        ]
    ].copy()

    has_both_pitchers = (
        slate["home_probable_pitcher_id"].notna() & slate["away_probable_pitcher_id"].notna()
    ).to_numpy()

    probs = model.predict_yrfi_proba(feats)
    out["p_yrfi"] = np.where(has_both_pitchers, np.round(probs, 4), np.nan)
    out["p_nrfi"] = np.where(has_both_pitchers, np.round(1.0 - probs, 4), np.nan)
    out["model_version"] = version
    out["note"] = np.where(has_both_pitchers, "", MISSING_PROBABLE_NOTE)
    return out[PREDICTION_COLUMNS]


def render_predictions_markdown(predictions: pd.DataFrame, date: str) -> str:
    lines = [
        f"# First-inning predictions — {date}",
        "",
        "Calibrated model probabilities for the full first inning (both",
        "halves). `p_nrfi` = P(zero runs in inning 1). These are model",
        "probabilities, not betting advice; price-aware decisions live in a",
        "separate research layer.",
        "",
    ]
    if predictions.empty:
        lines.append("No games with status Preview on this date.")
        return "\n".join(lines) + "\n"
    view = predictions[
        [
            "away_team_name",
            "home_team_name",
            "away_probable_pitcher_name",
            "home_probable_pitcher_name",
            "p_nrfi",
            "p_yrfi",
            "note",
        ]
    ].copy()
    view = view.sort_values("p_nrfi", ascending=False, na_position="last")
    lines.append(view.to_markdown(index=False))
    lines.append("")
    return "\n".join(lines)


def _clean(value: object) -> object:
    """JSON-safe scalar: NaN/NaT -> None, numpy scalars -> Python scalars."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, np.generic):
        return value.item()
    return value


def predictions_to_records(predictions: pd.DataFrame) -> list[dict]:
    """One JSON-safe dict per game, sorted by P(NRFI) descending."""
    if predictions.empty:
        return []
    ordered = predictions.sort_values("p_nrfi", ascending=False, na_position="last")
    records: list[dict] = []
    for row in ordered.to_dict("records"):
        records.append({key: _clean(val) for key, val in row.items()})
    return records


def render_predictions_json(predictions: pd.DataFrame, date: str, model: NRFIModel) -> dict:
    """The per-date payload the dashboard renders."""
    records = predictions_to_records(predictions)
    predicted = [r for r in records if r.get("p_yrfi") is not None]
    return {
        "date": date,
        "model_version": model.metadata.get("trained_at_utc", "unknown"),
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "n_games": len(records),
        "n_predicted": len(predicted),
        "games": records,
    }


def _backtest_summary(reports_dir: Path) -> dict | None:
    """Pooled walk-forward row from the committed backtest, if present."""
    path = reports_dir / "backtest_metrics.csv"
    if not path.exists():
        return None
    metrics = pd.read_csv(path)
    pooled = metrics[metrics["season"].astype(str) == "ALL"]
    if pooled.empty:
        return None
    row = pooled.iloc[0]
    keep = [
        "n_games",
        "yrfi_base_rate",
        "log_loss_model",
        "log_loss_baseline",
        "brier_model",
        "brier_baseline",
        "brier_skill_score",
        "roc_auc",
    ]
    return {col: _clean(row[col]) for col in keep if col in row}


def _calibration_rows(reports_dir: Path) -> list[dict]:
    path = reports_dir / "calibration_table.csv"
    if not path.exists():
        return []
    table = pd.read_csv(path)
    return [{key: _clean(val) for key, val in row.items()} for row in table.to_dict("records")]


def write_prediction_outputs(
    predictions: pd.DataFrame,
    date: str,
    model: NRFIModel,
    predictions_dir: Path,
    reports_dir: Path,
) -> dict:
    """Write per-date JSON and refresh the manifest the dashboard reads.

    Returns the per-date payload. The manifest (``index.json``) lists every
    stored prediction date plus the current model's walk-forward quality and
    calibration, so the UI can show trustworthiness alongside the picks.
    """
    predictions_dir.mkdir(parents=True, exist_ok=True)
    payload = render_predictions_json(predictions, date, model)
    (predictions_dir / f"{date}.json").write_text(json.dumps(payload, indent=2))

    dates = sorted(p.stem for p in predictions_dir.glob("*.json") if p.stem not in {"index", "latest"})
    manifest = {
        "generated_utc": payload["generated_utc"],
        "model_version": payload["model_version"],
        "model_metadata": {
            "trained_at_utc": model.metadata.get("trained_at_utc"),
            "train_date_min": model.metadata.get("train_date_min"),
            "train_date_max": model.metadata.get("train_date_max"),
            "n_trainable_rows": model.metadata.get("n_trainable_rows"),
            "base_rate_yrfi": model.metadata.get("base_rate_yrfi"),
            "calibrated": model.metadata.get("calibrated"),
        },
        "latest_date": dates[-1] if dates else date,
        "dates": dates,
        "backtest": _backtest_summary(reports_dir),
        "calibration": _calibration_rows(reports_dir),
    }
    (predictions_dir / "index.json").write_text(json.dumps(manifest, indent=2))
    (predictions_dir / "latest.json").write_text(json.dumps(payload, indent=2))
    return payload
