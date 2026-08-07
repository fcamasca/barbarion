"""Pruebas de contexto, prompts, citas y ask RAG."""

import hashlib
import logging
import sqlite3
from collections.abc import Iterator
from dataclasses import replace

import pytest

from barbarion.application.rag import (
    AskService,
    CitationValidator,
    ContextBuilder,
    PromptBuilder,
    _build_context_for_input_budget,
    _build_repair_context_for_input_budget,
)
from barbarion.domain.rag import (
    CitationValidation,
    LlmProviderError,
    RagQueryStatus,
    RetrievalCandidate,
    RetrievalMode,
)
from barbarion.infrastructure.anthropic import AnthropicLlmProvider
from tests.unit.test_rag_search_service import service_for


SHA_A = "a" * 64
SHA_B = "b" * 64


class _ListHandler(logging.Handler):
    """Captura registros sin depender del logger raíz de pytest."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Conserva un registro emitido para las aserciones."""
        self.records.append(record)


@pytest.fixture
def ask_log_records() -> Iterator[list[logging.LogRecord]]:
    """Aísla y captura directamente los eventos del logger de Barbarion."""
    logger = logging.getLogger("barbarion")
    original_handlers = list(logger.handlers)
    original_level = logger.level
    original_propagate = logger.propagate
    original_disabled = logger.disabled
    handler = _ListHandler()
    logger.handlers[:] = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.disabled = False
    try:
        yield handler.records
    finally:
        logger.handlers[:] = original_handlers
        logger.setLevel(original_level)
        logger.propagate = original_propagate
        logger.disabled = original_disabled


class FakeLlm:
    provider = "fake"
    model = "responder"

    def __init__(
        self,
        answer: str | BaseException | tuple[str | BaseException, ...],
    ) -> None:
        self.answers = list(answer) if isinstance(answer, tuple) else [answer]
        self.prompts: list[str] = []

    def generate(self, *, prompt: str, timeout_seconds: float) -> str:
        del timeout_seconds
        self.prompts.append(prompt)
        index = min(len(self.prompts) - 1, len(self.answers) - 1)
        answer = self.answers[index]
        if isinstance(answer, BaseException):
            raise answer
        return answer


class FakeCitationValidator:
    """Devuelve resultados controlados sin inspeccionar respuestas sensibles."""

    def __init__(self, results: tuple[CitationValidation, ...]) -> None:
        self.results = list(results)

    def validate(self, answer, context, *, question=""):  # noqa: ANN001, ANN201
        """Entrega el siguiente resultado configurado."""
        del answer, context, question
        return self.results.pop(0)


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


def test_context_builder_omits_candidate_without_evidence_content() -> None:
    """Una ruta nunca debe convertirse en contenido aparente de evidencia."""
    builder = ContextBuilder(
        token_budget=200,
        max_chunk_tokens=50,
        dedupe_min_hash_prefix=8,
    )
    missing_content = RetrievalCandidate(
        chunk_id="missing-content",
        content_sha256=SHA_A,
        combined_score=0.9,
        source={"relative_path": "oracle/only-a-path.fnc"},
    )

    result = builder.build((missing_content,), debug=True)

    assert result.sources == ()
    assert result.rendered_context == ""
    assert result.omitted == (
        {"chunk_id": "missing-content", "reason": "missing_content"},
    )


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


def test_citation_validator_rejects_uncited_factual_paragraphs_and_bullets() -> None:
    context = ContextBuilder(
        token_budget=100,
        max_chunk_tokens=50,
        dedupe_min_hash_prefix=8,
    ).build(
        (
            candidate(
                "one",
                SHA_A,
                0.9,
                content="La configuracion A esta declarada.",
            ),
        )
    )
    answer = """## Conclusion
La configuracion A participa en el proceso.

## Evidencia
- La configuracion A esta declarada. [F1]

## Supuestos y limites
- Podrian existir otras configuraciones."""

    validation = CitationValidator().validate(
        answer,
        context,
        question="configuracion A",
    )

    assert validation.valid is False
    assert validation.cited_source_ids == ("F1",)
    assert validation.missing_source_ids == ()
    assert validation.unsupported_claims == (
        "La configuracion A participa en el proceso.",
        "- Podrian existir otras configuraciones.",
    )
    assert "no respaldadas" in validation.reason


def test_citation_validator_accepts_insufficient_evidence_when_context_does_not_answer() -> None:
    context = ContextBuilder(
        token_budget=100,
        max_chunk_tokens=50,
        dedupe_min_hash_prefix=8,
    ).build((candidate("one", SHA_A, 0.9, content="select order_total from dual;"),))

    validation = CitationValidator().validate(
        "Evidencia insuficiente: falta customer_tax en la fuente recuperada [F1].",
        context,
        question="customer_tax",
    )

    assert validation.valid is True


def test_citation_validator_rejects_valid_citation_with_unsupported_content() -> None:
    context = ContextBuilder(
        token_budget=100,
        max_chunk_tokens=50,
        dedupe_min_hash_prefix=8,
    ).build((candidate("one", SHA_A, 0.9, content="select order_total from dual;"),))

    validation = CitationValidator().validate(
        "customer_tax se calcula con una regla externa [F1].",
        context,
        question="order_total",
    )

    assert validation.valid is False
    assert validation.unsupported_claims
    assert "no respaldadas" in validation.reason


@pytest.mark.parametrize(
    ("content", "answer"),
    (
        (
            "VAL_FORMULA=ROUND(([@NOM_OPERACION_DIA] * [@TASA_CUPON]),2)",
            "El resultado final se redondea a 2 decimales mediante ROUND [F1].",
        ),
        (
            "VAL_FORMULA=ROUND(([@NOM_OPERACION_DIA] * [@TASA_CUPON]),2)",
            "La formula usa NOM_OPERACION_DIA y TASA_CUPON [F1].",
        ),
        (
            "des_variable=provision diaria para la operacion vigente",
            "La descripcion corresponde a una provision diaria de la operacion [F1].",
        ),
        (
            "VAL_FORMULA=ROUND([@IMPORTE] * [@TASA],2)",
            "La evidencia no especifica la moneda del importe [F1].",
        ),
    ),
)
def test_citation_validator_accepts_direct_formula_and_evidence_claims(
    content: str,
    answer: str,
) -> None:
    context = ContextBuilder(
        token_budget=200,
        max_chunk_tokens=100,
        dedupe_min_hash_prefix=8,
    ).build((candidate("one", SHA_A, 0.9, content=content),))

    validation = CitationValidator().validate(answer, context)

    assert validation.valid is True
    assert validation.unsupported_claims == ()


@pytest.mark.parametrize(
    ("content", "answer"),
    (
        (
            "VAL_FORMULA=ROUND([@IMPORTE] * [@TASA],2)",
            "La evidencia no especifica el redondeo [F1].",
        ),
        (
            "VAL_FORMULA=ROUND([@IMPORTE] * [@TASA],2)",
            "La formula usa IMPORTE, TASA y BONIFICACION_SECRETA [F1].",
        ),
    ),
)
def test_citation_validator_rejects_false_limitation_and_invented_claim(
    content: str,
    answer: str,
) -> None:
    context = ContextBuilder(
        token_budget=200,
        max_chunk_tokens=100,
        dedupe_min_hash_prefix=8,
    ).build((candidate("one", SHA_A, 0.9, content=content),))

    validation = CitationValidator().validate(answer, context)

    assert validation.valid is False
    assert validation.unsupported_claims


def test_citation_validator_rejects_answer_contradicted_by_context() -> None:
    context = ContextBuilder(
        token_budget=100,
        max_chunk_tokens=50,
        dedupe_min_hash_prefix=8,
    ).build((candidate("one", SHA_A, 0.9, content="estado es activo"),))

    validation = CitationValidator().validate(
        "estado no es activo [F1].",
        context,
        question="estado",
    )

    assert validation.valid is False
    assert validation.contradiction_claims
    assert "contradice" in validation.reason


def test_prompt_builder_lists_allowed_sources_and_inline_citation_rule() -> None:
    context = ContextBuilder(
        token_budget=100,
        max_chunk_tokens=50,
        dedupe_min_hash_prefix=8,
    ).build((candidate("one", SHA_A, 0.9),))

    prompt = PromptBuilder().build(question="Como se calcula?", context=context)

    assert "Usa solo estos IDs de fuente existentes: [F1]." in prompt
    assert "Cada parrafo o bullet" in prompt
    assert "Evidencia insuficiente" in prompt
    assert "No infieras" in prompt
    assert "## Conclusion\n... [F1]" in prompt
    assert "## Supuestos y limites" not in prompt
    assert "si no existen, omite la seccion" in prompt
    assert "recapitulaciones ni comentarios accesorios" in prompt


def test_prompt_builder_generation_and_repair_text_are_characterized_before_adapter() -> None:
    """Congela el texto previo a cualquier serializacion del proveedor."""
    context = ContextBuilder(
        token_budget=100,
        max_chunk_tokens=50,
        dedupe_min_hash_prefix=8,
    ).build(
        (
            candidate(
                "one",
                SHA_A,
                0.9,
                content="contenido recuperado",
            ),
        )
    )
    builder = PromptBuilder()

    generation = builder.build(question="Como se calcula?", context=context)
    repair = builder.repair(
        question="Como se calcula?",
        context=context,
        answer="Respuesta sin cita.",
    )

    assert hashlib.sha256(generation.encode("utf-8")).hexdigest() == (
        "2cb7950ca1b20a109a37e997fff3bbe29cecf1d177c4b7a659f06bce6306ad0a"
    )
    assert hashlib.sha256(repair.encode("utf-8")).hexdigest() == (
        "3185002c20b75f0a0b157cc20a6e3efa481e21b8de71d7321b95e592206c3cd2"
    )


def test_generation_and_repair_share_the_same_grounding_rules() -> None:
    context = ContextBuilder(
        token_budget=100,
        max_chunk_tokens=50,
        dedupe_min_hash_prefix=8,
    ).build((candidate("one", SHA_A, 0.9),))
    builder = PromptBuilder()
    generation = builder.build(question="order_total", context=context)
    repair = builder.repair(
        question="order_total",
        context=context,
        answer="Respuesta sin cita.",
    )
    shared_rules = (
        "Toda afirmacion factual debe citar una fuente inline como [F1].",
        "Cada parrafo o bullet de la respuesta debe incluir al menos una cita inline.",
        "No infieras, no completes con conocimiento general y no inventes conclusiones.",
        "Responde de forma compacta y directa, sin conclusiones generales, "
        "recapitulaciones ni comentarios accesorios.",
        "La seccion 'Supuestos y limites' es opcional: incluyela solo para "
        "supuestos o limites explicitamente demostrados por las fuentes, con "
        "una cita inline en cada bullet; si no existen, omite la seccion.",
    )

    for rule in shared_rules:
        assert generation.count(rule) == 1
        assert repair.count(rule) == 1
    assert (
        "Corrige unicamente los problemas de soporte y citacion de la "
        "respuesta anterior."
    ) in repair


def test_repair_receives_safe_failure_categories_and_forbids_new_facts() -> None:
    context = ContextBuilder(
        token_budget=100,
        max_chunk_tokens=50,
        dedupe_min_hash_prefix=8,
    ).build((candidate("one", SHA_A, 0.9),))
    sensitive_claim = "detalle interno que no debe copiarse al diagnostico"
    repair = PromptBuilder().repair(
        question="order_total",
        context=context,
        answer="Respuesta anterior.",
        validation=CitationValidation(
            valid=False,
            missing_source_ids=("F9",),
            cited_source_ids=("F1",),
            unsupported_claims=(sensitive_claim, "otro claim"),
            contradiction_claims=("contradiccion sensible",),
            reason="detalle sensible",
        ),
    )

    assert "- missing_source_ids: 1" in repair
    assert "- unsupported_claims: 2" in repair
    assert "- contradiction_claims: 1" in repair
    assert "no_valid_citations" not in repair
    assert sensitive_claim not in repair
    assert "detalle sensible" not in repair
    assert "No agregues hechos, interpretaciones ni conclusiones nuevas" in repair
    assert "Conserva solo contenido respaldado" in repair


def ask_service(
    tmp_path,
    answer: str | BaseException | tuple[str | BaseException, ...],
) -> tuple[AskService, FakeLlm]:
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


def _with_input_budget(service: AskService, budget: int) -> AskService:
    return replace(
        service,
        settings=replace(
            service.settings,
            rag=replace(service.settings.rag, input_token_budget_est=budget),
        ),
    )


def _with_optimized_policy(service: AskService, budget: int = 1000) -> AskService:
    return replace(
        _with_input_budget(service, budget),
        context_builder=replace(
            service.context_builder,
            selection_policy="optimized_v1",
        ),
        settings=replace(
            service.settings,
            rag=replace(
                service.settings.rag,
                input_token_budget_est=budget,
                context_selection_policy="optimized_v1",
            ),
        ),
    )


@pytest.mark.parametrize("provider", ["ollama", "anthropic"])
def test_optimized_policy_supports_fake_providers_and_unicode(
    tmp_path,
    provider: str,
) -> None:
    service, fake_llm = ask_service(
        tmp_path,
        "order_total se selecciona desde dual [F1].",
    )
    fake_llm.provider = provider
    service = _with_optimized_policy(service)

    result = service.ask(
        "¿order_total ñ?",
        mode=RetrievalMode.KEYWORD,
        top_k=3,
        candidate_k=3,
        threshold=0,
        debug=True,
    )

    assert result.status is RagQueryStatus.COMPLETED
    assert len(fake_llm.prompts) == 1
    assert "¿order_total ñ?" in fake_llm.prompts[0]
    assert result.debug["observability"]["selection_policy"] == "optimized_v1"
    assert result.debug["prompt_composition"]["tokens_est_local"] <= 1000


def test_optimized_policy_preserves_no_llm_without_provider_call(tmp_path) -> None:
    service, fake_llm = ask_service(
        tmp_path,
        "esta respuesta no debe generarse [F1].",
    )
    service = _with_optimized_policy(service)

    result = service.ask(
        "order_total",
        mode=RetrievalMode.KEYWORD,
        top_k=3,
        candidate_k=3,
        threshold=0,
        no_llm=True,
        debug=True,
    )

    assert result.status is RagQueryStatus.COMPLETED
    assert result.no_llm is True
    assert fake_llm.prompts == []
    assert result.context.debug["selection_policy"] == "optimized_v1"


def test_input_budget_applies_to_complete_generation_prompt(tmp_path) -> None:
    service, fake_llm = ask_service(
        tmp_path,
        "order_total se selecciona desde dual [F1].",
    )
    service = _with_input_budget(service, 501)

    result = service.ask(
        "order_total",
        mode=RetrievalMode.KEYWORD,
        top_k=3,
        candidate_k=3,
        threshold=0,
        debug=True,
    )

    assert result.status is RagQueryStatus.COMPLETED
    assert len(fake_llm.prompts) == 1
    assert result.debug["prompt_composition"]["tokens_est_local"] <= 501
    budget = result.debug["input_budget"]
    assert budget["configured_tokens_est_local"] == 501
    assert budget["estimator_id"] == "chars4_v1"
    assert budget["fixed_overhead_tokens_est_local"] > 0
    assert budget["evidence_budget_tokens_est_local"] > 0
    assert budget["final_prompt_tokens_est_local"] == result.debug[
        "prompt_composition"
    ]["tokens_est_local"]
    assert budget["result"] == "fits"


def test_input_budget_returns_insufficient_without_calling_llm_when_overhead_does_not_fit(
    tmp_path,
) -> None:
    service, fake_llm = ask_service(
        tmp_path,
        "esta respuesta nunca debe solicitarse [F1].",
    )
    service = _with_input_budget(service, 501)

    result = service.ask(
        "order_total " + ("pregunta-muy-larga " * 180),
        mode=RetrievalMode.KEYWORD,
        top_k=3,
        candidate_k=3,
        threshold=0,
        debug=True,
    )

    assert result.status is RagQueryStatus.INSUFFICIENT_EVIDENCE
    assert result.no_llm is True
    assert fake_llm.prompts == []
    assert result.debug["input_budget"]["result"] == "fixed_overhead_exceeds_budget"
    assert result.debug["observability"]["generation"] is None
    assert result.debug["observability"]["input_budget"]["result"] == (
        "fixed_overhead_exceeds_budget"
    )


def test_repair_is_not_called_when_its_complete_prompt_exceeds_input_budget(
    tmp_path,
) -> None:
    invalid = "respuesta sin cita " + ("contenido " * 160)
    service, fake_llm = ask_service(
        tmp_path,
        (invalid, "order_total se selecciona desde dual [F1]."),
    )
    service = _with_input_budget(service, 501)

    result = service.ask(
        "order_total",
        mode=RetrievalMode.KEYWORD,
        top_k=3,
        candidate_k=3,
        threshold=0,
        debug=True,
    )

    assert result.status is RagQueryStatus.ERROR
    assert len(fake_llm.prompts) == 1
    assert result.debug["citation_repair_attempted"] is False
    assert result.debug["citation_repair_skipped_reason"] == "input_token_budget_est"
    assert result.debug["repair_outcome"] == {
        "triggered": True,
        "trigger_categories": ("no_valid_citations",),
        "trigger_counts": {"no_valid_citations": 1},
        "attempted": False,
        "succeeded": None,
        "result": "skipped_budget",
    }
    assert (
        result.debug["repair_prompt_composition"]["tokens_est_local"]
        > result.debug["input_budget"]["configured_tokens_est_local"]
    )
    assert result.debug["repair_input_budget"]["same_sources"] is True
    assert result.debug["repair_input_budget"]["result"] == (
        "insufficient_evidence_budget"
    )


def test_generation_and_repair_each_fit_the_configured_input_budget(tmp_path) -> None:
    service, fake_llm = ask_service(
        tmp_path,
        (
            "respuesta sin cita",
            "order_total se selecciona desde dual [F1].",
        ),
    )
    service = _with_input_budget(service, 1000)

    result = service.ask(
        "order_total",
        mode=RetrievalMode.KEYWORD,
        top_k=3,
        candidate_k=3,
        threshold=0,
        debug=True,
    )

    assert result.status is RagQueryStatus.COMPLETED
    assert len(fake_llm.prompts) == 2
    assert result.debug["prompt_composition"]["tokens_est_local"] <= 1000
    assert result.debug["repair_prompt_composition"]["tokens_est_local"] <= 1000
    assert result.debug["repair_input_budget"]["same_sources"] is True
    assert result.debug["repair_input_budget"]["result"] == "fits"


def test_repair_rebudgets_same_sources_when_generation_fills_input_budget() -> None:
    candidates = tuple(
        candidate(
            f"source-{index}",
            f"{index}" * 64,
            1.0 - (index / 10),
            document_id=index,
            content=(f"order_total evidencia fuente {index} " * 700),
        )
        for index in range(1, 5)
    )
    builder = ContextBuilder(
        token_budget=6000,
        max_chunk_tokens=1200,
        dedupe_min_hash_prefix=8,
        threshold=0,
        selection_policy="optimized_v1",
    )
    prompt_builder = PromptBuilder()
    generation_context, generation_budget = _build_context_for_input_budget(
        context_builder=builder,
        prompt_builder=prompt_builder,
        candidates=candidates,
        question="order_total",
        input_token_budget_est=4500,
        debug=True,
    )
    rejected_answer = "respuesta factual sin cita " * 55
    initial_repair = prompt_builder.compose_repair(
        question="order_total",
        context=generation_context,
        answer=rejected_answer,
    )

    repair_context, repair_composition, repair_budget = (
        _build_repair_context_for_input_budget(
            prompt_builder=prompt_builder,
            generation_context=generation_context,
            question="order_total",
            rejected_answer=rejected_answer,
            validation=CitationValidation(
                valid=False,
                unsupported_claims=("respuesta factual sin cita",),
                reason="afirmaciones no respaldadas",
            ),
            input_token_budget_est=4500,
        )
    )

    assert generation_budget["final_prompt_tokens_est_local"] <= 4500
    assert generation_budget["final_prompt_tokens_est_local"] >= 4400
    assert initial_repair.tokens_est_local > 4500
    assert repair_context is not None
    assert repair_composition.tokens_est_local <= 4500
    assert [source.source_id for source in repair_context.sources] == [
        source.source_id for source in generation_context.sources
    ]
    assert [source.candidate.chunk_id for source in repair_context.sources] == [
        source.candidate.chunk_id for source in generation_context.sources
    ]
    assert repair_budget["same_sources"] is True
    assert repair_budget["trimmed_evidence_tokens_est_local"] > 0
    assert repair_budget["result"] == "fits"


def test_ask_logs_success_without_prompt_or_response_content(
    tmp_path,
    ask_log_records,
) -> None:
    prompt_secret = "order_total"
    response_secret = "order_total se selecciona desde dual [F1]."
    service, _fake_llm = ask_service(tmp_path, response_secret)

    service.ask(
        prompt_secret,
        mode=RetrievalMode.KEYWORD,
        top_k=3,
        candidate_k=3,
        threshold=0,
    )

    messages = [record.getMessage() for record in ask_log_records]
    assert any("ask_llm_started stage=generation" in item for item in messages)
    assert any(
        "ask_llm_finished stage=generation" in item
        and "result=completed" in item
        and "response_chars=" in item
        and "duration_ms=" in item
        for item in messages
    )
    log_text = "\n".join(messages)
    assert "model=" in log_text
    assert "timeout_seconds=" in log_text
    assert "prompt_chars=" in log_text
    assert "prompt_tokens_est=" in log_text
    assert prompt_secret not in log_text
    assert response_secret not in log_text


def test_anthropic_labels_local_prompt_estimate_without_claiming_actual_usage(
    tmp_path,
    ask_log_records,
) -> None:
    service, fake_llm = ask_service(
        tmp_path,
        "order_total se selecciona desde dual [F1].",
    )
    fake_llm.provider = "anthropic"

    result = service.ask(
        "order_total",
        mode=RetrievalMode.KEYWORD,
        top_k=3,
        candidate_k=3,
        threshold=0,
        debug=True,
    )

    log_text = "\n".join(record.getMessage() for record in ask_log_records)
    assert "prompt_tokens_est_local=" in log_text
    assert " prompt_tokens_est=" not in log_text
    assert "prompt_tokens_est_local" in result.debug
    assert "prompt_tokens_est" not in result.debug
    assert result.debug["citation_coverage"]["cited_source_ids"] == ("F1",)
    assert result.debug["citation_coverage"]["uncited_selected_source_ids"] == ()


def test_ask_logs_timeout_during_initial_generation(
    tmp_path,
    ask_log_records,
) -> None:
    service, fake_llm = ask_service(
        tmp_path,
        LlmProviderError("OLLAMA_LLM_TIMEOUT: timeout inicial"),
    )

    with pytest.raises(LlmProviderError):
        service.ask(
            "order_total",
            mode=RetrievalMode.KEYWORD,
            top_k=3,
            candidate_k=3,
            threshold=0,
        )

    log_text = "\n".join(record.getMessage() for record in ask_log_records)
    assert "stage=generation" in log_text
    assert "result=timeout" in log_text
    assert "model=" in log_text
    assert "timeout_seconds=" in log_text
    assert "duration_ms=" in log_text
    assert "prompt_chars=" in log_text
    assert "prompt_tokens_est=" in log_text
    assert "stage=repair" not in log_text
    assert "timeout inicial" not in log_text
    with sqlite3.connect(tmp_path / "barbarion.db") as connection:
        status = connection.execute(
            "SELECT status FROM rag_queries ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
    assert status == "error"


def test_ask_logs_timeout_during_repair(tmp_path, ask_log_records) -> None:
    service, fake_llm = ask_service(
        tmp_path,
        (
            "Respuesta original sin cita.",
            LlmProviderError("OLLAMA_LLM_TIMEOUT: timeout reparacion"),
        ),
    )

    with pytest.raises(LlmProviderError):
        service.ask(
            "order_total",
            mode=RetrievalMode.KEYWORD,
            top_k=3,
            candidate_k=3,
            threshold=0,
        )

    messages = [record.getMessage() for record in ask_log_records]
    assert any(
        "stage=generation" in item and "result=completed" in item
        for item in messages
    )
    assert any(
        "stage=repair" in item
        and "result=timeout" in item
        and "duration_ms=" in item
        and "prompt_tokens_est=" in item
        for item in messages
    )
    assert "timeout reparacion" not in "\n".join(messages)
    with sqlite3.connect(tmp_path / "barbarion.db") as connection:
        status = connection.execute(
            "SELECT status FROM rag_queries ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
    assert status == "error"


def test_ask_marks_query_error_and_propagates_keyboard_interrupt(
    tmp_path,
    ask_log_records,
) -> None:
    service, _fake_llm = ask_service(tmp_path, KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        service.ask(
            "order_total",
            mode=RetrievalMode.KEYWORD,
            top_k=3,
            candidate_k=3,
            threshold=0,
        )

    messages = [record.getMessage() for record in ask_log_records]
    assert any("result=interrupted" in message for message in messages)
    assert not any("result=completed" in message for message in messages)
    with sqlite3.connect(tmp_path / "barbarion.db") as connection:
        row = connection.execute(
            "SELECT status, llm_ms FROM rag_queries ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row[0] == "error"
    assert row[1] is not None


@pytest.mark.parametrize(
    ("question", "no_llm", "expected_status"),
    [
        ("order_total", True, RagQueryStatus.COMPLETED),
        (
            "identificador_sintetico_totalmente_ausente",
            False,
            RagQueryStatus.INSUFFICIENT_EVIDENCE,
        ),
    ],
)
def test_ask_does_not_read_anthropic_key_before_generation(
    tmp_path,
    question: str,
    no_llm: bool,
    expected_status: RagQueryStatus,
) -> None:
    reads = 0

    def resolve_key() -> str | None:
        nonlocal reads
        reads += 1
        return None

    search_service = service_for(tmp_path)
    provider = AnthropicLlmProvider(
        model="claude-test",
        temperature=0.1,
        max_output_tokens=4096,
        _api_key_resolver=resolve_key,
    )
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
        llm_provider=provider,
        settings=search_service.settings,
    )

    result = service.ask(
        question,
        mode=RetrievalMode.KEYWORD,
        top_k=3,
        candidate_k=3,
        threshold=0,
        no_llm=no_llm,
    )

    assert result.status is expected_status
    assert reads == 0
    assert provider.usage_snapshot() is None


def test_ask_logs_citation_validation_reasons_without_response(
    tmp_path,
    ask_log_records,
) -> None:
    initial_secret = "respuesta_inicial_secreta"
    repair_secret = "respuesta_reparada_secreta"
    service, fake_llm = ask_service(
        tmp_path,
        (initial_secret, repair_secret),
    )
    service = replace(
        service,
        citation_validator=FakeCitationValidator(
            (
                CitationValidation(
                    valid=False,
                    cited_source_ids=("F1",),
                    unsupported_claims=("contenido no respaldado",),
                    contradiction_claims=("contenido contradictorio",),
                    reason="detalle sensible del rechazo",
                ),
                CitationValidation(valid=True, cited_source_ids=("F1",)),
            )
        ),
    )

    service.ask(
        "order_total",
        mode=RetrievalMode.KEYWORD,
        top_k=3,
        candidate_k=3,
        threshold=0,
    )

    messages = [record.getMessage() for record in ask_log_records]
    validation_logs = [
        item for item in messages if item.startswith("ask_citation_validation")
    ]
    assert len(validation_logs) == 2
    assert "stage=generation result=FAIL" in validation_logs[0]
    assert "reasons=unsupported_claims,contradiction_claims" in validation_logs[0]
    assert "unsupported_claims_count=1" in validation_logs[0]
    assert "contradiction_claims_count=1" in validation_logs[0]
    assert "stage=repair result=PASS reasons=ok" in validation_logs[1]
    assert "- unsupported_claims: 1" in fake_llm.prompts[1]
    assert "- contradiction_claims: 1" in fake_llm.prompts[1]
    repair_logs = [
        item for item in messages if item.startswith("ask_citation_repair")
    ]
    assert repair_logs == [
        "ask_citation_repair triggered=True attempted=True result=succeeded "
        "causes=unsupported_claims,contradiction_claims"
    ]
    log_text = "\n".join(messages)
    assert initial_secret not in log_text
    assert repair_secret not in log_text
    assert "detalle sensible del rechazo" not in log_text
    assert "contenido no respaldado" not in log_text
    assert "contenido contradictorio" not in log_text


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
    assert "- [F1] pkg/demo.sql" in result.answer


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
    assert "- [F1] pkg/demo.sql" in result.answer


def test_ask_repairs_llm_answer_without_inline_citation(tmp_path) -> None:
    service, fake_llm = ask_service(
        tmp_path,
        ("Conclusion sin cita.", "order_total se selecciona desde dual [F1]."),
    )

    result = service.ask(
        "order_total",
        mode=RetrievalMode.KEYWORD,
        top_k=3,
        candidate_k=3,
        threshold=0,
        debug=True,
    )

    assert result.citations_valid is True
    assert result.status == RagQueryStatus.COMPLETED
    assert result.answer == "order_total se selecciona desde dual [F1]."
    assert len(fake_llm.prompts) == 2
    assert "Respuesta original:\nConclusion sin cita." in fake_llm.prompts[1]
    assert "Usa solo estos IDs de fuente existentes: [F1]." in fake_llm.prompts[1]
    assert "No generes codigo ni completes codigo" in fake_llm.prompts[1]
    assert result.debug["citation_repair_attempted"] is True
    assert result.debug["citation_repair_valid"] is True
    assert result.debug["repair_outcome"]["trigger_categories"] == (
        "no_valid_citations",
    )
    assert result.debug["repair_outcome"]["attempted"] is True
    assert result.debug["repair_outcome"]["succeeded"] is True
    assert result.debug["repair_outcome"]["result"] == "succeeded"
    assert result.debug["observability"]["repair_outcome"] == (
        result.debug["repair_outcome"]
    )


def test_ask_falls_back_when_citation_repair_is_still_invalid(tmp_path) -> None:
    service, fake_llm = ask_service(
        tmp_path,
        ("Conclusion sin cita.", "Conclusion todavia sin cita."),
    )

    result = service.ask(
        "order_total",
        mode=RetrievalMode.KEYWORD,
        top_k=3,
        candidate_k=3,
        threshold=0,
        debug=True,
    )

    assert result.citations_valid is False
    assert result.status == RagQueryStatus.ERROR
    assert len(fake_llm.prompts) == 2
    assert "no pudo ser reparada automaticamente" in result.answer
    assert "Ejecute el mismo comando con `--debug`" in result.answer
    assert "- [F1] pkg/demo.sql" in result.answer
    assert result.debug["citation_repair_attempted"] is True
    assert result.debug["citation_repair_valid"] is False
    assert result.debug["repair_outcome"]["result"] == "failed_validation"
    assert result.debug["repair_outcome"]["succeeded"] is False


def test_ask_repairs_valid_citation_with_unsupported_content_to_insufficient_evidence(
    tmp_path,
) -> None:
    service, fake_llm = ask_service(
        tmp_path,
        (
            "customer_tax se calcula con una regla externa [F1].",
            "Evidencia insuficiente: falta customer_tax en la evidencia recuperada [F1].",
        ),
    )

    result = service.ask(
        "customer_tax",
        mode=RetrievalMode.HYBRID,
        top_k=3,
        candidate_k=3,
        threshold=0,
        debug=True,
    )

    assert result.citations_valid is True
    assert result.status == RagQueryStatus.COMPLETED
    assert "Evidencia insuficiente" in result.answer
    assert len(fake_llm.prompts) == 2
    assert result.debug["validation"]["result"] == "FAIL"
    assert result.debug["citation_repair_attempted"] is True
    assert result.debug["citation_repair_valid"] is True


def test_ask_accepts_llm_answer_with_valid_inline_citation(tmp_path) -> None:
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
    )

    assert result.citations_valid is True
    assert result.status == RagQueryStatus.COMPLETED
    assert result.answer == "order_total se selecciona desde dual [F1]."


def test_ask_sends_exact_prompt_produced_by_its_prompt_builder(tmp_path) -> None:
    """Caracteriza el seam reutilizado por el benchmark sin cambiar `ask`."""
    service, fake_llm = ask_service(
        tmp_path,
        "order_total se selecciona desde dual [F1].",
    )

    result = service.ask(
        "order_total",
        mode=RetrievalMode.KEYWORD,
        top_k=3,
        candidate_k=3,
        threshold=0,
    )

    assert fake_llm.prompts == [
        service.prompt_builder.build(
            question="order_total",
            context=result.context,
        )
    ]


def test_ask_debug_reports_size_metrics_without_context_dump(tmp_path) -> None:
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

    assert result.debug["sources"] == 1
    assert result.debug["context_chars"] > 0
    assert result.debug["context_tokens_est"] > 0
    assert result.debug["prompt_chars"] > result.debug["context_chars"]
    assert result.debug["llm_timeout_seconds"] > 0
    assert result.debug["truncated_sources"] == 0
    observability = result.debug["observability"]
    assert observability["schema_version"] == "h31_observability_v1"
    assert observability["selection_policy"] == "baseline_v1"
    assert observability["estimator_id"] == "chars4_v1"
    assert observability["generation"]["tokens_est_local"] == result.debug[
        "prompt_composition"
    ]["tokens_est_local"]
    assert observability["provider_usage"] is None
    assert observability["repair_outcome"]["result"] == "not_needed"
    assert "order_total :=" not in str(dict(result.debug))


def test_ask_debug_does_not_persist_prompts_or_responses(tmp_path) -> None:
    service, _fake_llm = ask_service(
        tmp_path,
        "order_total se selecciona desde dual [F1] secret=visible",
    )

    result = service.ask(
        "order_total",
        mode=RetrievalMode.KEYWORD,
        top_k=3,
        candidate_k=3,
        threshold=0,
        debug=True,
    )

    assert "secret=visible" in result.debug["llm_response"]
    assert "secret=visible" not in str(result.debug["observability"])
    with sqlite3.connect(tmp_path / "barbarion.db") as connection:
        dump = "\n".join(connection.iterdump())
    assert "secret=visible" not in dump
    assert "Respuesta candidata rechazada" not in dump


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
