"""Daily slate prediction.

Fetches the day's schedule with probable pitchers, replays stored history
through yesterday to build pre-game features, and emits calibrated
P(YRFI)/P(NRFI) per game. Games without an announced probable pitcher get
an explicit no-prediction note — pitcher identity is core signal and is
never inferred.
"""

from __future__ import annotations

import datetime as dt
import logging
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
