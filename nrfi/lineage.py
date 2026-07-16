"""Storage-neutral, append-only lineage envelopes.

This module records metadata only. It does not admit data, interpret baseball
semantics, open source assets, or authorize a network operation. Every unknown
time or provenance role remains explicit and all records fail closed in an
unadmitted, quarantined, or rejected state.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping

LINEAGE_ENVELOPE_VERSION = "nrfi.lineage.v1"
INPUT_MANIFEST_VERSION = "nrfi.input-manifest.v1"

RECORD_TYPES = frozenset(
    {
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
)

LINK_RELATIONS = frozenset(
    {
        "affects_deployment",
        "calibrates_model",
        "consumes",
        "deploys_calibrator",
        "deploys_model",
        "evaluated_by_fold",
        "grades_prediction",
        "part_of_experiment",
        "produced_by_experiment",
        "repairs_incident",
        "responds_to_incident",
        "rolls_back_deployment",
        "uses_calibrator",
        "uses_feature_version",
        "uses_market_snapshot",
        "uses_model",
        "uses_prediction",
    }
)

TIME_ROLES = (
    "availability_time",
    "computed_time",
    "cutoff_time",
    "event_time",
    "finalized_time",
    "ingestion_time",
    "retrieval_time",
    "source_time",
)

PROVENANCE_ROLES = (
    "adapter_version",
    "code_commit",
    "input_manifest_id",
    "record_checksum",
    "source_id",
    "source_record_id",
    "validation_result",
)

FAIL_CLOSED_STATUSES = frozenset({"quarantined", "rejected", "unadmitted"})

_SHA256 = re.compile(r"[0-9a-f]{64}")
_SAFE_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_GAP_CODE = re.compile(r"[A-Z0-9][A-Z0-9_-]{1,127}")
_WINDOWS_ABSOLUTE = re.compile(r"[A-Za-z]:[\\/]")


class LineageValidationError(ValueError):
    """The requested envelope is incomplete, unsafe, or internally inconsistent."""


class LineageIntegrityError(RuntimeError):
    """Stored lineage bytes do not match their content identity."""


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    """Return the sole canonical JSON representation used for lineage identity."""
    try:
        text = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise LineageValidationError("lineage payload is not canonical JSON") from exc
    return (text + "\n").encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_sha256(value: str, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise LineageValidationError(f"{field} must be lowercase SHA-256")
    return value


def _require_segment(value: str, field: str) -> str:
    if not isinstance(value, str) or _SAFE_SEGMENT.fullmatch(value) is None:
        raise LineageValidationError(f"{field} is not a safe public identifier")
    return value


def _require_gap_code(value: str, field: str) -> str:
    if not isinstance(value, str) or _GAP_CODE.fullmatch(value) is None:
        raise LineageValidationError(f"{field} must be an explicit gap code")
    return value


def _reject_private_path(value: str, field: str) -> str:
    if (
        _WINDOWS_ABSOLUTE.match(value)
        or value.startswith(("/", "\\\\", "~/", "~\\"))
        or "\\Users\\" in value
        or "/home/" in value
    ):
        raise LineageValidationError(f"{field} must use a public alias, not a path")
    return value


def _utc_timestamp(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LineageValidationError(f"{field} must be a timestamp string")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise LineageValidationError(f"{field} is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LineageValidationError(f"{field} must include a UTC offset")
    normalized = parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")
    return normalized.replace("+00:00", "Z")


def _public_relative_path(value: str, field: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise LineageValidationError(f"{field} must use a public POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise LineageValidationError(f"{field} must not be absolute or traverse")
    if any(_SAFE_SEGMENT.fullmatch(part) is None for part in path.parts):
        raise LineageValidationError(f"{field} contains an unsafe path segment")
    return path


def artifact_relative_path(digest: str, name: str) -> str:
    """Return the immutable public path for a content-addressed artifact."""
    digest = _require_sha256(digest, "artifact_sha256")
    name = _require_segment(name, "artifact name")
    return f"artifacts/sha256/{digest[:2]}/{digest}/{name}"


def _freeze_mapping(value: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LineageValidationError(f"{field} must be a mapping")
    return MappingProxyType(dict(value))


@dataclass(frozen=True, order=True)
class ManifestEntry:
    """One immutable, public, content-addressed manifest input."""

    path: str
    sha256: str
    bytes: int
    role: str

    def __post_init__(self) -> None:
        path = _public_relative_path(self.path, "manifest entry path")
        digest = _require_sha256(self.sha256, "manifest entry SHA-256")
        if str(path) != artifact_relative_path(digest, path.name):
            raise LineageValidationError(
                "manifest entry path must use the content-addressed convention"
            )
        if (
            not isinstance(self.bytes, int)
            or isinstance(self.bytes, bool)
            or self.bytes < 0
        ):
            raise LineageValidationError("manifest entry bytes must be nonnegative")
        _require_segment(self.role, "manifest entry role")

    def record(self) -> dict[str, Any]:
        return {
            "bytes": self.bytes,
            "path": self.path,
            "role": self.role,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class InputManifest:
    """Deterministic identity for the exact artifact set consumed by a record."""

    contract_id: str
    schema_version: str
    entries: tuple[ManifestEntry, ...]

    def __post_init__(self) -> None:
        _require_segment(self.contract_id, "manifest contract_id")
        _require_segment(self.schema_version, "manifest schema_version")
        entries = tuple(self.entries)
        if not entries:
            raise LineageValidationError(
                "input manifest must contain at least one entry"
            )
        if any(not isinstance(entry, ManifestEntry) for entry in entries):
            raise LineageValidationError("input manifest entries must be ManifestEntry")
        paths = [entry.path for entry in entries]
        if len(paths) != len(set(paths)):
            raise LineageValidationError("input manifest contains duplicate paths")
        object.__setattr__(
            self, "entries", tuple(sorted(entries, key=lambda item: item.path))
        )

    def payload(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "entries": [entry.record() for entry in self.entries],
            "entry_count": len(self.entries),
            "manifest_version": INPUT_MANIFEST_VERSION,
            "schema_version": self.schema_version,
            "total_bytes": sum(entry.bytes for entry in self.entries),
        }

    @property
    def manifest_id(self) -> str:
        return sha256_hex(canonical_json_bytes(self.payload()))

    def record(self) -> dict[str, Any]:
        return {"manifest_id": self.manifest_id, **self.payload()}

    @property
    def relative_path(self) -> str:
        return f"manifests/v1/{self.manifest_id[:2]}/{self.manifest_id}.json"

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "InputManifest":
        expected_fields = {
            "contract_id",
            "entries",
            "entry_count",
            "manifest_id",
            "manifest_version",
            "schema_version",
            "total_bytes",
        }
        if set(record) != expected_fields:
            raise LineageValidationError("input manifest fields do not match v1")
        if record.get("manifest_version") != INPUT_MANIFEST_VERSION:
            raise LineageValidationError("input manifest version is unsupported")
        try:
            entries = tuple(ManifestEntry(**entry) for entry in record["entries"])
            manifest = cls(
                contract_id=record["contract_id"],
                schema_version=record["schema_version"],
                entries=entries,
            )
        except (KeyError, TypeError) as exc:
            raise LineageValidationError(
                "input manifest value types are invalid"
            ) from exc
        if manifest.record() != dict(record):
            raise LineageIntegrityError("input manifest identity is inconsistent")
        return manifest


@dataclass(frozen=True, order=True)
class LineageLink:
    """A typed immutable edge to another content-addressed lineage record."""

    relation: str
    target_record_id: str

    def __post_init__(self) -> None:
        if self.relation not in LINK_RELATIONS:
            raise LineageValidationError("lineage link relation is not predeclared")
        _require_sha256(self.target_record_id, "lineage link target_record_id")

    def record(self) -> dict[str, str]:
        return {
            "relation": self.relation,
            "target_record_id": self.target_record_id,
        }


@dataclass(frozen=True)
class LineageEnvelope:
    """A deterministic metadata envelope with no implicit time or provenance."""

    record_type: str
    contract_id: str
    schema_version: str
    identity: Mapping[str, str]
    times: Mapping[str, str | None]
    time_gaps: Mapping[str, str]
    provenance: Mapping[str, str | None]
    provenance_gaps: Mapping[str, str]
    admission_status: str = "unadmitted"
    artifact_path: str | None = None
    artifact_sha256: str | None = None
    artifact_bytes: int | None = None
    links: tuple[LineageLink, ...] = ()
    supersedes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.record_type not in RECORD_TYPES:
            raise LineageValidationError("record_type is not predeclared")
        _require_segment(self.contract_id, "contract_id")
        _require_segment(self.schema_version, "schema_version")
        if self.admission_status not in FAIL_CLOSED_STATUSES:
            raise LineageValidationError(
                "lineage foundation cannot create an admitted record"
            )

        identity = _freeze_mapping(self.identity, "identity")
        if not identity:
            raise LineageValidationError("identity must not be empty")
        for key, value in identity.items():
            _require_segment(str(key), "identity key")
            if not isinstance(value, str) or not value.strip():
                raise LineageValidationError("identity values must be nonempty strings")
            _reject_private_path(value, f"identity.{key}")

        raw_times = _freeze_mapping(self.times, "times")
        if set(raw_times) != set(TIME_ROLES):
            raise LineageValidationError("times must declare every time role exactly")
        normalized_times: dict[str, str | None] = {}
        for role in TIME_ROLES:
            value = raw_times[role]
            normalized_times[role] = (
                None if value is None else _utc_timestamp(str(value), role)
            )

        time_gaps = _freeze_mapping(self.time_gaps, "time_gaps")
        expected_time_gaps = {
            role for role, value in normalized_times.items() if value is None
        }
        if set(time_gaps) != expected_time_gaps:
            raise LineageValidationError(
                "each unavailable time role must have exactly one explicit gap"
            )
        for role, gap in time_gaps.items():
            _require_gap_code(str(gap), f"time_gaps.{role}")

        provenance = _freeze_mapping(self.provenance, "provenance")
        if set(provenance) != set(PROVENANCE_ROLES):
            raise LineageValidationError(
                "provenance must declare every provenance role exactly"
            )
        for role, value in provenance.items():
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise LineageValidationError(
                    f"provenance.{role} must be nonempty or explicitly unavailable"
                )
            if value is not None:
                _reject_private_path(value, f"provenance.{role}")
        checksum = provenance["record_checksum"]
        if checksum is not None:
            _require_sha256(checksum, "provenance.record_checksum")
        manifest_id = provenance["input_manifest_id"]
        if manifest_id is not None:
            _require_sha256(manifest_id, "provenance.input_manifest_id")
        provenance_gaps = _freeze_mapping(self.provenance_gaps, "provenance_gaps")
        expected_provenance_gaps = {
            role for role, value in provenance.items() if value is None
        }
        if set(provenance_gaps) != expected_provenance_gaps:
            raise LineageValidationError(
                "each unavailable provenance role must have exactly one explicit gap"
            )
        for role, gap in provenance_gaps.items():
            _require_gap_code(str(gap), f"provenance_gaps.{role}")

        artifact_values = (
            self.artifact_path,
            self.artifact_sha256,
            self.artifact_bytes,
        )
        if any(value is not None for value in artifact_values):
            if any(value is None for value in artifact_values):
                raise LineageValidationError(
                    "artifact path, SHA-256, and byte size must be declared together"
                )
            digest = _require_sha256(str(self.artifact_sha256), "artifact_sha256")
            if checksum != digest:
                raise LineageValidationError(
                    "provenance record checksum must equal artifact SHA-256"
                )
            path = _public_relative_path(str(self.artifact_path), "artifact_path")
            if str(path) != artifact_relative_path(digest, path.name):
                raise LineageValidationError(
                    "artifact_path must use the content-addressed convention"
                )
            if (
                not isinstance(self.artifact_bytes, int)
                or isinstance(self.artifact_bytes, bool)
                or self.artifact_bytes < 0
            ):
                raise LineageValidationError("artifact_bytes must be nonnegative")

        supersedes = tuple(self.supersedes)
        if len(supersedes) != len(set(supersedes)):
            raise LineageValidationError("supersedes contains duplicate record IDs")
        for record_id in supersedes:
            _require_sha256(record_id, "supersedes record ID")

        links = tuple(self.links)
        if any(not isinstance(link, LineageLink) for link in links):
            raise LineageValidationError("links must contain LineageLink values")
        link_keys = [(link.relation, link.target_record_id) for link in links]
        if len(link_keys) != len(set(link_keys)):
            raise LineageValidationError("links contain duplicate typed edges")
        links = tuple(sorted(links))

        for earlier_role, later_role in (
            ("source_time", "availability_time"),
            ("availability_time", "retrieval_time"),
            ("retrieval_time", "ingestion_time"),
            ("availability_time", "cutoff_time"),
        ):
            earlier = normalized_times[earlier_role]
            later = normalized_times[later_role]
            if earlier is None or later is None:
                continue
            earlier_value = datetime.fromisoformat(earlier.replace("Z", "+00:00"))
            later_value = datetime.fromisoformat(later.replace("Z", "+00:00"))
            if earlier_value > later_value:
                raise LineageValidationError(
                    f"{earlier_role} must not be after {later_role}"
                )

        object.__setattr__(self, "identity", identity)
        object.__setattr__(self, "times", MappingProxyType(normalized_times))
        object.__setattr__(self, "time_gaps", time_gaps)
        object.__setattr__(self, "provenance", provenance)
        object.__setattr__(self, "provenance_gaps", provenance_gaps)
        object.__setattr__(self, "links", links)
        object.__setattr__(self, "supersedes", supersedes)

    def payload(self) -> dict[str, Any]:
        artifact = None
        if self.artifact_path is not None:
            artifact = {
                "bytes": self.artifact_bytes,
                "path": self.artifact_path,
                "sha256": self.artifact_sha256,
            }
        return {
            "admission_status": self.admission_status,
            "artifact": artifact,
            "contract_id": self.contract_id,
            "envelope_version": LINEAGE_ENVELOPE_VERSION,
            "identity": dict(self.identity),
            "links": [link.record() for link in self.links],
            "provenance": dict(self.provenance),
            "provenance_gaps": dict(self.provenance_gaps),
            "record_type": self.record_type,
            "schema_version": self.schema_version,
            "supersedes": list(self.supersedes),
            "time_gaps": dict(self.time_gaps),
            "times": dict(self.times),
        }

    @property
    def record_id(self) -> str:
        return sha256_hex(canonical_json_bytes(self.payload()))

    def record(self) -> dict[str, Any]:
        return {"record_id": self.record_id, **self.payload()}

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "LineageEnvelope":
        expected_fields = {
            "admission_status",
            "artifact",
            "contract_id",
            "envelope_version",
            "identity",
            "links",
            "provenance",
            "provenance_gaps",
            "record_id",
            "record_type",
            "schema_version",
            "supersedes",
            "time_gaps",
            "times",
        }
        if set(record) != expected_fields:
            raise LineageValidationError("lineage record fields do not match v1")
        if record.get("envelope_version") != LINEAGE_ENVELOPE_VERSION:
            raise LineageValidationError("lineage envelope version is unsupported")
        artifact = record.get("artifact")
        if artifact is not None:
            if not isinstance(artifact, Mapping) or set(artifact) != {
                "bytes",
                "path",
                "sha256",
            }:
                raise LineageValidationError("artifact fields do not match v1")
        try:
            envelope = cls(
                record_type=record["record_type"],
                contract_id=record["contract_id"],
                schema_version=record["schema_version"],
                identity=record["identity"],
                links=tuple(LineageLink(**link) for link in record["links"]),
                times=record["times"],
                time_gaps=record["time_gaps"],
                provenance=record["provenance"],
                provenance_gaps=record["provenance_gaps"],
                admission_status=record["admission_status"],
                artifact_path=None if artifact is None else artifact["path"],
                artifact_sha256=None if artifact is None else artifact["sha256"],
                artifact_bytes=None if artifact is None else artifact["bytes"],
                supersedes=tuple(record["supersedes"]),
            )
        except (KeyError, TypeError) as exc:
            raise LineageValidationError(
                "lineage record value types are invalid"
            ) from exc
        if envelope.record() != dict(record):
            raise LineageIntegrityError("lineage record identity is inconsistent")
        return envelope

    @property
    def relative_path(self) -> str:
        return (
            f"lineage/v1/{self.record_type}/{self.record_id[:2]}/{self.record_id}.json"
        )


class AppendOnlyLineageStore:
    """Local fallback store with content identity and no update/delete surface."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def _destination(self, relative: PurePosixPath) -> Path:
        resolved_root = self.root.resolve()
        destination = resolved_root.joinpath(*relative.parts)
        if not destination.resolve(strict=False).is_relative_to(resolved_root):
            raise LineageIntegrityError("lineage storage path escapes its root")
        return destination

    def _append_record(self, relative_path: str, record: Mapping[str, Any]) -> str:
        return self._append_bytes(relative_path, canonical_json_bytes(record))

    def _append_bytes(self, relative_path: str, expected: bytes) -> str:
        relative = _public_relative_path(relative_path, "record path")
        destination = self._destination(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open("xb") as handle:
                handle.write(expected)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            existing = destination.read_bytes()
            if existing != expected:
                raise LineageIntegrityError(
                    "existing immutable record differs; overwrite refused"
                ) from None
        return str(relative)

    @staticmethod
    def _artifact_digest(relative: PurePosixPath) -> str:
        if len(relative.parts) != 5 or relative.parts[:2] != (
            "artifacts",
            "sha256",
        ):
            raise LineageValidationError(
                "artifact path does not follow content-addressed layout"
            )
        digest = _require_sha256(relative.parts[3], "artifact path SHA-256")
        if relative.parts[2] != digest[:2]:
            raise LineageValidationError("artifact path digest prefix is inconsistent")
        if _SAFE_SEGMENT.fullmatch(relative.parts[4]) is None:
            raise LineageValidationError("artifact path name is unsafe")
        return digest

    def _read_record(self, relative_path: str) -> tuple[PurePosixPath, dict[str, Any]]:
        relative = _public_relative_path(relative_path, "record path")
        data = self._destination(relative).read_bytes()
        try:
            record = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LineageIntegrityError(
                "immutable record is not valid UTF-8 JSON"
            ) from exc
        if not isinstance(record, dict):
            raise LineageIntegrityError("immutable record must be a JSON object")
        if canonical_json_bytes(record) != data:
            raise LineageIntegrityError("immutable record bytes are not canonical")
        return relative, record

    def _require_manifest(self, manifest_id: str) -> None:
        relative = f"manifests/v1/{manifest_id[:2]}/{manifest_id}.json"
        try:
            self.verify_manifest(relative)
        except (
            FileNotFoundError,
            LineageIntegrityError,
            LineageValidationError,
        ) as exc:
            raise LineageIntegrityError(
                f"input manifest {manifest_id} is missing or invalid"
            ) from exc

    def _require_lineage_record(self, record_id: str) -> None:
        resolved_root = self.root.resolve()
        pattern = f"lineage/v1/*/{record_id[:2]}/{record_id}.json"
        candidates = list(resolved_root.glob(pattern))
        if len(candidates) != 1:
            raise LineageIntegrityError(
                f"linked lineage record {record_id} is missing or ambiguous"
            )
        relative = candidates[0].relative_to(resolved_root).as_posix()
        try:
            self.verify(relative)
        except (
            FileNotFoundError,
            LineageIntegrityError,
            LineageValidationError,
        ) as exc:
            raise LineageIntegrityError(
                f"linked lineage record {record_id} is missing or invalid"
            ) from exc

    def _require_artifact(self, envelope: LineageEnvelope) -> None:
        if envelope.artifact_path is None:
            return
        try:
            artifact = self.verify_artifact(envelope.artifact_path)
        except (
            FileNotFoundError,
            LineageIntegrityError,
            LineageValidationError,
        ) as exc:
            raise LineageIntegrityError(
                "lineage artifact is missing or invalid"
            ) from exc
        if sha256_hex(artifact) != envelope.artifact_sha256:
            raise LineageIntegrityError(
                "lineage artifact SHA-256 does not match its envelope"
            )
        if len(artifact) != envelope.artifact_bytes:
            raise LineageIntegrityError(
                "lineage artifact byte size does not match its envelope"
            )

    def append(self, envelope: LineageEnvelope) -> str:
        manifest_id = envelope.provenance["input_manifest_id"]
        if manifest_id is not None:
            self._require_manifest(manifest_id)
        self._require_artifact(envelope)
        dependency_ids = {link.target_record_id for link in envelope.links}
        dependency_ids.update(envelope.supersedes)
        for record_id in sorted(dependency_ids):
            self._require_lineage_record(record_id)
        return self._append_record(envelope.relative_path, envelope.record())

    def verify(self, relative_path: str) -> dict[str, Any]:
        relative, record = self._read_record(relative_path)
        if len(relative.parts) != 5 or relative.parts[:2] != ("lineage", "v1"):
            raise LineageValidationError(
                "lineage path does not follow versioned layout"
            )
        record_type = relative.parts[2]
        if record_type not in RECORD_TYPES:
            raise LineageValidationError("lineage path has unknown record type")
        path_id = relative.stem
        _require_sha256(path_id, "lineage path record ID")
        if relative.parts[3] != path_id[:2]:
            raise LineageValidationError("lineage path digest prefix is inconsistent")

        record_id = record.get("record_id")
        if record_id != path_id:
            raise LineageIntegrityError("lineage record ID does not match its path")
        try:
            envelope = LineageEnvelope.from_record(record)
        except LineageValidationError as exc:
            raise LineageIntegrityError("lineage envelope validation failed") from exc
        if envelope.record_type != record_type:
            raise LineageIntegrityError("lineage record type does not match its path")
        self._require_artifact(envelope)
        return record

    def append_manifest(self, manifest: InputManifest) -> str:
        return self._append_record(manifest.relative_path, manifest.record())

    def append_artifact(self, relative_path: str, content: bytes) -> str:
        if not isinstance(content, bytes):
            raise LineageValidationError("artifact content must be bytes")
        relative = _public_relative_path(relative_path, "artifact path")
        digest = self._artifact_digest(relative)
        if sha256_hex(content) != digest:
            raise LineageIntegrityError(
                "artifact bytes do not match the content-addressed path"
            )
        return self._append_bytes(str(relative), content)

    def verify_artifact(self, relative_path: str) -> bytes:
        relative = _public_relative_path(relative_path, "artifact path")
        digest = self._artifact_digest(relative)
        content = self._destination(relative).read_bytes()
        if sha256_hex(content) != digest:
            raise LineageIntegrityError(
                "artifact bytes do not match the content-addressed path"
            )
        return content

    def verify_manifest(self, relative_path: str) -> dict[str, Any]:
        relative, record = self._read_record(relative_path)
        if len(relative.parts) != 4 or relative.parts[:2] != ("manifests", "v1"):
            raise LineageValidationError(
                "manifest path does not follow versioned layout"
            )
        manifest_id = relative.stem
        _require_sha256(manifest_id, "manifest path ID")
        if relative.parts[2] != manifest_id[:2]:
            raise LineageValidationError("manifest path digest prefix is inconsistent")
        if record.get("manifest_id") != manifest_id:
            raise LineageIntegrityError("manifest ID does not match its path")
        try:
            InputManifest.from_record(record)
        except LineageValidationError as exc:
            raise LineageIntegrityError("input manifest validation failed") from exc
        return record
