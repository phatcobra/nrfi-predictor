"""Authoritative model-registry reads and guarded production promotion."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from nrfi.snowflake_loader import SnowflakeLoader

MODEL_STATUS_TABLE = "NRFI_DB.ML.MODEL_STATUS"


def get_model_record(version: str, loader: SnowflakeLoader | None = None) -> dict[str, Any] | None:
    warehouse = loader or SnowflakeLoader()
    rows = warehouse.execute_query(
        f"""
        SELECT model_version, trained_at, feature_version, cv_logloss, cv_brier,
               holdout_logloss, holdout_brier, holdout_passed, gates_passed,
               holdout_burned_rerun, status
        FROM {MODEL_STATUS_TABLE}
        WHERE model_version = %s
        """,
        [version],
    )
    return rows[0] if rows else None


def production_model_version(loader: SnowflakeLoader | None = None) -> str:
    """Return the newest approved production version or fail closed."""
    warehouse = loader or SnowflakeLoader()
    rows = warehouse.execute_query(
        f"""
        SELECT model_version
        FROM {MODEL_STATUS_TABLE}
        WHERE status = 'production'
          AND gates_passed = TRUE
          AND holdout_passed = TRUE
          AND COALESCE(holdout_burned_rerun, FALSE) = FALSE
        ORDER BY trained_at DESC, model_version DESC
        LIMIT 1
        """
    )
    if not rows or not rows[0].get("model_version"):
        raise RuntimeError(
            "no registry-approved production model exists; scoring refused")
    return str(rows[0]["model_version"])


def promote_candidate(version: str, loader: SnowflakeLoader | None = None) -> None:
    """Atomically retire the old production row and promote a proven candidate."""
    warehouse = loader or SnowflakeLoader()
    record = get_model_record(version, warehouse)
    if record is None:
        raise ValueError(f"model {version} is not registered")
    if record.get("status") != "candidate":
        raise ValueError(
            f"model {version} has status {record.get('status')!r}, not 'candidate'")
    if not bool(record.get("gates_passed")):
        raise ValueError("candidate failed out-of-fold evidence gates")
    if not bool(record.get("holdout_passed")):
        raise ValueError("candidate has not passed the locked holdout")
    if bool(record.get("holdout_burned_rerun")):
        raise ValueError("candidate holdout evidence was burned by re-evaluation")

    from sqlalchemy import text

    promoted_at = datetime.now(timezone.utc).isoformat()
    with warehouse.engine.begin() as connection:
        connection.execute(text(
            f"UPDATE {MODEL_STATUS_TABLE} SET status = 'retired' "
            "WHERE status = 'production' AND model_version <> :version"
        ), {"version": version})
        connection.execute(text(
            f"UPDATE {MODEL_STATUS_TABLE} "
            "SET status = 'production', gate_report = OBJECT_INSERT("
            "COALESCE(gate_report, OBJECT_CONSTRUCT()), 'promoted_at', "
            "TO_VARIANT(:promoted_at), TRUE) "
            "WHERE model_version = :version AND status = 'candidate' "
            "AND gates_passed = TRUE AND holdout_passed = TRUE "
            "AND COALESCE(holdout_burned_rerun, FALSE) = FALSE"
        ), {"version": version, "promoted_at": promoted_at})
        verified = connection.execute(text(
            f"SELECT status FROM {MODEL_STATUS_TABLE} "
            "WHERE model_version = :version"
        ), {"version": version}).mappings().first()
        if verified is None or verified.get("status") != "production":
            raise RuntimeError(
                "candidate changed during promotion; transaction aborted")
