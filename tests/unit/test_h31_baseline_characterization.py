"""Caracterizacion reproducible de H3.1-T01 sin optimizar el pipeline."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pytest

from barbarion.application.rag import (
    CitationValidator,
    ContextBuilder,
    PromptBuilder,
    _ask_debug_payload,
    _merge_ask_candidates,
)
from barbarion.config import load_settings
from barbarion.domain.rag import (
    RetrievalCandidate,
    RetrievalMode,
    SearchRequest,
    combine_hybrid_candidates,
)
from tests.unit.test_rag_search_service import service_for


BASELINE_PATH = Path("reports/h31/baseline-v1.json")
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


def _baseline() -> dict[str, object]:
    """Carga el manifiesto versionado que estas pruebas deben congelar."""
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _candidate(
    chunk_id: str,
    sha: str,
    score: float,
    *,
    document_id: int = 1,
    ordinal: int = 0,
    content: str = "contenido sintetico",
    **source: object,
) -> RetrievalCandidate:
    """Construye evidencia sintetica sin nombres de sistemas privados."""
    return RetrievalCandidate(
        chunk_id=chunk_id,
        content_sha256=sha,
        combined_score=score,
        source={
            "document_id": document_id,
            "ordinal": ordinal,
            "relative_path": f"synthetic/doc-{document_id}.txt",
            "content": content,
            **source,
        },
    )


def _characterized_context():
    baseline = _baseline()["context_characterization"]
    builder = ContextBuilder(
        token_budget=baseline["token_budget_est_local"],
        max_chunk_tokens=baseline["max_chunk_tokens_est_local"],
        dedupe_min_hash_prefix=8,
        threshold=0.2,
    )
    return builder.build(
        (
            _candidate("highest", SHA_A, 0.95, document_id=2, ordinal=1, content="A" * 24),
            _candidate("document-first", SHA_B, 0.60, document_id=1, content="B" * 24),
            _candidate("duplicate", SHA_A, 0.90, document_id=3, content="A" * 24),
            _candidate("below", SHA_C, 0.10, document_id=0),
        ),
        debug=True,
    )


def test_baseline_manifest_is_explicitly_non_optimized() -> None:
    baseline = _baseline()

    assert baseline["baseline_id"] == "h31-baseline-v1"
    assert baseline["status"] == "characterized-not-optimized"
    assert baseline["historical_h12_observation"]["exact_component_breakdown_available"] is False
    assert baseline["optimization"] == {
        "enabled": False,
        "new_budget": None,
        "overlap_trimming": False,
        "relevance_first_selection": False,
    }


def test_baseline_freezes_effective_defaults(tmp_path: Path) -> None:
    baseline = _baseline()["defaults"]
    settings = load_settings(environ={}, cwd=tmp_path)

    assert {
        "mode": settings.retrieval.mode,
        "top_k": settings.retrieval.top_k,
        "candidate_k": settings.retrieval.candidate_k,
        "similarity_threshold": settings.retrieval.similarity_threshold,
        "vector_weight": settings.retrieval.vector_weight,
        "keyword_weight": settings.retrieval.keyword_weight,
    } == baseline["retrieval"]
    assert {
        "context_token_budget": settings.rag.context_token_budget,
        "max_chunk_tokens": settings.rag.max_chunk_tokens,
        "dedupe_min_hash_prefix": settings.rag.dedupe_min_hash_prefix,
        "include_snippets": settings.rag.include_snippets,
    } == baseline["rag"]


@pytest.mark.parametrize("mode", tuple(RetrievalMode))
def test_baseline_characterizes_retrieval_modes(
    tmp_path: Path,
    mode: RetrievalMode,
) -> None:
    baseline = _baseline()["retrieval_characterization"]
    response = service_for(tmp_path).search(
        SearchRequest(
            query="order_total",
            mode=mode,
            top_k=3,
            candidate_k=3,
            vector_weight=0.7,
            keyword_weight=0.3,
            debug=True,
        )
    )

    expected = baseline[f"{mode.value}_order"]
    assert [candidate.chunk_id for candidate in response.candidates] == expected
    if mode is RetrievalMode.SEMANTIC:
        assert all(candidate.vector_score is not None for candidate in response.candidates)
    elif mode is RetrievalMode.KEYWORD:
        assert all(candidate.keyword_score is not None for candidate in response.candidates)
    else:
        assert len(response.candidates) == len(
            {candidate.chunk_id for candidate in response.candidates}
        )
        assert response.candidates[0].vector_score is not None
        assert response.candidates[0].keyword_score is not None


def test_baseline_freezes_hybrid_fusion_and_structured_precedence() -> None:
    vector = (
        RetrievalCandidate("shared", SHA_A, 0.8, vector_score=0.8),
        RetrievalCandidate("vector-only", SHA_B, 0.6, vector_score=0.6),
    )
    keyword = (
        RetrievalCandidate("shared", SHA_A, 0.7, keyword_score=0.7),
        RetrievalCandidate("keyword-only", SHA_C, 0.9, keyword_score=0.9),
    )
    hybrid = combine_hybrid_candidates(
        vector,
        keyword,
        vector_weight=0.7,
        keyword_weight=0.3,
        top_k=3,
    )

    assert [candidate.chunk_id for candidate in hybrid] == [
        "shared",
        "keyword-only",
        "vector-only",
    ]
    assert hybrid[0].combined_score == pytest.approx(0.7)
    assert hybrid[1].combined_score == pytest.approx(0.3)
    assert hybrid[2].combined_score == pytest.approx(0.0)

    structured = (
        _candidate("structured", SHA_D, 0.4, evidence_kind="structured_symbol"),
    )
    chunks = (
        _candidate("high-chunk", SHA_C, 0.99),
        _candidate("structured", SHA_D, 0.8),
    )
    merged = _merge_ask_candidates(structured, chunks, limit=2)

    assert [candidate.chunk_id for candidate in merged] == _baseline()[
        "ask_merge_characterization"
    ]["output"]


def test_baseline_freezes_context_order_dedupe_truncation_and_budget() -> None:
    baseline = _baseline()["context_characterization"]
    context = _characterized_context()

    assert [source.candidate.chunk_id for source in context.sources] == baseline[
        "selected_order"
    ]
    assert list(context.omitted) == baseline["omitted"]
    assert context.token_estimate == baseline["rendered_context_tokens_est_local"]
    assert len(context.rendered_context) == baseline["rendered_context_chars"]
    assert context.debug["truncated_sources"] == baseline["truncated_sources"]
    assert hashlib.sha256(context.rendered_context.encode("utf-8")).hexdigest() == baseline[
        "rendered_context_sha256"
    ]
    assert context.token_estimate <= baseline["token_budget_est_local"]


def test_baseline_freezes_generation_repair_citations_and_debug(
    tmp_path: Path,
) -> None:
    baseline = _baseline()
    context = _characterized_context()
    builder = PromptBuilder()
    prompt_data = baseline["prompt_characterization"]
    generation = builder.build(question=prompt_data["question"], context=context)
    repair = builder.repair(
        question=prompt_data["question"],
        context=context,
        answer="Respuesta sin cita.",
    )

    assert len(generation) == prompt_data["generation_chars"]
    assert len(repair) == prompt_data["repair_chars"]
    assert hashlib.sha256(generation.encode("utf-8")).hexdigest() == prompt_data[
        "generation_sha256"
    ]
    assert hashlib.sha256(repair.encode("utf-8")).hexdigest() == prompt_data[
        "repair_sha256"
    ]
    assert context.rendered_context in generation
    assert context.rendered_context in repair
    assert "Respuesta original:\nRespuesta sin cita." in repair

    validation = CitationValidator().validate(
        "Respuesta con fuente desconocida [F9].",
        context,
        question=prompt_data["question"],
    )
    assert validation.valid is False
    assert validation.missing_source_ids == ("F9",)

    search = service_for(tmp_path).search(
        SearchRequest(
            query="order_total",
            mode=RetrievalMode.HYBRID,
            top_k=3,
            candidate_k=3,
            debug=True,
        )
    )
    debug = _ask_debug_payload(
        started=time.monotonic(),
        search=search,
        context=context,
        prompt=generation,
        timeout_seconds=120.0,
    )
    assert set(baseline["debug_characterization"]["size_metrics"]).issubset(debug)
    assert debug["context_chars"] == len(context.rendered_context)
    assert debug["context_tokens_est"] == context.token_estimate
    assert debug["prompt_chars"] == len(generation)


def test_historical_observation_is_aggregate_and_arithmetically_consistent() -> None:
    observation = _baseline()["historical_h12_observation"]

    assert observation["provider_input_tokens"] + observation["provider_output_tokens"] == observation[
        "provider_total_tokens"
    ]
    assert observation["provider_input_tokens"] - observation[
        "prompt_tokens_est_local"
    ] == observation["input_difference_real_minus_estimate"]
    assert observation["exact_component_breakdown_available"] is False
