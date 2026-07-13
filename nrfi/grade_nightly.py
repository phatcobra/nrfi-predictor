"""Nightly grading: outcomes -> per-game Brier/log-loss + CLV -> drift alerts.

CLV (paper-mode diagnostic): did the market move toward the model?
    clv = sign(edge_at_predict) * (p_yrfi_market_close - p_yrfi_market_at_predict)
Positive mean CLV over >=1 month + stable calibration is the evidence bar
that any future staking module is gated on. This job only measures.

Drift alert: any decile of trailing-200 graded predictions with
|mean(p) - rate(yrfi)| > 0.07 (n>=20), or 30-day mean CLV < 0.
Alerts go to logs + a GitHub issue when GH_TOKEN/GITHUB_REPO are set
(fail-open on alert DELIVERY only; the measurement itself always lands).
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta, timezone

import numpy as np

from nrfi._obs import logger, sentry_sdk
from nrfi.config import TZ_ET
from nrfi.ingest_first_inning_outcomes import backfill
from nrfi.snowflake_loader import SnowflakeLoader

DRIFT_GAP = 0.07
DRIFT_MIN_N = 20
TRAILING = 200


def _github_issue(title: str, body: str) -> None:
    token, repo = os.getenv("GH_TOKEN"), os.getenv("GITHUB_REPO")
    if not token or not repo:
        logger.warning(f"ALERT (no GH_TOKEN set, log-only): {title}")
        return
    import requests
    try:
        requests.post(
            f"https://api.github.com/repos/{repo}/issues",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json"},
            json={"title": title, "body": body, "labels": ["auto-alert"]},
            timeout=20,
        ).raise_for_status()
        logger.info(f"opened GitHub issue: {title}")
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.error(f"issue creation failed ({e}); alert logged instead: {title}")


def grade_date(sf: SnowflakeLoader, date_str: str) -> int:
    """Grade the latest pre-game prediction of every final game on a date."""
    rows = sf.execute_query("""
        WITH latest_pred AS (
            SELECT * FROM NRFI_DB.ML.PREDICTIONS
            WHERE game_date = %s AND p_yrfi IS NOT NULL
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY game_id ORDER BY predicted_at DESC) = 1
        ),
        closing AS (
            SELECT home_team, away_team,
                   MEDIAN(yrfi_prob_novig) AS p_close
            FROM NRFI_DB.CORE.ODDS_SNAPSHOTS
            WHERE game_date = %s
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY home_team, away_team, sportsbook
                ORDER BY captured_at DESC) = 1
            GROUP BY home_team, away_team
        )
        SELECT p.game_id, p.model_version, p.p_yrfi, p.p_yrfi_market, p.edge,
               o.yrfi AS yrfi_actual, c.p_close
        FROM latest_pred p
        JOIN NRFI_DB.CORE.FIRST_INNING_OUTCOMES o ON o.game_id = p.game_id
        LEFT JOIN closing c ON c.home_team = p.home_team
                           AND c.away_team = p.away_team
        WHERE o.yrfi IS NOT NULL
    """, [date_str, date_str])

    grades = []
    now = datetime.now(timezone.utc).isoformat()
    for r in rows:
        p = float(r["p_yrfi"])
        y = 1.0 if r["yrfi_actual"] else 0.0
        pc = min(max(p, 1e-6), 1 - 1e-6)
        clv = None
        if (r.get("edge") is not None and r.get("p_close") is not None
                and r.get("p_yrfi_market") is not None):
            direction = 1.0 if float(r["edge"]) >= 0 else -1.0
            clv = direction * (float(r["p_close"]) - float(r["p_yrfi_market"]))
        grades.append({
            "game_id": r["game_id"],
            "model_version": r["model_version"],
            "p_yrfi": p,
            "yrfi_actual": bool(r["yrfi_actual"]),
            "brier": (p - y) ** 2,
            "logloss": -(y * math.log(pc) + (1 - y) * math.log(1 - pc)),
            "closing_p_yrfi_market": r.get("p_close"),
            "clv": clv,
            "graded_at": now,
        })
    if grades:
        sf.merge_upsert("NRFI_DB.ML.PREDICTION_GRADES", grades,
                        key_cols=["game_id"])
    logger.info(f"graded {len(grades)} games for {date_str}")
    return len(grades)


def check_drift(sf: SnowflakeLoader) -> list[str]:
    alerts: list[str] = []
    recent = sf.execute_query(f"""
        SELECT p_yrfi, yrfi_actual FROM NRFI_DB.ML.PREDICTION_GRADES
        ORDER BY graded_at DESC LIMIT {TRAILING}
    """, [])
    if len(recent) >= 5 * DRIFT_MIN_N:
        p = np.array([r["p_yrfi"] for r in recent], dtype=float)
        y = np.array([1.0 if r["yrfi_actual"] else 0.0 for r in recent])
        for lo in np.arange(0.0, 1.0, 0.1):
            m = (p >= lo) & (p < lo + 0.1)
            if m.sum() >= DRIFT_MIN_N and abs(p[m].mean() - y[m].mean()) > DRIFT_GAP:
                alerts.append(
                    f"calibration drift in decile [{lo:.1f},{lo+0.1:.1f}): "
                    f"pred {p[m].mean():.3f} vs actual {y[m].mean():.3f} "
                    f"(n={int(m.sum())})")
    clv_rows = sf.execute_query("""
        SELECT AVG(clv) AS clv_mean, COUNT(clv) AS n
        FROM NRFI_DB.ML.PREDICTION_GRADES
        WHERE graded_at >= DATEADD(day, -30, CURRENT_TIMESTAMP())
    """, [])
    if clv_rows and clv_rows[0].get("n", 0) and clv_rows[0]["n"] >= 50 \
            and clv_rows[0]["clv_mean"] is not None \
            and float(clv_rows[0]["clv_mean"]) < 0:
        alerts.append(f"30-day mean CLV negative: {clv_rows[0]['clv_mean']:.4f} "
                      f"(n={clv_rows[0]['n']})")
    for a in alerts:
        _github_issue(f"[nrfi] drift alert: {a.split(':')[0]}", a)
    return alerts


def evidence_readiness(sf: SnowflakeLoader) -> dict:
    """The paper-mode evidence bar for the (future, human-gated) staking
    module: >=30 days graded, positive mean CLV, no active drift alerts.
    This function REPORTS readiness; it never enables anything."""
    stats = sf.execute_query("""
        SELECT COUNT(*) AS n_graded,
               MIN(graded_at) AS first_graded,
               AVG(clv) AS clv_mean
        FROM NRFI_DB.ML.PREDICTION_GRADES
    """, [])[0]
    days = 0.0
    if stats.get("first_graded"):
        first = datetime.fromisoformat(str(stats["first_graded"]).replace("Z", "+00:00"))
        if first.tzinfo is None:
            first = first.replace(tzinfo=timezone.utc)
        days = (datetime.now(timezone.utc) - first).total_seconds() / 86400
    drift = check_drift(sf)
    return {
        "graded_days": round(days, 1),
        "n_graded": stats.get("n_graded", 0),
        "clv_mean": stats.get("clv_mean"),
        "drift_alerts": drift,
        "evidence_period_met": bool(
            days >= 30 and (stats.get("clv_mean") or 0) > 0 and not drift),
        "note": "staking remains out of scope until a HUMAN reviews this evidence",
    }


def main() -> None:
    sf = SnowflakeLoader()
    yesterday = (datetime.now(TZ_ET) - timedelta(days=1)).date()
    backfill(yesterday, yesterday, sleep_s=0.1)   # labels first
    grade_date(sf, yesterday.isoformat())
    readiness = evidence_readiness(sf)
    logger.info(json.dumps(readiness, indent=2, default=str))


if __name__ == "__main__":
    main()
