"""Synthetic lifecycle graph tests; no model, data, or runtime action occurs."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from nrfi.lifecycle import LifecycleFactory, LifecycleFields, LifecyclePolicyError
from nrfi.lineage import (
    AppendOnlyLineageStore,
    InputManifest,
    LineageEnvelope,
    ManifestEntry,
    artifact_relative_path,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _manifest() -> InputManifest:
    digest = _digest("synthetic-input")
    return InputManifest(
        contract_id="synthetic.lifecycle.inputs.v1",
        schema_version="1.0",
        entries=(
            ManifestEntry(
                path=artifact_relative_path(digest, "input.json"),
                sha256=digest,
                bytes=15,
                role="synthetic_fixture",
            ),
        ),
    )


def _factory() -> LifecycleFactory:
    return LifecycleFactory(
        manifest=_manifest(),
        code_commit="0" * 40,
        producer_version="synthetic-lifecycle-v1",
        validation_result="unadmitted_synthetic_fixture",
    )


def _fields(name: str, *, artifact: bool = False) -> LifecycleFields:
    digest = _digest(name)
    return LifecycleFields(
        identity={f"{name}_id": f"synthetic-{name}-1"},
        times={
            "availability_time": None,
            "computed_time": "2026-07-15T16:00:00Z",
            "cutoff_time": "2026-07-15T15:30:00Z",
            "event_time": "2026-07-15T19:00:00Z",
            "finalized_time": None,
            "ingestion_time": "2026-07-15T16:05:00Z",
            "retrieval_time": None,
            "source_time": None,
        },
        time_gaps={
            "availability_time": "DERIVED_FROM_INPUT_MANIFEST",
            "finalized_time": "NOT_APPLICABLE_SYNTHETIC_LIFECYCLE",
            "retrieval_time": "NOT_APPLICABLE_DERIVED_RECORD",
            "source_time": "NOT_APPLICABLE_DERIVED_RECORD",
        },
        record_checksum=digest,
        artifact_name=f"{name}.bin" if artifact else None,
        artifact_sha256=digest if artifact else None,
        artifact_bytes=len(name) if artifact else None,
    )


def _relations(envelope: LineageEnvelope) -> set[str]:
    return {link.relation for link in envelope.links}


def _source_envelope(factory: LifecycleFactory) -> LineageEnvelope:
    fields = _fields("source")
    return LineageEnvelope(
        record_type="source_snapshot",
        contract_id="synthetic.source.v1",
        schema_version="1.0",
        identity=fields.identity,
        times=fields.times,
        time_gaps=fields.time_gaps,
        provenance={
            "adapter_version": "synthetic-source-v1",
            "code_commit": "0" * 40,
            "input_manifest_id": factory.manifest.manifest_id,
            "record_checksum": fields.record_checksum,
            "source_id": "synthetic-source",
            "source_record_id": "synthetic-source-record-1",
            "validation_result": "unadmitted_synthetic_fixture",
        },
        provenance_gaps={},
    )


def test_prediction_and_evaluation_lifecycle_is_fully_linked(tmp_path: Path):
    factory = _factory()
    store = AppendOnlyLineageStore(tmp_path)

    source = _source_envelope(factory)
    feature = factory.feature_version(
        _fields("feature"), input_record_ids=[source.record_id]
    )
    experiment = factory.experiment(
        _fields("experiment"), input_record_ids=[feature.record_id]
    )
    fold = factory.fold(_fields("fold"), experiment_record_id=experiment.record_id)
    model = factory.model(
        _fields("model", artifact=True),
        experiment_record_id=experiment.record_id,
        fold_record_ids=[fold.record_id],
    )
    calibrator = factory.calibrator(
        _fields("calibrator", artifact=True),
        model_record_id=model.record_id,
        fold_record_ids=[fold.record_id],
    )
    prediction = factory.prediction(
        _fields("prediction"),
        model_record_id=model.record_id,
        calibrator_record_id=calibrator.record_id,
        feature_version_record_id=feature.record_id,
    )
    grade = factory.grade(_fields("grade"), prediction_record_id=prediction.record_id)

    assert _relations(feature) == {"consumes"}
    assert _relations(experiment) == {"consumes"}
    assert _relations(fold) == {"part_of_experiment"}
    assert _relations(model) == {"evaluated_by_fold", "produced_by_experiment"}
    assert _relations(calibrator) == {"calibrates_model", "evaluated_by_fold"}
    assert _relations(prediction) == {
        "uses_calibrator",
        "uses_feature_version",
        "uses_model",
    }
    assert _relations(grade) == {"grades_prediction"}
    assert all(
        record.admission_status == "unadmitted"
        for record in (feature, experiment, fold, model, calibrator, prediction, grade)
    )
    assert all(
        record.provenance["input_manifest_id"] == factory.manifest.manifest_id
        for record in (feature, experiment, fold, model, calibrator, prediction, grade)
    )

    store.append_manifest(factory.manifest)
    for record in (
        source,
        feature,
        experiment,
        fold,
        model,
        calibrator,
        prediction,
        grade,
    ):
        if record.artifact_path is not None:
            store.append_artifact(record.artifact_path, record.record_type.encode())
        store.append(record)
        assert store.verify(record.relative_path) == record.record()


def test_operations_lifecycle_and_wager_signal_are_linked():
    factory = _factory()
    model_id = _digest("model")
    calibrator_id = _digest("calibrator")
    prediction_id = _digest("prediction")
    market_id = _digest("market")
    deployment = factory.deployment(
        _fields("deployment"),
        model_record_id=model_id,
        calibrator_record_id=calibrator_id,
    )
    incident = factory.incident(
        _fields("incident"), deployment_record_id=deployment.record_id
    )
    repair = factory.repair(_fields("repair"), incident_record_id=incident.record_id)
    rollback = factory.rollback(
        _fields("rollback"),
        deployment_record_id=deployment.record_id,
        incident_record_id=incident.record_id,
    )
    wager = factory.wager_signal(
        _fields("wager"),
        prediction_record_id=prediction_id,
        market_snapshot_record_id=market_id,
    )

    assert _relations(deployment) == {"deploys_calibrator", "deploys_model"}
    assert _relations(incident) == {"affects_deployment"}
    assert _relations(repair) == {"repairs_incident"}
    assert _relations(rollback) == {
        "responds_to_incident",
        "rolls_back_deployment",
    }
    assert _relations(wager) == {"uses_market_snapshot", "uses_prediction"}


def test_model_and_calibrator_require_bound_artifacts():
    factory = _factory()
    with pytest.raises(LifecyclePolicyError, match="requires an immutable artifact"):
        factory.model(
            _fields("model"),
            experiment_record_id=_digest("experiment"),
            fold_record_ids=[_digest("fold")],
        )

    mismatched = LifecycleFields(
        **{
            **_fields("model", artifact=True).__dict__,
            "record_checksum": _digest("different"),
        }
    )
    with pytest.raises(LifecyclePolicyError, match="must equal"):
        factory.model(
            mismatched,
            experiment_record_id=_digest("experiment"),
            fold_record_ids=[_digest("fold")],
        )


def test_lifecycle_factories_reject_empty_or_invalid_dependencies():
    factory = _factory()
    with pytest.raises(LifecyclePolicyError, match="at least one"):
        factory.experiment(_fields("experiment"), input_record_ids=[])
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        factory.fold(_fields("fold"), experiment_record_id="not-a-record-id")
