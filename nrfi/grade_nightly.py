"""Nightly grading: outcomes, proper scores, market movement, and drift."""

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
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            json={"title": title, "body": body, "labels": ["auto-alert"]},
            timeout=20,
        ).raise_for_status()
        logger.info(f"opened GitHub issue: {title}")
    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        logger.error(f"issue creation failed ({exc}); alert logged instead: {title}")


def grade_date(warehouse: SnowflakeLoader, date_string: str) -> int:
    """Grade the latest pre-game probability for every finalized game."""
    rows = warehouse.execute_query(
        """
        WITH latest_pred AS (
            SELECT *
            FROM NRFI_DB.ML.PREDICTIONS
            WHERE game_date = %s AND p_yrfi IS NOT NULL
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY game_id ORDER BY predicted_at DESC) = 1
        ),
        latest_book AS (
            SELECT home_team, away_team, sportsbook, yrfi_prob_novig
            FROM NRFI_DB.CORE.ODDS_SNAPSHOTS
            WHERE game_date = %s
              AND yrfi_prob_novig IS NOT NULL
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY home_team, away_team, sportsbook
                ORDER BY captured_at DESC) = 1
        ),
        closing AS (
            SELECT home_team, away_team,
                   MEDIAN(yrfi_prob_novig) AS p_close
            FROM latest_book
            GROUP BY home_team, away_team
        )
        SELECT p.game_id, p.model_version, p.p_yrfi, p.p_yrfi_market, p.edge,
               o.yrfi AS yrfi_actual, c.p_close
        FROM latest_pred p
        JOIN NRFI_DB.CORE.FIRST_INNING_OUTCOMES o
          ON o.game_id = p.game_id
        LEFT JOIN closing c
          ON c.home_team = p.home_team AND c.away_team = p.away_team
        WHERE o.yrfi IS NOT NULL
    """,
        [date_string, date_string],
    )

    grades = []
    graded_at = datetime.now(timezone.utc).isoformat()
    for row in rows:
        probability = float(row["p_yrfi"])
        if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
            logger.error(
                f"invalid stored probability for game {row['game_id']}; skipped"
            )
            continue
        actual = 1.0 if row["yrfi_actual"] else 0.0
        clipped = min(max(probability, 1e-6), 1 - 1e-6)
        clv = None
        if (
            row.get("edge") is not None
            and row.get("p_close") is not None
            and row.get("p_yrfi_market") is not None
        ):
            direction = 1.0 if float(row["edge"]) >= 0 else -1.0
            clv = direction * (float(row["p_close"]) - float(row["p_yrfi_market"]))
        grades.append(
            {
                "game_id": row["game_id"],
                "model_version": row["model_version"],
                "p_yrfi": probability,
                "yrfi_actual": bool(row["yrfi_actual"]),
                "brier": (probability - actual) ** 2,
                "logloss": -(
                    actual * math.log(clipped) + (1 - actual) * math.log(1 - clipped)
                ),
                "closing_p_yrfi_market": row.get("p_close"),
                "clv": clv,
                "graded_at": graded_at,
            }
        )
    if grades:
        warehouse.merge_upsert(
            "NRFI_DB.ML.PREDICTION_GRADES", grades, key_cols=["game_id"]
        )
    logger.info(f"graded {len(grades)} games for {date_string}")
    return len(grades)


def check_drift(warehouse: SnowflakeLoader) -> list[str]:
    alerts: list[str] = []
    recent = warehouse.execute_query(f"""
        SELECT p_yrfi, yrfi_actual
        FROM NRFI_DB.ML.PREDICTION_GRADES
        ORDER BY graded_at DESC
        LIMIT {TRAILING}
    """)
    if len(recent) >= 5 * DRIFT_MIN_N:
        probabilities = np.array([row["p_yrfi"] for row in recent], dtype=float)
        actuals = np.array([1.0 if row["yrfi_actual"] else 0.0 for row in recent])
        for lower in np.arange(0.0, 1.0, 0.1):
            mask = (probabilities >= lower) & (probabilities < lower + 0.1)
            if (
                mask.sum() >= DRIFT_MIN_N
                and abs(probabilities[mask].mean() - actuals[mask].mean()) > DRIFT_GAP
            ):
                alerts.append(
                    f"calibration drift in decile [{lower:.1f},{lower + 0.1:.1f}): "
                    f"pred {probabilities[mask].mean():.3f} vs actual "
                    f"{actuals[mask].mean():.3f} (n={int(mask.sum())})"
                )

    clv_rows = warehouse.execute_query("""
        SELECT AVG(clv) AS clv_mean, COUNT(clv) AS n
        FROM NRFI_DB.ML.PREDICTION_GRADES
        WHERE graded_at >= DATEADD(day, -30, CURRENT_TIMESTAMP())
    """)
    if (
        clv_rows
        and clv_rows[0].get("n", 0) >= 50
        and clv_rows[0].get("clv_mean") is not None
        and float(clv_rows[0]["clv_mean"]) < 0
    ):
        alerts.append(
            f"30-day mean CLV negative: {clv_rows[0]['clv_mean']:.4f} "
            f"(n={clv_rows[0]['n']})"
        )
    for alert in alerts:
        _github_issue(f"[nrfi] drift alert: {alert.split(':')[0]}", alert)
    return alerts


def evidence_readiness(warehouse: SnowflakeLoader) -> dict:
    """Report prospective evidence status without enabling downstream actions."""
    rows = warehouse.execute_query("""
        SELECT COUNT(*) AS n_graded,
               MIN(graded_at) AS first_graded,
               AVG(clv) AS clv_mean
        FROM NRFI_DB.ML.PREDICTION_GRADES
    """)
    stats = rows[0] if rows else {"n_graded": 0, "first_graded": None, "clv_mean": None}
    days = 0.0
    if stats.get("first_graded"):
        first = datetime.fromisoformat(
            str(stats["first_graded"]).replace("Z", "+00:00")
        )
        if first.tzinfo is None:
            first = first.replace(tzinfo=timezone.utc)
        days = (datetime.now(timezone.utc) - first).total_seconds() / 86400
    drift = check_drift(warehouse)
    return {
        "graded_days": round(days, 1),
        "n_graded": stats.get("n_graded", 0),
        "clv_mean": stats.get("clv_mean"),
        "drift_alerts": drift,
        "evidence_period_met": bool(
            days >= 30 and (stats.get("clv_mean") or 0) > 0 and not drift
        ),
        "note": "prospective evidence requires human review",
    }


def main() -> None:
    warehouse = SnowflakeLoader()
    yesterday = (datetime.now(TZ_ET) - timedelta(days=1)).date()
    backfill(yesterday, yesterday, sleep_s=0.1)
    grade_date(warehouse, yesterday.isoformat())
    logger.info(json.dumps(evidence_readiness(warehouse), indent=2, default=str))


if __name__ == "__main__":
    main()
