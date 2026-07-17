"""Synthetic-only tests for immutable lineage envelopes and local fallback."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from nrfi.lineage import (
    PROVENANCE_ROLES,
    RECORD_TYPES,
    TIME_ROLES,
    AppendOnlyLineageStore,
    InputManifest,
    LineageEnvelope,
    LineageIntegrityError,
    LineageLink,
    LineageValidationError,
    ManifestEntry,
    artifact_relative_path,
    canonical_json_bytes,
)

_ARTIFACT_BYTES = b"synthetic-snapshot"
_ARTIFACT_SHA256 = hashlib.sha256(_ARTIFACT_BYTES).hexdigest()


def _envelope(**overrides) -> LineageEnvelope:
    digest = _ARTIFACT_SHA256
    values = {
        "record_type": "source_snapshot",
        "contract_id": "synthetic.source.v1",
        "schema_version": "1.0",
        "identity": {"snapshot_id": "synthetic-1"},
        "times": {
            "availability_time": "2026-07-15T11:00:00-04:00",
            "computed_time": None,
            "cutoff_time": "2026-07-15T15:30:00Z",
            "event_time": "2026-07-15T19:00:00Z",
            "finalized_time": None,
            "ingestion_time": "2026-07-15T15:10:00Z",
            "retrieval_time": "2026-07-15T15:05:00Z",
            "source_time": "2026-07-15T15:00:00Z",
        },
        "time_gaps": {
            "computed_time": "NOT_APPLICABLE_OBSERVED_RECORD",
            "finalized_time": "NOT_APPLICABLE_SOURCE_SNAPSHOT",
        },
        "provenance": {
            "adapter_version": "synthetic-adapter-v1",
            "code_commit": "0" * 40,
            "input_manifest_id": _manifest().manifest_id,
            "record_checksum": digest,
            "source_id": "synthetic-source",
            "source_record_id": "synthetic-record-1",
            "validation_result": "unadmitted_synthetic_fixture",
        },
        "provenance_gaps": {},
        "artifact_path": artifact_relative_path(digest, "snapshot.json"),
        "artifact_sha256": digest,
        "artifact_bytes": len(_ARTIFACT_BYTES),
    }
    values.update(overrides)
    return LineageEnvelope(**values)


def _manifest(reverse: bool = False) -> InputManifest:
    entries = [
        ManifestEntry(
            path=artifact_relative_path("a" * 64, "source-a.json"),
            sha256="a" * 64,
            bytes=17,
            role="source_snapshot",
        ),
        ManifestEntry(
            path=artifact_relative_path("b" * 64, "source-b.json"),
            sha256="b" * 64,
            bytes=19,
            role="source_snapshot",
        ),
    ]
    return InputManifest(
        contract_id="synthetic.inputs.v1",
        schema_version="1.0",
        entries=tuple(reversed(entries)) if reverse else tuple(entries),
    )


def test_record_vocabulary_covers_governing_immutable_classes():
    assert RECORD_TYPES == {
        "calibrator",
        "dataset",
        "deployment",
        "experiment",
        "feature_version",
        "fold",
        "grade",
        "incident",
        "market_snapshot",
        "model",
        "prediction",
        "repair",
        "rollback",
        "source_snapshot",
        "wager_signal",
    }


def test_identity_is_deterministic_and_timestamps_are_normalized():
    first = _envelope(identity={"b": "2", "a": "1"})
    second = _envelope(identity={"a": "1", "b": "2"})
    assert first.record_id == second.record_id
    assert first.times["availability_time"] == "2026-07-15T15:00:00.000000Z"
    assert first.relative_path.endswith(f"/{first.record_id}.json")
    assert canonical_json_bytes(first.record()) == canonical_json_bytes(second.record())


def test_typed_links_are_deterministic_and_strict():
    first = LineageLink("consumes", "a" * 64)
    second = LineageLink("evaluated_by_fold", "b" * 64)
    envelope = _envelope(links=(second, first))
    assert envelope.links == (first, second)
    assert envelope.record()["links"] == [first.record(), second.record()]
    with pytest.raises(LineageValidationError, match="duplicate"):
        _envelope(links=(first, first))
    with pytest.raises(LineageValidationError, match="not predeclared"):
        LineageLink("unknown_relation", "a" * 64)
    with pytest.raises(LineageValidationError, match="lowercase SHA-256"):
        LineageLink("consumes", "not-a-record-id")


def test_input_manifest_identity_is_order_independent_and_complete():
    first = _manifest()
    second = _manifest(reverse=True)
    assert first.manifest_id == second.manifest_id
    assert first.record() == second.record()
    assert first.record()["entry_count"] == 2
    assert first.record()["total_bytes"] == 36
    assert first.relative_path.endswith(f"/{first.manifest_id}.json")


def test_input_manifest_rejects_duplicate_or_mismatched_entries():
    entry = _manifest().entries[0]
    with pytest.raises(LineageValidationError, match="duplicate paths"):
        InputManifest(
            contract_id="synthetic.inputs.v1",
            schema_version="1.0",
            entries=(entry, entry),
        )
    with pytest.raises(LineageValidationError, match="content-addressed"):
        ManifestEntry(
            path=artifact_relative_path("a" * 64, "source.json"),
            sha256="b" * 64,
            bytes=1,
            role="source_snapshot",
        )


def test_every_time_and_provenance_role_is_explicit():
    envelope = _envelope()
    assert set(envelope.times) == set(TIME_ROLES)
    assert set(envelope.provenance) == set(PROVENANCE_ROLES)

    missing_time = dict(envelope.times)
    missing_time.pop("source_time")
    with pytest.raises(LineageValidationError, match="every time role"):
        _envelope(times=missing_time)

    unavailable_time = dict(envelope.times)
    unavailable_time["source_time"] = None
    with pytest.raises(LineageValidationError, match="explicit gap"):
        _envelope(times=unavailable_time)

    unavailable = dict(envelope.provenance)
    unavailable["source_record_id"] = None
    with pytest.raises(LineageValidationError, match="explicit gap"):
        _envelope(provenance=unavailable)
    accepted = _envelope(
        provenance=unavailable,
        provenance_gaps={"source_record_id": "SOURCE_RECORD_ID_UNKNOWN"},
    )
    assert accepted.provenance["source_record_id"] is None


@pytest.mark.parametrize(
    ("earlier_role", "later_role"),
    [
        ("source_time", "availability_time"),
        ("availability_time", "retrieval_time"),
        ("retrieval_time", "ingestion_time"),
        ("availability_time", "cutoff_time"),
    ],
)
def test_fail_closed_status_and_temporal_order_are_enforced(earlier_role, later_role):
    with pytest.raises(LineageValidationError, match="cannot create an admitted"):
        _envelope(admission_status="admitted")

    times = dict(_envelope().times)
    times[earlier_role] = "2026-07-15T18:00:00Z"
    times[later_role] = "2026-07-15T17:00:00Z"
    if later_role == "cutoff_time":
        times["retrieval_time"] = "2026-07-15T18:30:00Z"
        times["ingestion_time"] = "2026-07-15T18:45:00Z"
    with pytest.raises(LineageValidationError, match=f"after {later_role}"):
        _envelope(times=times)


def test_artifact_paths_are_relative_and_content_addressed():
    digest = "b" * 64
    assert artifact_relative_path(digest, "artifact.bin") == (
        f"artifacts/sha256/bb/{digest}/artifact.bin"
    )
    with pytest.raises(LineageValidationError, match="content-addressed"):
        _envelope(artifact_path="artifacts/snapshot.json")
    with pytest.raises(LineageValidationError, match="public POSIX relative path"):
        _envelope(artifact_path="C:\\private\\snapshot.json")
    with pytest.raises(LineageValidationError, match="record checksum"):
        _envelope(
            artifact_path=artifact_relative_path(digest, "artifact.bin"),
            artifact_sha256=digest,
            artifact_bytes=1,
        )


def test_private_paths_and_non_sha_record_checksums_are_rejected():
    with pytest.raises(LineageValidationError, match="public alias"):
        _envelope(identity={"snapshot_id": "C:\\Users\\private\\asset.json"})
    provenance = dict(_envelope().provenance)
    provenance["record_checksum"] = "not-a-sha256"
    with pytest.raises(LineageValidationError, match="lowercase SHA-256"):
        _envelope(provenance=provenance)
    provenance = dict(_envelope().provenance)
    provenance["input_manifest_id"] = "not-a-manifest-sha256"
    with pytest.raises(LineageValidationError, match="lowercase SHA-256"):
        _envelope(provenance=provenance)


def test_append_only_store_is_idempotent_and_detects_tampering(tmp_path: Path):
    store = AppendOnlyLineageStore(tmp_path / "private-local-root")
    envelope = _envelope()
    store.append_manifest(_manifest())
    store.append_artifact(envelope.artifact_path or "", _ARTIFACT_BYTES)
    relative = store.append(envelope)
    assert relative == envelope.relative_path
    assert "private-local-root" not in relative
    assert store.append(envelope) == relative
    assert store.verify(relative) == envelope.record()

    stored = (tmp_path / "private-local-root").joinpath(*relative.split("/"))
    record = json.loads(stored.read_text(encoding="utf-8"))
    record["identity"]["snapshot_id"] = "tampered"
    stored.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(LineageIntegrityError, match="canonical|identity"):
        store.verify(relative)
    with pytest.raises(LineageIntegrityError, match="overwrite refused"):
        store.append(envelope)


def test_manifest_store_is_append_only_and_verified(tmp_path: Path):
    store = AppendOnlyLineageStore(tmp_path)
    manifest = _manifest()
    relative = store.append_manifest(manifest)
    assert store.append_manifest(manifest) == relative
    assert store.verify_manifest(relative) == manifest.record()

    stored = tmp_path.joinpath(*relative.split("/"))
    record = json.loads(stored.read_text(encoding="utf-8"))
    record["total_bytes"] += 1
    stored.write_bytes(canonical_json_bytes(record))
    with pytest.raises(LineageIntegrityError, match="identity"):
        store.verify_manifest(relative)


def test_artifact_store_is_append_only_and_content_verified(tmp_path: Path):
    store = AppendOnlyLineageStore(tmp_path)
    path = artifact_relative_path(_ARTIFACT_SHA256, "snapshot.json")
    assert store.append_artifact(path, _ARTIFACT_BYTES) == path
    assert store.append_artifact(path, _ARTIFACT_BYTES) == path
    assert store.verify_artifact(path) == _ARTIFACT_BYTES

    with pytest.raises(LineageIntegrityError, match="content-addressed"):
        store.append_artifact(path, b"different")
    stored = tmp_path.joinpath(*path.split("/"))
    stored.write_bytes(b"tampered")
    with pytest.raises(LineageIntegrityError, match="content-addressed"):
        store.verify_artifact(path)


def test_store_rejects_path_traversal(tmp_path: Path):
    store = AppendOnlyLineageStore(tmp_path)
    with pytest.raises(LineageValidationError, match="traverse"):
        store.verify("../private-record.json")


def test_verify_rejects_self_hashed_but_semantically_invalid_record(tmp_path: Path):
    store = AppendOnlyLineageStore(tmp_path)
    record = _envelope().record()
    record["admission_status"] = "admitted"
    payload = dict(record)
    payload.pop("record_id")
    from nrfi.lineage import sha256_hex

    record_id = sha256_hex(canonical_json_bytes(payload))
    record["record_id"] = record_id
    relative = f"lineage/v1/source_snapshot/{record_id[:2]}/{record_id}.json"
    destination = tmp_path.joinpath(*relative.split("/"))
    destination.parent.mkdir(parents=True)
    destination.write_bytes(canonical_json_bytes(record))
    with pytest.raises(LineageIntegrityError, match="validation failed"):
        store.verify(relative)


def test_store_refuses_existing_symlink_escape(tmp_path: Path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    outside.mkdir()
    store = AppendOnlyLineageStore(root)
    store.append_manifest(_manifest())
    envelope = _envelope()
    store.append_artifact(envelope.artifact_path or "", _ARTIFACT_BYTES)
    try:
        (root / "lineage").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable in this environment")
    with pytest.raises(LineageIntegrityError, match="escapes"):
        store.append(envelope)


def test_store_rejects_missing_manifest_and_dangling_links(tmp_path: Path):
    store = AppendOnlyLineageStore(tmp_path)
    with pytest.raises(LineageIntegrityError, match="input manifest"):
        store.append(_envelope())

    store.append_manifest(_manifest())
    store.append_artifact(_envelope().artifact_path or "", _ARTIFACT_BYTES)
    linked = _envelope(links=(LineageLink("consumes", "f" * 64),))
    with pytest.raises(LineageIntegrityError, match="linked lineage record"):
        store.append(linked)


def test_json_schema_is_public_and_parseable():
    schema_root = Path(__file__).resolve().parents[1] / "schemas"
    expected = {
        "input-manifest-v1.schema.json": (
            "https://schemas.nrfi.local/input-manifest-v1.schema.json"
        ),
        "lineage-envelope-v1.schema.json": (
            "https://schemas.nrfi.local/lineage-envelope-v1.schema.json"
        ),
    }
    for name, identifier in expected.items():
        content = (schema_root / name).read_text(encoding="utf-8")
        assert json.loads(content)["$id"] == identifier
        assert "C:\\Users\\" not in content
