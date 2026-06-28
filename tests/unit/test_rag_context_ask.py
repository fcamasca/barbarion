"""Pruebas de contexto, prompts, citas y ask H3."""

import sqlite3

from barbarion.application.rag import (
    AskService,
    CitationValidator,
    ContextBuilder,
    PromptBuilder,
)
from barbarion.domain.rag import RagQueryStatus, RetrievalCandidate, RetrievalMode
from tests.unit.test_rag_search_service import service_for


SHA_A = "a" * 64
SHA_B = "b" * 64


class FakeLlm:
    provider = "fake"
    model = "responder"

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    def generate(self, *, prompt: str, timeout_seconds: float) -> str:
        del timeout_seconds
        self.prompts.append(prompt)
        return self.answer


def candidate(
    chunk_id: str,
    sha: str,
    score: float,
    *,
    document_id: int = 1,
    ordinal: int = 0,
    content: str = "contenido recuperado",
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id,
        content_sha256=sha,
        combined_score=score,
        source={
            "document_id": document_id,
            "ordinal": ordinal,
            "relative_path": "pkg/demo.sql",
            "content": content,
        },
    )


def test_context_builder_threshold_dedupe_order_and_budget() -> None:
    builder = ContextBuilder(
        token_budget=80,
        max_chunk_tokens=4,
        dedupe_min_hash_prefix=8,
        threshold=0.5,
    )
    result = builder.build(
        (
            candidate("low", SHA_A, 0.1),
            candidate("one", SHA_A, 0.9, ordinal=1, content="a" * 8),
            candidate("duplicate", SHA_A, 0.8, ordinal=2),
            candidate("two", SHA_B, 0.7, ordinal=0, content="b" * 20),
        ),
        debug=True,
    )

    assert [source.source_id for source in result.sources] == ["F1", "F2"]
    assert [source.candidate.chunk_id for source in result.sources] == ["two", "one"]
    assert {item["reason"] for item in result.omitted} == {"threshold", "duplicate"}
    assert result.metrics.duplicate_ratio == 0.25
    assert result.debug["after_dedupe"] == 2
    assert result.debug["truncated_sources"] == 1


def test_context_builder_respects_max_chunk_tokens() -> None:
    builder = ContextBuilder(
        token_budget=200,
        max_chunk_tokens=5,
        dedupe_min_hash_prefix=8,
    )

    result = builder.build(
        (candidate("large", SHA_A, 0.9, content="x" * 200),),
        debug=True,
    )

    assert result.sources[0].content_truncated is True
    assert result.sources[0].token_estimate <= 5
    assert "contenido_truncado=true" in result.rendered_context
    assert "x" * 80 not in result.rendered_context


def test_context_builder_respects_global_context_budget() -> None:
    builder = ContextBuilder(
        token_budget=20,
        max_chunk_tokens=100,
        dedupe_min_hash_prefix=8,
    )

    result = builder.build(
        (
            candidate("one", SHA_A, 0.9, content="a" * 200),
            candidate("two", SHA_B, 0.8, content="b" * 200),
        ),
        debug=True,
    )

    assert result.token_estimate <= 20
    assert len(result.sources) == 1
    assert result.sources[0].content_truncated is True
    assert result.omitted[0]["reason"] == "budget"


def test_citation_validator_rejects_unknown_source() -> None:
    context = ContextBuilder(
        token_budget=100,
        max_chunk_tokens=50,
        dedupe_min_hash_prefix=8,
    ).build((candidate("one", SHA_A, 0.9),))

    validation = CitationValidator().validate("Respuesta [F1] y [F9]", context)

    assert validation.valid is False
    assert validation.missing_source_ids == ("F9",)


def test_citation_validator_rejects_answer_without_inline_citation() -> None:
    context = ContextBuilder(
        token_budget=100,
        max_chunk_tokens=50,
        dedupe_min_hash_prefix=8,
    ).build((candidate("one", SHA_A, 0.9),))

    validation = CitationValidator().validate("Respuesta sin marcador.", context)

    assert validation.valid is False
    assert validation.missing_source_ids == ()
    assert validation.cited_source_ids == ()


def ask_service(tmp_path, answer: str) -> tuple[AskService, FakeLlm]:
    search_service = service_for(tmp_path)
    fake_llm = FakeLlm(answer)
    service = AskService(
        search_service=search_service,
        context_builder=ContextBuilder(
            token_budget=200,
            max_chunk_tokens=100,
            dedupe_min_hash_prefix=8,
            threshold=0,
        ),
        prompt_builder=PromptBuilder(),
        citation_validator=CitationValidator(),
        llm_provider=fake_llm,
        settings=search_service.settings,
    )
    return service, fake_llm


def test_ask_no_llm_returns_context_and_updates_metrics(tmp_path) -> None:
    service, fake_llm = ask_service(tmp_path, "no usado")

    result = service.ask(
        "order_total",
        mode=RetrievalMode.KEYWORD,
        top_k=3,
        candidate_k=3,
        threshold=0,
        no_llm=True,
        debug=True,
    )

    assert result.no_llm is True
    assert result.status == RagQueryStatus.COMPLETED
    assert "[F1]" in result.answer
    assert result.context.sources[0].candidate.source["start_line"] == 5
    assert result.context.sources[0].candidate.source["end_line"] == 8
    assert "lineas=5-8" in result.context.rendered_context
    assert fake_llm.prompts == []
    with sqlite3.connect(tmp_path / "barbarion.db") as connection:
        row = connection.execute(
            "SELECT context_sources, context_ms, duplicate_ratio FROM rag_queries"
        ).fetchone()
    assert row[0] == 1
    assert row[1] is not None
    assert row[2] == 0


def test_ask_rejects_llm_answer_with_invalid_citation(tmp_path) -> None:
    service, fake_llm = ask_service(tmp_path, "Conclusion con cita inexistente [F9].")

    result = service.ask(
        "order_total",
        mode=RetrievalMode.KEYWORD,
        top_k=3,
        candidate_k=3,
        threshold=0,
    )

    assert fake_llm.prompts
    assert result.citations_valid is False
    assert result.missing_citations == ("F9",)
    assert "citas inexistentes" in result.answer.lower()


def test_ask_rejects_llm_answer_without_inline_citation(tmp_path) -> None:
    service, fake_llm = ask_service(tmp_path, "Conclusion sin cita.")

    result = service.ask(
        "order_total",
        mode=RetrievalMode.KEYWORD,
        top_k=3,
        candidate_k=3,
        threshold=0,
    )

    assert fake_llm.prompts
    assert result.citations_valid is False
    assert result.missing_citations == ()
    assert "no incluyo citas validas" in result.answer


def test_ask_accepts_llm_answer_with_valid_inline_citation(tmp_path) -> None:
    service, _fake_llm = ask_service(tmp_path, "Conclusion con soporte [F1].")

    result = service.ask(
        "order_total",
        mode=RetrievalMode.KEYWORD,
        top_k=3,
        candidate_k=3,
        threshold=0,
    )

    assert result.citations_valid is True
    assert result.status == RagQueryStatus.COMPLETED
    assert result.answer == "Conclusion con soporte [F1]."


def test_ask_debug_reports_size_metrics_without_context_dump(tmp_path) -> None:
    service, _fake_llm = ask_service(tmp_path, "Conclusion con soporte [F1].")

    result = service.ask(
        "order_total",
        mode=RetrievalMode.KEYWORD,
        top_k=3,
        candidate_k=3,
        threshold=0,
        debug=True,
    )

    assert result.debug["sources"] == 1
    assert result.debug["context_chars"] > 0
    assert result.debug["context_tokens_est"] > 0
    assert result.debug["prompt_chars"] > result.debug["context_chars"]
    assert result.debug["llm_timeout_seconds"] > 0
    assert result.debug["truncated_sources"] == 0
    assert "order_total :=" not in str(dict(result.debug))


def test_ask_insufficient_evidence_does_not_call_llm(tmp_path) -> None:
    service, fake_llm = ask_service(tmp_path, "no usado")

    result = service.ask(
        "NO_EXISTE_EN_CORPUS",
        mode=RetrievalMode.KEYWORD,
        top_k=3,
        candidate_k=3,
        threshold=0,
    )

    assert result.status == RagQueryStatus.INSUFFICIENT_EVIDENCE
    assert fake_llm.prompts == []
    assert "Evidencia insuficiente" in result.answer
