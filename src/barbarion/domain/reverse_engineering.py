"""Modelos puros para H4 Reverse Engineering."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from barbarion.domain.models import Confidence


class H4AnalysisRunMode(StrEnum):
    """Modo operativo de una corrida H4."""

    INCREMENTAL = "incremental"
    FULL = "full"
    PARTIAL = "partial"


class H4AnalysisRunStatus(StrEnum):
    """Estado persistible de una corrida H4."""

    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class H4SymbolStatus(StrEnum):
    """Estado vigente de un simbolo H4."""

    ACTIVE = "active"
    STALE = "stale"
    DELETED = "deleted"
    AMBIGUOUS = "ambiguous"


class H4ResolutionStatus(StrEnum):
    """Estado de resolucion de una referencia o relacion H4."""

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"
    EXTERNAL = "external"
    DYNAMIC = "dynamic"


class H4Classification(StrEnum):
    """Clasificacion de evidencia de una relacion H4."""

    DETECTED = "detectado"
    INFERRED = "inferido"
    TO_CONFIRM = "por_confirmar"


class H4RelationStatus(StrEnum):
    """Estado vigente de una relacion H4."""

    ACTIVE = "active"
    STALE = "stale"
    DELETED = "deleted"


@dataclass(frozen=True, slots=True)
class H4AnalysisRunRecord:
    """Resumen persistido de una corrida H4."""

    id: int
    mode: H4AnalysisRunMode
    status: H4AnalysisRunStatus
    scope: dict[str, Any] = field(default_factory=dict)
    symbols_detected: int = 0
    references_detected: int = 0
    relations_resolved: int = 0
    relations_unresolved: int = 0
    relations_ambiguous: int = 0
    warning_count: int = 0
    error_count: int = 0
    duration_ms: int | None = None

    def __post_init__(self) -> None:
        _require_positive(self.id, "id")
        for field_name in (
            "symbols_detected",
            "references_detected",
            "relations_resolved",
            "relations_unresolved",
            "relations_ambiguous",
            "warning_count",
            "error_count",
        ):
            _require_non_negative(getattr(self, field_name), field_name)
        if self.duration_ms is not None:
            _require_non_negative(self.duration_ms, "duration_ms")
        object.__setattr__(self, "scope", _freeze_mapping(self.scope))


@dataclass(frozen=True, slots=True)
class H4Symbol:
    """Simbolo logico vigente detectado por H4."""

    symbol_id: str
    original_name: str
    normalized_name: str
    symbol_type: str
    technology: str
    extraction_method: str
    confidence: Confidence
    file_id: int | None = None
    document_id: int | None = None
    chunk_id: str | None = None
    parent_symbol_id: str | None = None
    container_name: str | None = None
    signature: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    status: H4SymbolStatus = H4SymbolStatus.ACTIVE
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_sha256(self.symbol_id, "symbol_id")
        _require_non_empty(self.original_name, "original_name")
        _require_non_empty(self.normalized_name, "normalized_name")
        _require_non_empty(self.symbol_type, "symbol_type")
        _require_non_empty(self.technology, "technology")
        _require_non_empty(self.extraction_method, "extraction_method")
        _validate_optional_positive(self.file_id, "file_id")
        _validate_optional_positive(self.document_id, "document_id")
        if self.chunk_id is not None:
            _require_non_empty(self.chunk_id, "chunk_id")
        if self.parent_symbol_id is not None:
            _require_sha256(self.parent_symbol_id, "parent_symbol_id")
        if self.container_name is not None:
            _require_non_empty(self.container_name, "container_name")
        if self.signature is not None:
            _require_non_empty(self.signature, "signature")
        _validate_optional_range(self.start_line, self.end_line, "line")
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class H4Reference:
    """Referencia textual vigente antes o despues de resolverla."""

    reference_id: str
    source_file_id: int
    raw_text: str
    normalized_target: str
    reference_type: str
    technology: str
    detection_method: str
    confidence: Confidence
    resolution_status: H4ResolutionStatus
    source_symbol_id: str | None = None
    source_chunk_id: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_sha256(self.reference_id, "reference_id")
        _require_positive(self.source_file_id, "source_file_id")
        _require_non_empty(self.raw_text, "raw_text")
        _require_non_empty(self.normalized_target, "normalized_target")
        _require_non_empty(self.reference_type, "reference_type")
        _require_non_empty(self.technology, "technology")
        _require_non_empty(self.detection_method, "detection_method")
        if self.source_symbol_id is not None:
            _require_sha256(self.source_symbol_id, "source_symbol_id")
        if self.source_chunk_id is not None:
            _require_non_empty(self.source_chunk_id, "source_chunk_id")
        _validate_optional_range(self.start_line, self.end_line, "line")
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class H4Relation:
    """Relacion canonica source -> target derivada de una referencia."""

    relation_id: str
    reference_id: str
    relation_type: str
    classification: H4Classification
    resolution_status: H4ResolutionStatus
    confidence: Confidence
    evidence_file_id: int
    source_symbol_id: str | None = None
    target_symbol_id: str | None = None
    target_key: str | None = None
    evidence_chunk_id: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    notes: str | None = None
    status: H4RelationStatus = H4RelationStatus.ACTIVE

    def __post_init__(self) -> None:
        _require_sha256(self.relation_id, "relation_id")
        _require_sha256(self.reference_id, "reference_id")
        _require_non_empty(self.relation_type, "relation_type")
        _require_positive(self.evidence_file_id, "evidence_file_id")
        if self.source_symbol_id is not None:
            _require_sha256(self.source_symbol_id, "source_symbol_id")
        if self.target_symbol_id is not None:
            _require_sha256(self.target_symbol_id, "target_symbol_id")
        if self.target_key is not None:
            _require_non_empty(self.target_key, "target_key")
        if self.evidence_chunk_id is not None:
            _require_non_empty(self.evidence_chunk_id, "evidence_chunk_id")
        if self.notes is not None:
            _require_non_empty(self.notes, "notes")
        if (
            self.resolution_status == H4ResolutionStatus.DYNAMIC
            and self.classification != H4Classification.TO_CONFIRM
        ):
            raise ValueError("Las relaciones dynamic requieren clasificacion por_confirmar.")
        _validate_optional_range(self.start_line, self.end_line, "line")


@dataclass(frozen=True, slots=True)
class H4RelationCandidate:
    """Candidato alternativo para relaciones ambiguas."""

    relation_id: str
    candidate_symbol_id: str
    rank: int
    reason: str

    def __post_init__(self) -> None:
        _require_sha256(self.relation_id, "relation_id")
        _require_sha256(self.candidate_symbol_id, "candidate_symbol_id")
        _require_positive(self.rank, "rank")
        _require_non_empty(self.reason, "reason")


def normalize_symbol_name(value: str) -> str:
    """Normaliza nombres de simbolos para identidad logica y busqueda."""
    _require_non_empty(value, "value")
    parts = [
        _unquote_identifier(part.strip())
        for part in re.split(r"\s*\.\s*", value.strip())
        if part.strip()
    ]
    if not parts:
        raise ValueError("value debe contener al menos un identificador.")
    return ".".join(part.lower() for part in parts)


def h4_symbol_id(
    *,
    normalized_name: str,
    symbol_type: str,
    technology: str,
    container_name: str | None = None,
) -> str:
    """Calcula la identidad logica determinista de un simbolo vigente."""
    return _sha256_payload(
        "barbarion.h4.symbol-id.v1",
        {
            "container_name": normalize_symbol_name(container_name)
            if container_name
            else None,
            "normalized_name": normalize_symbol_name(normalized_name),
            "symbol_type": _normalized_token(symbol_type),
            "technology": _normalized_token(technology),
        },
    )


def h4_reference_id(
    *,
    source_file_id: int,
    raw_text: str,
    normalized_target: str,
    reference_type: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    """Calcula un ID estable para una referencia textual."""
    _require_positive(source_file_id, "source_file_id")
    _validate_optional_range(start_line, end_line, "line")
    return _sha256_payload(
        "barbarion.h4.reference-id.v1",
        {
            "end_line": end_line,
            "normalized_target": normalize_symbol_name(normalized_target),
            "raw_text": raw_text.strip(),
            "reference_type": _normalized_token(reference_type),
            "source_file_id": source_file_id,
            "start_line": start_line,
        },
    )


def h4_relation_id(
    *,
    reference_id: str,
    relation_type: str,
    source_symbol_id: str | None = None,
    target_symbol_id: str | None = None,
    target_key: str | None = None,
) -> str:
    """Calcula un ID estable para la relacion canonica source -> target."""
    _require_sha256(reference_id, "reference_id")
    if source_symbol_id is not None:
        _require_sha256(source_symbol_id, "source_symbol_id")
    if target_symbol_id is not None:
        _require_sha256(target_symbol_id, "target_symbol_id")
    return _sha256_payload(
        "barbarion.h4.relation-id.v1",
        {
            "reference_id": reference_id,
            "relation_type": _normalized_token(relation_type),
            "source_symbol_id": source_symbol_id,
            "target_key": normalize_symbol_name(target_key) if target_key else None,
            "target_symbol_id": target_symbol_id,
        },
    )


def _sha256_payload(namespace: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        {"namespace": namespace, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalized_token(value: str) -> str:
    _require_non_empty(value, "value")
    return value.strip().lower()


def _unquote_identifier(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'", "`"}:
        return value[1:-1]
    return value


def _require_non_empty(value: str, key: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} debe ser una cadena no vacia.")


def _require_positive(value: int, key: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{key} debe ser un entero mayor que 0.")


def _require_non_negative(value: int, key: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} debe ser un entero mayor o igual que 0.")


def _validate_optional_positive(value: int | None, key: str) -> None:
    if value is not None:
        _require_positive(value, key)


def _require_sha256(value: str, key: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{key} debe ser un SHA-256 hexadecimal en minusculas.")


def _validate_optional_range(
    start: int | None,
    end: int | None,
    label: str,
) -> None:
    if start is None and end is None:
        return
    if start is None or end is None:
        raise ValueError(f"El rango {label} debe tener inicio y fin.")
    _require_positive(start, f"start_{label}")
    _require_positive(end, f"end_{label}")
    if end < start:
        raise ValueError(f"El rango {label} debe terminar despues del inicio.")


def _freeze_mapping(values: dict[str, Any]) -> MappingProxyType[str, Any]:
    return MappingProxyType(dict(values))
