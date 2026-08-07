"""Caracterizacion previa al Privacy Preflight H3.2.

Estas pruebas congelan la frontera generativa vigente antes de modificar el
pipeline. T01 no introduce comportamiento productivo.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace

from barbarion.application.rag import (
    AskService,
    CitationValidator,
    ContextBuilder,
    PromptBuilder,
)
from barbarion.application.privacy import (
    PrivacyPreflightService,
    UnavailableAccountPrivacyVerifier,
)
from barbarion.domain.privacy import PrivacyPolicy
from barbarion.domain.rag import RagQueryStatus, RetrievalMode
from tests.unit.test_rag_search_service import service_for


class RecordingLlm:
    """Provider unico que conserva prompts y entrega respuestas controladas."""

    provider = "synthetic"
    model = "baseline-v1"

    def __init__(self, *answers: str) -> None:
        self.answers = answers
        self.prompts: list[str] = []

    def generate(self, *, prompt: str, timeout_seconds: float) -> str:
        assert timeout_seconds > 0
        self.prompts.append(prompt)
        return self.answers[len(self.prompts) - 1]


def _service(tmp_path, provider: RecordingLlm) -> AskService:
    search = service_for(tmp_path)
    settings = replace(
        search.settings,
        llm=replace(search.settings.llm, execution="local"),
        rag=replace(search.settings.rag, input_token_budget_est=4500),
    )
    return AskService(
        search_service=search,
        context_builder=ContextBuilder(
            token_budget=200,
            max_chunk_tokens=100,
            dedupe_min_hash_prefix=8,
            threshold=0,
        ),
        prompt_builder=PromptBuilder(),
        citation_validator=CitationValidator(),
        llm_provider=provider,
        settings=settings,
        privacy_preflight=PrivacyPreflightService(
            policy=PrivacyPolicy(),
            policy_source=None,
            account_verifier=UnavailableAccountPrivacyVerifier(),
        ),
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_h32_tp001_generation_crosses_provider_boundary_once(tmp_path) -> None:
    """Una respuesta valida realiza una sola llamada con el prompt H3.1."""
    provider = RecordingLlm("order_total se selecciona desde dual [F1].")
    service = _service(tmp_path, provider)

    result = service.ask(
        "order_total",
        mode=RetrievalMode.KEYWORD,
        top_k=3,
        candidate_k=3,
        threshold=0,
        debug=True,
    )

    assert result.status is RagQueryStatus.COMPLETED
    assert result.citations_valid is True
    assert len(provider.prompts) == 1
    assert provider.prompts[0] == result.debug["prompt"]
    assert _sha256(provider.prompts[0]) == (
        "bd711053422d72f510344843a12a7ea3d37648794ade96b3e628acdf754add3e"
    )
    assert result.debug["prompt_composition"]["tokens_est_local"] <= 4500
    assert result.debug["citation_repair_attempted"] is False


def test_h32_tp001_repair_reuses_same_provider_without_fallback(tmp_path) -> None:
    """Generation y repair son las dos unicas llamadas al mismo provider."""
    provider = RecordingLlm(
        "Conclusion inicial sin cita.",
        "order_total se selecciona desde dual [F1].",
    )
    service = _service(tmp_path, provider)

    result = service.ask(
        "order_total",
        mode=RetrievalMode.KEYWORD,
        top_k=3,
        candidate_k=3,
        threshold=0,
        debug=True,
    )

    assert result.status is RagQueryStatus.COMPLETED
    assert result.citations_valid is True
    assert len(provider.prompts) == 2
    assert _sha256(provider.prompts[0]) == (
        "bd711053422d72f510344843a12a7ea3d37648794ade96b3e628acdf754add3e"
    )
    assert _sha256(provider.prompts[1]) == (
        "22393ad2298e506b62c1888e7f62b54fa8c5db3089c631b611d6986014099eb7"
    )
    assert provider.prompts[1] == result.debug["repair_prompt"]
    assert result.debug["citation_repair_attempted"] is True
    assert result.debug["citation_repair_valid"] is True
    assert result.debug["repair_prompt_composition"]["tokens_est_local"] <= 4500


def test_h32_tp002_local_returns_never_cross_provider_boundary(tmp_path) -> None:
    """No-LLM e insuficiencia retornan antes de cualquier generacion."""
    no_llm_provider = RecordingLlm("no debe usarse")
    no_llm_path = tmp_path / "no-llm"
    no_llm_path.mkdir()
    no_llm_service = _service(no_llm_path, no_llm_provider)

    no_llm = no_llm_service.ask(
        "order_total",
        mode=RetrievalMode.KEYWORD,
        top_k=3,
        candidate_k=3,
        threshold=0,
        no_llm=True,
        debug=True,
    )

    insufficient_provider = RecordingLlm("no debe usarse")
    insufficient_path = tmp_path / "insufficient"
    insufficient_path.mkdir()
    insufficient_service = _service(insufficient_path, insufficient_provider)
    insufficient = insufficient_service.ask(
        "identificador_sintetico_totalmente_ausente",
        mode=RetrievalMode.KEYWORD,
        top_k=3,
        candidate_k=3,
        threshold=0,
        debug=True,
    )

    assert no_llm.status is RagQueryStatus.COMPLETED
    assert no_llm.no_llm is True
    assert no_llm_provider.prompts == []
    assert insufficient.status is RagQueryStatus.INSUFFICIENT_EVIDENCE
    assert insufficient.no_llm is True
    assert insufficient_provider.prompts == []
