"""Offline regressions for the versioned probability and holdout contracts."""

from __future__ import annotations

import hashlib
import json
import sys
from types import SimpleNamespace
from typing import cast

import numpy as np
import pandas as pd
import pytest

import nrfi.train as train_module
import scripts.evaluate_holdout as holdout_module
from nrfi.build_features import FeatureBuilder
from nrfi.probability import (
    FINAL_PROBABILITY_PIPELINE_VERSION,
    HOLDOUT_EVIDENCE_CONTRACT_VERSION,
    OOF_EVIDENCE_CONTRACT_VERSION,
    PROBABILITY_EPSILON,
    canonical_probability,
)
from nrfi.train import NFRIModelTrainer
from nrfi.venn_abers import VennAbersCalibrator


def test_canonical_probability_clips_once_and_rejects_invalid_values():
    values = canonical_probability(np.array([0.0, 0.25, 1.0]))
    assert values.tolist() == pytest.approx(
        [PROBABILITY_EPSILON, 0.25, 1.0 - PROBABILITY_EPSILON]
    )
    for invalid in (np.array([np.nan]), np.array([-0.01]), np.array([1.01])):
        with pytest.raises(ValueError):
            canonical_probability(invalid)


def test_prepare_features_preserves_loaded_feature_contract():
    class DifferentBuilder(FeatureBuilder):
        @staticmethod
        def prepare(max_date):
            assert max_date == "2026-07-02"

        @staticmethod
        def build_game(game):
            return {"unexpected": float(game["yrfi"])}

    games = pd.DataFrame(
        {
            "game_id": ["g1", "g2"],
            "game_date": ["2026-07-01", "2026-07-02"],
            "yrfi": [0, 1],
        }
    )
    trainer = NFRIModelTrainer()
    trainer.feature_names = ["expected"]
    with pytest.raises(ValueError, match="feature contract differs"):
        trainer.prepare_features(games, builder=DifferentBuilder())
    assert trainer.feature_names == ["expected"]


def test_failed_training_clears_any_previous_calibrator(monkeypatch):
    class FailingEnsemble:
        def __init__(self, purge_days):
            self.purge_days = purge_days

        @staticmethod
        def fit(X, y, dates, feature_names):
            raise RuntimeError("synthetic evidence failure")

    monkeypatch.setattr(train_module, "StackedEnsemble", FailingEnsemble)
    trainer = NFRIModelTrainer()
    trainer.calibrator = VennAbersCalibrator()
    trainer.feature_names = ["x"]
    X = np.array([[0.0], [1.0]])
    y = np.array([0, 1])
    dates = pd.Series(pd.to_datetime(["2024-06-01", "2024-06-02"]))
    kept = pd.DataFrame({"venue_id": [1, 1]})
    with pytest.raises(RuntimeError, match="synthetic evidence failure"):
        trainer.train(X, y, dates, kept)
    assert trainer.calibrator is None


def test_holdout_preflight_binds_registry_metadata_and_bundle(tmp_path):
    version = "candidate-v1"
    bundle_path = tmp_path / f"nrfi_bundle_{version}.joblib"
    bundle_path.write_bytes(b"synthetic candidate bundle")
    digest = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    metadata = {
        "version": version,
        "artifact_sha256": digest,
        "probability_pipeline_version": FINAL_PROBABILITY_PIPELINE_VERSION,
        "oof_evidence_contract_version": OOF_EVIDENCE_CONTRACT_VERSION,
        "holdout_evidence_contract_version": HOLDOUT_EVIDENCE_CONTRACT_VERSION,
        "metrics": {
            "probability_pipeline_version": FINAL_PROBABILITY_PIPELINE_VERSION,
            "oof_evidence_contract_version": OOF_EVIDENCE_CONTRACT_VERSION,
            "holdout_evidence_contract_version": HOLDOUT_EVIDENCE_CONTRACT_VERSION,
            "gates_passed": True,
            "final_probability_oof": {
                "oof_evidence_contract_version": OOF_EVIDENCE_CONTRACT_VERSION,
                "gates_passed": True,
            },
        },
    }
    (tmp_path / f"nrfi_meta_{version}.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    trainer = cast(
        NFRIModelTrainer,
        SimpleNamespace(
            config=SimpleNamespace(MODEL_DIR=str(tmp_path)),
            _sha256=NFRIModelTrainer._sha256,
        ),
    )
    existing = {
        "probability_pipeline_version": FINAL_PROBABILITY_PIPELINE_VERSION,
        "oof_evidence_contract_version": OOF_EVIDENCE_CONTRACT_VERSION,
        "holdout_evidence_contract_version": HOLDOUT_EVIDENCE_CONTRACT_VERSION,
        "artifact_sha256": digest,
    }
    loaded, actual = holdout_module._preflight_candidate(trainer, existing, version)
    assert loaded == metadata
    assert actual == digest

    existing["artifact_sha256"] = "0" * 64
    with pytest.raises(SystemExit, match="SHA-256 evidence mismatch"):
        holdout_module._preflight_candidate(trainer, existing, version)


def test_holdout_slot_is_burned_before_artifact_load(monkeypatch):
    events = []

    class FakeWarehouse:
        @staticmethod
        def execute_query(query, params=None):
            return [
                {
                    "model_version": "candidate-v1",
                    "status": "candidate",
                    "gates_passed": True,
                    "gate_report": {},
                    "holdout_evaluated_at": None,
                }
            ]

        @staticmethod
        def merge_upsert(table, rows, key_cols):
            events.append(("burn", table, rows, key_cols))

    class FakeTrainer:
        config = SimpleNamespace(
            MODEL_DIR="unused",
            HOLDOUT_START_DATE="2026-07-01",
            HOLDOUT_END_DATE="2026-07-31",
        )

        @staticmethod
        def load_model(*args, **kwargs):
            events.append(("load_model",))
            raise RuntimeError("synthetic artifact load failure")

        @staticmethod
        def load_training_data(*args, **kwargs):
            events.append(("locked_data",))
            raise AssertionError("locked data must not be opened")

    metadata = {
        "holdout_evidence_contract_version": HOLDOUT_EVIDENCE_CONTRACT_VERSION,
        "metrics": {
            "training_end": "2026-06-30",
            "baseline_constant": {"deployment_rate": 0.5},
        },
    }
    monkeypatch.setattr(holdout_module, "SnowflakeLoader", FakeWarehouse)
    monkeypatch.setattr(holdout_module, "NFRIModelTrainer", FakeTrainer)
    monkeypatch.setattr(
        holdout_module,
        "_preflight_candidate",
        lambda trainer, existing, version: (metadata, "a" * 64),
    )
    monkeypatch.setattr(
        sys, "argv", ["evaluate_holdout.py", "--version", "candidate-v1"]
    )

    with pytest.raises(RuntimeError, match="synthetic artifact load failure"):
        holdout_module.main()
    assert [event[0] for event in events] == ["burn", "load_model"]
    burned_row = events[0][2][0]
    assert burned_row["holdout_evaluated_at"]
    assert burned_row["holdout_burned_rerun"] is False


def test_non_candidate_is_rejected_before_preflight_or_locked_data(monkeypatch):
    class FakeWarehouse:
        @staticmethod
        def execute_query(query, params=None):
            return [{"model_version": "v1", "status": "production"}]

    monkeypatch.setattr(holdout_module, "SnowflakeLoader", FakeWarehouse)
    monkeypatch.setattr(
        holdout_module,
        "NFRIModelTrainer",
        lambda: SimpleNamespace(config=SimpleNamespace()),
    )
    monkeypatch.setattr(
        holdout_module,
        "_preflight_candidate",
        lambda *args: pytest.fail("preflight must not run for a non-candidate"),
    )
    monkeypatch.setattr(sys, "argv", ["evaluate_holdout.py", "--version", "v1"])
    with pytest.raises(SystemExit, match="requires candidate status"):
        holdout_module.main()
