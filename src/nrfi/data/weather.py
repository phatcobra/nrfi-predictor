"""Optional weather enrichment via Open-Meteo (free, keyless).

Historical: archive API, one request per (venue, season) date range.
Prediction day: forecast API, one request per venue on the slate.

Strictly fail-soft: any error yields missing values, never a crashed
pipeline. The model handles missing weather natively (NaN-aware trees).
Domed/roofed parks get climate-neutral indoor defaults.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd
import requests

from nrfi.config import OPEN_METEO_ARCHIVE, OPEN_METEO_FORECAST, REQUEST_TIMEOUT

log = logging.getLogger(__name__)

INDOOR_ROOF_TYPES = {"Dome", "Retractable"}
INDOOR_TEMP_C = 21.0
HOURLY_VARS = "temperature_2m,wind_speed_10m"

WEATHER_COLUMNS = ["game_pk", "temperature_c", "wind_speed_kmh", "is_indoor_park"]


def _hourly_lookup(payload: dict[str, Any]) -> dict[str, tuple[float | None, float | None]]:
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    winds = hourly.get("wind_speed_10m") or []
    out: dict[str, tuple[float | None, float | None]] = {}
    for i, ts in enumerate(times):
        temp = temps[i] if i < len(temps) else None
        wind = winds[i] if i < len(winds) else None
        out[ts] = (temp, wind)
    return out


def _round_to_hour_utc(iso_datetime: str) -> str | None:
    try:
        ts = pd.Timestamp(iso_datetime)
        if ts.tzinfo is not None:
            ts = ts.tz_convert("UTC").tz_localize(None)
        return ts.round("h").strftime("%Y-%m-%dT%H:00")
    except (ValueError, TypeError):
        return None


def fetch_weather_for_games(
    games: pd.DataFrame,
    venues: pd.DataFrame,
    session: requests.Session | None = None,
    sleep_between: float = 0.2,
) -> pd.DataFrame:
    """Return one weather row per game_pk (fail-soft; may be partial)."""
    sess = session or requests.Session()
    venue_meta = {
        int(v.venue_id): v
        for v in venues.itertuples()
        if pd.notna(v.venue_id)
    }
    records: list[dict[str, Any]] = []
    work = games.dropna(subset=["venue_id", "game_datetime_utc"]).copy()
    work["venue_id"] = work["venue_id"].astype(int)
    work["_year"] = work["game_date"].astype(str).str[:4]

    for (venue_id, _year), group in work.groupby(["venue_id", "_year"]):
        meta = venue_meta.get(int(venue_id))
        if meta is None or pd.isna(meta.latitude) or pd.isna(meta.longitude):
            continue
        indoor = str(getattr(meta, "roof_type", "")) in INDOOR_ROOF_TYPES
        if indoor:
            for game in group.itertuples():
                records.append(
                    {
                        "game_pk": int(game.game_pk),
                        "temperature_c": INDOOR_TEMP_C,
                        "wind_speed_kmh": 0.0,
                        "is_indoor_park": 1,
                    }
                )
            continue
        start = str(group["game_date"].min())
        end = str(group["game_date"].max())
        try:
            resp = sess.get(
                OPEN_METEO_ARCHIVE,
                params={
                    "latitude": float(meta.latitude),
                    "longitude": float(meta.longitude),
                    "start_date": start,
                    "end_date": end,
                    "hourly": HOURLY_VARS,
                    "timezone": "UTC",
                },
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            lookup = _hourly_lookup(resp.json())
        except (requests.RequestException, ValueError) as err:
            log.warning("weather fetch failed for venue %s %s-%s: %s", venue_id, start, end, err)
            continue
        for game in group.itertuples():
            hour_key = _round_to_hour_utc(str(game.game_datetime_utc))
            temp, wind = lookup.get(hour_key, (None, None)) if hour_key else (None, None)
            records.append(
                {
                    "game_pk": int(game.game_pk),
                    "temperature_c": temp,
                    "wind_speed_kmh": wind,
                    "is_indoor_park": 0,
                }
            )
        if sleep_between:
            time.sleep(sleep_between)
    return pd.DataFrame(records, columns=WEATHER_COLUMNS)


def fetch_forecast_for_slate(
    games: pd.DataFrame,
    venues: pd.DataFrame,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Forecast weather for a same-day slate (fail-soft)."""
    sess = session or requests.Session()
    venue_meta = {
        int(v.venue_id): v
        for v in venues.itertuples()
        if pd.notna(v.venue_id)
    }
    records: list[dict[str, Any]] = []
    for game in games.dropna(subset=["venue_id"]).itertuples():
        meta = venue_meta.get(int(game.venue_id))
        if meta is None or pd.isna(meta.latitude) or pd.isna(meta.longitude):
            continue
        if str(getattr(meta, "roof_type", "")) in INDOOR_ROOF_TYPES:
            records.append(
                {
                    "game_pk": int(game.game_pk),
                    "temperature_c": INDOOR_TEMP_C,
                    "wind_speed_kmh": 0.0,
                    "is_indoor_park": 1,
                }
            )
            continue
        try:
            resp = sess.get(
                OPEN_METEO_FORECAST,
                params={
                    "latitude": float(meta.latitude),
                    "longitude": float(meta.longitude),
                    "hourly": HOURLY_VARS,
                    "timezone": "UTC",
                    "forecast_days": 3,
                },
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            lookup = _hourly_lookup(resp.json())
        except (requests.RequestException, ValueError) as err:
            log.warning("forecast fetch failed for venue %s: %s", game.venue_id, err)
            continue
        hour_key = _round_to_hour_utc(str(game.game_datetime_utc))
        temp, wind = lookup.get(hour_key, (None, None)) if hour_key else (None, None)
        records.append(
            {
                "game_pk": int(game.game_pk),
                "temperature_c": temp,
                "wind_speed_kmh": wind,
                "is_indoor_park": 0,
            }
        )
    return pd.DataFrame(records, columns=WEATHER_COLUMNS)
