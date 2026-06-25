"""Reglas y value objects puros para H3 RAG."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from barbarion.domain.models import SHA256_HEX_LENGTH


class EmbeddingManifestStatus(StrEnum):
    """Estado persistible de una version de embeddings."""

    ACTIVE = "active"
    OBSOLETE = "obsolete"
    FAILED = "failed"


class EmbeddingRunStatus(StrEnum):
    """Estado persistible de una corrida de indexacion H3."""

    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class EmbeddingRunMode(StrEnum):
    """Modo de indexacion H3."""

    INCREMENTAL = "incremental"
    FULL = "full"
    PARTIAL = "partial"


class ChunkEmbeddingStatus(StrEnum):
    """Estado de indexacion de un chunk para un manifest."""

    INDEXED = "indexed"
    STALE = "stale"
    DELETED = "deleted"
    ERROR = "error"


class IndexAction(StrEnum):
    """Accion incremental para un chunk."""

    NEW = "new"
    UPDATE = "update"
    UNCHANGED = "unchanged"
    DELETE = "delete"


class EmbeddingProviderError(RuntimeError):
    """Error esperado al generar embeddings."""


class VectorStoreError(RuntimeError):
    """Error esperado del almacenamiento vectorial local."""


@dataclass(frozen=True, slots=True)
class EmbeddingManifest:
    """Identidad canonica de una version de embeddings."""

    provider: str
    model: str
    dimension: int
    distance: str = "cosine"
    normalize: bool = True
    version: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.provider, "provider")
        _require_non_empty(self.model, "model")
        _require_positive(self.dimension, "dimension")
        _require_non_empty(self.distance, "distance")
        version = self.version or embedding_version(
            provider=self.provider,
            model=self.model,
            dimension=self.dimension,
            distance=self.distance,
            normalize=self.normalize,
        )
        _require_sha256(version, "version")
        object.__setattr__(self, "version", version)


@dataclass(frozen=True, slots=True)
class EmbeddingRequest:
    """Solicitud batch al proveedor de embeddings."""

    texts: tuple[str, ...]
    input_kind: str
    embedding_version: str

    def __post_init__(self) -> None:
        if not self.texts:
            raise ValueError("texts debe contener al menos un texto.")
        for text in self.texts:
            _require_non_empty(text, "texts")
        _require_non_empty(self.input_kind, "input_kind")
        _require_sha256(self.embedding_version, "embedding_version")


@dataclass(frozen=True, slots=True)
class EmbeddingVector:
    """Vector producido por un proveedor de embeddings."""

    text_index: int
    values: tuple[float, ...]
    provider: str
    model: str

    def __post_init__(self) -> None:
        if self.text_index < 0:
            raise ValueError("text_index debe ser mayor o igual que 0.")
        if not self.values:
            raise ValueError("values debe contener al menos una dimension.")
        _require_non_empty(self.provider, "provider")
        _require_non_empty(self.model, "model")

    @property
    def dimension(self) -> int:
        """Cantidad de dimensiones del vector."""
        return len(self.values)


@dataclass(frozen=True, slots=True)
class H4SymbolMetadata:
    """Metadata simbolica reservada para H4; puede estar vacia en H3."""

    symbol_name: str | None = None
    symbol_kind: str | None = None
    parent_symbol: str | None = None
    package_name: str | None = None
    procedure_name: str | None = None
    class_name: str | None = None
    event_name: str | None = None


@dataclass(frozen=True, slots=True)
class RetrievalFilter:
    """Filtros de recuperacion soportados por H3."""

    domain: str | None = None
    artifact_kind: str | None = None
    language: str | None = None
    document_id: int | None = None
    folder: str | None = None
    extension: str | None = None


@dataclass(frozen=True, slots=True)
class IndexScope:
    """Alcance opcional de indexacion H3."""

    path_prefix: str | None = None
    document_id: int | None = None
    chunk_id: str | None = None

    def __post_init__(self) -> None:
        if self.document_id is not None:
            _require_positive(self.document_id, "document_id")
        if self.chunk_id is not None:
            _require_non_empty(self.chunk_id, "chunk_id")


@dataclass(frozen=True, slots=True)
class VectorMetadata:
    """Metadata filtrable asociada a un vector."""

    content_sha256: str
    domain: str
    artifact_kind: str | None = None
    language: str | None = None
    document_id: int | None = None
    file_id: int | None = None
    relative_path: str | None = None
    folder: str | None = None
    extension: str | None = None
    object_type: str | None = None
    object_name: str | None = None
    symbols: H4SymbolMetadata = field(default_factory=H4SymbolMetadata)

    def __post_init__(self) -> None:
        _require_sha256(self.content_sha256, "content_sha256")
        _require_non_empty(self.domain, "domain")
        if self.document_id is not None:
            _require_non_negative(self.document_id, "document_id")
        if self.file_id is not None:
            _require_non_negative(self.file_id, "file_id")


@dataclass(frozen=True, slots=True)
class IndexableChunk:
    """Chunk vigente H2 listo para indexacion H3."""

    chunk_id: str
    content: str
    metadata: VectorMetadata

    def __post_init__(self) -> None:
        _require_non_empty(self.chunk_id, "chunk_id")
        _require_non_empty(self.content, "content")


@dataclass(frozen=True, slots=True)
class ChunkEmbeddingState:
    """Estado persistido de embedding para un chunk."""

    chunk_id: str
    content_sha256: str
    status: ChunkEmbeddingStatus

    def __post_init__(self) -> None:
        _require_non_empty(self.chunk_id, "chunk_id")
        _require_sha256(self.content_sha256, "content_sha256")


@dataclass(frozen=True, slots=True)
class IndexDecision:
    """Decision incremental sobre un chunk o vector obsoleto."""

    action: IndexAction
    chunk: IndexableChunk | None = None
    chunk_id: str | None = None

    def __post_init__(self) -> None:
        if self.action == IndexAction.DELETE:
            if self.chunk_id is None:
                raise ValueError("Las decisiones delete requieren chunk_id.")
            _require_non_empty(self.chunk_id, "chunk_id")
            return
        if self.chunk is None:
            raise ValueError("Las decisiones de indexacion requieren chunk.")


@dataclass(frozen=True, slots=True)
class IndexPlan:
    """Plan incremental completo para una corrida."""

    decisions: tuple[IndexDecision, ...]
    dry_run: bool = False

    @property
    def new_chunks(self) -> int:
        return _count(self.decisions, IndexAction.NEW)

    @property
    def updated_chunks(self) -> int:
        return _count(self.decisions, IndexAction.UPDATE)

    @property
    def unchanged_chunks(self) -> int:
        return _count(self.decisions, IndexAction.UNCHANGED)

    @property
    def deleted_chunks(self) -> int:
        return _count(self.decisions, IndexAction.DELETE)


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    """Resultado estructurado de recuperacion."""

    chunk_id: str
    content_sha256: str
    combined_score: float
    vector_score: float | None = None
    keyword_score: float | None = None
    metadata: H4SymbolMetadata = field(default_factory=H4SymbolMetadata)
    source: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.chunk_id, "chunk_id")
        _require_sha256(self.content_sha256, "content_sha256")
        _require_unit_score(self.combined_score, "combined_score")
        if self.vector_score is not None:
            _require_unit_score(self.vector_score, "vector_score")
        if self.keyword_score is not None:
            _require_unit_score(self.keyword_score, "keyword_score")
        object.__setattr__(self, "source", _freeze_mapping(self.source))


@dataclass(frozen=True, slots=True)
class ContextQualityMetrics:
    """Metricas preparadas para comparar cambios de contexto."""

    context_precision: float | None = None
    context_recall: float | None = None
    duplicate_ratio: float | None = None
    token_waste: float | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "context_precision",
            "context_recall",
            "duplicate_ratio",
            "token_waste",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _require_unit_score(value, field_name)


@dataclass(frozen=True, slots=True)
class IndexRunSummary:
    """Resumen de una corrida de indexacion H3."""

    status: EmbeddingRunStatus
    new_chunks: int = 0
    updated_chunks: int = 0
    unchanged_chunks: int = 0
    deleted_chunks: int = 0
    failed_chunks: int = 0
    duration_ms: int = 0
    run_id: int | None = None
    dry_run: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "new_chunks",
            "updated_chunks",
            "unchanged_chunks",
            "deleted_chunks",
            "failed_chunks",
            "duration_ms",
        ):
            _require_non_negative(getattr(self, field_name), field_name)


def embedding_version(
    *,
    provider: str,
    model: str,
    dimension: int,
    distance: str,
    normalize: bool,
) -> str:
    """Calcula una version canonica de embeddings."""
    _require_non_empty(provider, "provider")
    _require_non_empty(model, "model")
    _require_positive(dimension, "dimension")
    _require_non_empty(distance, "distance")
    payload = {
        "dimension": dimension,
        "distance": distance,
        "model": model,
        "normalize": normalize,
        "provider": provider,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def decide_index_plan(
    chunks: tuple[IndexableChunk, ...],
    states: dict[str, ChunkEmbeddingState],
    *,
    full: bool = False,
    delete_obsolete: bool = True,
    dry_run: bool = False,
) -> IndexPlan:
    """Decide que chunks indexar, omitir o eliminar."""
    decisions: list[IndexDecision] = []
    current_ids = {chunk.chunk_id for chunk in chunks}
    for chunk in chunks:
        state = states.get(chunk.chunk_id)
        if full or state is None:
            decisions.append(IndexDecision(IndexAction.NEW, chunk=chunk))
        elif (
            state.status != ChunkEmbeddingStatus.INDEXED
            or state.content_sha256 != chunk.metadata.content_sha256
        ):
            decisions.append(IndexDecision(IndexAction.UPDATE, chunk=chunk))
        else:
            decisions.append(IndexDecision(IndexAction.UNCHANGED, chunk=chunk))

    if delete_obsolete:
        for chunk_id in sorted(set(states) - current_ids):
            decisions.append(
                IndexDecision(IndexAction.DELETE, chunk_id=chunk_id)
            )
    return IndexPlan(decisions=tuple(decisions), dry_run=dry_run)


def _count(decisions: tuple[IndexDecision, ...], action: IndexAction) -> int:
    return sum(1 for decision in decisions if decision.action == action)


def _require_non_empty(value: str, key: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} debe ser una cadena no vacia.")


def _require_positive(value: int, key: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{key} debe ser un entero mayor que 0.")


def _require_non_negative(value: int, key: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} debe ser un entero mayor o igual que 0.")


def _require_sha256(value: str, key: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != SHA256_HEX_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{key} debe ser un SHA-256 hexadecimal en minusculas.")


def _require_unit_score(value: float, key: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} debe ser numerico.")
    if not 0 <= float(value) <= 1:
        raise ValueError(f"{key} debe estar entre 0 y 1.")


def _freeze_mapping(values: dict[str, Any]) -> MappingProxyType[str, Any]:
    return MappingProxyType(dict(values))
