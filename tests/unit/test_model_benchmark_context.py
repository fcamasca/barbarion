"""Pruebas de contexto congelado y reutilizacion del RAG vigente."""

from dataclasses import replace

import pytest

from barbarion.application.model_benchmark_context import (
    ModelBenchmarkContextError,
    ModelBenchmarkRagAdapter,
)
from barbarion.application.model_benchmark_dataset import (
    load_model_benchmark_dataset,
)
from barbarion.application.rag import CitationValidator, ContextBuilder, PromptBuilder


def _adapter(*, token_budget: int = 1000) -> ModelBenchmarkRagAdapter:
    return ModelBenchmarkRagAdapter(
        context_builder=ContextBuilder(
            token_budget=token_budget,
            max_chunk_tokens=500,
            dedupe_min_hash_prefix=8,
            threshold=0,
        ),
        prompt_builder=PromptBuilder(),
        citation_validator=CitationValidator(),
    )


def test_prepare_reuses_context_and_prompt_builders_without_retrieval() -> None:
    case = load_model_benchmark_dataset().cases[6]

    prepared = _adapter().prepare(case)

    assert tuple(source.source_id for source in prepared.context.sources) == (
        "F1",
        "F2",
    )
    assert tuple(source.content for source in prepared.context.sources) == tuple(
        fragment.content for fragment in case.context
    )
    assert prepared.prompt == PromptBuilder().build(
        question=case.question,
        context=prepared.context,
    )
    assert "Usa solo estos IDs de fuente existentes: [F1], [F2]." in prepared.prompt


def test_preparation_is_model_independent_and_hashes_exact_utf8_bytes() -> None:
    case = load_model_benchmark_dataset().cases[0]
    adapter = _adapter()

    first = adapter.prepare(case)
    second = adapter.prepare(case)

    assert first.prompt == second.prompt
    assert first.question_hash == second.question_hash
    assert first.context_hash == second.context_hash
    assert first.prompt_hash == second.prompt_hash
    assert len({first.question_hash, first.context_hash, first.prompt_hash}) == 3


def test_adapter_delegates_validation_to_productive_citation_validator() -> None:
    case = load_model_benchmark_dataset().cases[0]
    adapter = _adapter()
    prepared = adapter.prepare(case)
    answer = "El Componente A es ámbar y su estado es estable [F1]."

    through_adapter = adapter.validate(prepared, answer)
    direct = CitationValidator().validate(
        answer,
        prepared.context,
        question=case.question,
    )

    assert through_adapter == direct
    assert through_adapter.valid is True


def test_adapter_rejects_budget_that_would_change_frozen_context() -> None:
    case = load_model_benchmark_dataset().cases[6]

    with pytest.raises(ModelBenchmarkContextError, match="omitio, reordeno o trunco"):
        _adapter(token_budget=10).prepare(case)


def test_question_change_changes_question_and_prompt_hash_not_context_hash() -> None:
    case = load_model_benchmark_dataset().cases[0]
    adapter = _adapter()
    original = adapter.prepare(case)
    changed = adapter.prepare(replace(case, question=case.question + " Responde brevemente."))

    assert changed.question_hash != original.question_hash
    assert changed.prompt_hash != original.prompt_hash
    assert changed.context_hash == original.context_hash

