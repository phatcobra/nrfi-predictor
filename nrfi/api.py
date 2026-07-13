"""NRFI/YRFI prediction API (interim; v3 schema lands in Phase 3).

One serving app, deployed on Render:
    uvicorn nrfi.api:app --host 0.0.0.0 --port $PORT

Security/correctness vs the old version:
  - Mangum/Lambda removed (was never the deploy target).
  - POST routes require a Bearer token; empty token disables them (fail closed).
  - CORS pinned to configured origins; no wildcard-with-credentials.
  - Errors return generic messages (detail goes to Sentry/logs).
  - Explicit column lists; parameterized values; no SELECT *.
  - Lazy Snowflake connection; 60s in-process TTL cache on reads.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime

import sentry_sdk
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from nrfi.config import ALLOWED_ORIGINS, API_BEARER_TOKEN, TZ_ET
from nrfi.snowflake_loader import SnowflakeLoader

logger = logging.getLogger(__name__)

if os.getenv("SENTRY_DSN"):
    sentry_sdk.init(dsn=os.getenv("SENTRY_DSN"),
                    environment=os.getenv("ENV", "production"),
                    traces_sample_rate=0.1)

app = FastAPI(title="NRFI/YRFI Prediction API",
              description="Paper-mode first-inning probabilities with diagnostic "
                          "edge. Not betting advice; no staking functionality.",
              version="2.0.0-interim")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS or ["http://localhost:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

_sf: SnowflakeLoader | None = None
_cache: dict[str, tuple[float, object]] = {}
CACHE_TTL_S = 60

PREDICTION_COLS = (
    "game_id, predicted_at, game_date, home_team, away_team, "
    "home_pitcher, away_pitcher, model_version, p_yrfi, p_yrfi_market, "
    "edge, books_n, odds_age_sec, lineup_confirmed, tier, status, block_reason"
)


def sf() -> SnowflakeLoader:
    global _sf
    if _sf is None:
        _sf = SnowflakeLoader()
    return _sf


def cached(key: str, fn):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < CACHE_TTL_S:
        return hit[1]
    val = fn()
    _cache[key] = (now, val)
    return val


_bearer = HTTPBearer(auto_error=False)


def require_token(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> None:
    if not API_BEARER_TOKEN:
        raise HTTPException(status_code=503, detail="mutating routes disabled (no token configured)")
    if creds is None or creds.credentials != API_BEARER_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")


def _validate_date(d: str) -> str:
    try:
        datetime.strptime(d, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid date, use YYYY-MM-DD")
    return d


@app.get("/")
async def root():
    return {"service": "NRFI/YRFI Prediction API", "version": app.version,
            "mode": "paper", "note": "diagnostic edge display only"}


@app.get("/health")
async def health():
    db = "healthy"
    try:
        sf().execute_query("SELECT 1 AS ok")
    except Exception as e:
        logger.error(f"health check db failure: {e}")
        db = "unhealthy"
    return {"status": "healthy" if db == "healthy" else "degraded",
            "database": db, "timestamp": datetime.now(TZ_ET).isoformat()}


@app.get("/predictions/date/{date}")
async def predictions_by_date(date: str):
    date = _validate_date(date)

    def q():
        # latest prediction per game for the date
        return sf().execute_query(f"""
            SELECT {PREDICTION_COLS}
            FROM NRFI_DB.ML.PREDICTIONS
            WHERE game_date = %s
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY game_id ORDER BY predicted_at DESC) = 1
            ORDER BY game_id
        """, [date])

    try:
        rows = cached(f"pred:{date}", q)
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.error(f"predictions query failed: {e}")
        raise HTTPException(status_code=500, detail="internal error")
    return {"date": date, "count": len(rows), "predictions": rows,
            "disclaimer": "paper-mode diagnostics; not betting advice"}


@app.get("/predictions/today")
async def predictions_today():
    return await predictions_by_date(datetime.now(TZ_ET).strftime("%Y-%m-%d"))


@app.get("/predictions/game/{game_id}")
async def prediction_by_game(game_id: str):
    def q():
        return sf().execute_query(f"""
            SELECT {PREDICTION_COLS}
            FROM NRFI_DB.ML.PREDICTIONS
            WHERE game_id = %s
            ORDER BY predicted_at DESC
            LIMIT 1
        """, [game_id])

    try:
        rows = cached(f"game:{game_id}", q)
    except Exception as e:
        sentry_sdk.capture_exception(e)
        raise HTTPException(status_code=500, detail="internal error")
    if not rows:
        raise HTTPException(status_code=404, detail="no prediction for this game")
    return rows[0]


@app.get("/metrics/summary")
async def metrics_summary(window_days: int = Query(30, ge=1, le=365)):
    def q():
        return sf().execute_query("""
            SELECT COUNT(*)      AS n_graded,
                   AVG(brier)    AS brier_mean,
                   AVG(logloss)  AS logloss_mean,
                   AVG(clv)      AS clv_mean,
                   MEDIAN(clv)   AS clv_median
            FROM NRFI_DB.ML.PREDICTION_GRADES
            WHERE graded_at >= DATEADD(day, -%s, CURRENT_TIMESTAMP())
        """, [window_days])

    try:
        rows = cached(f"metrics:{window_days}", q)
    except Exception as e:
        sentry_sdk.capture_exception(e)
        raise HTTPException(status_code=500, detail="internal error")
    return {"window_days": window_days, "stats": rows[0] if rows else {}}


@app.post("/jobs/predict", dependencies=[Depends(require_token)])
async def trigger_predict(date: str | None = Query(None)):
    from nrfi.predict_daily import NFRIDailyPredictor  # lazy: heavy imports
    if date:
        _validate_date(date)
    try:
        rows = NFRIDailyPredictor().run(date)
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.error(f"predict job failed: {e}")
        raise HTTPException(status_code=500, detail="job failed")
    return {"status": "done", "scored": len(rows),
            "timestamp": datetime.now(TZ_ET).isoformat()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
