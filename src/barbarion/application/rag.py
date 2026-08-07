"""Servicios de aplicacion para indexacion, busqueda y respuesta RAG."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import PurePosixPath

from barbarion.application.privacy import (
    InvalidPrivacyAuthorizationError,
    PrivacyPreflightService,
    resolve_inference_target,
)
from barbarion.config import Settings
from barbarion.domain.privacy import (
    InferenceTarget,
    PrivacyAuthorization,
    PrivacyPolicy,
)
from barbarion.domain.progress import (
    CancellationTokenPort,
    ProgressReporterPort,
    ProgressSnapshot,
    ProgressStage,
)
from barbarion.domain.ports import EmbeddingProviderPort, LlmProviderPort, VectorStorePort
from barbarion.domain.rag import (
    AnswerResult,
    ChunkEmbeddingState,
    CitationValidation,
    ContextBuildResult,
    ContextQualityMetrics,
    ContextSource,
    EmbeddingManifest,
    EmbeddingRequest,
    EmbeddingRunMode,
    EmbeddingRunStatus,
    IndexAction,
    IndexRunSummary,
    IndexScope,
    IndexableChunk,
    LlmProviderError,
    RagQueryStatus,
    RetrievalCandidate,
    RetrievalFilter,
    RetrievalMode,
    SearchRequest,
    SearchResponse,
    SearchTimings,
    SymbolMetadata,
    combine_hybrid_candidates,
    decide_index_plan,
)
from barbarion.domain.reverse_engineering import (
    DependencyDirection,
    TechnicalRelation,
    TechnicalSymbol,
)
from barbarion.infrastructure.sqlite import (
    SQLiteRagRepository,
    SQLiteReverseEngineeringRepository,
)

_LOGGER = logging.getLogger("barbarion")

TOKEN_ESTIMATOR_ID = "chars4_v1"
_PROMPT_COMPONENT_KINDS = frozenset(
    {
        "instructions",
        "question",
        "source_metadata",
        "source_content",
        "rejected_answer",
        "output_format",
    }
)


def estimate_tokens(text: str) -> int:
    """Estima tokens localmente con la heuristica historica de H3.

    Esta aproximacion no representa uso real de Ollama o Anthropic. El ID
    versionado permite interpretar metricas sin introducir un puerto mientras
    exista una unica estrategia efectiva.
    """
    return max(1, (len(text) + 3) // 4)


@dataclass(frozen=True, slots=True)
class PromptComponent:
    """Fragmento ordenado y medible de un prompt RAG."""

    kind: str
    text: str
    source_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in _PROMPT_COMPONENT_KINDS:
            raise ValueError(f"Tipo de componente de prompt no soportado: {self.kind}.")

    @property
    def chars(self) -> int:
        """Cantidad exacta de caracteres Python del fragmento."""
        return len(self.text)

    @property
    def utf8_bytes(self) -> int:
        """Cantidad exacta de bytes UTF-8 del fragmento."""
        return len(self.text.encode("utf-8"))

    @property
    def tokens_est_local(self) -> int:
        """Estimacion local del fragmento, no uso real del proveedor."""
        return estimate_tokens(self.text)


@dataclass(frozen=True, slots=True)
class PromptComposition:
    """Composicion estructurada cuyo render es el prompt enviado al LLM."""

    components: tuple[PromptComponent, ...]
    estimator_id: str = TOKEN_ESTIMATOR_ID

    @property
    def rendered_prompt(self) -> str:
        """Concatena los componentes sin insertar ni normalizar caracteres."""
        return "".join(component.text for component in self.components)

    @property
    def chars(self) -> int:
        """Caracteres exactos del prompt renderizado."""
        return len(self.rendered_prompt)

    @property
    def utf8_bytes(self) -> int:
        """Bytes UTF-8 exactos del prompt renderizado."""
        return len(self.rendered_prompt.encode("utf-8"))

    @property
    def tokens_est_local(self) -> int:
        """Estimacion local total aplicada al string finalmente enviado."""
        return estimate_tokens(self.rendered_prompt)

    def metrics(self) -> dict[str, object]:
        """Expone tamaños y procedencia sin incluir texto del prompt."""
        component_chars = sum(component.chars for component in self.components)
        component_utf8_bytes = sum(
            component.utf8_bytes for component in self.components
        )
        component_tokens = sum(
            component.tokens_est_local for component in self.components
        )
        return {
            "estimator_id": self.estimator_id,
            "chars": self.chars,
            "utf8_bytes": self.utf8_bytes,
            "tokens_est_local": self.tokens_est_local,
            "component_chars_total": component_chars,
            "component_utf8_bytes_total": component_utf8_bytes,
            "component_tokens_est_local_total": component_tokens,
            "chars_reconciled": component_chars == self.chars,
            "utf8_bytes_reconciled": component_utf8_bytes == self.utf8_bytes,
            "components": tuple(
                {
                    "kind": component.kind,
                    "source_id": component.source_id,
                    "chars": component.chars,
                    "utf8_bytes": component.utf8_bytes,
                    "tokens_est_local": component.tokens_est_local,
                }
                for component in self.components
            ),
        }


@dataclass(frozen=True, slots=True)
class IndexService:
    """Orquesta la indexacion local de chunks RAG.

    Attributes:
        settings: Configuracion efectiva de Barbarion.
        repository: Repositorio SQLite para metadata RAG.
        embedding_provider: Proveedor local de embeddings.
        vector_store: Almacen vectorial local.
    """

    settings: Settings
    repository: SQLiteRagRepository
    embedding_provider: EmbeddingProviderPort
    vector_store: VectorStorePort

    def run(
        self,
        *,
        mode: EmbeddingRunMode = EmbeddingRunMode.INCREMENTAL,
        scope: IndexScope | None = None,
        dry_run: bool = False,
        delete_obsolete: bool = True,
        progress: ProgressReporterPort | None = None,
        cancellation: CancellationTokenPort | None = None,
    ) -> IndexRunSummary:
        """Ejecuta una corrida de indexacion o calcula un plan dry-run.

        Args:
            mode: Modo de indexacion solicitado.
            scope: Alcance opcional para indexacion parcial.
            dry_run: Si es `True`, calcula el plan sin persistir cambios.
            delete_obsolete: Si es `True`, marca chunks obsoletos fuera de
                ejecuciones parciales.
            progress: Reporter opcional para progreso cooperativo.
            cancellation: Token opcional para interrupcion cooperativa.

        Returns:
            Resumen persistible de la corrida de indexacion.
        """
        started = time.monotonic()
        tracker = _IndexProgressTracker(progress)
        counters = _IndexCounters()
        tracker.start(_initial_stages())
        tracker.advance("discover", current=0, total=1)
        chunks = self.repository.indexable_chunks(
            domain=self.settings.domain,
            scope=scope,
        )
        tracker.advance("discover", current=1, total=1, message=f"chunks={len(chunks)}")
        if _is_cancelled(cancellation):
            summary = IndexRunSummary(
                status=EmbeddingRunStatus.INTERRUPTED,
                duration_ms=_duration_ms(started),
                pending_chunks=len(chunks),
                dry_run=dry_run,
            )
            tracker.finish(summary.status.value)
            return summary
        tracker.advance("plan", current=0, total=1)
        active_manifest = self.repository.find_active_manifest(
            provider=self.embedding_provider.provider,
            model=self.embedding_provider.model,
            distance=self.settings.vector_store.distance,
            normalize=self.settings.embeddings.normalize,
        )
        states: dict[str, ChunkEmbeddingState] = {}
        manifest: EmbeddingManifest | None = None
        manifest_id: int | None = None
        if active_manifest is not None:
            manifest = active_manifest.manifest
            manifest_id = active_manifest.id
            states = self.repository.chunk_embedding_states(
                manifest_id=manifest_id,
                scope=scope,
            )

        full = mode == EmbeddingRunMode.FULL
        plan = decide_index_plan(
            chunks,
            states,
            full=full,
            delete_obsolete=delete_obsolete and scope is None,
            dry_run=dry_run,
        )
        tracker.configure(_stages_for_plan(plan, manifest_probe=False, dry_run=dry_run))
        tracker.advance("plan", current=1, total=1, counters=_plan_counters(plan))
        if _is_cancelled(cancellation):
            summary = _interrupted_summary(
                counters=counters,
                plan_total=len(plan.decisions),
                started=started,
                dry_run=dry_run,
            )
            tracker.finish(summary.status.value)
            return summary
        if dry_run:
            tracker.advance("final", current=1, total=1)
            summary = _summary_from_plan(
                plan,
                status=EmbeddingRunStatus.COMPLETED,
                duration_ms=_duration_ms(started),
                dry_run=True,
            )
            tracker.finish(summary.status.value)
            return summary
        if scope is None and delete_obsolete:
            pruned_vectors = self.vector_store.prune_orphans()
            if pruned_vectors:
                _LOGGER.info(
                    "index_vector_integrity_pruned vectors=%d",
                    pruned_vectors,
                )
        if not chunks and not plan.deleted_chunks:
            tracker.advance("final", current=1, total=1)
            summary = IndexRunSummary(
                status=EmbeddingRunStatus.COMPLETED,
                duration_ms=_duration_ms(started),
            )
            tracker.finish(summary.status.value)
            return summary

        manifest_probe = manifest is None or manifest_id is None
        if manifest_probe:
            tracker.configure(_stages_for_plan(plan, manifest_probe=True, dry_run=dry_run))
            if _is_cancelled(cancellation):
                summary = _interrupted_summary(
                    counters=counters,
                    plan_total=len(plan.decisions),
                    started=started,
                    dry_run=dry_run,
                )
                tracker.finish(summary.status.value)
                return summary
            tracker.advance("embeddings", current=0, counters=counters.as_dict())
        if manifest is None or manifest_id is None:
            manifest = self._create_manifest_from_first_chunk(chunks)
            counters.embeddings_generated += 1
            tracker.advance("embeddings", current=1, counters=counters.as_dict())
            persisted = self.repository.get_or_create_manifest(manifest)
            manifest_id = persisted.id
            states = self.repository.chunk_embedding_states(
                manifest_id=manifest_id,
                scope=scope,
            )
            plan = decide_index_plan(
                chunks,
                states,
                full=full,
                delete_obsolete=delete_obsolete and scope is None,
            )
            tracker.configure(_stages_for_plan(plan, manifest_probe=True, dry_run=dry_run))

        run_id = self.repository.begin_embedding_run(
            manifest_id=manifest_id,
            mode=mode,
            scope=scope,
        )
        plan_total = len(plan.decisions)
        embedding_current = 1 if manifest_probe else 0
        vector_current = 0
        metadata_current = 0
        for decision in plan.decisions:
            if _is_cancelled(cancellation):
                break
            try:
                if decision.action == IndexAction.UNCHANGED:
                    counters.unchanged_chunks += 1
                    counters.processed_chunks += 1
                    metadata_current += 1
                    tracker.advance(
                        "metadata",
                        current=metadata_current,
                        counters=counters.as_dict(),
                    )
                    continue
                if decision.action == IndexAction.DELETE:
                    assert decision.chunk_id is not None
                    self.vector_store.delete(
                        manifest=manifest,
                        chunk_id=decision.chunk_id,
                    )
                    self.repository.mark_chunk_deleted(
                        run_id=run_id,
                        manifest_id=manifest_id,
                        chunk_id=decision.chunk_id,
                    )
                    counters.deleted_chunks += 1
                    counters.processed_chunks += 1
                    vector_current += 1
                    metadata_current += 1
                    tracker.advance(
                        "vectors",
                        current=vector_current,
                        counters=counters.as_dict(),
                    )
                    tracker.advance(
                        "metadata",
                        current=metadata_current,
                        counters=counters.as_dict(),
                    )
                    continue
                assert decision.chunk is not None
                vector = self._embed_chunk(decision.chunk, manifest)
                counters.embeddings_generated += 1
                embedding_current += 1
                tracker.advance(
                    "embeddings",
                    current=embedding_current,
                    counters=counters.as_dict(),
                )
                self.vector_store.upsert(
                    manifest=manifest,
                    chunk_id=decision.chunk.chunk_id,
                    vector=vector,
                    metadata=decision.chunk.metadata,
                )
                self.repository.record_chunk_indexed(
                    run_id=run_id,
                    manifest_id=manifest_id,
                    chunk=decision.chunk,
                )
                counters.vectors_persisted += 1
                counters.processed_chunks += 1
                vector_current += 1
                metadata_current += 1
                if decision.action == IndexAction.NEW:
                    counters.new_chunks += 1
                else:
                    counters.updated_chunks += 1
                tracker.advance(
                    "vectors",
                    current=vector_current,
                    counters=counters.as_dict(),
                )
                tracker.advance(
                    "metadata",
                    current=metadata_current,
                    counters=counters.as_dict(),
                )
            except Exception as exc:
                counters.failed_chunks += 1
                counters.processed_chunks += 1
                metadata_current += 1
                if decision.chunk is not None:
                    self.repository.record_chunk_error(
                        run_id=run_id,
                        manifest_id=manifest_id,
                        chunk=decision.chunk,
                        error_code=type(exc).__name__,
                        error_message=str(exc),
                    )
                tracker.advance(
                    "metadata",
                    current=metadata_current,
                    counters=counters.as_dict(),
                )

        interrupted = _is_cancelled(cancellation)
        status = _run_status(interrupted=interrupted, failed=counters.failed_chunks)
        summary = IndexRunSummary(
            status=status,
            new_chunks=counters.new_chunks,
            updated_chunks=counters.updated_chunks,
            unchanged_chunks=counters.unchanged_chunks,
            deleted_chunks=counters.deleted_chunks,
            failed_chunks=counters.failed_chunks,
            processed_chunks=counters.processed_chunks,
            pending_chunks=max(0, plan_total - counters.processed_chunks),
            embeddings_generated=counters.embeddings_generated,
            vectors_persisted=counters.vectors_persisted,
            duration_ms=_duration_ms(started),
            run_id=run_id,
        )
        self.repository.finish_embedding_run(
            run_id=run_id,
            status=status,
            new_chunks=summary.new_chunks,
            updated_chunks=summary.updated_chunks,
            unchanged_chunks=summary.unchanged_chunks,
            deleted_chunks=summary.deleted_chunks,
            failed_chunks=summary.failed_chunks,
            duration_ms=summary.duration_ms,
        )
        tracker.advance("final", current=1, total=1, counters=counters.as_dict())
        tracker.finish(summary.status.value)
        return summary

    def _create_manifest_from_first_chunk(
        self,
        chunks: tuple[IndexableChunk, ...],
    ) -> EmbeddingManifest:
        if not chunks:
            raise ValueError("No hay chunks para detectar dimension de embeddings.")
        placeholder_version = "0" * 64
        vector = self.embedding_provider.embed(
            EmbeddingRequest(
                texts=(chunks[0].content,),
                input_kind="chunk",
                embedding_version=placeholder_version,
            )
        )[0]
        return EmbeddingManifest(
            provider=self.embedding_provider.provider,
            model=self.embedding_provider.model,
            dimension=vector.dimension,
            distance=self.settings.vector_store.distance,
            normalize=self.settings.embeddings.normalize,
        )

    def _embed_chunk(
        self,
        chunk: IndexableChunk,
        manifest: EmbeddingManifest,
    ) -> tuple[float, ...]:
        vector = self.embedding_provider.embed(
            EmbeddingRequest(
                texts=(chunk.content,),
                input_kind="chunk",
                embedding_version=manifest.version or "",
            )
        )[0]
        if vector.dimension != manifest.dimension:
            raise ValueError("La dimension del embedding no coincide con el manifest.")
        return vector.values


def _summary_from_plan(
    plan,
    *,
    status: EmbeddingRunStatus,
    duration_ms: int,
    dry_run: bool,
) -> IndexRunSummary:
    return IndexRunSummary(
        status=status,
        new_chunks=plan.new_chunks,
        updated_chunks=plan.updated_chunks,
        unchanged_chunks=plan.unchanged_chunks,
        deleted_chunks=plan.deleted_chunks,
        processed_chunks=len(plan.decisions),
        pending_chunks=0,
        duration_ms=duration_ms,
        dry_run=dry_run,
    )


@dataclass(slots=True)
class _IndexCounters:
    new_chunks: int = 0
    updated_chunks: int = 0
    unchanged_chunks: int = 0
    deleted_chunks: int = 0
    failed_chunks: int = 0
    processed_chunks: int = 0
    embeddings_generated: int = 0
    vectors_persisted: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "new": self.new_chunks,
            "update": self.updated_chunks,
            "unchanged": self.unchanged_chunks,
            "delete": self.deleted_chunks,
            "errores": self.failed_chunks,
            "procesados": self.processed_chunks,
            "embeddings": self.embeddings_generated,
            "vectores": self.vectors_persisted,
        }


class _IndexProgressTracker:
    def __init__(self, reporter: ProgressReporterPort | None) -> None:
        self._reporter = reporter
        self._stages: dict[str, ProgressStage] = {}
        self._stage_done: dict[str, int] = {}

    def start(self, stages: tuple[ProgressStage, ...]) -> None:
        self.configure(stages)
        if self._reporter is not None:
            self._reporter.start(stages)

    def configure(self, stages: tuple[ProgressStage, ...]) -> None:
        self._stages = {stage.key: stage for stage in stages}
        self._stage_done = {
            key: self._stage_done.get(key, 0)
            for key in self._stages
        }

    def advance(
        self,
        key: str,
        *,
        current: int,
        total: int | None = None,
        counters: dict[str, int] | None = None,
        message: str | None = None,
    ) -> None:
        if self._reporter is None:
            return
        stage = self._stages.get(key, ProgressStage(key=key, label=key, total=total))
        stage_total = total if total is not None else stage.total
        safe_current = max(0, current)
        if stage_total is not None:
            safe_current = min(safe_current, stage_total)
        self._stage_done[key] = safe_current
        global_total = self._global_total
        global_current = sum(self._stage_done.values())
        self._reporter.stage(
            ProgressSnapshot(
                stage_key=key,
                stage_label=stage.label,
                current=safe_current,
                total=stage_total,
                global_current=global_current,
                global_total=global_total,
                counters=dict(counters or {}),
                message=message,
            )
        )

    def finish(self, status: str) -> None:
        if self._reporter is not None:
            self._reporter.finish(status)

    @property
    def _global_total(self) -> int | None:
        totals = [stage.total for stage in self._stages.values()]
        if any(total is None for total in totals):
            return None
        return sum(int(total) for total in totals)


def _initial_stages() -> tuple[ProgressStage, ...]:
    return (
        ProgressStage("discover", "Descubriendo chunks", 1),
        ProgressStage("plan", "Planificando indexacion", 1),
        ProgressStage("final", "Finalizando", 1),
    )


def _stages_for_plan(plan, *, manifest_probe: bool, dry_run: bool) -> tuple[ProgressStage, ...]:
    if dry_run:
        return _initial_stages()
    embedding_work = plan.new_chunks + plan.updated_chunks + (1 if manifest_probe else 0)
    vector_work = plan.new_chunks + plan.updated_chunks + plan.deleted_chunks
    return (
        ProgressStage("discover", "Descubriendo chunks", 1),
        ProgressStage("plan", "Planificando indexacion", 1),
        ProgressStage("embeddings", "Generando embeddings", embedding_work),
        ProgressStage("vectors", "Persistiendo vectores", vector_work),
        ProgressStage("metadata", "Actualizando metadata", len(plan.decisions)),
        ProgressStage("final", "Finalizando", 1),
    )


def _plan_counters(plan) -> dict[str, int]:
    return {
        "new": plan.new_chunks,
        "update": plan.updated_chunks,
        "unchanged": plan.unchanged_chunks,
        "delete": plan.deleted_chunks,
        "errores": 0,
    }


def _is_cancelled(cancellation: CancellationTokenPort | None) -> bool:
    return bool(cancellation is not None and cancellation.cancelled)


def _run_status(*, interrupted: bool, failed: int) -> EmbeddingRunStatus:
    if interrupted:
        return EmbeddingRunStatus.INTERRUPTED
    if failed:
        return EmbeddingRunStatus.COMPLETED_WITH_ERRORS
    return EmbeddingRunStatus.COMPLETED


def _interrupted_summary(
    *,
    counters: _IndexCounters,
    plan_total: int,
    started: float,
    dry_run: bool,
) -> IndexRunSummary:
    return IndexRunSummary(
        status=EmbeddingRunStatus.INTERRUPTED,
        new_chunks=counters.new_chunks,
        updated_chunks=counters.updated_chunks,
        unchanged_chunks=counters.unchanged_chunks,
        deleted_chunks=counters.deleted_chunks,
        failed_chunks=counters.failed_chunks,
        processed_chunks=counters.processed_chunks,
        pending_chunks=max(0, plan_total - counters.processed_chunks),
        embeddings_generated=counters.embeddings_generated,
        vectors_persisted=counters.vectors_persisted,
        duration_ms=_duration_ms(started),
        dry_run=dry_run,
    )


def _duration_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


@dataclass(frozen=True, slots=True)
class SearchService:
    """Orquesta recuperacion semantic, keyword e hybrid para RAG.

    Attributes:
        settings: Configuracion efectiva de Barbarion.
        repository: Repositorio SQLite para consultas y chunks.
        embedding_provider: Proveedor local usado para consultas semanticas.
        vector_store: Almacen vectorial local.
    """

    settings: Settings
    repository: SQLiteRagRepository
    embedding_provider: EmbeddingProviderPort
    vector_store: VectorStorePort

    def search(self, request: SearchRequest) -> SearchResponse:
        """Ejecuta busqueda RAG y registra observabilidad local.

        Args:
            request: Parametros de consulta, filtros, modo y limites.

        Returns:
            Respuesta con candidatos enriquecidos, timings y debug opcional.
        """
        manifest_row = self.repository.find_active_manifest(
            provider=self.embedding_provider.provider,
            model=self.embedding_provider.model,
            distance=self.settings.vector_store.distance,
            normalize=self.settings.embeddings.normalize,
        )
        manifest = manifest_row.manifest if manifest_row is not None else None
        vector_candidates = ()
        keyword_candidates = ()
        vector_ms = None
        keyword_ms = None
        ranking_started = time.monotonic()
        try:
            if request.mode in {RetrievalMode.SEMANTIC, RetrievalMode.HYBRID}:
                if manifest is not None:
                    vector_started = time.monotonic()
                    vector_candidates = self._semantic_search(request, manifest)
                    vector_ms = _duration_ms(vector_started)
                else:
                    vector_candidates = ()
                    vector_ms = 0
            if request.mode in {RetrievalMode.KEYWORD, RetrievalMode.HYBRID}:
                keyword_started = time.monotonic()
                keyword_candidates = self.repository.keyword_search(
                    domain=self.settings.domain,
                    query=request.query,
                    filters=request.filters,
                    top_k=request.candidate_k,
                )
                keyword_ms = _duration_ms(keyword_started)

            candidates = self._rank(
                request=request,
                vector_candidates=vector_candidates,
                keyword_candidates=keyword_candidates,
            )
            ranking_ms = _duration_ms(ranking_started)
            timings = SearchTimings(
                vector_ms=vector_ms,
                keyword_ms=keyword_ms,
                ranking_ms=ranking_ms,
            )
            status = (
                RagQueryStatus.COMPLETED
                if candidates
                else RagQueryStatus.INSUFFICIENT_EVIDENCE
            )
            query_id = self.repository.record_rag_query(
                manifest_id=None if manifest_row is None else manifest_row.id,
                query_text=request.query,
                mode=request.mode,
                top_k=request.top_k,
                filters=request.filters,
                candidate_count=len(candidates),
                timings=timings,
                status=status,
            )
        except Exception:
            timings = SearchTimings(
                vector_ms=vector_ms,
                keyword_ms=keyword_ms,
                ranking_ms=_duration_ms(ranking_started),
            )
            self.repository.record_rag_query(
                manifest_id=None if manifest_row is None else manifest_row.id,
                query_text=request.query,
                mode=request.mode,
                top_k=request.top_k,
                filters=request.filters,
                candidate_count=0,
                timings=timings,
                status=RagQueryStatus.ERROR,
            )
            raise

        debug = {}
        if request.debug:
            debug = {
                "vector_candidates": len(vector_candidates),
                "keyword_candidates": len(keyword_candidates),
                "threshold": request.similarity_threshold,
            }
        return SearchResponse(
            query_id=query_id,
            mode=request.mode,
            candidates=candidates,
            timings=timings,
            debug=debug,
        )

    def _semantic_search(
        self,
        request: SearchRequest,
        manifest: EmbeddingManifest,
    ):
        vector = self.embedding_provider.embed(
            EmbeddingRequest(
                texts=(request.query,),
                input_kind="query",
                embedding_version=manifest.version or "",
            )
        )[0]
        if vector.dimension != manifest.dimension:
            raise ValueError("La dimension del embedding de consulta no coincide.")
        candidates = self.vector_store.search(
            manifest=manifest,
            query_vector=vector.values,
            filters=request.filters,
            top_k=request.candidate_k,
        )
        return tuple(
            candidate
            for candidate in candidates
            if candidate.combined_score >= request.similarity_threshold
        )

    def _rank(
        self,
        *,
        request: SearchRequest,
        vector_candidates,
        keyword_candidates,
    ):
        result_limit = request.candidate_k if request.defer_top_k else request.top_k
        if request.mode == RetrievalMode.SEMANTIC:
            candidates = tuple(
                _with_mode(candidate, RetrievalMode.SEMANTIC)
                for candidate in vector_candidates
            )[:result_limit]
        elif request.mode == RetrievalMode.KEYWORD:
            candidates = tuple(
                candidate
                for candidate in keyword_candidates
                if candidate.combined_score >= request.similarity_threshold
            )[:result_limit]
        else:
            candidates = combine_hybrid_candidates(
                vector_candidates,
                keyword_candidates,
                vector_weight=request.vector_weight,
                keyword_weight=request.keyword_weight,
                top_k=result_limit,
                threshold=request.similarity_threshold,
            )
        return self.repository.enrich_candidates(
            candidates,
            include_snippets=self.settings.rag.include_snippets,
        )


def _with_mode(candidate, mode: RetrievalMode):
    return type(candidate)(
        chunk_id=candidate.chunk_id,
        content_sha256=candidate.content_sha256,
        combined_score=candidate.combined_score,
        vector_score=candidate.vector_score,
        keyword_score=candidate.keyword_score,
        metadata=candidate.metadata,
        source={**dict(candidate.source), "retrieval_mode": mode.value},
    )


@dataclass(frozen=True, slots=True)
class DataDrivenEvidenceRetriever:
    """Recupera evidencia estructurada Data-Driven para preguntas RAG.

    El recuperador consulta exclusivamente el catalogo tecnico persistido. Solo
    considera simbolos activos, aplica filtros RAG compatibles y expande las
    coincidencias mediante jerarquia y relaciones activas. Las expresiones y el
    SQL se presentan como evidencia; nunca se ejecutan.

    Attributes:
        repository: Repositorio de simbolos y relaciones reverse engineering.
        rag_repository: Repositorio usado para cargar chunks de codigo trazables.
        domain: Dominio local efectivo de la consulta.
    """

    repository: SQLiteReverseEngineeringRepository
    rag_repository: SQLiteRagRepository
    domain: str

    def retrieve(
        self,
        question: str,
        *,
        filters: RetrievalFilter,
        limit: int,
    ) -> tuple[RetrievalCandidate, ...]:
        """Recupera simbolos por concepto y expande sus relaciones vigentes.

        Args:
            question: Pregunta natural usada para el matching lexical.
            filters: Alcance RAG que tambien debe respetar la evidencia H4.
            limit: Cantidad maxima de candidatos estructurados y de codigo.

        Returns:
            Candidatos citables ordenados de forma determinista.
        """
        if limit <= 0 or not _structured_domain_allowed(filters, self.domain):
            return ()
        question_concepts = _query_concept_groups(question)
        if not question_concepts:
            return ()
        active_symbols = self.repository.active_symbols()
        by_id = {symbol.symbol_id: symbol for symbol in active_symbols}
        configuration_symbols = tuple(
            symbol
            for symbol in active_symbols
            if symbol.technology == "configuration"
            and _structured_symbol_in_scope(symbol, filters)
        )
        frequency_contexts = _structured_frequency_contexts(
            configuration_symbols,
            by_id,
        )
        concept_frequencies = _structured_concept_frequencies(
            question_concepts,
            frequency_contexts,
        )
        ranked = [
            (score, symbol)
            for symbol in configuration_symbols
            if (
                score := _structured_symbol_score(
                    symbol,
                    question,
                    question_concepts,
                    concept_frequencies,
                    population_size=len(frequency_contexts),
                )
            )
            > 0
        ]
        ranked.sort(key=lambda item: (-item[0], _structured_symbol_sort_key(item[1])))

        candidates: list[RetrievalCandidate] = []
        seen_chunks: set[str] = set()
        seen_records: set[str] = set()
        for score, seed in ranked:
            if len(candidates) >= limit:
                break
            roots = _structured_relation_roots(seed, by_id)
            record_key = next(
                (
                    root.symbol_id
                    for root in roots
                    if root.symbol_type == "configuration_record"
                ),
                seed.symbol_id,
            )
            if record_key in seen_records:
                continue
            seen_records.add(record_key)
            relations = _active_relations_for_roots(self.repository, roots)
            related = _active_related_symbols(relations, by_id)
            block = _render_structured_evidence(seed, roots, relations, by_id)
            structured = _structured_candidate(
                seed,
                relations,
                block,
                score,
                domain=self.domain,
            )
            candidates.append(structured)
            seen_chunks.add(structured.chunk_id)

            for related_symbol, relation_ids in related:
                if len(candidates) >= limit:
                    break
                if related_symbol.technology == "configuration":
                    continue
                if not _structured_symbol_in_scope(related_symbol, filters):
                    continue
                chunk_candidate = _related_code_candidate(
                    related_symbol,
                    relation_ids=relation_ids,
                    score=max(0.01, score * 0.95),
                )
                if chunk_candidate is None or chunk_candidate.chunk_id in seen_chunks:
                    continue
                enriched = self.rag_repository.enrich_candidates(
                    (chunk_candidate,),
                    include_snippets=True,
                )[0]
                if not enriched.source.get("content"):
                    continue
                candidates.append(enriched)
                seen_chunks.add(enriched.chunk_id)
        return tuple(candidates[:limit])


_STRUCTURED_METADATA_KEYS = (
    "configuration_name",
    "table_name",
    "declared_columns",
    "display_values",
    "identity",
    "values",
    "value",
    "column",
    "operation",
    "partial",
)


def _structured_domain_allowed(filters: RetrievalFilter, domain: str) -> bool:
    """Comprueba el filtro de dominio antes de consultar simbolos."""
    return filters.domain is None or filters.domain == domain


def _structured_symbol_in_scope(
    symbol: TechnicalSymbol,
    filters: RetrievalFilter,
) -> bool:
    """Aplica al simbolo los filtros RAG que tienen equivalente trazable."""
    metadata = symbol.metadata
    path = str(metadata.get("relative_path") or "").replace("\\", "/")
    artifact_kind = str(metadata.get("artifact_kind") or symbol.technology)
    language = {
        "oracle": "plsql",
        "powerbuilder": "powerscript",
    }.get(artifact_kind)
    if filters.artifact_kind is not None and filters.artifact_kind != artifact_kind:
        return False
    if filters.language is not None and filters.language != language:
        return False
    if filters.document_id is not None and filters.document_id != symbol.document_id:
        return False
    if filters.folder is not None:
        folder = str(PurePosixPath(path).parent)
        if folder == ".":
            folder = ""
        if not folder.startswith(filters.folder.rstrip("/")):
            return False
    if filters.extension is not None and not path.lower().endswith(
        filters.extension.lower()
    ):
        return False
    return True


def _structured_symbol_score(
    symbol: TechnicalSymbol,
    question: str,
    question_concepts: tuple[frozenset[str], ...],
    concept_frequencies: tuple[int, ...],
    *,
    population_size: int,
) -> float:
    """Puntua cobertura, rareza y precision de campos estructurados."""
    fields = _structured_symbol_token_fields(symbol)
    matched_indexes = tuple(
        index
        for index, variants in enumerate(question_concepts)
        if variants & fields["all"]
    )
    if not matched_indexes:
        return 0.0

    matched_count = len(matched_indexes)
    coverage = matched_count / len(question_concepts)
    quantity = min(1.0, matched_count / 3)
    rarity = sum(
        _structured_inverse_frequency(
            concept_frequencies[index],
            population_size=population_size,
        )
        for index in matched_indexes
    ) / matched_count
    field_precision = sum(
        _structured_concept_field_precision(
            question_concepts[index],
            fields,
        )
        for index in matched_indexes
    ) / matched_count
    multi_concept = min(1.0, max(0, matched_count - 1) / 2)
    score = (
        (0.30 * coverage)
        + (0.15 * quantity)
        + (0.25 * rarity)
        + (0.20 * field_precision)
        + (0.10 * multi_concept)
    )
    if _symbol_matches_exact_query_identifier(symbol, question):
        score += 0.1
    return min(1.0, score)


def _symbol_matches_exact_query_identifier(
    symbol: TechnicalSymbol,
    question: str,
) -> bool:
    """Detecta identificadores tecnicos completos en identidad/nombre del simbolo."""
    normalized_question = _normalize_text(question).strip()
    if normalized_question in {
        _normalize_text(symbol.original_name),
        _normalize_text(symbol.normalized_name),
    }:
        return True
    query_identifiers = _query_identifiers(question)
    if not query_identifiers:
        return False
    identity_text = " ".join(
        (
            symbol.original_name,
            symbol.normalized_name,
            _metadata_values_text(symbol, ("identity",)),
        )
    )
    return bool(query_identifiers & _identifier_tokens(identity_text))


def _query_concept_groups(text: str) -> tuple[frozenset[str], ...]:
    """Agrupa cada termino original con sus variantes morfologicas."""
    groups: list[frozenset[str]] = []
    seen: set[frozenset[str]] = set()
    for token in re.findall(r"[a-z0-9_]+", _normalize_text(text)):
        if (
            (len(token) < 4 and "_" not in token)
            or re.fullmatch(r"f\d+", token)
        ):
            continue
        group = frozenset(_concept_token_variants(token))
        if group & _STOPWORDS:
            continue
        if group in seen:
            continue
        seen.add(group)
        groups.append(group)
    return tuple(groups)


def _structured_symbol_token_fields(
    symbol: TechnicalSymbol,
) -> dict[str, set[str]]:
    """Separa tokens por precision general del campo estructurado."""
    names = _important_tokens(f"{symbol.original_name} {symbol.normalized_name}")
    declared_values = _important_tokens(
        _metadata_values_text(symbol, ("identity", "values", "value"))
    )
    descriptive = _important_tokens(
        _metadata_values_text(symbol, ("display_values",))
    )
    structural = _important_tokens(
        " ".join(
            (
                symbol.symbol_type,
                _metadata_values_text(
                    symbol,
                    (
                        "configuration_name",
                        "table_name",
                        "declared_columns",
                        "column",
                    ),
                ),
            )
        )
    )
    return {
        "names": names,
        "declared_values": declared_values,
        "descriptive": descriptive,
        "structural": structural,
        "all": names | declared_values | descriptive | structural,
    }


def _metadata_values_text(
    symbol: TechnicalSymbol,
    keys: tuple[str, ...],
) -> str:
    """Serializa valores de metadata seleccionados para tokenizacion."""
    selected = {
        key: _plain_metadata_value(symbol.metadata[key])
        for key in keys
        if key in symbol.metadata
    }
    return json.dumps(selected, ensure_ascii=True, sort_keys=True)


def _structured_frequency_contexts(
    symbols: tuple[TechnicalSymbol, ...],
    active_symbols: dict[str, TechnicalSymbol],
) -> tuple[set[str], ...]:
    """Agrupa tokens por registro para estimar frecuencia sin contar hijos."""
    contexts: dict[str, set[str]] = {}
    for symbol in symbols:
        record_key = _structured_record_key(symbol, active_symbols)
        contexts.setdefault(record_key, set()).update(
            _structured_symbol_token_fields(symbol)["all"]
        )
    return tuple(contexts[key] for key in sorted(contexts))


def _structured_record_key(
    symbol: TechnicalSymbol,
    active_symbols: dict[str, TechnicalSymbol],
) -> str:
    """Obtiene el registro ancestro usado como unidad de frecuencia."""
    current = symbol
    while current.symbol_type != "configuration_record":
        if current.parent_symbol_id is None:
            return current.symbol_id
        parent = active_symbols.get(current.parent_symbol_id)
        if parent is None:
            return current.symbol_id
        current = parent
    return current.symbol_id


def _structured_concept_frequencies(
    concepts: tuple[frozenset[str], ...],
    contexts: tuple[set[str], ...],
) -> tuple[int, ...]:
    """Cuenta en cuantos registros aparece cada concepto de la consulta."""
    return tuple(
        sum(1 for context in contexts if variants & context)
        for variants in concepts
    )


def _structured_inverse_frequency(frequency: int, *, population_size: int) -> float:
    """Normaliza IDF a 0..1 para reducir terminos muy frecuentes."""
    if population_size <= 1 or frequency <= 1:
        return 1.0
    numerator = math.log((population_size + 1) / (frequency + 0.5))
    denominator = math.log((population_size + 1) / 1.5)
    return max(0.0, min(1.0, numerator / denominator))


def _structured_concept_field_precision(
    concept: frozenset[str],
    fields: dict[str, set[str]],
) -> float:
    """Asigna mayor peso a identidad, nombres y valores declarados."""
    if concept & fields["names"]:
        return 1.0
    if concept & fields["declared_values"]:
        return 0.9
    if concept & fields["descriptive"]:
        return 0.7
    if concept & fields["structural"]:
        return 0.5
    return 0.0


def _structured_metadata_text(symbol: TechnicalSymbol) -> str:
    """Serializa solo metadata seleccionada para recuperacion y evidencia."""
    selected = {
        key: _plain_metadata_value(symbol.metadata[key])
        for key in _STRUCTURED_METADATA_KEYS
        if key in symbol.metadata
    }
    return json.dumps(selected, ensure_ascii=True, sort_keys=True)


def _plain_metadata_value(value):
    """Convierte metadata congelada en estructuras JSON deterministas."""
    if isinstance(value, Mapping):
        return {
            str(key): _plain_metadata_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_plain_metadata_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _structured_relation_roots(
    seed: TechnicalSymbol,
    active_symbols: dict[str, TechnicalSymbol],
) -> tuple[TechnicalSymbol, ...]:
    """Incluye la semilla y sus padres activos para encontrar relaciones."""
    roots: list[TechnicalSymbol] = [seed]
    current = seed
    while current.parent_symbol_id is not None:
        parent = active_symbols.get(current.parent_symbol_id)
        if parent is None or parent in roots:
            break
        roots.append(parent)
        current = parent
    return tuple(roots)


def _active_relations_for_roots(
    repository: SQLiteReverseEngineeringRepository,
    roots: tuple[TechnicalSymbol, ...],
) -> tuple[TechnicalRelation, ...]:
    """Carga y deduplica relaciones activas adyacentes a las raices."""
    relations: dict[str, TechnicalRelation] = {}
    for root in roots:
        for relation in repository.active_relations_for_symbol(
            root.symbol_id,
            direction=DependencyDirection.BOTH,
        ):
            relations.setdefault(relation.relation_id, relation)
    return tuple(
        sorted(
            relations.values(),
            key=lambda relation: (
                relation.relation_type,
                relation.resolution_status.value,
                relation.target_key or "",
                relation.relation_id,
            ),
        )
    )


def _active_related_symbols(
    relations: tuple[TechnicalRelation, ...],
    active_symbols: dict[str, TechnicalSymbol],
) -> tuple[tuple[TechnicalSymbol, tuple[str, ...]], ...]:
    """Agrupa simbolos activos alcanzados por las relaciones recuperadas."""
    relation_ids: dict[str, list[str]] = {}
    for relation in relations:
        for symbol_id in (relation.source_symbol_id, relation.target_symbol_id):
            if symbol_id is not None and symbol_id in active_symbols:
                relation_ids.setdefault(symbol_id, []).append(relation.relation_id)
    return tuple(
        (
            active_symbols[symbol_id],
            tuple(sorted(set(ids))),
        )
        for symbol_id, ids in sorted(
            relation_ids.items(),
            key=lambda item: _structured_symbol_sort_key(active_symbols[item[0]]),
        )
    )


def _render_structured_evidence(
    seed: TechnicalSymbol,
    roots: tuple[TechnicalSymbol, ...],
    relations: tuple[TechnicalRelation, ...],
    active_symbols: dict[str, TechnicalSymbol],
) -> str:
    """Genera un bloque legible y citable desde simbolos y relaciones."""
    metadata = _structured_metadata_text(seed)
    lines = [
        "Evidencia estructurada del catalogo tecnico",
        f"simbolo_id={seed.symbol_id}",
        f"nombre_original={seed.original_name}",
        f"nombre_normalizado={seed.normalized_name}",
        f"tipo={seed.symbol_type}",
        f"tecnologia={seed.technology}",
        f"estado={seed.status.value}",
        f"archivo={seed.metadata.get('relative_path') or 'desconocido'}",
        f"lineas={seed.start_line or 'n/a'}-{seed.end_line or 'n/a'}",
        f"chunk={seed.chunk_id or 'n/a'}",
        f"metadata_declarada={metadata}",
    ]
    hierarchy = [
        f"{symbol.symbol_type}:{symbol.normalized_name}:{symbol.symbol_id}"
        for symbol in roots
    ]
    lines.append("jerarquia=" + " -> ".join(hierarchy))
    lines.append("relaciones:")
    if not relations:
        lines.append("- ninguna relacion activa adyacente")
    for relation in relations:
        source = active_symbols.get(relation.source_symbol_id or "")
        target = active_symbols.get(relation.target_symbol_id or "")
        source_label = source.normalized_name if source is not None else "desconocido"
        target_label = (
            target.normalized_name
            if target is not None
            else relation.target_key or "sin_destino"
        )
        target_detail = (
            f"{target.technology}/{target.symbol_type}"
            if target is not None
            else "sin_simbolo_activo"
        )
        lines.append(
            "- "
            f"relacion_id={relation.relation_id}; "
            f"tipo={relation.relation_type}; "
            f"estado={relation.resolution_status.value}; "
            f"origen={source_label}; destino={target_label}; "
            f"destino_tecnico={target_detail}; "
            f"archivo_id={relation.evidence_file_id}; "
            f"chunk={relation.evidence_chunk_id or 'n/a'}; "
            f"lineas={relation.start_line or 'n/a'}-{relation.end_line or 'n/a'}"
        )
    related_ids = {
        symbol_id
        for relation in relations
        for symbol_id in (relation.source_symbol_id, relation.target_symbol_id)
        if symbol_id is not None
        and symbol_id in active_symbols
        and symbol_id not in {root.symbol_id for root in roots}
    }
    lines.append("simbolos_relacionados:")
    if not related_ids:
        lines.append("- ninguno")
    for symbol_id in sorted(
        related_ids,
        key=lambda item: _structured_symbol_sort_key(active_symbols[item]),
    ):
        related = active_symbols[symbol_id]
        lines.append(
            "- "
            f"simbolo_id={related.symbol_id}; "
            f"nombre={related.normalized_name}; "
            f"tecnologia={related.technology}; tipo={related.symbol_type}; "
            f"metadata_declarada={_structured_metadata_text(related)}"
        )
    return "\n".join(lines)


def _structured_candidate(
    symbol: TechnicalSymbol,
    relations: tuple[TechnicalRelation, ...],
    content: str,
    score: float,
    *,
    domain: str,
) -> RetrievalCandidate:
    """Convierte un bloque estructurado en candidato RAG trazable."""
    return RetrievalCandidate(
        chunk_id=f"symbol:{symbol.symbol_id}",
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        combined_score=score,
        keyword_score=score,
        metadata=SymbolMetadata(
            symbol_name=symbol.normalized_name,
            symbol_kind=symbol.symbol_type,
            parent_symbol=symbol.container_name,
        ),
        source={
            "evidence_kind": "structured_symbol",
            "retrieval_mode": "structured",
            "symbol_id": symbol.symbol_id,
            "relation_ids": tuple(
                relation.relation_id for relation in relations
            ),
            "domain": domain,
            "artifact_kind": "configuration",
            "language": "sql",
            "document_id": symbol.document_id,
            "file_id": symbol.file_id,
            "relative_path": symbol.metadata.get("relative_path")
            or "catalogo-tecnico",
            "folder": str(
                PurePosixPath(
                    str(symbol.metadata.get("relative_path") or "")
                ).parent
            ),
            "extension": ".sql",
            "ordinal": -1,
            "start_line": symbol.start_line,
            "end_line": symbol.end_line,
            "content": content,
        },
    )


def _related_code_candidate(
    symbol: TechnicalSymbol,
    *,
    relation_ids: tuple[str, ...],
    score: float,
) -> RetrievalCandidate | None:
    """Prepara un chunk de codigo relacionado para enriquecimiento RAG."""
    if symbol.chunk_id is None:
        return None
    return RetrievalCandidate(
        chunk_id=symbol.chunk_id,
        content_sha256=symbol.symbol_id,
        combined_score=score,
        keyword_score=score,
        metadata=SymbolMetadata(
            symbol_name=symbol.normalized_name,
            symbol_kind=symbol.symbol_type,
            parent_symbol=symbol.container_name,
        ),
        source={
            "evidence_kind": "related_code",
            "retrieval_mode": "structured_expansion",
            "symbol_id": symbol.symbol_id,
            "relation_ids": relation_ids,
        },
    )


def _structured_symbol_sort_key(symbol: TechnicalSymbol) -> tuple[str, ...]:
    """Ordena simbolos estructurados de forma estable."""
    return (
        symbol.technology,
        symbol.container_name or "",
        symbol.normalized_name,
        symbol.symbol_type,
        symbol.symbol_id,
    )


@dataclass(frozen=True, slots=True)
class ContextBuilder:
    """Construye el contexto final que recibira el LLM.

    Attributes:
        token_budget: Presupuesto maximo estimado del contexto renderizado.
        max_chunk_tokens: Limite estimado por chunk individual.
        dedupe_min_hash_prefix: Longitud de prefijo para deduplicar contenido.
        threshold: Score minimo aceptado antes de construir contexto.
    """

    token_budget: int
    max_chunk_tokens: int
    dedupe_min_hash_prefix: int
    threshold: float = 0.0
    selection_policy: str = "baseline_v1"

    def build(
        self,
        candidates,
        *,
        debug: bool = False,
    ) -> ContextBuildResult:
        """Aplica threshold, dedupe, orden estable y presupuesto de contexto.

        Args:
            candidates: Candidatos recuperados por `SearchService`.
            debug: Si es `True`, incluye metricas efimeras del armado.

        Returns:
            Contexto renderizado con fuentes numeradas y metricas de calidad.
        """
        thresholded, score_omitted = self._threshold(candidates)
        deduped, duplicate_omitted = self._dedupe(thresholded)
        ordered = (
            self._relevance_order(deduped)
            if self.selection_policy == "optimized_v1"
            else self._stable_document_order(deduped)
        )
        sources: list[ContextSource] = []
        budget_candidates: list[RetrievalCandidate] = []
        content_omitted: list[dict[str, object]] = []
        used_tokens = 0
        for candidate in ordered:
            content = str(candidate.source.get("content") or candidate.source.get("snippet") or "")
            if not content:
                content_omitted.append(
                    {"chunk_id": candidate.chunk_id, "reason": "missing_content"}
                )
                continue
            remaining_tokens = self.token_budget - used_tokens
            source = _source_for_context_budget(
                candidate,
                source_id=f"F{len(sources) + 1}",
                max_chunk_tokens=self.max_chunk_tokens,
                remaining_tokens=remaining_tokens,
            )
            if source is None:
                budget_candidates.append(candidate)
                continue
            token_estimate = estimate_tokens(_render_source_context(source))
            sources.append(source)
            used_tokens += token_estimate
        if self.selection_policy == "optimized_v1":
            pending = list(budget_candidates)
            while True:
                sources, _trimmed_pairs = _trim_exact_contiguous_overlaps(sources)
                used_tokens = sum(
                    estimate_tokens(_render_source_context(source))
                    for source in sources
                )
                added = False
                still_pending: list[RetrievalCandidate] = []
                for candidate in pending:
                    source = _source_for_context_budget(
                        candidate,
                        source_id=f"F{len(sources) + 1}",
                        max_chunk_tokens=self.max_chunk_tokens,
                        remaining_tokens=self.token_budget - used_tokens,
                    )
                    if source is None:
                        still_pending.append(candidate)
                        continue
                    sources.append(source)
                    used_tokens += estimate_tokens(_render_source_context(source))
                    added = True
                pending = still_pending
                if not added:
                    break
            budget_candidates = pending
            sources = [
                replace(source, source_id=f"F{index}")
                for index, source in enumerate(
                    self._stable_source_document_order(sources),
                    start=1,
                )
            ]
        omitted = tuple(
            (
                *score_omitted,
                *duplicate_omitted,
                *content_omitted,
                *(
                    {"chunk_id": candidate.chunk_id, "reason": "budget"}
                    for candidate in budget_candidates
                ),
            )
        )
        duplicate_ratio = (
            len(duplicate_omitted) / len(candidates) if candidates else 0.0
        )
        selected_candidates = len(sources)
        token_waste = (
            max(0, self.token_budget - used_tokens) / self.token_budget
            if self.token_budget
            else 0.0
        )
        metrics = ContextQualityMetrics(
            context_precision=None,
            context_recall=(
                selected_candidates / len(candidates) if candidates else 0.0
            ),
            duplicate_ratio=duplicate_ratio,
            token_waste=token_waste,
        )
        debug_payload = {}
        if debug:
            evidence_decisions = _evidence_decisions(
                candidates,
                sources=tuple(sources),
                omitted=omitted,
                dedupe_min_hash_prefix=self.dedupe_min_hash_prefix,
            )
            redundancy = _context_redundancy_report(
                candidates,
                sources=tuple(sources),
                dedupe_min_hash_prefix=self.dedupe_min_hash_prefix,
            )
            debug_payload = {
                "input_candidates": len(candidates),
                "after_threshold": len(thresholded),
                "after_dedupe": len(deduped),
                "omitted": len(omitted),
                "token_budget": self.token_budget,
                "token_estimate": used_tokens,
                "context_chars": len(_render_context(sources)),
                "truncated_sources": sum(
                    1 for source in sources if source.content_truncated
                ),
                "selection_policy": self.selection_policy,
                "evidence_decisions": evidence_decisions,
                "redundancy_report": redundancy,
            }
        return ContextBuildResult(
            sources=tuple(sources),
            omitted=omitted,
            rendered_context=_render_context(sources),
            token_estimate=used_tokens,
            metrics=metrics,
            debug=debug_payload,
        )

    def _threshold(self, candidates):
        selected = []
        omitted = []
        for candidate in candidates:
            if candidate.combined_score < self.threshold:
                omitted.append({"chunk_id": candidate.chunk_id, "reason": "threshold"})
            else:
                selected.append(candidate)
        return tuple(selected), tuple(omitted)

    def _dedupe(self, candidates):
        selected = []
        omitted = []
        seen_chunks: set[str] = set()
        seen_hashes: set[str] = set()
        prefix = self.dedupe_min_hash_prefix
        for candidate in candidates:
            hash_prefix = candidate.content_sha256[:prefix]
            if candidate.chunk_id in seen_chunks or hash_prefix in seen_hashes:
                omitted.append({"chunk_id": candidate.chunk_id, "reason": "duplicate"})
                continue
            seen_chunks.add(candidate.chunk_id)
            seen_hashes.add(hash_prefix)
            selected.append(candidate)
        return tuple(selected), tuple(omitted)

    def _stable_document_order(self, candidates):
        return tuple(
            sorted(
                candidates,
                key=lambda candidate: (
                    0
                    if candidate.source.get("evidence_kind") == "structured_symbol"
                    else 1,
                    int(candidate.source.get("document_id") or 0),
                    int(candidate.source.get("ordinal") or 0),
                    -candidate.combined_score,
                    candidate.chunk_id,
                ),
            )
        )

    def _relevance_order(self, candidates):
        return tuple(
            sorted(
                candidates,
                key=lambda candidate: (
                    int(
                        candidate.source.get("selection_global_rank")
                        if candidate.source.get("selection_global_rank") is not None
                        else 0
                    ),
                    -candidate.combined_score,
                    candidate.chunk_id,
                ),
            )
        )

    def _stable_source_document_order(self, sources):
        candidates = self._stable_document_order(
            tuple(source.candidate for source in sources)
        )
        source_by_candidate = {id(source.candidate): source for source in sources}
        return tuple(source_by_candidate[id(candidate)] for candidate in candidates)


@dataclass(frozen=True, slots=True)
class PromptBuilder:
    """Construye prompts controlados para respuestas citadas en espanol."""

    def compose(
        self,
        *,
        question: str,
        context: ContextBuildResult,
    ) -> PromptComposition:
        """Compone el prompt inicial sin alterar su representacion historica.

        Args:
            question: Pregunta original del usuario.
            context: Contexto recuperado con fuentes permitidas.

        Returns:
            Componentes ordenados y reconciliables con el prompt enviado.
        """
        source_ids = ", ".join(f"[{source.source_id}]" for source in context.sources)
        factual_rule, block_rule, inference_rule = _grounding_rules()
        compact_rule, list_rule, limits_rule = _response_contract_rules()
        components = (
            PromptComponent(
                "instructions",
                "Responde en espanol usando solo la evidencia provista.\n"
                f"{factual_rule}"
                "Usa solo estos IDs de fuente existentes: "
                f"{source_ids}.\n"
                f"{block_rule}"
                "No incluyas una seccion final de fuentes; las citas deben ir en el texto.\n"
                "Si la evidencia no responde directamente la pregunta, responde "
                "\"Evidencia insuficiente\".\n"
                f"{inference_rule}"
                f"{compact_rule}"
                f"{list_rule}"
                f"{limits_rule}"
                "Cuando declares evidencia insuficiente, indica que evidencia falto "
                "y cita las fuentes que demuestran el limite.\n\n",
            ),
            PromptComponent("question", f"Pregunta:\n{question}\n\n"),
            *_context_prompt_components(context),
            PromptComponent(
                "output_format",
                "Formato requerido:\n"
                "## Conclusion\n"
                "... [F1]\n\n"
                "## Evidencia\n"
                "- ... [F1]\n",
            ),
        )
        return PromptComposition(components=components)

    def build(self, *, question: str, context: ContextBuildResult) -> str:
        """Renderiza el prompt inicial conservando el contrato publico."""
        return self.compose(question=question, context=context).rendered_prompt

    def compose_repair(
        self,
        *,
        question: str,
        context: ContextBuildResult,
        answer: str,
        validation: CitationValidation | None = None,
    ) -> PromptComposition:
        """Compone un repair conservador orientado por categorias seguras.

        Args:
            question: Pregunta original del usuario.
            context: Contexto recuperado con las fuentes permitidas.
            answer: Respuesta candidata rechazada por el validador.

        Returns:
            Componentes ordenados del prompt de reparacion.
        """
        source_ids = ", ".join(f"[{source.source_id}]" for source in context.sources)
        factual_rule, block_rule, inference_rule = _grounding_rules()
        compact_rule, list_rule, limits_rule = _response_contract_rules()
        failure_summary = _validation_failure_summary(validation)
        failure_diagnostic = _render_repair_failure_diagnostic(failure_summary)
        components = (
            PromptComponent(
                "instructions",
                "Reescribe la respuesta en espanol usando solo la evidencia provista.\n"
                f"{factual_rule}"
                f"{block_rule}"
                f"Usa solo estos IDs de fuente existentes: {source_ids}.\n"
                f"{inference_rule}"
                f"{compact_rule}"
                f"{list_rule}"
                f"{limits_rule}"
                "Corrige unicamente los problemas de soporte y citacion de la "
                "respuesta anterior.\n"
                "No agregues hechos, interpretaciones ni conclusiones nuevas. "
                "Conserva solo contenido respaldado y elimina lo que no "
                "pueda corregirse con estas mismas fuentes.\n"
                f"{failure_diagnostic}"
                "Si el contexto no responde la pregunta, responde "
                "\"Evidencia insuficiente\" y cita la evidencia disponible.\n"
                "No generes codigo ni completes codigo; solo corrige la respuesta textual.\n\n",
            ),
            PromptComponent("question", f"Pregunta:\n{question}\n\n"),
            *_context_prompt_components(context),
            PromptComponent(
                "rejected_answer",
                f"Respuesta original:\n{answer}\n\n",
            ),
            PromptComponent("output_format", "Respuesta corregida:"),
        )
        return PromptComposition(components=components)

    def repair(
        self,
        *,
        question: str,
        context: ContextBuildResult,
        answer: str,
        validation: CitationValidation | None = None,
    ) -> str:
        """Renderiza el prompt de reparacion conservando el contrato publico."""
        return self.compose_repair(
            question=question,
            context=context,
            answer=answer,
            validation=validation,
        ).rendered_prompt


def _grounding_rules() -> tuple[str, str, str]:
    """Devuelve las reglas literales compartidas por generation y repair."""
    return (
        "Toda afirmacion factual debe citar una fuente inline como [F1].\n",
        "Cada parrafo o bullet de la respuesta debe incluir al menos una cita inline.\n",
        "No infieras, no completes con conocimiento general y no inventes "
        "conclusiones.\n",
    )


def _response_contract_rules() -> tuple[str, str, str]:
    """Devuelve reglas de estilo compartidas sin clasificar la consulta."""
    return (
        "Responde de forma compacta y directa, sin conclusiones generales, "
        "recapitulaciones ni comentarios accesorios.\n",
        "Para listas factuales, empieza directamente con bullets citados; no "
        "agregues una frase introductoria que resuma o anuncie la lista.\n",
        "La seccion 'Supuestos y limites' es opcional: incluyela solo para "
        "supuestos o limites explicitamente demostrados por las fuentes, con "
        "una cita inline en cada bullet; si no existen, omite la seccion.\n",
    )


def _validation_failure_summary(
    validation: CitationValidation | None,
) -> dict[str, object]:
    """Resume causas de rechazo sin incluir claims ni contenido sensible."""
    if validation is None:
        return {
            "categories": ("validation_failed",),
            "counts": {"validation_failed": 1},
        }
    categories: list[str] = []
    counts: dict[str, int] = {}
    if validation.missing_source_ids:
        categories.append("missing_source_ids")
        counts["missing_source_ids"] = len(validation.missing_source_ids)
    if not validation.cited_source_ids:
        categories.append("no_valid_citations")
        counts["no_valid_citations"] = 1
    if validation.unsupported_claims:
        categories.append("unsupported_claims")
        counts["unsupported_claims"] = len(validation.unsupported_claims)
    if validation.contradiction_claims:
        categories.append("contradiction_claims")
        counts["contradiction_claims"] = len(validation.contradiction_claims)
    if not categories:
        categories.append("validation_failed")
        counts["validation_failed"] = 1
    return {"categories": tuple(categories), "counts": counts}


def _render_repair_failure_diagnostic(summary: Mapping[str, object]) -> str:
    """Renderiza solo categorias y conteos seguros para orientar el repair."""
    categories = summary.get("categories")
    counts = summary.get("counts")
    if not isinstance(categories, tuple) or not isinstance(counts, Mapping):
        return "Diagnostico del validador:\n- validation_failed: 1\n"
    lines = "".join(
        f"- {category}: {int(counts.get(category) or 0)}\n"
        for category in categories
    )
    return "Diagnostico del validador (categorias y conteos):\n" + lines


def _evidence_decisions(
    candidates,
    *,
    sources: tuple[ContextSource, ...],
    omitted: tuple[dict[str, object], ...],
    dedupe_min_hash_prefix: int,
) -> tuple[dict[str, object], ...]:
    """Explica la politica vigente sin modificar seleccion ni orden."""
    selected = {id(source.candidate): source for source in sources}
    omitted_by_chunk = {str(item["chunk_id"]): str(item["reason"]) for item in omitted}
    duplicate_kinds = _duplicate_kinds(
        candidates, dedupe_min_hash_prefix=dedupe_min_hash_prefix
    )
    decisions = []
    for index, candidate in enumerate(candidates):
        source = selected.get(id(candidate))
        if source is not None:
            reasons_list: list[str] = []
            if source.content_truncated:
                reasons_list.append("max_chunk_tokens")
            if source.overlap_trimmed_chars:
                reasons_list.append("exact_contiguous_overlap")
            action = "truncated" if reasons_list else "selected"
            reasons = tuple(reasons_list) if reasons_list else ("selected",)
            contribution = estimate_tokens(_render_source_context(source))
        else:
            action = "omitted"
            reason = omitted_by_chunk.get(candidate.chunk_id, "not_selected")
            if reason == "duplicate":
                reason = duplicate_kinds[index] or "duplicate_content"
            reasons = (reason,)
            contribution = 0
        decisions.append(
            {
                "chunk_id": candidate.chunk_id,
                "action": action,
                "reasons": reasons,
                "combined_score": candidate.combined_score,
                "contribution_tokens_est_local": contribution,
            }
        )
    return tuple(decisions)


def _duplicate_kinds(
    candidates,
    *,
    dedupe_min_hash_prefix: int,
) -> tuple[str | None, ...]:
    seen_chunks: set[str] = set()
    seen_hashes: set[str] = set()
    kinds: list[str | None] = []
    for candidate in candidates:
        hash_prefix = candidate.content_sha256[:dedupe_min_hash_prefix]
        if candidate.chunk_id in seen_chunks:
            kinds.append("duplicate_chunk_id")
        elif hash_prefix in seen_hashes:
            kinds.append("duplicate_content")
        else:
            kinds.append(None)
        seen_chunks.add(candidate.chunk_id)
        seen_hashes.add(hash_prefix)
    return tuple(kinds)


def _context_redundancy_report(
    candidates,
    *,
    sources: tuple[ContextSource, ...],
    dedupe_min_hash_prefix: int,
) -> dict[str, object]:
    """Mide redundancia exacta y overlap; nunca cambia el contexto efectivo."""
    duplicate_kinds = _duplicate_kinds(
        candidates, dedupe_min_hash_prefix=dedupe_min_hash_prefix
    )
    selected_candidates = {id(source.candidate) for source in sources}
    overlap_pairs: list[dict[str, object]] = []
    for index, left in enumerate(sources):
        for right in sources[index + 1 :]:
            if left.candidate.source.get("document_id") != right.candidate.source.get(
                "document_id"
            ):
                continue
            overlap_chars = _suffix_prefix_overlap_chars(left.content, right.content)
            if overlap_chars:
                overlap_text = right.content[:overlap_chars]
                overlap_pairs.append(
                    {
                        "left_chunk_id": left.candidate.chunk_id,
                        "right_chunk_id": right.candidate.chunk_id,
                        "overlap_chars": overlap_chars,
                        "overlap_utf8_bytes": len(overlap_text.encode("utf-8")),
                        "overlap_tokens_est_local": estimate_tokens(overlap_text),
                        "effect": "report_only",
                    }
                )
    exact_candidates = tuple(
        {
            "chunk_id": candidate.chunk_id,
            "kind": kind,
            "included_in_context": id(candidate) in selected_candidates,
            "content_chars": len(
                str(candidate.source.get("content") or candidate.source.get("snippet") or "")
            ),
            "content_tokens_est_local": estimate_tokens(
                str(candidate.source.get("content") or candidate.source.get("snippet") or "")
            ),
        }
        for candidate, kind in zip(candidates, duplicate_kinds, strict=True)
        if kind is not None
    )
    trimmed_pairs = tuple(
        {
            "left_chunk_id": source.overlap_trimmed_from_chunk_id,
            "right_chunk_id": source.candidate.chunk_id,
            "overlap_chars": source.overlap_trimmed_chars,
            "overlap_tokens_est_local": estimate_tokens(
                "x" * source.overlap_trimmed_chars
            ),
            "effect": "trim_overlap_v1",
        }
        for source in sources
        if source.overlap_trimmed_chars
        and source.overlap_trimmed_from_chunk_id is not None
    )
    return {
        "mode": "trim_overlap_v1" if trimmed_pairs else "report_only",
        "exact_duplicate_candidates": exact_candidates,
        "exact_duplicate_count": len(exact_candidates),
        "exact_duplicate_prompt_tokens_est_local": 0,
        "exact_duplicate_avoided_content_tokens_est_local": sum(
            int(item["content_tokens_est_local"]) for item in exact_candidates
        ),
        "overlap_pairs": tuple(overlap_pairs),
        "overlap_chars": sum(int(pair["overlap_chars"]) for pair in overlap_pairs),
        "overlap_utf8_bytes": sum(
            int(pair["overlap_utf8_bytes"]) for pair in overlap_pairs
        ),
        "overlap_tokens_est_local": sum(
            int(pair["overlap_tokens_est_local"]) for pair in overlap_pairs
        ),
        "trimmed_overlap_pairs": trimmed_pairs,
        "trimmed_overlap_chars": sum(
            int(pair["overlap_chars"]) for pair in trimmed_pairs
        ),
        "trimmed_overlap_tokens_est_local": sum(
            int(pair["overlap_tokens_est_local"]) for pair in trimmed_pairs
        ),
    }


def _suffix_prefix_overlap_chars(left: str, right: str) -> int:
    for size in range(min(len(left), len(right)), 3, -1):
        if left[-size:] == right[:size]:
            return size
    return 0


@dataclass(frozen=True, slots=True)
class CitationValidator:
    """Valida citas y soporte basico contra el contexto recuperado."""

    def validate(
        self,
        answer: str,
        context: ContextBuildResult,
        *,
        question: str = "",
    ) -> CitationValidation:
        """Valida una respuesta generada contra las fuentes disponibles.

        Args:
            answer: Respuesta generada por el LLM.
            context: Contexto con fuentes permitidas para citar.
            question: Pregunta original; se usa para detectar evidencia
                insuficiente cuando el contexto no cubre la consulta.

        Returns:
            Resultado de validacion con citas, claims no soportados,
            contradicciones y razon principal.
        """
        allowed = {source.source_id for source in context.sources}
        cited = set(re.findall(r"\[(F\d+)\]", answer))
        missing = tuple(sorted(cited - allowed))
        valid_cited = tuple(sorted(cited & allowed))
        if missing:
            return CitationValidation(
                valid=False,
                missing_source_ids=missing,
                cited_source_ids=valid_cited,
                reason=f"citas inexistentes: {', '.join(missing)}",
            )
        if not valid_cited:
            return CitationValidation(
                valid=False,
                missing_source_ids=missing,
                cited_source_ids=valid_cited,
                reason="la respuesta no incluyo citas validas",
            )
        if not _context_answers_question(question, context):
            if _is_insufficient_evidence_answer(answer):
                return CitationValidation(
                    valid=True,
                    cited_source_ids=valid_cited,
                )
            return CitationValidation(
                valid=False,
                cited_source_ids=valid_cited,
                unsupported_claims=("la evidencia recuperada no responde la pregunta",),
                reason="la evidencia recuperada no responde directamente la pregunta",
            )
        unsupported = _unsupported_claims(answer, context)
        contradictions = _contradiction_claims(answer, context)
        if unsupported or contradictions:
            reason = "la respuesta contiene afirmaciones no respaldadas"
            if contradictions:
                reason = "la respuesta contradice el contexto citado"
            return CitationValidation(
                valid=False,
                cited_source_ids=valid_cited,
                unsupported_claims=unsupported,
                contradiction_claims=contradictions,
                reason=reason,
            )
        return CitationValidation(
            valid=True,
            cited_source_ids=valid_cited,
        )


def _require_reconciled_prompt(
    prompt: str,
    composition: PromptComposition,
) -> None:
    """Impide observar una composicion distinta del string productivo."""
    if composition.rendered_prompt != prompt:
        raise ValueError(
            "La composicion del prompt no coincide con el texto enviado al LLM."
        )


@dataclass(frozen=True, slots=True)
class AskService:
    """Orquesta busqueda, contexto, prompt, LLM y validacion de `ask`.

    Attributes:
        search_service: Servicio de recuperacion de evidencia.
        context_builder: Constructor del contexto numerado.
        prompt_builder: Constructor de prompts de generacion y reparacion.
        citation_validator: Validador de citas y soporte.
        llm_provider: Proveedor local de generacion.
        settings: Configuracion efectiva de Barbarion.
        structured_retriever: Recuperador opcional de conocimiento Data-Driven.
    """

    search_service: SearchService
    context_builder: ContextBuilder
    prompt_builder: PromptBuilder
    citation_validator: CitationValidator
    llm_provider: LlmProviderPort
    settings: Settings
    privacy_preflight: PrivacyPreflightService
    structured_retriever: DataDrivenEvidenceRetriever | None = None

    def _generate_with_observability(
        self,
        prompt: str,
        *,
        stage: str,
        authorization: PrivacyAuthorization,
        operation_id: str,
        target: InferenceTarget,
        policy: PrivacyPolicy,
    ) -> str:
        """Genera una respuesta registrando métricas sin contenido sensible.

        Args:
            prompt: Prompt que se enviará al proveedor local.
            stage: Etapa de generación, `generation` o `repair`.

        Returns:
            Respuesta completa entregada por el proveedor.

        Raises:
            Exception: Conserva sin cambios cualquier error del proveedor.
        """
        if not isinstance(authorization, PrivacyAuthorization) or not authorization.is_valid_for(
            operation_id=operation_id,
            target=target,
            policy=policy,
        ):
            raise InvalidPrivacyAuthorizationError(
                "PrivacyAuthorization ausente o invalida para esta operacion."
            )
        timeout_seconds = self.settings.llm.timeout_seconds
        prompt_chars = len(prompt)
        prompt_tokens_est = estimate_tokens(prompt)
        prompt_tokens_metric = (
            "prompt_tokens_est_local"
            if self.llm_provider.provider == "anthropic"
            else "prompt_tokens_est"
        )
        _LOGGER.info(
            "ask_llm_started stage=%s provider=%s model=%s timeout_seconds=%g "
            "prompt_chars=%d %s=%d",
            stage,
            self.llm_provider.provider,
            self.settings.llm.model,
            timeout_seconds,
            prompt_chars,
            prompt_tokens_metric,
            prompt_tokens_est,
        )
        started = time.monotonic()
        try:
            response = self.llm_provider.generate(
                prompt=prompt,
                timeout_seconds=timeout_seconds,
            )
        except KeyboardInterrupt:
            _LOGGER.warning(
                "ask_llm_finished stage=%s provider=%s model=%s "
                "timeout_seconds=%g prompt_chars=%d %s=%d "
                "duration_ms=%d result=interrupted",
                stage,
                self.llm_provider.provider,
                self.settings.llm.model,
                timeout_seconds,
                prompt_chars,
                prompt_tokens_metric,
                prompt_tokens_est,
                _duration_ms(started),
            )
            raise
        except Exception as error:
            duration_ms = _duration_ms(started)
            result = (
                "timeout"
                if isinstance(error, LlmProviderError)
                and "TIMEOUT" in str(error)
                else "error"
            )
            log = _LOGGER.warning if result == "timeout" else _LOGGER.error
            log(
                "ask_llm_finished stage=%s provider=%s model=%s timeout_seconds=%g "
                "prompt_chars=%d %s=%d duration_ms=%d result=%s",
                stage,
                self.llm_provider.provider,
                self.settings.llm.model,
                timeout_seconds,
                prompt_chars,
                prompt_tokens_metric,
                prompt_tokens_est,
                duration_ms,
                result,
            )
            raise
        _LOGGER.info(
            "ask_llm_finished stage=%s provider=%s model=%s timeout_seconds=%g "
            "prompt_chars=%d %s=%d duration_ms=%d "
            "result=completed response_chars=%d",
            stage,
            self.llm_provider.provider,
            self.settings.llm.model,
            timeout_seconds,
            prompt_chars,
            prompt_tokens_metric,
            prompt_tokens_est,
            _duration_ms(started),
            len(response),
        )
        return response

    def _log_citation_validation(
        self,
        validation: CitationValidation,
        *,
        stage: str,
    ) -> None:
        """Registra el resultado del validador sin contenido de la respuesta.

        Args:
            validation: Resultado estructurado del validador de citas.
            stage: Etapa validada, `generation` o `repair`.
        """
        reasons: list[str] = []
        if validation.missing_source_ids:
            reasons.append("missing_source_ids")
        if not validation.cited_source_ids:
            reasons.append("no_valid_citations")
        if validation.unsupported_claims:
            reasons.append("unsupported_claims")
        if validation.contradiction_claims:
            reasons.append("contradiction_claims")
        if not reasons:
            reasons.append("ok" if validation.valid else "validation_failed")
        _LOGGER.info(
            "ask_citation_validation stage=%s result=%s reasons=%s "
            "cited_source_ids_count=%d missing_source_ids_count=%d "
            "unsupported_claims_count=%d contradiction_claims_count=%d",
            stage,
            "PASS" if validation.valid else "FAIL",
            ",".join(reasons),
            len(validation.cited_source_ids),
            len(validation.missing_source_ids),
            len(validation.unsupported_claims),
            len(validation.contradiction_claims),
        )

    def ask(
        self,
        question: str,
        *,
        mode: RetrievalMode,
        filters=None,
        top_k: int,
        candidate_k: int,
        threshold: float,
        no_llm: bool = False,
        debug: bool = False,
    ) -> AnswerResult:
        """Responde una pregunta RAG con validacion estricta de evidencia.

        Args:
            question: Pregunta original del usuario.
            mode: Modo de recuperacion RAG.
            filters: Filtros opcionales de recuperacion.
            top_k: Cantidad maxima de fuentes finales.
            candidate_k: Cantidad inicial de candidatos a evaluar.
            threshold: Score minimo aceptado.
            no_llm: Si es `True`, devuelve solo contexto recuperado.
            debug: Si es `True`, incluye diagnostico efimero para CLI.

        Returns:
            Resultado con respuesta, fuentes, estado y debug opcional.
        """
        started = time.monotonic()
        effective_filters = filters or RetrievalFilter()
        search = self.search_service.search(
            SearchRequest(
                query=question,
                mode=mode,
                filters=effective_filters,
                top_k=top_k,
                candidate_k=candidate_k,
                similarity_threshold=threshold,
                vector_weight=self.settings.retrieval.vector_weight,
                keyword_weight=self.settings.retrieval.keyword_weight,
                debug=debug,
                defer_top_k=(
                    self.settings.rag.context_selection_policy == "optimized_v1"
                ),
            )
        )
        structured_candidates = (
            self.structured_retriever.retrieve(
                question,
                filters=effective_filters,
                limit=candidate_k,
            )
            if self.structured_retriever is not None
            else ()
        )
        chunk_candidates = self.search_service.repository.enrich_candidates(
            search.candidates,
            include_snippets=True,
        )
        candidate_selection_debug = None
        if self.settings.rag.context_selection_policy == "optimized_v1":
            candidates, candidate_selection_debug = (
                _select_ask_candidates_relevance_first(
                    structured_candidates,
                    chunk_candidates,
                    limit=top_k,
                    dedupe_min_hash_prefix=self.context_builder.dedupe_min_hash_prefix,
                    question=question,
                )
            )
        else:
            candidates = _merge_ask_candidates(
                structured_candidates,
                chunk_candidates,
                limit=top_k,
            )
        context_started = time.monotonic()
        input_budget = self.settings.rag.input_token_budget_est
        input_budget_debug = None
        if input_budget is not None and not no_llm:
            context, input_budget_debug = _build_context_for_input_budget(
                context_builder=self.context_builder,
                prompt_builder=self.prompt_builder,
                candidates=candidates,
                question=question,
                input_token_budget_est=input_budget,
                debug=debug,
            )
        else:
            context = self.context_builder.build(candidates, debug=debug)
        context_ms = _duration_ms(context_started)
        base_debug_payload = (
            _ask_debug_payload(
                started=started,
                search=search,
                context=context,
                prompt="",
                timeout_seconds=self.settings.llm.timeout_seconds,
            )
            if debug
            else {}
        )
        if debug and self.llm_provider.provider == "anthropic":
            base_debug_payload["prompt_tokens_est_local"] = (
                base_debug_payload.pop("prompt_tokens_est")
            )
        if debug:
            base_debug_payload["structured_candidates"] = len(
                structured_candidates
            )
            base_debug_payload["combined_candidates"] = len(candidates)
            base_debug_payload["input_budget"] = input_budget_debug
            base_debug_payload["candidate_selection"] = candidate_selection_debug
        budget_has_insufficient_evidence = (
            input_budget is not None
            and not no_llm
            and bool(context.sources)
            and not _context_answers_question(question, context)
        )
        if budget_has_insufficient_evidence and input_budget_debug is not None:
            input_budget_debug["result"] = "insufficient_evidence"
        if debug:
            base_debug_payload["observability"] = _ask_observability_summary(
                context=context,
                policy=self.settings.rag.context_selection_policy,
                candidate_selection=candidate_selection_debug,
                input_budget=input_budget_debug,
                repair_input_budget=None,
                repair_outcome={
                    "triggered": False,
                    "trigger_categories": (),
                    "trigger_counts": {},
                    "attempted": False,
                    "succeeded": None,
                    "result": "not_applicable",
                },
                generation=None,
                repair=None,
                citation_coverage=None,
                provider_usage=None,
            )
        if not context.sources or budget_has_insufficient_evidence:
            answer = _insufficient_evidence_answer()
            self.search_service.repository.update_rag_query_metrics(
                query_id=search.query_id,
                context_sources=len(context.sources),
                context_ms=context_ms,
                llm_ms=None,
                metrics=context.metrics,
            )
            return AnswerResult(
                query_id=search.query_id,
                question=question,
                answer=answer,
                context=context,
                status=RagQueryStatus.INSUFFICIENT_EVIDENCE,
                no_llm=True,
                debug=base_debug_payload if debug else {},
            )
        if no_llm:
            answer = _no_llm_answer(context)
            self.search_service.repository.update_rag_query_metrics(
                query_id=search.query_id,
                context_sources=len(context.sources),
                context_ms=context_ms,
                llm_ms=None,
                metrics=context.metrics,
            )
            return AnswerResult(
                query_id=search.query_id,
                question=question,
                answer=answer,
                context=context,
                status=RagQueryStatus.COMPLETED,
                no_llm=True,
                debug=base_debug_payload if debug else {},
            )
        target = resolve_inference_target(self.settings)
        operation_id = uuid.uuid4().hex
        authorization = self.privacy_preflight.authorize(
            operation_id=operation_id,
            target=target,
        )
        prompt = self.prompt_builder.build(question=question, context=context)
        prompt_composition = self.prompt_builder.compose(
            question=question,
            context=context,
        )
        _require_reconciled_prompt(prompt, prompt_composition)
        debug_payload = dict(base_debug_payload)
        if debug:
            debug_payload["prompt"] = prompt
            debug_payload["prompt_chars"] = len(prompt)
            prompt_tokens_key = (
                "prompt_tokens_est_local"
                if self.llm_provider.provider == "anthropic"
                else "prompt_tokens_est"
            )
            debug_payload[prompt_tokens_key] = prompt_composition.tokens_est_local
            debug_payload["prompt_composition"] = prompt_composition.metrics()
        llm_started = time.monotonic()
        try:
            answer = self._generate_with_observability(
                prompt,
                stage="generation",
                authorization=authorization,
                operation_id=operation_id,
                target=target,
                policy=self.privacy_preflight.policy,
            )
        except (Exception, KeyboardInterrupt):
            self._record_failed_llm_query(
                query_id=search.query_id,
                context=context,
                context_ms=context_ms,
                llm_started=llm_started,
            )
            raise
        validation = self.citation_validator.validate(
            answer,
            context,
            question=question,
        )
        self._log_citation_validation(validation, stage="generation")
        failure_summary = (
            _validation_failure_summary(validation)
            if not validation.valid
            else {"categories": (), "counts": {}}
        )
        repair_outcome: dict[str, object] = {
            "triggered": not validation.valid,
            "trigger_categories": failure_summary["categories"],
            "trigger_counts": failure_summary["counts"],
            "attempted": False,
            "succeeded": None,
            "result": "pending" if not validation.valid else "not_needed",
        }
        if debug:
            debug_payload["llm_response"] = answer
            debug_payload["validation"] = _citation_validation_debug(
                answer=answer,
                context=context,
                validation=validation,
            )
        repair_attempted = False
        repair_valid = None
        if not validation.valid:
            repair_context = context
            repair_budget_debug = None
            if input_budget is not None:
                (
                    repair_context,
                    repair_composition,
                    repair_budget_debug,
                ) = _build_repair_context_for_input_budget(
                    prompt_builder=self.prompt_builder,
                    generation_context=context,
                    question=question,
                    rejected_answer=answer,
                    validation=validation,
                    input_token_budget_est=input_budget,
                )
                repair_prompt = repair_composition.rendered_prompt
            else:
                repair_prompt = self.prompt_builder.repair(
                    question=question,
                    context=repair_context,
                    answer=answer,
                    validation=validation,
                )
                repair_composition = self.prompt_builder.compose_repair(
                    question=question,
                    context=repair_context,
                    answer=answer,
                    validation=validation,
                )
            _require_reconciled_prompt(repair_prompt, repair_composition)
            repair_fits_budget = (
                repair_context is not None
                and (
                    input_budget is None
                    or repair_composition.tokens_est_local <= input_budget
                )
            )
            if not repair_fits_budget:
                repair_outcome["result"] = "skipped_budget"
                answer = _invalid_citations_answer(
                    validation,
                    context,
                    repair_attempted=False,
                )
                if debug:
                    debug_payload["citation_repair_skipped_reason"] = (
                        "input_token_budget_est"
                    )
                    debug_payload["repair_prompt_composition"] = (
                        repair_composition.metrics()
                    )
                    debug_payload["repair_input_budget"] = repair_budget_debug
            else:
                context = repair_context
                repair_attempted = True
                repair_outcome["attempted"] = True
                try:
                    repaired_answer = self._generate_with_observability(
                        repair_prompt,
                        stage="repair",
                        authorization=authorization,
                        operation_id=operation_id,
                        target=target,
                        policy=self.privacy_preflight.policy,
                    )
                except (Exception, KeyboardInterrupt):
                    self._record_failed_llm_query(
                        query_id=search.query_id,
                        context=context,
                        context_ms=context_ms,
                        llm_started=llm_started,
                    )
                    raise
                validation = self.citation_validator.validate(
                    repaired_answer,
                    repair_context,
                    question=question,
                )
                self._log_citation_validation(validation, stage="repair")
                repair_valid = validation.valid
                repair_outcome["succeeded"] = repair_valid
                repair_outcome["result"] = (
                    "succeeded" if repair_valid else "failed_validation"
                )
                if debug:
                    debug_payload["repair_prompt"] = repair_prompt
                    debug_payload["repair_prompt_composition"] = (
                        repair_composition.metrics()
                    )
                    debug_payload["repair_response"] = repaired_answer
                    debug_payload["repair_validation"] = _citation_validation_debug(
                        answer=repaired_answer,
                        context=repair_context,
                        validation=validation,
                    )
                    debug_payload["repair_input_budget"] = repair_budget_debug
                if validation.valid:
                    answer = repaired_answer
                else:
                    answer = _invalid_citations_answer(
                        validation,
                        context,
                        repair_attempted=True,
                    )
        llm_ms = _duration_ms(llm_started)
        _LOGGER.info(
            "ask_citation_repair triggered=%s attempted=%s result=%s causes=%s",
            repair_outcome["triggered"],
            repair_outcome["attempted"],
            repair_outcome["result"],
            ",".join(
                str(item) for item in repair_outcome["trigger_categories"]
            )
            or "none",
        )
        if debug:
            debug_payload["citation_repair_attempted"] = repair_attempted
            debug_payload["citation_repair_valid"] = repair_valid
            debug_payload["repair_outcome"] = repair_outcome
            debug_payload["citation_coverage"] = _citation_coverage_debug(
                answer, context
            )
            if not repair_attempted:
                debug_payload["repair_prompt"] = None
                debug_payload.setdefault("repair_prompt_composition", None)
                debug_payload["repair_response"] = None
                debug_payload["repair_validation"] = None
                debug_payload.setdefault("repair_input_budget", None)
            debug_payload["observability"] = _ask_observability_summary(
                context=context,
                policy=self.settings.rag.context_selection_policy,
                candidate_selection=candidate_selection_debug,
                input_budget=input_budget_debug,
                repair_input_budget=debug_payload.get("repair_input_budget"),
                repair_outcome=repair_outcome,
                generation=debug_payload.get("prompt_composition"),
                repair=debug_payload.get("repair_prompt_composition"),
                citation_coverage=debug_payload.get("citation_coverage"),
                provider_usage=_provider_usage_debug(self.llm_provider),
            )
        self.search_service.repository.update_rag_query_metrics(
            query_id=search.query_id,
            context_sources=len(context.sources),
            context_ms=context_ms,
            llm_ms=llm_ms,
            metrics=context.metrics,
        )
        return AnswerResult(
            query_id=search.query_id,
            question=question,
            answer=answer,
            context=context,
            status=RagQueryStatus.COMPLETED if validation.valid else RagQueryStatus.ERROR,
            no_llm=False,
            citations_valid=validation.valid,
            missing_citations=validation.missing_source_ids,
            debug=debug_payload if debug else {},
        )

    def _record_failed_llm_query(
        self,
        *,
        query_id: int | None,
        context: ContextBuildResult,
        context_ms: int,
        llm_started: float,
    ) -> None:
        """Evita conservar como exitosa una consulta cuya generacion fallo."""
        self.search_service.repository.update_rag_query_metrics(
            query_id=query_id,
            context_sources=len(context.sources),
            context_ms=context_ms,
            llm_ms=_duration_ms(llm_started),
            metrics=context.metrics,
            status=RagQueryStatus.ERROR,
        )


def _build_context_for_input_budget(
    *,
    context_builder: ContextBuilder,
    prompt_builder: PromptBuilder,
    candidates: tuple[RetrievalCandidate, ...],
    question: str,
    input_token_budget_est: int,
    debug: bool,
) -> tuple[ContextBuildResult, dict[str, object]]:
    """Presupuesta el prompt completo manteniendo la seleccion baseline."""
    empty_context = context_builder.build((), debug=debug)
    fixed_overhead = prompt_builder.compose(
        question=question,
        context=empty_context,
    ).tokens_est_local
    evidence_budget = max(0, input_token_budget_est - fixed_overhead)
    context_budget = evidence_budget
    while context_budget > 0:
        context = replace(context_builder, token_budget=context_budget).build(
            candidates,
            debug=debug,
        )
        composition = prompt_builder.compose(question=question, context=context)
        if composition.tokens_est_local <= input_token_budget_est:
            return context, {
                "configured_tokens_est_local": input_token_budget_est,
                "estimator_id": TOKEN_ESTIMATOR_ID,
                "fixed_overhead_tokens_est_local": fixed_overhead,
                "evidence_budget_tokens_est_local": evidence_budget,
                "final_prompt_tokens_est_local": composition.tokens_est_local,
                "result": "fits" if context.sources else "insufficient_evidence",
            }
        if not context.sources:
            break
        overage = composition.tokens_est_local - input_token_budget_est
        context_budget -= max(1, overage)
    return empty_context, {
        "configured_tokens_est_local": input_token_budget_est,
        "estimator_id": TOKEN_ESTIMATOR_ID,
        "fixed_overhead_tokens_est_local": fixed_overhead,
        "evidence_budget_tokens_est_local": evidence_budget,
        "final_prompt_tokens_est_local": fixed_overhead,
        "result": (
            "fixed_overhead_exceeds_budget"
            if fixed_overhead > input_token_budget_est
            else "insufficient_evidence"
        ),
    }


def _build_repair_context_for_input_budget(
    *,
    prompt_builder: PromptBuilder,
    generation_context: ContextBuildResult,
    question: str,
    rejected_answer: str,
    validation: CitationValidation,
    input_token_budget_est: int,
) -> tuple[ContextBuildResult | None, PromptComposition, dict[str, object]]:
    """Redistribuye el presupuesto de repair sin cambiar fuentes ni IDs."""
    source_ids = tuple(source.source_id for source in generation_context.sources)
    original_evidence_tokens = sum(
        estimate_tokens(source.content) for source in generation_context.sources
    )
    target_evidence_tokens = original_evidence_tokens
    attempted_context = generation_context
    composition = prompt_builder.compose_repair(
        question=question,
        context=attempted_context,
        answer=rejected_answer,
        validation=validation,
    )
    initial_prompt_tokens = composition.tokens_est_local

    while composition.tokens_est_local > input_token_budget_est:
        overage = composition.tokens_est_local - input_token_budget_est
        target_evidence_tokens -= max(1, overage)
        fitted_sources = _fit_same_sources_to_content_budget(
            generation_context.sources,
            target_evidence_tokens,
        )
        if fitted_sources is None:
            return None, composition, {
                "configured_tokens_est_local": input_token_budget_est,
                "estimator_id": TOKEN_ESTIMATOR_ID,
                "initial_prompt_tokens_est_local": initial_prompt_tokens,
                "final_prompt_tokens_est_local": composition.tokens_est_local,
                "original_evidence_tokens_est_local": original_evidence_tokens,
                "final_evidence_tokens_est_local": sum(
                    estimate_tokens(source.content)
                    for source in attempted_context.sources
                ),
                "trimmed_evidence_tokens_est_local": max(
                    0,
                    original_evidence_tokens
                    - sum(
                        estimate_tokens(source.content)
                        for source in attempted_context.sources
                    ),
                ),
                "source_ids": source_ids,
                "same_sources": True,
                "result": "insufficient_evidence_budget",
            }
        attempted_context = _context_with_sources(
            generation_context,
            fitted_sources,
        )
        composition = prompt_builder.compose_repair(
            question=question,
            context=attempted_context,
            answer=rejected_answer,
            validation=validation,
        )

    evidence_is_sufficient = _context_answers_question(
        question,
        attempted_context,
    )
    final_evidence_tokens = sum(
        estimate_tokens(source.content) for source in attempted_context.sources
    )
    debug = {
        "configured_tokens_est_local": input_token_budget_est,
        "estimator_id": TOKEN_ESTIMATOR_ID,
        "initial_prompt_tokens_est_local": initial_prompt_tokens,
        "final_prompt_tokens_est_local": composition.tokens_est_local,
        "original_evidence_tokens_est_local": original_evidence_tokens,
        "final_evidence_tokens_est_local": final_evidence_tokens,
        "trimmed_evidence_tokens_est_local": (
            original_evidence_tokens - final_evidence_tokens
        ),
        "source_ids": source_ids,
        "same_sources": True,
        "result": "fits" if evidence_is_sufficient else "insufficient_evidence",
    }
    if not evidence_is_sufficient:
        return None, composition, debug
    return attempted_context, composition, debug


def _fit_same_sources_to_content_budget(
    sources: tuple[ContextSource, ...],
    token_budget: int,
) -> tuple[ContextSource, ...] | None:
    """Trunca contenido proporcionalmente conservando todas las fuentes."""
    if not sources or token_budget < len(sources):
        return None
    weights = [max(1, estimate_tokens(source.content)) for source in sources]
    allocations = [1] * len(sources)
    remaining = token_budget - len(sources)
    if remaining > 0:
        capacities = [max(0, weight - 1) for weight in weights]
        total_capacity = sum(capacities)
        if total_capacity > 0:
            raw = [remaining * capacity / total_capacity for capacity in capacities]
            extras = [
                min(capacity, int(value))
                for capacity, value in zip(capacities, raw)
            ]
            for index, extra in enumerate(extras):
                allocations[index] += extra
            leftover = remaining - sum(extras)
            order = sorted(
                range(len(sources)),
                key=lambda index: (-(raw[index] - int(raw[index])), index),
            )
            for index in order:
                if leftover <= 0:
                    break
                if allocations[index] < weights[index]:
                    allocations[index] += 1
                    leftover -= 1
    fitted: list[ContextSource] = []
    for source, allocation in zip(sources, allocations):
        content = _truncate_to_tokens(source.content, allocation)
        if not content:
            return None
        fitted.append(
            replace(
                source,
                content=content,
                token_estimate=estimate_tokens(content),
                content_truncated=(
                    source.content_truncated or content != source.content
                ),
            )
        )
    return tuple(fitted)


def _context_with_sources(
    original: ContextBuildResult,
    sources: tuple[ContextSource, ...],
) -> ContextBuildResult:
    """Reconcilia un contexto reducido conservando identidad y trazabilidad."""
    rendered = _render_context(list(sources))
    return ContextBuildResult(
        sources=sources,
        omitted=original.omitted,
        rendered_context=rendered,
        token_estimate=sum(
            estimate_tokens(_render_source_context(source)) for source in sources
        ),
        metrics=original.metrics,
        debug=dict(original.debug),
    )


def _select_ask_candidates_relevance_first(
    structured: tuple[RetrievalCandidate, ...],
    chunks: tuple[RetrievalCandidate, ...],
    *,
    limit: int,
    dedupe_min_hash_prefix: int,
    question: str = "",
) -> tuple[tuple[RetrievalCandidate, ...], tuple[dict[str, object], ...]]:
    """Fusiona familias por rango relativo antes de gastar top-k."""
    pool = tuple((*structured, *chunks))
    has_structured_configuration = any(
        candidate.source.get("evidence_kind") == "structured_symbol"
        for candidate in structured
    )
    decisions: list[dict[str, object] | None] = [None] * len(pool)
    eligible_by_family: dict[str, list[tuple[int, RetrievalCandidate]]] = {
        "chunks": [],
        "structured": [],
    }
    for index, candidate in enumerate(pool):
        if (
            has_structured_configuration
            and candidate.source.get("artifact_kind") == "configuration"
            and candidate.source.get("evidence_kind") is None
        ):
            decisions[index] = _candidate_selection_decision(
                candidate,
                action="omitted",
                reason="shadowed_configuration",
            )
        elif not _candidate_has_materializable_content(candidate):
            decisions[index] = _candidate_selection_decision(
                candidate,
                action="omitted",
                reason="missing_content",
            )
        else:
            family = "structured" if index < len(structured) else "chunks"
            eligible_by_family[family].append((index, candidate))
    ranked: list[tuple[int, RetrievalCandidate, str, int, float, bool]] = []
    for family, items in eligible_by_family.items():
        relevance_keys = {
            index: (
                _candidate_matches_exact_query_identifier(candidate, question)
                if family == "structured"
                else False,
                candidate.combined_score,
            )
            for index, candidate in items
        }
        items.sort(
            key=lambda item: (
                -int(relevance_keys[item[0]][0]),
                -item[1].combined_score,
                item[1].chunk_id,
                item[0],
            )
        )
        levels = tuple(
            dict.fromkeys(relevance_keys[index] for index, _candidate in items)
        )
        level_rank = {level: rank for rank, level in enumerate(levels)}
        denominator = max(1, len(levels) - 1)
        for index, candidate in items:
            family_rank = level_rank[relevance_keys[index]]
            relative_score = (
                1.0
                if len(levels) == 1
                else 1.0 - (family_rank / denominator)
            )
            ranked.append(
                (
                    index,
                    candidate,
                    family,
                    family_rank,
                    relative_score,
                    relevance_keys[index][0],
                )
            )
    family_tie_order = {"chunks": 0, "structured": 1}
    ranked.sort(
        key=lambda item: (
            -item[4],
            -int(item[5]),
            family_tie_order[item[2]],
            item[1].chunk_id,
            item[0],
        )
    )
    selected: list[RetrievalCandidate] = []
    seen_chunks: set[str] = set()
    seen_hashes: set[str] = set()
    for global_rank, (
        index,
        candidate,
        family,
        family_rank,
        relative_score,
        exact_identifier_match,
    ) in enumerate(ranked):
        hash_prefix = candidate.content_sha256[:dedupe_min_hash_prefix]
        if candidate.chunk_id in seen_chunks:
            action, reason = "omitted", "duplicate_chunk_id"
        elif hash_prefix in seen_hashes:
            action, reason = "omitted", "duplicate_content"
        elif len(selected) >= limit:
            action, reason = "omitted", "top_k"
        else:
            action, reason = "selected", "relevance"
            selected.append(
                replace(
                    candidate,
                    source={
                        **dict(candidate.source),
                        "selection_family": family,
                        "selection_family_rank": family_rank,
                        "selection_relative_score": relative_score,
                        "selection_global_rank": global_rank,
                        "selection_exact_identifier_match": exact_identifier_match,
                    },
                )
            )
            seen_chunks.add(candidate.chunk_id)
            seen_hashes.add(hash_prefix)
        decisions[index] = _candidate_selection_decision(
            candidate,
            action=action,
            reason=reason,
            family=family,
            family_rank=family_rank,
            relative_score=relative_score,
            exact_identifier_match=exact_identifier_match,
        )
    return tuple(selected), tuple(
        decision for decision in decisions if decision is not None
    )


def _candidate_has_materializable_content(candidate: RetrievalCandidate) -> bool:
    """Indica si el candidato puede convertirse en evidencia citable."""
    return bool(candidate.source.get("content") or candidate.source.get("snippet"))


def _candidate_matches_exact_query_identifier(
    candidate: RetrievalCandidate,
    question: str,
) -> bool:
    """Conserva la precision de identidad dentro de la familia estructurada."""
    identifiers = _query_identifiers(question)
    if not identifiers:
        return False
    symbol_name = candidate.metadata.symbol_name or ""
    return bool(identifiers & _identifier_tokens(symbol_name))


def _candidate_selection_decision(
    candidate: RetrievalCandidate,
    *,
    action: str,
    reason: str,
    family: str | None = None,
    family_rank: int | None = None,
    relative_score: float | None = None,
    exact_identifier_match: bool | None = None,
) -> dict[str, object]:
    decision: dict[str, object] = {
        "chunk_id": candidate.chunk_id,
        "action": action,
        "reasons": (reason,),
        "combined_score": candidate.combined_score,
        "evidence_kind": candidate.source.get("evidence_kind"),
    }
    if family is not None:
        decision.update(
            {
                "selection_family": family,
                "selection_family_rank": family_rank,
                "selection_relative_score": relative_score,
                "selection_exact_identifier_match": exact_identifier_match,
            }
        )
    return decision


def _merge_ask_candidates(
    structured: tuple[RetrievalCandidate, ...],
    chunks: tuple[RetrievalCandidate, ...],
    *,
    limit: int,
) -> tuple[RetrievalCandidate, ...]:
    """Combina evidencia estructurada y chunks sin duplicar ni exceder top-k."""
    merged: list[RetrievalCandidate] = []
    seen_chunks: set[str] = set()
    has_structured_configuration = any(
        candidate.source.get("evidence_kind") == "structured_symbol"
        for candidate in structured
    )
    for candidate in (*structured, *chunks):
        if (
            has_structured_configuration
            and candidate.source.get("artifact_kind") == "configuration"
            and candidate.source.get("evidence_kind") is None
        ):
            continue
        if candidate.chunk_id in seen_chunks:
            continue
        merged.append(candidate)
        seen_chunks.add(candidate.chunk_id)
        if len(merged) >= limit:
            break
    return tuple(merged)


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    limit = max_tokens * 4
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _source_for_context_budget(
    candidate: RetrievalCandidate,
    *,
    source_id: str,
    max_chunk_tokens: int,
    remaining_tokens: int,
) -> ContextSource | None:
    """Materializa un candidato respetando limites por fuente y contexto."""
    content = str(candidate.source.get("content") or candidate.source.get("snippet") or "")
    if not content:
        return None
    original_token_estimate = estimate_tokens(content)
    content = _truncate_to_tokens(content, max_chunk_tokens)
    source = ContextSource(
        source_id=source_id,
        candidate=candidate,
        content=content,
        token_estimate=estimate_tokens(content),
        original_token_estimate=original_token_estimate,
        content_truncated=original_token_estimate > max_chunk_tokens,
    )
    return _fit_source_to_budget(source, remaining_tokens)


def _trim_exact_contiguous_overlaps(
    sources: list[ContextSource],
) -> tuple[list[ContextSource], tuple[dict[str, object], ...]]:
    """Recorta prefijos repetidos solo con igualdad y continuidad demostrables."""
    ordered = sorted(
        sources,
        key=lambda source: (
            int(source.candidate.source.get("document_id") or 0),
            int(source.candidate.source.get("start_line") or 0),
            int(source.candidate.source.get("ordinal") or 0),
            source.candidate.chunk_id,
        ),
    )
    by_identity = {id(source): source for source in sources}
    pairs: list[dict[str, object]] = []
    for index, left_original in enumerate(ordered):
        left = by_identity[id(left_original)]
        for right_original in ordered[index + 1 :]:
            right = by_identity[id(right_original)]
            if not _sources_have_contiguous_ranges(left, right):
                continue
            overlap_chars = _suffix_prefix_overlap_chars(left.content, right.content)
            if overlap_chars <= 0 or overlap_chars >= len(right.content):
                continue
            overlap_text = right.content[:overlap_chars]
            trimmed = replace(
                right,
                content=right.content[overlap_chars:],
                token_estimate=estimate_tokens(right.content[overlap_chars:]),
                overlap_trimmed_chars=(
                    right.overlap_trimmed_chars + overlap_chars
                ),
                overlap_trimmed_from_chunk_id=left.candidate.chunk_id,
            )
            by_identity[id(right_original)] = trimmed
            pairs.append(
                {
                    "left_chunk_id": left.candidate.chunk_id,
                    "right_chunk_id": right.candidate.chunk_id,
                    "overlap_chars": overlap_chars,
                    "overlap_utf8_bytes": len(overlap_text.encode("utf-8")),
                    "overlap_tokens_est_local": estimate_tokens(overlap_text),
                    "effect": "trim_overlap_v1",
                }
            )
    return [by_identity[id(source)] for source in sources], tuple(pairs)


def _sources_have_contiguous_ranges(
    left: ContextSource,
    right: ContextSource,
) -> bool:
    """Confirma mismo documento y continuidad/solape de rangos de lineas."""
    left_source = left.candidate.source
    right_source = right.candidate.source
    if left_source.get("document_id") != right_source.get("document_id"):
        return False
    values = (
        left_source.get("start_line"),
        left_source.get("end_line"),
        right_source.get("start_line"),
        right_source.get("end_line"),
    )
    if any(not isinstance(value, int) for value in values):
        return False
    left_start, left_end, right_start, right_end = values
    return bool(
        left_start <= right_start <= left_end + 1
        and left_end <= right_end
    )


def _fit_source_to_budget(
    source: ContextSource,
    remaining_tokens: int,
) -> ContextSource | None:
    if remaining_tokens <= 0:
        return None
    if estimate_tokens(_render_source_context(source)) <= remaining_tokens:
        return source
    header_tokens = estimate_tokens(
        _render_source_context(source).replace(source.content, "")
    )
    available_content_tokens = remaining_tokens - header_tokens
    if available_content_tokens <= 0:
        return None
    content = _truncate_to_tokens(source.content, available_content_tokens)
    fitted = ContextSource(
        source_id=source.source_id,
        candidate=source.candidate,
        content=content,
        token_estimate=estimate_tokens(content),
        original_token_estimate=source.original_token_estimate,
        content_truncated=True,
        overlap_trimmed_chars=source.overlap_trimmed_chars,
        overlap_trimmed_from_chunk_id=source.overlap_trimmed_from_chunk_id,
    )
    if estimate_tokens(_render_source_context(fitted)) > remaining_tokens:
        return None
    return fitted


def _render_context(sources: list[ContextSource]) -> str:
    return "\n\n".join(_render_source_context(source) for source in sources)


def _context_prompt_components(
    context: ContextBuildResult,
) -> tuple[PromptComponent, ...]:
    """Descompone el bloque Contexto sin cambiar un solo caracter renderizado."""
    components: list[PromptComponent] = [
        PromptComponent("source_metadata", "Contexto:\n"),
    ]
    for index, source in enumerate(context.sources):
        separator = "\n\n" if index else ""
        components.append(
            PromptComponent(
                "source_metadata",
                separator + _render_source_metadata(source),
                source_id=source.source_id,
            )
        )
        components.append(
            PromptComponent(
                "source_content",
                source.content,
                source_id=source.source_id,
            )
        )
    components.append(PromptComponent("source_metadata", "\n\n"))
    return tuple(components)


def _render_source_context(source: ContextSource) -> str:
    return _render_source_metadata(source) + source.content


def _citation_coverage_debug(
    answer: str,
    context: ContextBuildResult,
) -> dict[str, object]:
    """Lista IDs citados/no citados sin persistir contenido de evidencia."""
    selected = tuple(source.source_id for source in context.sources)
    cited = tuple(
        source_id
        for source_id in selected
        if re.search(rf"\[{re.escape(source_id)}\]", answer)
    )
    cited_set = set(cited)
    return {
        "selected_source_count": len(selected),
        "cited_source_count": len(cited),
        "cited_source_ids": cited,
        "uncited_selected_source_ids": tuple(
            source_id for source_id in selected if source_id not in cited_set
        ),
    }


def _render_source_metadata(source: ContextSource) -> str:
    """Renderiza exclusivamente metadata y delimitadores de una fuente."""
    candidate = source.candidate
    path = candidate.source.get("relative_path") or "fuente desconocida"
    line_start = candidate.source.get("start_line")
    line_end = candidate.source.get("end_line")
    lines = ""
    if line_start is not None and line_end is not None:
        lines = f"\nlineas={line_start}-{line_end}"
    page_start = candidate.source.get("page_start")
    page_end = candidate.source.get("page_end")
    pages = ""
    if page_start is not None and page_end is not None:
        pages = f"\npaginas={page_start}-{page_end}"
    symbol_id = candidate.source.get("symbol_id")
    symbol_trace = f"\nsimbolo={symbol_id}" if symbol_id else ""
    relation_ids = candidate.source.get("relation_ids")
    relation_trace = (
        "\nrelaciones=" + ",".join(str(item) for item in relation_ids)
        if isinstance(relation_ids, (list, tuple)) and relation_ids
        else ""
    )
    evidence_kind = candidate.source.get("evidence_kind")
    evidence_trace = f"\nevidencia={evidence_kind}" if evidence_kind else ""
    return (
        f"[{source.source_id}] {path}\n"
        f"chunk={candidate.chunk_id}\n"
        f"score={candidate.combined_score:.3f}"
        f"{lines}{pages}{symbol_trace}{relation_trace}{evidence_trace}\n"
        f"contenido_truncado={str(source.content_truncated).lower()}\n"
    )


def _ask_debug_payload(
    *,
    started: float,
    search: SearchResponse,
    context: ContextBuildResult,
    prompt: str,
    timeout_seconds: float,
) -> dict[str, object]:
    """Construye metricas efimeras para diagnostico de `ask --debug`.

    Args:
        started: Marca temporal de inicio del flujo `ask`.
        search: Resultado de recuperacion usado para construir el contexto.
        context: Contexto final que recibira el LLM.
        prompt: Prompt enviado al LLM, si ya fue construido.
        timeout_seconds: Timeout configurado para el LLM.

    Returns:
        Diccionario de metricas en memoria, no persistido en SQLite.
    """
    retrieved_chunks = int(search.debug.get("vector_candidates") or 0) + int(
        search.debug.get("keyword_candidates") or 0
    )
    return {
        "duration_ms": _duration_ms(started),
        "sources": len(context.sources),
        "retrieved_chunks": retrieved_chunks,
        "reranked_chunks": len(search.candidates),
        "context_chars": len(context.rendered_context),
        "context_tokens_est": context.token_estimate,
        "prompt_chars": len(prompt),
        "prompt_tokens_est": estimate_tokens(prompt) if prompt else 0,
        "llm_timeout_seconds": timeout_seconds,
        "truncated_sources": sum(
            1 for source in context.sources if source.content_truncated
        ),
        "context_builder": dict(context.debug),
        "search": dict(search.debug),
    }


def _ask_observability_summary(
    *,
    context: ContextBuildResult,
    policy: str,
    candidate_selection: object,
    input_budget: object,
    repair_input_budget: object,
    repair_outcome: object,
    generation: object,
    repair: object,
    citation_coverage: object,
    provider_usage: object,
) -> dict[str, object]:
    """Construye una vista comparable sin prompt, pregunta ni contenido."""
    context_debug = dict(context.debug)
    return {
        "schema_version": "h31_observability_v1",
        "selection_policy": policy,
        "estimator_id": TOKEN_ESTIMATOR_ID,
        "candidate_selection": candidate_selection or (),
        "context_decisions": context_debug.get("evidence_decisions", ()),
        "redundancy": context_debug.get("redundancy_report"),
        "input_budget": input_budget,
        "repair_input_budget": repair_input_budget,
        "repair_outcome": repair_outcome,
        "generation": generation,
        "repair": repair,
        "citation_coverage": citation_coverage,
        "context": {
            "selected_sources": len(context.sources),
            "omitted_candidates": len(context.omitted),
            "chars": len(context.rendered_context),
            "tokens_est_local": context.token_estimate,
        },
        "provider_usage": provider_usage,
    }


def _provider_usage_debug(provider: object) -> dict[str, object] | None:
    snapshot = getattr(provider, "usage_snapshot", None)
    if not callable(snapshot):
        return None
    usage = snapshot()
    if usage is None:
        return None
    return {
        "provider_input_tokens": getattr(usage, "input_tokens", None),
        "provider_output_tokens": getattr(usage, "output_tokens", None),
        "provider_total_tokens": getattr(usage, "total_tokens", None),
        "provider_request_count": getattr(usage, "request_count", None),
        "provider_elapsed_seconds": getattr(usage, "elapsed_seconds", None),
    }


def _citation_validation_debug(
    *,
    answer: str,
    context: ContextBuildResult,
    validation: CitationValidation,
) -> dict[str, object]:
    """Describe la validacion de citas para diagnostico efimero.

    Args:
        answer: Respuesta del modelo que se valido.
        context: Fuentes permitidas para la respuesta.
        validation: Resultado del validador de citas.

    Returns:
        Diccionario serializable para diagnostico en memoria.
    """
    expected = tuple(source.source_id for source in context.sources)
    found = tuple(sorted(set(re.findall(r"\[(F\d+)\]", answer))))
    valid = tuple(sorted(set(found) & set(expected)))
    invalid = tuple(sorted(set(found) - set(expected)))
    missing = tuple(source_id for source_id in expected if source_id not in found)
    reason = "ok"
    if invalid:
        reason = f"citas inexistentes: {', '.join(invalid)}"
    elif validation.reason != "ok":
        reason = validation.reason
    elif not valid:
        reason = "la respuesta no incluyo citas validas"
    return {
        "expected_citations": expected,
        "found_citations": found,
        "valid_citations": valid,
        "missing_citations": missing,
        "invalid_citations": invalid,
        "unsupported_claims": validation.unsupported_claims,
        "contradiction_claims": validation.contradiction_claims,
        "result": "PASS" if validation.valid else "FAIL",
        "reason": reason,
    }


_STOPWORDS = frozenset(
    {
        "como",
        "para",
        "por",
        "con",
        "que",
        "del",
        "las",
        "los",
        "una",
        "uno",
        "este",
        "esta",
        "esto",
        "desde",
        "sobre",
        "segun",
        "respuesta",
        "conclusion",
        "evidencia",
        "supuestos",
        "limites",
        "fuente",
        "fuentes",
        "calcula",
        "calculo",
        "calcular",
        "usando",
        "flujo",
        "explica",
        "indica",
        "valor",
        "valores",
    }
)


def _context_answers_question(question: str, context: ContextBuildResult) -> bool:
    """Estima si el contexto contiene terminos relevantes de la pregunta.

    Args:
        question: Pregunta original del usuario.
        context: Contexto recuperado que se evaluara.

    Returns:
        `True` si el solapamiento minimo sugiere evidencia directa.
    """
    if not question:
        return True
    question_tokens = _important_tokens(question)
    if not question_tokens:
        return True
    context_tokens = _important_tokens(context.rendered_context)
    overlap = question_tokens & context_tokens
    required = 1 if len(question_tokens) <= 2 else 2
    return len(overlap) >= required


def _is_insufficient_evidence_answer(answer: str) -> bool:
    """Detecta respuestas que declaran evidencia insuficiente.

    Args:
        answer: Respuesta generada o reparada.

    Returns:
        `True` si la respuesta declara evidencia insuficiente.
    """
    return "evidencia insuficiente" in _normalize_text(answer)


def _unsupported_claims(
    answer: str,
    context: ContextBuildResult,
) -> tuple[str, ...]:
    """Identifica afirmaciones citadas sin soporte lexical suficiente.

    Args:
        answer: Respuesta generada o reparada.
        context: Contexto con el contenido de cada fuente citada.

    Returns:
        Afirmaciones compactadas que no se sostienen en sus fuentes citadas.
    """
    source_tokens = {
        source.source_id: _important_tokens(source.content)
        for source in context.sources
    }
    source_contents = {
        source.source_id: source.content for source in context.sources
    }
    unsupported: list[str] = list(_uncited_factual_blocks(answer))
    for claim, source_ids in _cited_claims(answer):
        if _is_insufficient_evidence_answer(claim):
            continue
        claim_tokens = _important_tokens(_strip_citations(claim))
        if not claim_tokens:
            continue
        cited_tokens = set().union(
            *(source_tokens.get(source_id, set()) for source_id in source_ids)
        )
        cited_content = "\n".join(
            source_contents.get(source_id, "") for source_id in source_ids
        )
        if not _claim_supported(
            claim_tokens,
            cited_tokens,
            claim=_strip_citations(claim),
            source_content=cited_content,
        ):
            unsupported.append(_compact_claim(claim))
    return tuple(unsupported)


def _uncited_factual_blocks(answer: str) -> tuple[str, ...]:
    """Detecta parrafos y bullets factuales sin cita inline.

    Los encabezados Markdown, lineas vacias y bloques de codigo no son
    parrafos/bullets del contrato de respuesta y se excluyen deliberadamente.
    """
    blocks: list[str] = []
    current: list[str] = []
    in_fence = False

    def flush() -> None:
        if current:
            blocks.append(" ".join(current).strip())
            current.clear()

    for raw_line in answer.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            flush()
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not line or re.match(r"^#{1,6}\s+", line):
            flush()
            continue
        is_list_item = bool(re.match(r"^(?:[-*+]\s+|\d+[.)]\s+)", line))
        if is_list_item:
            flush()
            current.append(line)
            continue
        current.append(line)
    flush()

    return tuple(
        _compact_claim(block)
        for block in blocks
        if _important_tokens(_strip_citations(block))
        and not re.search(r"\[F\d+\]", block)
    )


def _contradiction_claims(
    answer: str,
    context: ContextBuildResult,
) -> tuple[str, ...]:
    """Detecta contradicciones negativas simples contra el contexto.

    Args:
        answer: Respuesta generada o reparada.
        context: Contexto recuperado completo.

    Returns:
        Afirmaciones compactadas que contradicen patrones explicitos.
    """
    normalized_context = _normalize_text(context.rendered_context)
    contradictions: list[str] = []
    for claim, _source_ids in _cited_claims(answer):
        normalized_claim = _normalize_text(_strip_citations(claim))
        for pattern in (
            r"\bno\s+es\s+([a-z0-9_]+)",
            r"\bno\s+usa\s+([a-z0-9_]+)",
            r"\bno\s+utiliza\s+([a-z0-9_]+)",
        ):
            for match in re.finditer(pattern, normalized_claim):
                token = match.group(1)
                if re.search(
                    rf"\b(es|usa|utiliza)\s+{re.escape(token)}\b",
                    normalized_context,
                ):
                    contradictions.append(_compact_claim(claim))
    return tuple(contradictions)


def _cited_claims(answer: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Extrae afirmaciones que contienen citas inline.

    Args:
        answer: Respuesta generada o reparada.

    Returns:
        Tuplas con el texto de la afirmacion y los IDs de fuente citados.
    """
    claims: list[tuple[str, tuple[str, ...]]] = []
    for raw_claim in re.split(r"(?<=[.!?])\s+|\n+", answer):
        claim = raw_claim.strip(" -\t")
        if not claim:
            continue
        source_ids = tuple(sorted(set(re.findall(r"\[(F\d+)\]", claim))))
        if source_ids:
            claims.append((claim, source_ids))
    return tuple(claims)


def _claim_supported(
    claim_tokens: set[str],
    source_tokens: set[str],
    *,
    claim: str = "",
    source_content: str = "",
) -> bool:
    """Evalua soporte lexical minimo entre una afirmacion y sus fuentes.

    Args:
        claim_tokens: Terminos relevantes de la afirmacion.
        source_tokens: Terminos relevantes de las fuentes citadas.

    Returns:
        `True` si hay solapamiento suficiente para aceptar soporte basico.
    """
    if not source_tokens:
        return False
    if _justified_evidence_limitation(claim, source_content):
        return True
    if _direct_formula_syntax_support(claim, source_content):
        return True
    claim_identifiers = _query_identifiers(claim)
    if claim_identifiers:
        source_identifiers = _identifier_tokens(source_content)
        if not claim_identifiers <= source_identifiers:
            return False
    unique_terms = {
        token
        for token in claim_tokens
        if "_" in token or token.startswith(("p_", "f_")) or len(token) >= 6
    }
    if unique_terms:
        return bool(unique_terms & source_tokens)
    overlap = claim_tokens & source_tokens
    return len(overlap) >= min(2, len(claim_tokens))


def _direct_formula_syntax_support(claim: str, source_content: str) -> bool:
    """Acepta solo inferencias mecanicas explicitas desde sintaxis de formulas."""
    normalized_claim = _normalize_text(claim)
    normalized_source = _normalize_text(source_content)
    describes_rounding = bool(
        re.search(r"\bredonde[a-z]*\b", normalized_claim)
        and re.search(r"\b2\s+decimal(?:es)?\b", normalized_claim)
    )
    has_round_two = bool(
        re.search(r"\bround\s*\([\s\S]*,\s*2\s*\)", normalized_source)
    )
    return describes_rounding and has_round_two


def _justified_evidence_limitation(claim: str, source_content: str) -> bool:
    """Valida ausencias literales acotadas al texto de una fuente citada."""
    normalized_claim = _normalize_text(claim)
    match = re.search(
        r"\b(?:la\s+)?(?:evidencia|fuente)(?:\s+citada)?\s+no\s+"
        r"(?:especifica|indica|explica|detalla|menciona|contiene)\s+(.+)$",
        normalized_claim,
    )
    if match is None:
        return False
    target_tokens = _important_tokens(match.group(1)) - {
        "evidencia",
        "fuente",
        "citada",
        "utiliza",
        "utilizada",
    }
    if not target_tokens:
        return False
    source_tokens = _important_tokens(source_content)
    if target_tokens & source_tokens:
        return False
    semantic_presence = {
        "redondeo": r"\bround\s*\(",
        "decimal": r"\bround\s*\([\s\S]*,\s*\d+\s*\)",
        "decimales": r"\bround\s*\([\s\S]*,\s*\d+\s*\)",
        "variables": r"[@%][a-z0-9_]+",
        "formula": r"(?:\bround\s*\(|[@%][a-z0-9_]+|[+*/-])",
    }
    normalized_source = _normalize_text(source_content)
    return not any(
        token in target_tokens and re.search(pattern, normalized_source)
        for token, pattern in semantic_presence.items()
    )


def _important_tokens(text: str) -> set[str]:
    """Normaliza y filtra terminos utiles para validacion lexical.

    Args:
        text: Texto a tokenizar.

    Returns:
        Conjunto de tokens relevantes sin stopwords operativas.
    """
    tokens: set[str] = set()
    for token in re.findall(r"[a-z0-9_]+", _normalize_text(text)):
        if (
            (len(token) < 4 and "_" not in token)
            or re.fullmatch(r"f\d+", token)
        ):
            continue
        variants = _concept_token_variants(token)
        if variants & _STOPWORDS:
            continue
        tokens.update(variants)
    return tokens


def _query_identifiers(text: str) -> set[str]:
    """Extrae identificadores compuestos pedidos literalmente por el usuario."""
    if "." in text and not re.search(r"\s", text.strip()):
        # Una identidad cualificada completa se resuelve por igualdad arriba;
        # sus segmentos no deben promover a todos los simbolos del contenedor.
        return set()
    return {
        token
        for token in _identifier_tokens(text)
        if "_" in token and any(character.isalpha() for character in token)
    }


def _identifier_tokens(text: str) -> set[str]:
    """Tokeniza identidades sin descomponer sus componentes por underscore."""
    return set(re.findall(r"[a-z0-9_]+", _normalize_text(text)))


def _concept_token_variants(token: str) -> set[str]:
    """Conserva un token y agrega su variante singular espanola predecible.

    La normalizacion es morfologica y agnostica al dominio. No intenta inferir
    sinonimos ni traducir identificadores tecnicos.

    Args:
        token: Token ya normalizado, sin espacios ni tildes.

    Returns:
        Token original y, cuando aplica, una variante singular conservadora.
    """
    variants = {token}
    if "_" in token:
        for component in token.split("_"):
            if len(component) >= 4:
                variants.update(_concept_token_variants(component))
        return variants
    if len(token) < 5:
        return variants
    if token.endswith("iones") and len(token) > 6:
        variants.add(token[:-2])
    elif token.endswith("ces") and len(token) > 5:
        variants.add(token[:-3] + "z")
    elif token.endswith("s") and not token.endswith("sis"):
        variants.add(token[:-1])
    return variants


def _normalize_text(text: str) -> str:
    """Normaliza texto para comparaciones case-insensitive y sin tildes.

    Args:
        text: Texto original.

    Returns:
        Texto en minusculas con vocales acentuadas normalizadas.
    """
    replacements = str.maketrans(
        {
            "á": "a",
            "é": "e",
            "í": "i",
            "ó": "o",
            "ú": "u",
            "ñ": "n",
            "Á": "a",
            "É": "e",
            "Í": "i",
            "Ó": "o",
            "Ú": "u",
            "Ñ": "n",
        }
    )
    return text.translate(replacements).lower()


def _strip_citations(text: str) -> str:
    """Elimina marcadores de cita del texto.

    Args:
        text: Texto con posibles citas inline.

    Returns:
        Texto sin marcadores `[F#]`.
    """
    return re.sub(r"\[(F\d+)\]", "", text)


def _compact_claim(text: str) -> str:
    """Compacta una afirmacion para reportarla en debug.

    Args:
        text: Afirmacion original.

    Returns:
        Afirmacion de una linea truncada a longitud razonable.
    """
    compact = " ".join(text.split())
    return compact[:180]


def _no_llm_answer(context: ContextBuildResult) -> str:
    """Construye la respuesta de inspeccion para `ask --no-llm`.

    Args:
        context: Contexto recuperado que se mostrara al usuario.

    Returns:
        Respuesta textual con fuentes recuperadas sin llamar al LLM.
    """
    return (
        "## Conclusion\n"
        "Modo sin LLM: se muestra el contexto recuperado para inspeccion.\n\n"
        "## Evidencia\n"
        + "\n".join(
            f"### [{source.source_id}] "
            f"{source.candidate.source.get('relative_path')}\n"
            f"chunk={source.candidate.chunk_id}; "
            f"lineas={_line_range(source)}; "
            f"score={source.candidate.combined_score:.3f}\n"
            f"{source.content}"
            for source in context.sources
        )
        + "\n\n## Supuestos y limites\n- No se genero respuesta natural."
    )


def _insufficient_evidence_answer() -> str:
    """Construye la respuesta estandar cuando no hay fuentes recuperadas.

    Returns:
        Mensaje de evidencia insuficiente sin invocar el LLM.
    """
    return (
        "## Conclusion\n"
        "Evidencia insuficiente para responder con seguridad.\n\n"
        "## Evidencia\n"
        "- No se recuperaron fuentes sobre el umbral configurado.\n\n"
        "## Supuestos y limites\n"
        "- No se invoco el LLM para evitar una respuesta sin sustento."
    )


def _invalid_citations_answer(
    validation: CitationValidation,
    context: ContextBuildResult,
    *,
    repair_attempted: bool = False,
) -> str:
    """Construye la respuesta de rechazo para validaciones fallidas.

    Args:
        validation: Resultado de validacion fallida.
        context: Contexto recuperado para listar fuentes disponibles.
        repair_attempted: Indica si ya se ejecuto un intento de reparacion.

    Returns:
        Respuesta textual que explica el rechazo y conserva evidencia util.
    """
    if validation.missing_source_ids:
        detail = f"Citas inexistentes: {', '.join(validation.missing_source_ids)}."
        conclusion = (
            "La respuesta reparada fue rechazada porque contiene citas invalidas."
            if repair_attempted
            else "La respuesta candidata fue rechazada porque contiene citas invalidas."
        )
    else:
        detail = (
            f"{validation.reason}. La respuesta generada no pudo ser "
            "reparada automaticamente."
            if repair_attempted
            else validation.reason
        )
        conclusion = detail
    debug_hint = (
        "\n\n"
        "Ejecute el mismo comando con `--debug` para inspeccionar:\n\n"
        "- evidencia recuperada;\n"
        "- resultados del retrieval;\n"
        "- prompt enviado al modelo;\n"
        "- respuesta original del LLM;\n"
        "- validacion de citas;\n"
        "- intento de reparacion;\n"
        "- resultado final de la validacion."
        if repair_attempted
        else ""
    )
    return (
        "## Conclusion\n"
        f"{conclusion}{debug_hint}\n\n"
        "## Evidencia\n"
        f"- {detail}\n"
        + "\n".join(
            f"- [{source.source_id}] {source.candidate.source.get('relative_path')} "
            f"lineas={_line_range(source)} "
            f"chunk={source.candidate.chunk_id}"
            for source in context.sources
        )
        + "\n\n"
        "## Supuestos y limites\n"
        '- Prueba: barbarion ask "..." --no-llm'
    )


def _line_range(source: ContextSource) -> str:
    """Renderiza el rango de lineas de una fuente de contexto.

    Args:
        source: Fuente numerada del contexto.

    Returns:
        Rango `inicio-fin`, linea unica o `n/a` si no hay metadata.
    """
    start = source.candidate.source.get("start_line")
    end = source.candidate.source.get("end_line")
    if start is None or end is None:
        return "n/a"
    return f"{start}-{end}" if start != end else str(start)
