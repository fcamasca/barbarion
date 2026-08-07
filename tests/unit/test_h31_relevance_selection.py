from __future__ import annotations

import hashlib

from barbarion.application.rag import (
    ContextBuilder,
    _select_ask_candidates_relevance_first,
)
from barbarion.domain.rag import RetrievalCandidate


def _candidate(
    chunk_id: str,
    score: float,
    *,
    content: str | None = None,
    document_id: int = 1,
    ordinal: int = 0,
    evidence_kind: str | None = None,
) -> RetrievalCandidate:
    text = content or f"evidencia de {chunk_id}"
    source: dict[str, object] = {
        "document_id": document_id,
        "ordinal": ordinal,
        "relative_path": f"synthetic/{chunk_id}.txt",
        "content": text,
    }
    if evidence_kind is not None:
        source["evidence_kind"] = evidence_kind
    return RetrievalCandidate(
        chunk_id=chunk_id,
        content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        combined_score=score,
        source=source,
    )


def test_global_relevance_prevents_structured_precedence_from_spending_top_k() -> None:
    structured = (
        _candidate("structured-low", 0.20, evidence_kind="structured_symbol"),
    )
    chunks = (
        _candidate("chunk-high", 0.95, document_id=2),
        _candidate("chunk-medium", 0.80, document_id=3),
    )

    selected, decisions = _select_ask_candidates_relevance_first(
        structured,
        chunks,
        limit=2,
        dedupe_min_hash_prefix=16,
    )

    assert [candidate.chunk_id for candidate in selected] == [
        "chunk-high",
        "chunk-medium",
    ]
    by_chunk = {decision["chunk_id"]: decision for decision in decisions}
    assert by_chunk["structured-low"]["reasons"] == ("top_k",)
    assert by_chunk["chunk-high"]["reasons"] == ("relevance",)


def test_relevance_selection_deduplicates_before_spending_slots() -> None:
    shared = "contenido exactamente repetido"
    selected, decisions = _select_ask_candidates_relevance_first(
        (),
        (
            _candidate("original", 0.90, content=shared),
            _candidate("copy", 0.85, content=shared, document_id=2),
            _candidate("useful", 0.80, document_id=3),
        ),
        limit=2,
        dedupe_min_hash_prefix=16,
    )

    assert [candidate.chunk_id for candidate in selected] == ["original", "useful"]
    by_chunk = {decision["chunk_id"]: decision for decision in decisions}
    assert by_chunk["copy"]["reasons"] == ("duplicate_content",)


def test_relevance_ties_are_broken_deterministically_by_chunk_id() -> None:
    candidates = (
        _candidate("zeta", 0.75),
        _candidate("alpha", 0.75, document_id=2),
    )

    first, _ = _select_ask_candidates_relevance_first(
        (), candidates, limit=2, dedupe_min_hash_prefix=16
    )
    second, _ = _select_ask_candidates_relevance_first(
        (), tuple(reversed(candidates)), limit=2, dedupe_min_hash_prefix=16
    )

    assert [item.chunk_id for item in first] == ["alpha", "zeta"]
    assert [item.chunk_id for item in second] == ["alpha", "zeta"]


def test_optimized_context_spends_budget_by_relevance_then_orders_for_presentation() -> None:
    candidates = (
        _candidate("document-first", 0.20, document_id=1, content="a" * 80),
        _candidate("relevant", 0.95, document_id=2, content="b" * 80),
    )
    baseline = ContextBuilder(
        token_budget=45,
        max_chunk_tokens=100,
        dedupe_min_hash_prefix=16,
        selection_policy="baseline_v1",
    ).build(candidates, debug=True)
    optimized = ContextBuilder(
        token_budget=45,
        max_chunk_tokens=100,
        dedupe_min_hash_prefix=16,
        selection_policy="optimized_v1",
    ).build(candidates, debug=True)

    assert baseline.sources[0].candidate.chunk_id == "document-first"
    assert optimized.sources[0].candidate.chunk_id == "relevant"
    assert optimized.debug["selection_policy"] == "optimized_v1"


def test_presentation_order_does_not_change_optimized_selection() -> None:
    candidates = (
        _candidate("high-late-document", 0.95, document_id=2),
        _candidate("low-first-document", 0.20, document_id=1),
    )
    result = ContextBuilder(
        token_budget=500,
        max_chunk_tokens=100,
        dedupe_min_hash_prefix=16,
        selection_policy="optimized_v1",
    ).build(candidates)

    assert [source.candidate.chunk_id for source in result.sources] == [
        "low-first-document",
        "high-late-document",
    ]
