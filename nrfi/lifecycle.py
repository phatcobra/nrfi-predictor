"""Fail-closed factories for immutable lifecycle audit records.

Factories in this module only assemble metadata envelopes. They do not train,
score, grade, promote, deploy, repair, or roll back a runtime system.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from nrfi.lineage import (
    InputManifest,
    LineageEnvelope,
    LineageLink,
    LineageValidationError,
    artifact_relative_path,
)


class LifecyclePolicyError(LineageValidationError):
    """A lifecycle record is missing a required immutable dependency."""


@dataclass(frozen=True)
class LifecycleFields:
    """Caller-supplied, already-observed metadata for one lifecycle record."""

    identity: Mapping[str, str]
    times: Mapping[str, str | None]
    time_gaps: Mapping[str, str]
    record_checksum: str
    artifact_name: str | None = None
    artifact_sha256: str | None = None
    artifact_bytes: int | None = None
    supersedes: tuple[str, ...] = ()


class LifecycleFactory:
    """Build typed fail-closed lifecycle envelopes with explicit graph edges."""

    def __init__(
        self,
        *,
        manifest: InputManifest,
        code_commit: str,
        producer_version: str,
        validation_result: str,
    ) -> None:
        self.manifest = manifest
        self.code_commit = code_commit
        self.producer_version = producer_version
        self.validation_result = validation_result

    @staticmethod
    def _require_ids(values: Sequence[str], field: str) -> tuple[str, ...]:
        items = tuple(values)
        if not items:
            raise LifecyclePolicyError(f"{field} must contain at least one record ID")
        return items

    @staticmethod
    def _links(relation: str, record_ids: Sequence[str]) -> tuple[LineageLink, ...]:
        return tuple(LineageLink(relation, record_id) for record_id in record_ids)

    @staticmethod
    def _require_artifact(fields: LifecycleFields, record_type: str) -> None:
        if (
            fields.artifact_name is None
            or fields.artifact_sha256 is None
            or fields.artifact_bytes is None
        ):
            raise LifecyclePolicyError(f"{record_type} requires an immutable artifact")
        if fields.record_checksum != fields.artifact_sha256:
            raise LifecyclePolicyError(
                f"{record_type} record checksum must equal its artifact SHA-256"
            )

    def _build(
        self,
        record_type: str,
        fields: LifecycleFields,
        links: Sequence[LineageLink],
    ) -> LineageEnvelope:
        artifact_path = None
        if fields.artifact_name is not None and fields.artifact_sha256 is not None:
            artifact_path = artifact_relative_path(
                fields.artifact_sha256, fields.artifact_name
            )
        return LineageEnvelope(
            record_type=record_type,
            contract_id=f"lifecycle.{record_type}.v1",
            schema_version="1.0",
            identity=fields.identity,
            times=fields.times,
            time_gaps=fields.time_gaps,
            provenance={
                "adapter_version": self.producer_version,
                "code_commit": self.code_commit,
                "input_manifest_id": self.manifest.manifest_id,
                "record_checksum": fields.record_checksum,
                "source_id": None,
                "source_record_id": None,
                "validation_result": self.validation_result,
            },
            provenance_gaps={
                "source_id": "NOT_APPLICABLE_DERIVED_RECORD",
                "source_record_id": "NOT_APPLICABLE_DERIVED_RECORD",
            },
            artifact_path=artifact_path,
            artifact_sha256=fields.artifact_sha256,
            artifact_bytes=fields.artifact_bytes,
            links=tuple(links),
            supersedes=fields.supersedes,
        )

    def feature_version(
        self, fields: LifecycleFields, *, input_record_ids: Sequence[str]
    ) -> LineageEnvelope:
        inputs = self._require_ids(input_record_ids, "input_record_ids")
        return self._build("feature_version", fields, self._links("consumes", inputs))

    def experiment(
        self, fields: LifecycleFields, *, input_record_ids: Sequence[str]
    ) -> LineageEnvelope:
        inputs = self._require_ids(input_record_ids, "input_record_ids")
        return self._build("experiment", fields, self._links("consumes", inputs))

    def fold(
        self, fields: LifecycleFields, *, experiment_record_id: str
    ) -> LineageEnvelope:
        return self._build(
            "fold",
            fields,
            (LineageLink("part_of_experiment", experiment_record_id),),
        )

    def model(
        self,
        fields: LifecycleFields,
        *,
        experiment_record_id: str,
        fold_record_ids: Sequence[str],
    ) -> LineageEnvelope:
        self._require_artifact(fields, "model")
        folds = self._require_ids(fold_record_ids, "fold_record_ids")
        links = (LineageLink("produced_by_experiment", experiment_record_id),)
        links += self._links("evaluated_by_fold", folds)
        return self._build("model", fields, links)

    def calibrator(
        self,
        fields: LifecycleFields,
        *,
        model_record_id: str,
        fold_record_ids: Sequence[str],
    ) -> LineageEnvelope:
        self._require_artifact(fields, "calibrator")
        folds = self._require_ids(fold_record_ids, "fold_record_ids")
        links = (LineageLink("calibrates_model", model_record_id),)
        links += self._links("evaluated_by_fold", folds)
        return self._build("calibrator", fields, links)

    def prediction(
        self,
        fields: LifecycleFields,
        *,
        model_record_id: str,
        calibrator_record_id: str,
        feature_version_record_id: str,
    ) -> LineageEnvelope:
        return self._build(
            "prediction",
            fields,
            (
                LineageLink("uses_model", model_record_id),
                LineageLink("uses_calibrator", calibrator_record_id),
                LineageLink("uses_feature_version", feature_version_record_id),
            ),
        )

    def grade(
        self, fields: LifecycleFields, *, prediction_record_id: str
    ) -> LineageEnvelope:
        return self._build(
            "grade",
            fields,
            (LineageLink("grades_prediction", prediction_record_id),),
        )

    def wager_signal(
        self,
        fields: LifecycleFields,
        *,
        prediction_record_id: str,
        market_snapshot_record_id: str,
    ) -> LineageEnvelope:
        return self._build(
            "wager_signal",
            fields,
            (
                LineageLink("uses_prediction", prediction_record_id),
                LineageLink("uses_market_snapshot", market_snapshot_record_id),
            ),
        )

    def deployment(
        self,
        fields: LifecycleFields,
        *,
        model_record_id: str,
        calibrator_record_id: str,
    ) -> LineageEnvelope:
        return self._build(
            "deployment",
            fields,
            (
                LineageLink("deploys_model", model_record_id),
                LineageLink("deploys_calibrator", calibrator_record_id),
            ),
        )

    def incident(
        self, fields: LifecycleFields, *, deployment_record_id: str
    ) -> LineageEnvelope:
        return self._build(
            "incident",
            fields,
            (LineageLink("affects_deployment", deployment_record_id),),
        )

    def repair(
        self, fields: LifecycleFields, *, incident_record_id: str
    ) -> LineageEnvelope:
        return self._build(
            "repair",
            fields,
            (LineageLink("repairs_incident", incident_record_id),),
        )

    def rollback(
        self,
        fields: LifecycleFields,
        *,
        deployment_record_id: str,
        incident_record_id: str,
    ) -> LineageEnvelope:
        return self._build(
            "rollback",
            fields,
            (
                LineageLink("rolls_back_deployment", deployment_record_id),
                LineageLink("responds_to_incident", incident_record_id),
            ),
        )
