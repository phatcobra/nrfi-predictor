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
from contextlib import asynccontextmanager
from datetime import datetime

from nrfi._obs import sentry_sdk
from nrfi._posthog import capture as ph_capture
from nrfi._posthog import init as ph_init
from nrfi._posthog import shutdown as ph_shutdown
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from nrfi.config import ALLOWED_ORIGINS, API_BEARER_TOKEN, TZ_ET
from nrfi.guards import data_health, display_fields
from nrfi.snowflake_loader import SnowflakeLoader

logger = logging.getLogger(__name__)

if os.getenv("SENTRY_DSN"):
    sentry_sdk.init(dsn=os.getenv("SENTRY_DSN"),
                    environment=os.getenv("ENV", "production"),
                    traces_sample_rate=0.1)

@asynccontextmanager
async def lifespan(app: FastAPI):
    ph_init()
    yield
    ph_shutdown()


app = FastAPI(title="NRFI/YRFI Prediction API",
              description="Paper-mode first-inning probabilities with diagnostic "
                          "edge. Not betting advice; no staking functionality.",
              version="2.0.0-interim",
              lifespan=lifespan)

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
    status = "healthy" if db == "healthy" else "degraded"
    if status == "degraded":
        ph_capture("health_check_degraded", {"database": db, "endpoint": "v2"})
    return {"status": status, "database": db,
            "timestamp": datetime.now(TZ_ET).isoformat()}


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
    ph_capture("predictions_fetched", {"date": date, "count": len(rows), "endpoint": "v2"})
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
    ph_capture("metrics_viewed", {"window_days": window_days, "endpoint": "v2"})
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
    ph_capture("job_triggered", {"job": "predict", "date": date, "scored": len(rows), "endpoint": "v2"})
    return {"status": "done", "scored": len(rows),
            "timestamp": datetime.now(TZ_ET).isoformat()}


# ============================== v3 (display contract) =======================
# FIRSTFRAME renders: "NRFI x% / Market y% / Edge +-z%"; "Locks" filter =
# edge_pct >= 5 AND tier = HIGH (display-only diagnostics, not betting
# advice); header dot = meta.data_health. Null => UNAVAILABLE,
# status BLOCKED => BLOCKED. No pick/staking fields exist.

@app.get("/v3/predictions")
async def v3_predictions(date: str | None = Query(None)):
    date = _validate_date(date) if date else datetime.now(TZ_ET).strftime("%Y-%m-%d")

    def q():
        return sf().execute_query(f"""
            SELECT {PREDICTION_COLS}
            FROM NRFI_DB.ML.PREDICTIONS
            WHERE game_date = %s
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY game_id ORDER BY predicted_at DESC) = 1
            ORDER BY game_id
        """, [date])

    try:
        rows = cached(f"v3:{date}", q)
    except Exception as e:
        sentry_sdk.capture_exception(e)
        raise HTTPException(status_code=500, detail="internal error")
    games = []
    for r in rows:
        games.append({
            "game_id": r["game_id"], "date": str(r["game_date"]),
            "away": {"team": r["away_team"], "sp": r["away_pitcher"]},
            "home": {"team": r["home_team"], "sp": r["home_pitcher"]},
            "status": r["status"], "block_reason": r["block_reason"],
            **display_fields(r),
            "tier": r["tier"], "lineup_confirmed": r["lineup_confirmed"],
            "odds": {"age_sec": r["odds_age_sec"], "books_n": r["books_n"]},
            "model_version": r["model_version"],
            "generated_at": str(r["predicted_at"]),
        })
    ph_capture("predictions_fetched", {"date": date, "count": len(games), "endpoint": "v3"})
    return {"date": date, "count": len(games), "games": games,
            "meta": {"data_health": data_health(rows),
                     "mode": "paper", "display_only": True}}


@app.get("/v3/metrics/calibration")
async def v3_calibration(window_days: int = Query(30, ge=1, le=365)):
    def q():
        return sf().execute_query("""
            SELECT FLOOR(p_yrfi * 10) / 10 AS p_lo,
                   AVG(p_yrfi) AS p_mean,
                   AVG(CASE WHEN yrfi_actual THEN 1.0 ELSE 0.0 END) AS yrfi_rate,
                   COUNT(*) AS n
            FROM NRFI_DB.ML.PREDICTION_GRADES
            WHERE graded_at >= DATEADD(day, -%s, CURRENT_TIMESTAMP())
            GROUP BY 1 ORDER BY 1
        """, [window_days])

    try:
        result = {"window_days": window_days, "deciles": cached(f"cal:{window_days}", q)}
        ph_capture("calibration_viewed", {"window_days": window_days})
        return result
    except Exception as e:
        sentry_sdk.capture_exception(e)
        raise HTTPException(status_code=500, detail="internal error")


@app.get("/v3/metrics/summary")
async def v3_summary(window_days: int = Query(30, ge=1, le=365)):
    base = await metrics_summary(window_days)  # reuse interim endpoint

    def readiness():
        from nrfi.grade_nightly import evidence_readiness
        return evidence_readiness(sf())

    try:
        base["evidence_readiness"] = cached("readiness", readiness)
    except Exception as e:
        sentry_sdk.capture_exception(e)
        base["evidence_readiness"] = {"error": "unavailable"}
    return base


@app.get("/v3/health")
async def v3_health():
    out = {"snowflake": "ok", "model_registry": "unknown",
           "newest_prediction_age_s": None, "newest_odds_age_s": None}
    try:
        sf().execute_query("SELECT 1 AS ok")
    except Exception:
        out["snowflake"] = "down"
        ph_capture("health_check_degraded", {"snowflake": "down", "endpoint": "v3"})
        return {"status": "red", "checks": out}
    try:
        prod = sf().execute_query(
            "SELECT COUNT(*) AS n FROM NRFI_DB.ML.MODEL_STATUS "
            "WHERE status = 'production'")
        out["model_registry"] = "ok" if prod and prod[0]["n"] > 0 else "no_production_model"
        for key, table, col in (
                ("newest_prediction_age_s", "NRFI_DB.ML.PREDICTIONS", "predicted_at"),
                ("newest_odds_age_s", "NRFI_DB.CORE.ODDS_SNAPSHOTS", "captured_at")):
            r = sf().execute_query(
                f"SELECT TIMESTAMPDIFF(second, MAX({col}), CURRENT_TIMESTAMP()) "
                f"AS age FROM {table}")
            out[key] = r[0]["age"] if r else None
    except Exception as e:
        sentry_sdk.capture_exception(e)
    red = out["snowflake"] != "ok" or out["model_registry"] == "no_production_model"
    if red:
        ph_capture("health_check_degraded", {
            "snowflake": out["snowflake"],
            "model_registry": out["model_registry"],
            "endpoint": "v3",
        })
    return {"status": "red" if red else "green", "checks": out}


@app.post("/v3/jobs/{job}", dependencies=[Depends(require_token)])
async def v3_jobs(job: str, date: str | None = Query(None)):
    if date:
        _validate_date(date)
    try:
        if job == "predict":
            from nrfi.predict_daily import NFRIDailyPredictor
            scored = len(NFRIDailyPredictor().run(date))
            ph_capture("job_triggered", {"job": "predict", "date": date, "scored": scored, "endpoint": "v3"})
            return {"job": job, "scored": scored}
        if job == "grade":
            from nrfi.grade_nightly import grade_date
            d = date or datetime.now(TZ_ET).strftime("%Y-%m-%d")
            graded = grade_date(sf(), d)
            ph_capture("job_triggered", {"job": "grade", "date": d, "graded": graded, "endpoint": "v3"})
            return {"job": job, "graded": graded}
        if job == "ingest_odds":
            from nrfi.ingest_opticodds import ingest_date
            from datetime import date as _date
            snapshots = ingest_date(_date.fromisoformat(date) if date else None)
            ph_capture("job_triggered", {"job": "ingest_odds", "date": date, "snapshots": snapshots, "endpoint": "v3"})
            return {"job": job, "snapshots": snapshots}
    except HTTPException:
        raise
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.error(f"job {job} failed: {e}")
        raise HTTPException(status_code=500, detail="job failed")
    raise HTTPException(status_code=404, detail="unknown job")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
