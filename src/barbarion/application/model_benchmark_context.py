"""Adaptacion del dataset sintetico al contrato RAG productivo."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from barbarion.application.rag import CitationValidator, ContextBuilder, PromptBuilder
from barbarion.domain.model_benchmark import ModelBenchmarkCase
from barbarion.domain.rag import (
    CitationValidation,
    ContextBuildResult,
    RetrievalCandidate,
)


class ModelBenchmarkContextError(ValueError):
    """El contexto sintetico no pudo conservarse de forma exacta."""


@dataclass(frozen=True, slots=True)
class PreparedBenchmarkCase:
    """Pregunta, contexto y prompt congelados antes de variar el modelo."""

    case: ModelBenchmarkCase
    context: ContextBuildResult
    prompt: str
    question_hash: str
    context_hash: str
    prompt_hash: str


@dataclass(frozen=True, slots=True)
class ModelBenchmarkRagAdapter:
    """Reutiliza constructores y validador RAG sin ejecutar retrieval."""

    context_builder: ContextBuilder
    prompt_builder: PromptBuilder
    citation_validator: CitationValidator

    def prepare(self, case: ModelBenchmarkCase) -> PreparedBenchmarkCase:
        """Prepara una unica entrada inmutable para todos los modelos."""
        candidates = tuple(
            _candidate(case, position)
            for position in range(len(case.context))
        )
        context = self.context_builder.build(candidates, debug=False)
        _ensure_frozen_context(case, context)
        prompt = self.prompt_builder.build(
            question=case.question,
            context=context,
        )
        return PreparedBenchmarkCase(
            case=case,
            context=context,
            prompt=prompt,
            question_hash=_sha256(case.question),
            context_hash=_sha256(context.rendered_context),
            prompt_hash=_sha256(prompt),
        )

    def validate(
        self,
        prepared: PreparedBenchmarkCase,
        answer: str,
    ) -> CitationValidation:
        """Delega sin cambios en el validador usado por `ask`."""
        return self.citation_validator.validate(
            answer,
            prepared.context,
            question=prepared.case.question,
        )


def _candidate(case: ModelBenchmarkCase, position: int) -> RetrievalCandidate:
    fragment = case.context[position]
    return RetrievalCandidate(
        chunk_id=f"benchmark-{case.id}-{fragment.citation_id.lower()}",
        content_sha256=_sha256(fragment.content),
        combined_score=1.0,
        source={
            "document_id": 1,
            "ordinal": position,
            "relative_path": fragment.source,
            "content": fragment.content,
        },
    )


def _ensure_frozen_context(
    case: ModelBenchmarkCase,
    context: ContextBuildResult,
) -> None:
    expected = tuple(
        (fragment.citation_id, fragment.content, fragment.source)
        for fragment in case.context
    )
    actual = tuple(
        (
            source.source_id,
            source.content,
            str(source.candidate.source.get("relative_path") or ""),
        )
        for source in context.sources
    )
    if actual != expected:
        raise ModelBenchmarkContextError(
            "ContextBuilder omitio, reordeno o trunco el contexto sintetico."
        )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

