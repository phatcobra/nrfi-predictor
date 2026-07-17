"""Offline tests for model registry release guards."""

from __future__ import annotations

import pytest

from nrfi.model_registry import get_model_record, production_model_version
from nrfi.probability import (
    FINAL_PROBABILITY_PIPELINE_VERSION,
    HOLDOUT_EVIDENCE_CONTRACT_VERSION,
    OOF_EVIDENCE_CONTRACT_VERSION,
)


class FakeLoader:
    def __init__(self, responses):
        self.responses = list(responses)
        self.queries = []

    def execute_query(self, query, params=None):
        self.queries.append((query, params))
        return self.responses.pop(0)


def test_production_version_returns_registry_approved_model():
    loader = FakeLoader(
        [
            [
                {
                    "model_version": "20260713_120000",
                    "probability_pipeline_version": FINAL_PROBABILITY_PIPELINE_VERSION,
                    "oof_evidence_contract_version": OOF_EVIDENCE_CONTRACT_VERSION,
                    "holdout_evidence_contract_version": HOLDOUT_EVIDENCE_CONTRACT_VERSION,
                    "artifact_sha256": "a" * 64,
                }
            ]
        ]
    )
    assert production_model_version(loader) == "20260713_120000"
    query = loader.queries[0][0]
    assert "status = 'production'" in query
    assert "gates_passed = TRUE" in query
    assert "holdout_passed = TRUE" in query
    assert "holdout_burned_rerun" in query
    assert "probability_pipeline_version = %s" in query


def test_production_record_without_artifact_attestation_fails_closed():
    loader = FakeLoader(
        [
            [
                {
                    "model_version": "v1",
                    "probability_pipeline_version": FINAL_PROBABILITY_PIPELINE_VERSION,
                    "oof_evidence_contract_version": OOF_EVIDENCE_CONTRACT_VERSION,
                    "holdout_evidence_contract_version": HOLDOUT_EVIDENCE_CONTRACT_VERSION,
                    "artifact_sha256": None,
                }
            ]
        ]
    )
    with pytest.raises(RuntimeError, match="artifact SHA-256"):
        production_model_version(loader)


def test_missing_production_model_fails_closed():
    with pytest.raises(RuntimeError, match="no registry-approved production"):
        production_model_version(FakeLoader([[]]))


def test_model_record_is_none_when_version_is_unknown():
    assert get_model_record("missing", FakeLoader([[]])) is None


def test_model_record_passes_version_as_parameter():
    loader = FakeLoader([[{"model_version": "v1", "status": "candidate"}]])
    record = get_model_record("v1", loader)
    assert record["status"] == "candidate"
    assert loader.queries[0][1] == ["v1"]
