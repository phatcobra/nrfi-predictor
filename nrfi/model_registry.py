"""Authoritative model-registry reads and guarded production promotion."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from nrfi.probability import (
    FINAL_PROBABILITY_PIPELINE_VERSION,
    HOLDOUT_EVIDENCE_CONTRACT_VERSION,
    OOF_EVIDENCE_CONTRACT_VERSION,
)
from nrfi.snowflake_loader import SnowflakeLoader

MODEL_STATUS_TABLE = "NRFI_DB.ML.MODEL_STATUS"


def get_model_record(
    version: str, loader: SnowflakeLoader | None = None
) -> dict[str, Any] | None:
    warehouse = loader or SnowflakeLoader()
    rows = warehouse.execute_query(
        f"""
        SELECT model_version, trained_at, feature_version, cv_logloss, cv_brier,
               holdout_logloss, holdout_brier, holdout_passed, gates_passed,
               holdout_burned_rerun, probability_pipeline_version,
               oof_evidence_contract_version, holdout_evidence_contract_version,
               artifact_sha256, status
        FROM {MODEL_STATUS_TABLE}
        WHERE model_version = %s
        """,
        [version],
    )
    return rows[0] if rows else None


def _valid_sha256(value: object) -> bool:
    text_value = str(value or "")
    return len(text_value) == 64 and all(
        character in "0123456789abcdef" for character in text_value
    )


def _contract_errors(record: dict[str, Any]) -> list[str]:
    errors = []
    if record.get("probability_pipeline_version") != FINAL_PROBABILITY_PIPELINE_VERSION:
        errors.append("probability pipeline version")
    if record.get("oof_evidence_contract_version") != OOF_EVIDENCE_CONTRACT_VERSION:
        errors.append("OOF evidence contract")
    if (
        record.get("holdout_evidence_contract_version")
        != HOLDOUT_EVIDENCE_CONTRACT_VERSION
    ):
        errors.append("holdout evidence contract")
    if not _valid_sha256(record.get("artifact_sha256")):
        errors.append("artifact SHA-256")
    return errors


def production_model_record(loader: SnowflakeLoader | None = None) -> dict[str, Any]:
    """Return the newest fully attested production record or fail closed."""
    warehouse = loader or SnowflakeLoader()
    rows = warehouse.execute_query(
        f"""
        SELECT model_version, probability_pipeline_version,
               oof_evidence_contract_version, holdout_evidence_contract_version,
               artifact_sha256
        FROM {MODEL_STATUS_TABLE}
        WHERE status = 'production'
          AND gates_passed = TRUE
          AND holdout_passed = TRUE
          AND COALESCE(holdout_burned_rerun, FALSE) = FALSE
          AND probability_pipeline_version = %s
          AND oof_evidence_contract_version = %s
          AND holdout_evidence_contract_version = %s
        ORDER BY trained_at DESC, model_version DESC
        LIMIT 1
        """,
        [
            FINAL_PROBABILITY_PIPELINE_VERSION,
            OOF_EVIDENCE_CONTRACT_VERSION,
            HOLDOUT_EVIDENCE_CONTRACT_VERSION,
        ],
    )
    if not rows or not rows[0].get("model_version"):
        raise RuntimeError(
            "no registry-approved production model exists; scoring refused"
        )
    errors = _contract_errors(rows[0])
    if errors:
        raise RuntimeError(
            "production model evidence is incomplete: " + ", ".join(errors)
        )
    return dict(rows[0])


def production_model_version(loader: SnowflakeLoader | None = None) -> str:
    return str(production_model_record(loader)["model_version"])


def promote_candidate(version: str, loader: SnowflakeLoader | None = None) -> None:
    """Atomically retire the old production row and promote a proven candidate."""
    warehouse = loader or SnowflakeLoader()
    record = get_model_record(version, warehouse)
    if record is None:
        raise ValueError(f"model {version} is not registered")
    if record.get("status") != "candidate":
        raise ValueError(
            f"model {version} has status {record.get('status')!r}, not 'candidate'"
        )
    if not bool(record.get("gates_passed")):
        raise ValueError("candidate failed out-of-fold evidence gates")
    if not bool(record.get("holdout_passed")):
        raise ValueError("candidate has not passed the locked holdout")
    if bool(record.get("holdout_burned_rerun")):
        raise ValueError("candidate holdout evidence was burned by re-evaluation")
    contract_errors = _contract_errors(record)
    if contract_errors:
        raise ValueError(
            "candidate evidence contract is incomplete: " + ", ".join(contract_errors)
        )

    from sqlalchemy import text

    promoted_at = datetime.now(timezone.utc).isoformat()
    with warehouse.engine.begin() as connection:
        connection.execute(
            text(
                f"UPDATE {MODEL_STATUS_TABLE} SET status = 'retired' "
                "WHERE status = 'production' AND model_version <> :version"
            ),
            {"version": version},
        )
        connection.execute(
            text(
                f"UPDATE {MODEL_STATUS_TABLE} "
                "SET status = 'production', gate_report = OBJECT_INSERT("
                "COALESCE(gate_report, OBJECT_CONSTRUCT()), 'promoted_at', "
                "TO_VARIANT(:promoted_at), TRUE) "
                "WHERE model_version = :version AND status = 'candidate' "
                "AND gates_passed = TRUE AND holdout_passed = TRUE "
                "AND COALESCE(holdout_burned_rerun, FALSE) = FALSE "
                "AND probability_pipeline_version = :pipeline_version "
                "AND oof_evidence_contract_version = :oof_contract "
                "AND holdout_evidence_contract_version = :holdout_contract "
                "AND artifact_sha256 = :artifact_sha256"
            ),
            {
                "version": version,
                "promoted_at": promoted_at,
                "pipeline_version": FINAL_PROBABILITY_PIPELINE_VERSION,
                "oof_contract": OOF_EVIDENCE_CONTRACT_VERSION,
                "holdout_contract": HOLDOUT_EVIDENCE_CONTRACT_VERSION,
                "artifact_sha256": record["artifact_sha256"],
            },
        )
        verified = (
            connection.execute(
                text(
                    f"SELECT status FROM {MODEL_STATUS_TABLE} "
                    "WHERE model_version = :version"
                ),
                {"version": version},
            )
            .mappings()
            .first()
        )
        if verified is None or verified.get("status") != "production":
            raise RuntimeError(
                "candidate changed during promotion; transaction aborted"
            )
