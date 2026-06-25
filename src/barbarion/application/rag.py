"""Casos de uso H3 para indexacion RAG."""

from __future__ import annotations

import time
from dataclasses import dataclass
import re

from barbarion.config import Settings
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
    ) -> IndexRunSummary:
        """Ejecuta una corrida de indexacion o calcula un dry-run."""
        started = time.monotonic()
        chunks = self.repository.indexable_chunks(
            domain=self.settings.domain,
            scope=scope,
        )
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
        if dry_run:
            return _summary_from_plan(
                plan,
                status=EmbeddingRunStatus.COMPLETED,
                duration_ms=_duration_ms(started),
                dry_run=True,
            )
        if not chunks and not plan.deleted_chunks:
            return IndexRunSummary(
                status=EmbeddingRunStatus.COMPLETED,
                duration_ms=_duration_ms(started),
            )

        if manifest is None or manifest_id is None:
            manifest = self._create_manifest_from_first_chunk(chunks)
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

        run_id = self.repository.begin_embedding_run(
            manifest_id=manifest_id,
            mode=mode,
            scope=scope,
        )
        failed = 0
        indexed_new = 0
        indexed_updated = 0
        deleted = 0
        for decision in plan.decisions:
            try:
                if decision.action == IndexAction.UNCHANGED:
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
                    deleted += 1
                    continue
                assert decision.chunk is not None
                vector = self._embed_chunk(decision.chunk, manifest)
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
                if decision.action == IndexAction.NEW:
                    indexed_new += 1
                else:
                    indexed_updated += 1
            except Exception as exc:
                failed += 1
                if decision.chunk is not None:
                    self.repository.record_chunk_error(
                        run_id=run_id,
                        manifest_id=manifest_id,
                        chunk=decision.chunk,
                        error_code=type(exc).__name__,
                        error_message=str(exc),
                    )

        status = (
            EmbeddingRunStatus.COMPLETED_WITH_ERRORS
            if failed
            else EmbeddingRunStatus.COMPLETED
        )
        summary = IndexRunSummary(
            status=status,
            new_chunks=indexed_new,
            updated_chunks=indexed_updated,
            unchanged_chunks=plan.unchanged_chunks,
            deleted_chunks=deleted,
            failed_chunks=failed,
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
        duration_ms=duration_ms,
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
            token_estimate = min(_estimate_tokens(content), self.max_chunk_tokens)
            if used_tokens + token_estimate > self.token_budget:
                budget_omitted.append(
                    {"chunk_id": candidate.chunk_id, "reason": "budget"}
                )
                continue
            source_id = f"F{len(sources) + 1}"
            sources.append(
                ContextSource(
                    source_id=source_id,
                    candidate=candidate,
                    content=_truncate_to_tokens(content, self.max_chunk_tokens),
                    token_estimate=token_estimate,
                )
            )
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
        return CitationValidation(valid=not missing, missing_source_ids=missing)


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
                debug={"duration_ms": _duration_ms(started)} if debug else {},
            )
        prompt = self.prompt_builder.build(question=question, context=context)
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
            debug={"duration_ms": _duration_ms(started)} if debug else {},
        )


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    limit = max_tokens * 4
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _render_context(sources: list[ContextSource]) -> str:
    blocks = []
    for source in sources:
        candidate = source.candidate
        path = candidate.source.get("relative_path") or "fuente desconocida"
        line_start = candidate.source.get("start_line")
        line_end = candidate.source.get("end_line")
        lines = ""
        if line_start is not None and line_end is not None:
            lines = f", lineas {line_start}-{line_end}"
        blocks.append(
            f"[{source.source_id}] {path}, chunk {candidate.chunk_id}, "
            f"score {candidate.combined_score:.3f}{lines}\n{source.content}"
        )
    return "\n\n".join(blocks)


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
    missing = ", ".join(validation.missing_source_ids)
    return (
        "## Conclusion\n"
        "La respuesta candidata fue rechazada porque contiene citas invalidas.\n\n"
        "## Evidencia\n"
        f"- Citas inexistentes: {missing}.\n\n"
        "## Supuestos y limites\n"
        "- Ejecuta con debug para inspeccionar el contexto recuperado."
    )
