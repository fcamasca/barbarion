"""Pruebas H3.1-T02 de composicion y tamaños del prompt."""

from __future__ import annotations

from pathlib import Path

from barbarion.application.rag import (
    TOKEN_ESTIMATOR_ID,
    ContextBuilder,
    PromptBuilder,
    estimate_tokens,
)
from barbarion.cli import _render_prompt_composition_metrics
from barbarion.domain.rag import RetrievalCandidate, RetrievalMode
from tests.unit.test_rag_context_ask import ask_service


def _candidate(
    chunk_id: str,
    sha_char: str,
    *,
    content: str,
    document_id: int,
) -> RetrievalCandidate:
    """Crea una fuente sintetica trazable para composicion."""
    return RetrievalCandidate(
        chunk_id=chunk_id,
        content_sha256=sha_char * 64,
        combined_score=0.9,
        source={
            "document_id": document_id,
            "ordinal": 0,
            "relative_path": f"synthetic/source-{document_id}.txt",
            "start_line": 1,
            "end_line": 2,
            "content": content,
        },
    )


def _context():
    return ContextBuilder(
        token_budget=500,
        max_chunk_tokens=100,
        dedupe_min_hash_prefix=8,
    ).build(
        (
            _candidate(
                "source-a",
                "a",
                content="Evidencia alfa con acento: á.",
                document_id=1,
            ),
            _candidate(
                "source-b",
                "b",
                content="Evidencia beta con símbolo: ñ.",
                document_id=2,
            ),
        )
    )


def _assert_exact_reconciliation(composition) -> None:  # noqa: ANN001
    rendered = composition.rendered_prompt
    metrics = composition.metrics()

    assert rendered == "".join(component.text for component in composition.components)
    assert composition.chars == len(rendered)
    assert composition.utf8_bytes == len(rendered.encode("utf-8"))
    assert composition.tokens_est_local == estimate_tokens(rendered)
    assert metrics["component_chars_total"] == metrics["chars"]
    assert metrics["component_utf8_bytes_total"] == metrics["utf8_bytes"]
    assert metrics["chars_reconciled"] is True
    assert metrics["utf8_bytes_reconciled"] is True
    assert metrics["estimator_id"] == TOKEN_ESTIMATOR_ID


def test_generation_composition_renders_the_public_prompt_exactly() -> None:
    builder = PromptBuilder()
    context = _context()
    composition = builder.compose(
        question="¿Qué evidencia existe?",
        context=context,
    )

    assert composition.rendered_prompt == builder.build(
        question="¿Qué evidencia existe?",
        context=context,
    )
    assert [component.kind for component in composition.components] == [
        "instructions",
        "question",
        "source_metadata",
        "source_metadata",
        "source_content",
        "source_metadata",
        "source_content",
        "source_metadata",
        "output_format",
    ]
    assert [
        component.source_id
        for component in composition.components
        if component.kind == "source_content"
    ] == ["F1", "F2"]
    _assert_exact_reconciliation(composition)


def test_repair_composition_renders_the_public_prompt_exactly() -> None:
    builder = PromptBuilder()
    context = _context()
    composition = builder.compose_repair(
        question="¿Qué evidencia existe?",
        context=context,
        answer="Respuesta rechazada sin cita.",
    )

    assert composition.rendered_prompt == builder.repair(
        question="¿Qué evidencia existe?",
        context=context,
        answer="Respuesta rechazada sin cita.",
    )
    rejected = [
        component
        for component in composition.components
        if component.kind == "rejected_answer"
    ]
    assert len(rejected) == 1
    assert rejected[0].text == (
        "Respuesta original:\nRespuesta rechazada sin cita.\n\n"
    )
    _assert_exact_reconciliation(composition)


def test_unicode_component_sizes_distinguish_chars_from_utf8_bytes() -> None:
    composition = PromptBuilder().compose(
        question="¿Dónde está la señal ñ?",
        context=_context(),
    )
    question = next(
        component
        for component in composition.components
        if component.kind == "question"
    )

    assert question.utf8_bytes > question.chars
    assert composition.utf8_bytes > composition.chars
    _assert_exact_reconciliation(composition)


def test_estimator_is_the_simple_versioned_historical_function() -> None:
    assert TOKEN_ESTIMATOR_ID == "chars4_v1"
    assert estimate_tokens("") == 1
    assert estimate_tokens("a") == 1
    assert estimate_tokens("a" * 4) == 1
    assert estimate_tokens("a" * 5) == 2


def test_cli_renders_component_sizes_without_content(capsys) -> None:  # noqa: ANN001
    composition = PromptBuilder().compose(
        question="¿Dónde está la señal ñ?",
        context=_context(),
    )

    _render_prompt_composition_metrics(composition.metrics())
    rendered = capsys.readouterr().err

    assert "prompt_estimator_id=chars4_v1" in rendered
    assert "prompt_utf8_bytes=" in rendered
    assert "prompt_component kind=instructions" in rendered
    assert "prompt_component kind=source_content source_id=F1" in rendered
    assert "¿Dónde" not in rendered
    assert "Evidencia alfa" not in rendered


def test_ask_debug_exposes_sizes_without_copying_component_text(
    tmp_path: Path,
) -> None:
    service, _fake_llm = ask_service(
        tmp_path,
        "order_total se selecciona desde dual [F1].",
    )
    result = service.ask(
        "order_total",
        mode=RetrievalMode.KEYWORD,
        top_k=3,
        candidate_k=3,
        threshold=0,
        debug=True,
    )

    metrics = result.debug["prompt_composition"]
    assert metrics["estimator_id"] == TOKEN_ESTIMATOR_ID
    assert metrics["chars"] == result.debug["prompt_chars"]
    assert metrics["tokens_est_local"] == result.debug["prompt_tokens_est"]
    assert metrics["chars_reconciled"] is True
    assert metrics["utf8_bytes_reconciled"] is True
    assert "order_total" not in str(metrics)
    assert "select order_total" not in str(metrics)
    assert result.debug["repair_prompt_composition"] is None


def test_ask_debug_measures_repair_as_a_separate_composition(
    tmp_path: Path,
) -> None:
    service, _fake_llm = ask_service(
        tmp_path,
        (
            "Respuesta sin cita.",
            "order_total se selecciona desde dual [F1].",
        ),
    )
    result = service.ask(
        "order_total",
        mode=RetrievalMode.KEYWORD,
        top_k=3,
        candidate_k=3,
        threshold=0,
        debug=True,
    )

    generation = result.debug["prompt_composition"]
    repair = result.debug["repair_prompt_composition"]
    assert repair["estimator_id"] == TOKEN_ESTIMATOR_ID
    assert repair["chars_reconciled"] is True
    assert repair["utf8_bytes_reconciled"] is True
    assert repair["chars"] == len(result.debug["repair_prompt"])
    assert repair["chars"] != generation["chars"]
    assert any(
        component["kind"] == "rejected_answer"
        for component in repair["components"]
    )
