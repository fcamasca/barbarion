"""Casos de uso H3 para indexacion RAG."""

from __future__ import annotations

import time
from dataclasses import dataclass
import re

from barbarion.config import Settings
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
    RagQueryStatus,
    RetrievalFilter,
    RetrievalMode,
    SearchRequest,
    SearchResponse,
    SearchTimings,
    combine_hybrid_candidates,
    decide_index_plan,
)
from barbarion.infrastructure.sqlite import SQLiteRagRepository


@dataclass(frozen=True, slots=True)
class IndexService:
    """Orquesta indexacion incremental H3."""

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
        """Ejecuta una corrida de indexacion o calcula un dry-run."""
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
    """Orquesta recuperacion semantic, keyword e hybrid para H3."""

    settings: Settings
    repository: SQLiteRagRepository
    embedding_provider: EmbeddingProviderPort
    vector_store: VectorStorePort

    def search(self, request: SearchRequest) -> SearchResponse:
        """Ejecuta busqueda RAG y registra observabilidad local."""
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
        if request.mode == RetrievalMode.SEMANTIC:
            candidates = tuple(
                _with_mode(candidate, RetrievalMode.SEMANTIC)
                for candidate in vector_candidates
            )[: request.top_k]
        elif request.mode == RetrievalMode.KEYWORD:
            candidates = tuple(
                candidate
                for candidate in keyword_candidates
                if candidate.combined_score >= request.similarity_threshold
            )[: request.top_k]
        else:
            candidates = combine_hybrid_candidates(
                vector_candidates,
                keyword_candidates,
                vector_weight=request.vector_weight,
                keyword_weight=request.keyword_weight,
                top_k=request.top_k,
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
class ContextBuilder:
    """Construye contexto final con deduplicacion antes del presupuesto."""

    token_budget: int
    max_chunk_tokens: int
    dedupe_min_hash_prefix: int
    threshold: float = 0.0

    def build(
        self,
        candidates,
        *,
        debug: bool = False,
    ) -> ContextBuildResult:
        """Aplica threshold, dedupe, agrupacion, orden y presupuesto."""
        thresholded, score_omitted = self._threshold(candidates)
        deduped, duplicate_omitted = self._dedupe(thresholded)
        ordered = self._stable_document_order(deduped)
        sources: list[ContextSource] = []
        budget_omitted: list[dict[str, object]] = []
        used_tokens = 0
        for candidate in ordered:
            content = str(candidate.source.get("content") or candidate.source.get("snippet") or "")
            if not content:
                content = str(candidate.source.get("relative_path") or candidate.chunk_id)
            original_token_estimate = _estimate_tokens(content)
            source_id = f"F{len(sources) + 1}"
            content = _truncate_to_tokens(content, self.max_chunk_tokens)
            source = ContextSource(
                source_id=source_id,
                candidate=candidate,
                content=content,
                token_estimate=_estimate_tokens(content),
                original_token_estimate=original_token_estimate,
                content_truncated=original_token_estimate > self.max_chunk_tokens,
            )
            remaining_tokens = self.token_budget - used_tokens
            source = _fit_source_to_budget(source, remaining_tokens)
            if source is None:
                budget_omitted.append(
                    {"chunk_id": candidate.chunk_id, "reason": "budget"}
                )
                continue
            token_estimate = _estimate_tokens(_render_source_context(source))
            sources.append(source)
            used_tokens += token_estimate
        omitted = tuple((*score_omitted, *duplicate_omitted, *budget_omitted))
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
                    int(candidate.source.get("document_id") or 0),
                    int(candidate.source.get("ordinal") or 0),
                    -candidate.combined_score,
                    candidate.chunk_id,
                ),
            )
        )


@dataclass(frozen=True, slots=True)
class PromptBuilder:
    """Construye prompts controlados en espanol."""

    def build(self, *, question: str, context: ContextBuildResult) -> str:
        return (
            "Responde en espanol usando solo la evidencia provista.\n"
            "Toda afirmacion factual debe citar una fuente como [F1].\n"
            "Si la evidencia no alcanza, declara evidencia insuficiente.\n\n"
            f"Pregunta:\n{question}\n\n"
            f"Contexto:\n{context.rendered_context}\n\n"
            "Formato requerido:\n"
            "## Conclusion\n"
            "...\n\n"
            "## Evidencia\n"
            "- [F1] ...\n\n"
            "## Supuestos y limites\n"
            "- ...\n"
        )


@dataclass(frozen=True, slots=True)
class CitationValidator:
    """Valida que las citas mencionadas existan en el contexto."""

    def validate(self, answer: str, context: ContextBuildResult) -> CitationValidation:
        allowed = {source.source_id for source in context.sources}
        cited = set(re.findall(r"\[(F\d+)\]", answer))
        missing = tuple(sorted(cited - allowed))
        valid_cited = tuple(sorted(cited & allowed))
        return CitationValidation(
            valid=bool(valid_cited) and not missing,
            missing_source_ids=missing,
            cited_source_ids=valid_cited,
        )


@dataclass(frozen=True, slots=True)
class AskService:
    """Orquesta search, contexto, prompt, LLM y validacion de citas."""

    search_service: SearchService
    context_builder: ContextBuilder
    prompt_builder: PromptBuilder
    citation_validator: CitationValidator
    llm_provider: LlmProviderPort
    settings: Settings

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
        started = time.monotonic()
        search = self.search_service.search(
            SearchRequest(
                query=question,
                mode=mode,
                filters=filters or RetrievalFilter(),
                top_k=top_k,
                candidate_k=candidate_k,
                similarity_threshold=threshold,
                vector_weight=self.settings.retrieval.vector_weight,
                keyword_weight=self.settings.retrieval.keyword_weight,
                debug=debug,
            )
        )
        context_started = time.monotonic()
        context = self.context_builder.build(search.candidates, debug=debug)
        context_ms = _duration_ms(context_started)
        if not context.sources:
            answer = _insufficient_evidence_answer()
            self.search_service.repository.update_rag_query_metrics(
                query_id=search.query_id,
                context_sources=0,
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
                debug={"duration_ms": _duration_ms(started)} if debug else {},
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
                debug=_ask_debug_payload(
                    started=started,
                    context=context,
                    prompt="",
                    timeout_seconds=self.settings.llm.timeout_seconds,
                )
                if debug
                else {},
            )
        prompt = self.prompt_builder.build(question=question, context=context)
        debug_payload = {}
        if debug:
            debug_payload = _ask_debug_payload(
                started=started,
                context=context,
                prompt=prompt,
                timeout_seconds=self.settings.llm.timeout_seconds,
            )
        llm_started = time.monotonic()
        answer = self.llm_provider.generate(
            prompt=prompt,
            timeout_seconds=self.settings.llm.timeout_seconds,
        )
        llm_ms = _duration_ms(llm_started)
        validation = self.citation_validator.validate(answer, context)
        if not validation.valid:
            answer = _invalid_citations_answer(validation)
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


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    limit = max_tokens * 4
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _fit_source_to_budget(
    source: ContextSource,
    remaining_tokens: int,
) -> ContextSource | None:
    if remaining_tokens <= 0:
        return None
    if _estimate_tokens(_render_source_context(source)) <= remaining_tokens:
        return source
    header_tokens = _estimate_tokens(_render_source_context(source).replace(source.content, ""))
    available_content_tokens = remaining_tokens - header_tokens
    if available_content_tokens <= 0:
        return None
    content = _truncate_to_tokens(source.content, available_content_tokens)
    fitted = ContextSource(
        source_id=source.source_id,
        candidate=source.candidate,
        content=content,
        token_estimate=_estimate_tokens(content),
        original_token_estimate=source.original_token_estimate,
        content_truncated=True,
    )
    if _estimate_tokens(_render_source_context(fitted)) > remaining_tokens:
        return None
    return fitted


def _render_context(sources: list[ContextSource]) -> str:
    return "\n\n".join(_render_source_context(source) for source in sources)


def _render_source_context(source: ContextSource) -> str:
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
    return (
        f"[{source.source_id}] {path}\n"
        f"chunk={candidate.chunk_id}\n"
        f"score={candidate.combined_score:.3f}"
        f"{lines}{pages}\n"
        f"contenido_truncado={str(source.content_truncated).lower()}\n"
        f"{source.content}"
    )


def _ask_debug_payload(
    *,
    started: float,
    context: ContextBuildResult,
    prompt: str,
    timeout_seconds: float,
) -> dict[str, object]:
    return {
        "duration_ms": _duration_ms(started),
        "sources": len(context.sources),
        "context_chars": len(context.rendered_context),
        "context_tokens_est": context.token_estimate,
        "prompt_chars": len(prompt),
        "llm_timeout_seconds": timeout_seconds,
        "truncated_sources": sum(
            1 for source in context.sources if source.content_truncated
        ),
        "context_builder": dict(context.debug),
    }


def _no_llm_answer(context: ContextBuildResult) -> str:
    return (
        "## Conclusion\n"
        "Modo sin LLM: se muestra el contexto recuperado para inspeccion.\n\n"
        "## Evidencia\n"
        + "\n".join(
            f"- [{source.source_id}] {source.candidate.source.get('relative_path')} "
            f"chunk {source.candidate.chunk_id}, score {source.candidate.combined_score:.3f}"
            for source in context.sources
        )
        + "\n\n## Supuestos y limites\n- No se genero respuesta natural."
    )


def _insufficient_evidence_answer() -> str:
    return (
        "## Conclusion\n"
        "Evidencia insuficiente para responder con seguridad.\n\n"
        "## Evidencia\n"
        "- No se recuperaron fuentes sobre el umbral configurado.\n\n"
        "## Supuestos y limites\n"
        "- No se invoco el LLM para evitar una respuesta sin sustento."
    )


def _invalid_citations_answer(validation: CitationValidation) -> str:
    if validation.missing_source_ids:
        detail = f"Citas inexistentes: {', '.join(validation.missing_source_ids)}."
        conclusion = "La respuesta candidata fue rechazada porque contiene citas invalidas."
    else:
        detail = "La respuesta generada no incluyo citas validas."
        conclusion = "La respuesta generada no incluyo citas validas."
    return (
        "## Conclusion\n"
        f"{conclusion}\n\n"
        "## Evidencia\n"
        f"- {detail}\n\n"
        "## Supuestos y limites\n"
        '- Prueba: barbarion ask "..." --no-llm'
    )
