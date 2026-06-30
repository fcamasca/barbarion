"""Reglas y value objects puros para RAG."""

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
    """Estado persistible de una corrida de indexacion RAG."""

    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class EmbeddingRunMode(StrEnum):
    """Modo de indexacion RAG."""

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


class RetrievalMode(StrEnum):
    """Modo de recuperacion RAG."""

    SEMANTIC = "semantic"
    KEYWORD = "keyword"
    HYBRID = "hybrid"


class RagQueryStatus(StrEnum):
    """Estado persistible de una consulta RAG."""

    COMPLETED = "completed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    ERROR = "error"


class EmbeddingProviderError(RuntimeError):
    """Error esperado al generar embeddings."""


class VectorStoreError(RuntimeError):
    """Error esperado del almacenamiento vectorial local."""


class LlmProviderError(RuntimeError):
    """Error esperado al generar respuestas con LLM local."""


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
class SymbolMetadata:
    """Metadata simbolica reservada para reverse engineering; puede estar vacia en RAG."""

    symbol_name: str | None = None
    symbol_kind: str | None = None
    parent_symbol: str | None = None
    package_name: str | None = None
    procedure_name: str | None = None
    class_name: str | None = None
    event_name: str | None = None


@dataclass(frozen=True, slots=True)
class RetrievalFilter:
    """Filtros de recuperacion soportados por RAG."""

    domain: str | None = None
    artifact_kind: str | None = None
    language: str | None = None
    document_id: int | None = None
    folder: str | None = None
    extension: str | None = None


@dataclass(frozen=True, slots=True)
class IndexScope:
    """Alcance opcional de indexacion RAG."""

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
    symbols: SymbolMetadata = field(default_factory=SymbolMetadata)

    def __post_init__(self) -> None:
        _require_sha256(self.content_sha256, "content_sha256")
        _require_non_empty(self.domain, "domain")
        if self.document_id is not None:
            _require_non_negative(self.document_id, "document_id")
        if self.file_id is not None:
            _require_non_negative(self.file_id, "file_id")


@dataclass(frozen=True, slots=True)
class IndexableChunk:
    """Chunk vigente listo para indexacion RAG."""

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
    metadata: SymbolMetadata = field(default_factory=SymbolMetadata)
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
class SearchTimings:
    """Tiempos principales de una busqueda RAG."""

    vector_ms: int | None = None
    keyword_ms: int | None = None
    ranking_ms: int | None = None

    def __post_init__(self) -> None:
        for field_name in ("vector_ms", "keyword_ms", "ranking_ms"):
            value = getattr(self, field_name)
            if value is not None:
                _require_non_negative(value, field_name)


@dataclass(frozen=True, slots=True)
class SearchRequest:
    """Entrada estructurada para busqueda RAG."""

    query: str
    mode: RetrievalMode
    filters: RetrievalFilter = field(default_factory=RetrievalFilter)
    top_k: int = 10
    candidate_k: int = 50
    similarity_threshold: float = 0.0
    vector_weight: float = 0.7
    keyword_weight: float = 0.3
    debug: bool = False

    def __post_init__(self) -> None:
        _require_non_empty(self.query, "query")
        _require_positive(self.top_k, "top_k")
        _require_positive(self.candidate_k, "candidate_k")
        if self.candidate_k < self.top_k:
            raise ValueError("candidate_k debe ser mayor o igual que top_k.")
        _require_unit_score(self.similarity_threshold, "similarity_threshold")
        _require_non_negative_float(self.vector_weight, "vector_weight")
        _require_non_negative_float(self.keyword_weight, "keyword_weight")
        if self.vector_weight + self.keyword_weight <= 0:
            raise ValueError("La suma de pesos debe ser mayor que 0.")


@dataclass(frozen=True, slots=True)
class SearchResponse:
    """Salida estructurada de busqueda RAG."""

    query_id: int | None
    mode: RetrievalMode
    candidates: tuple[RetrievalCandidate, ...]
    timings: SearchTimings = field(default_factory=SearchTimings)
    debug: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "debug", _freeze_mapping(self.debug))


@dataclass(frozen=True, slots=True)
class ContextSource:
    """Fuente seleccionada para el contexto final."""

    source_id: str
    candidate: RetrievalCandidate
    content: str
    token_estimate: int
    original_token_estimate: int = 0
    content_truncated: bool = False

    def __post_init__(self) -> None:
        _require_non_empty(self.source_id, "source_id")
        _require_non_empty(self.content, "content")
        _require_non_negative(self.token_estimate, "token_estimate")
        _require_non_negative(self.original_token_estimate, "original_token_estimate")


@dataclass(frozen=True, slots=True)
class ContextBuildResult:
    """Contexto final y metricas de calidad preparadas."""

    sources: tuple[ContextSource, ...]
    omitted: tuple[dict[str, Any], ...]
    rendered_context: str
    token_estimate: int
    metrics: ContextQualityMetrics
    debug: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_negative(self.token_estimate, "token_estimate")
        object.__setattr__(self, "debug", _freeze_mapping(self.debug))


@dataclass(frozen=True, slots=True)
class CitationValidation:
    """Resultado de validar citas contra fuentes disponibles."""

    valid: bool
    missing_source_ids: tuple[str, ...] = ()
    cited_source_ids: tuple[str, ...] = ()
    unsupported_claims: tuple[str, ...] = ()
    contradiction_claims: tuple[str, ...] = ()
    reason: str = "ok"


@dataclass(frozen=True, slots=True)
class AnswerResult:
    """Resultado estructurado de ask."""

    query_id: int | None
    question: str
    answer: str
    context: ContextBuildResult
    status: RagQueryStatus
    no_llm: bool = False
    citations_valid: bool = True
    missing_citations: tuple[str, ...] = ()
    debug: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.question, "question")
        _require_non_empty(self.answer, "answer")
        object.__setattr__(self, "debug", _freeze_mapping(self.debug))


@dataclass(frozen=True, slots=True)
class IndexRunSummary:
    """Resumen de una corrida de indexacion RAG."""

    status: EmbeddingRunStatus
    new_chunks: int = 0
    updated_chunks: int = 0
    unchanged_chunks: int = 0
    deleted_chunks: int = 0
    failed_chunks: int = 0
    processed_chunks: int = 0
    pending_chunks: int = 0
    embeddings_generated: int = 0
    vectors_persisted: int = 0
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
            "processed_chunks",
            "pending_chunks",
            "embeddings_generated",
            "vectors_persisted",
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


def combine_hybrid_candidates(
    vector_candidates: tuple[RetrievalCandidate, ...],
    keyword_candidates: tuple[RetrievalCandidate, ...],
    *,
    vector_weight: float,
    keyword_weight: float,
    top_k: int,
    threshold: float = 0.0,
) -> tuple[RetrievalCandidate, ...]:
    """Fusiona candidatos semanticos y keyword conservando scores individuales."""
    _require_positive(top_k, "top_k")
    _require_non_negative_float(vector_weight, "vector_weight")
    _require_non_negative_float(keyword_weight, "keyword_weight")
    if vector_weight + keyword_weight <= 0:
        raise ValueError("La suma de pesos debe ser mayor que 0.")
    _require_unit_score(threshold, "threshold")
    vector_norm = _normalizer(
        candidate.vector_score
        for candidate in vector_candidates
        if candidate.vector_score is not None
    )
    keyword_norm = _normalizer(
        candidate.keyword_score
        for candidate in keyword_candidates
        if candidate.keyword_score is not None
    )
    by_chunk: dict[str, RetrievalCandidate] = {}
    for candidate in (*vector_candidates, *keyword_candidates):
        current = by_chunk.get(candidate.chunk_id)
        by_chunk[candidate.chunk_id] = _merge_candidate(current, candidate)

    total_weight = vector_weight + keyword_weight
    ranked = []
    for candidate in by_chunk.values():
        vector_score = candidate.vector_score
        keyword_score = candidate.keyword_score
        combined = (
            vector_weight * vector_norm(vector_score)
            + keyword_weight * keyword_norm(keyword_score)
        ) / total_weight
        if combined >= threshold:
            ranked.append(
                RetrievalCandidate(
                    chunk_id=candidate.chunk_id,
                    content_sha256=candidate.content_sha256,
                    combined_score=combined,
                    vector_score=vector_score,
                    keyword_score=keyword_score,
                    metadata=candidate.metadata,
                    source={
                        **dict(candidate.source),
                        "retrieval_mode": RetrievalMode.HYBRID.value,
                    },
                )
            )
    ranked.sort(key=lambda item: (-item.combined_score, item.chunk_id))
    return tuple(ranked[:top_k])


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


def _require_non_negative_float(value: float, key: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{key} debe ser numerico mayor o igual que 0.")


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


def _normalizer(values: Any) -> Any:
    numbers = tuple(float(value) for value in values)
    if not numbers:
        return lambda value: 0.0 if value is None else float(value)
    minimum = min(numbers)
    maximum = max(numbers)
    if maximum == minimum:
        return lambda value: 0.0 if value is None else 1.0
    return (
        lambda value: 0.0
        if value is None
        else max(0.0, min(1.0, (float(value) - minimum) / (maximum - minimum)))
    )


def _merge_candidate(
    current: RetrievalCandidate | None,
    candidate: RetrievalCandidate,
) -> RetrievalCandidate:
    if current is None:
        return candidate
    vector_score = current.vector_score
    if candidate.vector_score is not None:
        vector_score = (
            candidate.vector_score
            if vector_score is None
            else max(vector_score, candidate.vector_score)
        )
    keyword_score = current.keyword_score
    if candidate.keyword_score is not None:
        keyword_score = (
            candidate.keyword_score
            if keyword_score is None
            else max(keyword_score, candidate.keyword_score)
        )
    source = {**dict(current.source), **dict(candidate.source)}
    return RetrievalCandidate(
        chunk_id=current.chunk_id,
        content_sha256=current.content_sha256,
        combined_score=max(current.combined_score, candidate.combined_score),
        vector_score=vector_score,
        keyword_score=keyword_score,
        metadata=current.metadata,
        source=source,
    )
