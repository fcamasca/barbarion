from __future__ import annotations

import hashlib
import json
from pathlib import Path

from barbarion.application.rag import (
    ContextBuilder,
    _merge_ask_candidates,
    _select_ask_candidates_relevance_first,
)
from barbarion.domain.rag import RetrievalCandidate
from barbarion.domain.rag import SymbolMetadata


ROOT = Path(__file__).resolve().parents[2]


def _candidate(
    chunk_id: str,
    score: float,
    *,
    content: str | None = None,
    document_id: int = 1,
    ordinal: int = 0,
    evidence_kind: str | None = None,
    symbol_name: str | None = None,
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
        metadata=SymbolMetadata(symbol_name=symbol_name),
        source=source,
    )


def _missing_candidate(chunk_id: str, score: float) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id,
        content_sha256=hashlib.sha256(chunk_id.encode("utf-8")).hexdigest(),
        combined_score=score,
        source={"relative_path": f"synthetic/{chunk_id}.txt"},
    )


def test_family_relative_ranking_does_not_compare_absolute_cross_family_scores() -> None:
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
        "structured-low",
    ]
    by_chunk = {decision["chunk_id"]: decision for decision in decisions}
    assert by_chunk["structured-low"]["combined_score"] == 0.20
    assert by_chunk["structured-low"]["selection_relative_score"] == 1.0
    assert by_chunk["structured-low"]["selection_family"] == "structured"
    assert by_chunk["chunk-medium"]["reasons"] == ("top_k",)
    assert by_chunk["chunk-high"]["reasons"] == ("relevance",)


def test_mixed_benchmark_keeps_specific_structured_evidence_among_strong_chunks() -> None:
    benchmark = json.loads(
        (ROOT / "tests/fixtures/h31_mixed_family_benchmark.json").read_text(
            encoding="utf-8"
        )
    )
    assert benchmark["license"] == "synthetic-for-barbarion"
    structured = tuple(
        _candidate(
            item["chunk_id"],
            item["score"],
            content=item["content"],
            evidence_kind="structured_symbol",
        )
        for item in benchmark["structured"]
    )
    chunks = tuple(
        _candidate(
            item["chunk_id"],
            item["score"],
            content=item["content"],
            document_id=index + 1,
        )
        for index, item in enumerate(benchmark["chunks"])
    )

    selected, _ = _select_ask_candidates_relevance_first(
        structured,
        chunks,
        limit=benchmark["top_k"],
        dedupe_min_hash_prefix=16,
    )

    assert benchmark["expected_chunk_id"] in {
        candidate.chunk_id for candidate in selected
    }
    assert next(
        candidate for candidate in selected
        if candidate.chunk_id == benchmark["expected_chunk_id"]
    ).combined_score == 0.526


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


def test_missing_content_does_not_spend_top_k_and_valid_candidate_backfills() -> None:
    selected, decisions = _select_ask_candidates_relevance_first(
        (),
        (
            _missing_candidate("orphan-high", 0.95),
            _candidate("valid-lower", 0.80),
        ),
        limit=1,
        dedupe_min_hash_prefix=16,
    )

    assert [candidate.chunk_id for candidate in selected] == ["valid-lower"]
    by_chunk = {decision["chunk_id"]: decision for decision in decisions}
    assert by_chunk["orphan-high"] == {
        "chunk_id": "orphan-high",
        "action": "omitted",
        "reasons": ("missing_content",),
        "combined_score": 0.95,
        "evidence_kind": None,
    }


def test_multiple_missing_and_exact_duplicate_backfill_deterministically() -> None:
    shared = "contenido sintetico compartido"
    candidates = (
        _missing_candidate("orphan-z", 0.99),
        _missing_candidate("orphan-a", 0.99),
        _candidate("original", 0.90, content=shared),
        _candidate("copy", 0.85, content=shared, document_id=2),
        _candidate("useful", 0.80, document_id=3),
    )

    selected, decisions = _select_ask_candidates_relevance_first(
        (), candidates, limit=2, dedupe_min_hash_prefix=16
    )

    assert [candidate.chunk_id for candidate in selected] == ["original", "useful"]
    by_chunk = {decision["chunk_id"]: decision for decision in decisions}
    assert by_chunk["orphan-a"]["reasons"] == ("missing_content",)
    assert by_chunk["orphan-z"]["reasons"] == ("missing_content",)
    assert by_chunk["copy"]["reasons"] == ("duplicate_content",)


def test_all_missing_content_returns_no_selection_with_traceability() -> None:
    selected, decisions = _select_ask_candidates_relevance_first(
        (),
        (
            _missing_candidate("orphan-b", 0.80),
            _missing_candidate("orphan-a", 0.80),
        ),
        limit=1,
        dedupe_min_hash_prefix=16,
    )

    assert selected == ()
    assert [decision["chunk_id"] for decision in decisions] == [
        "orphan-b",
        "orphan-a",
    ]
    assert all(
        decision["reasons"] == ("missing_content",) for decision in decisions
    )


def test_baseline_selection_keeps_legacy_missing_content_behavior() -> None:
    merged = _merge_ask_candidates(
        (),
        (
            _missing_candidate("orphan-high", 0.95),
            _candidate("valid-lower", 0.80),
        ),
        limit=1,
    )

    assert [candidate.chunk_id for candidate in merged] == ["orphan-high"]
    result = ContextBuilder(
        token_budget=100,
        max_chunk_tokens=50,
        dedupe_min_hash_prefix=16,
        selection_policy="baseline_v1",
    ).build(merged)
    assert result.omitted == (
        {"chunk_id": "orphan-high", "reason": "missing_content"},
    )


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


def test_exact_identifier_wins_tied_structured_candidates_under_mixed_budget() -> None:
    question = "como se calcula PROV_INT_DIA_GOMEF y que variables intervienen"
    related = (
        _candidate(
            "structured-related-z",
            0.7199344685007878,
            content="z" * 80,
            evidence_kind="structured_symbol",
            symbol_name="mci_variables.prov_int_acum_mes_ant_gomef.1",
        ),
        _candidate(
            "structured-exact",
            0.7199344685007878,
            content="e" * 80,
            evidence_kind="structured_symbol",
            symbol_name="mci_variables.prov_int_dia_gomef.1",
        ),
        _candidate(
            "structured-related-a",
            0.7199344685007878,
            content="a" * 80,
            evidence_kind="structured_symbol",
            symbol_name="mci_variables.prov_int_acum_dia_ajust_gomef.1",
        ),
    )
    chunks = (
        _candidate("chunk-strong", 0.95, content="c" * 80, document_id=2),
        _candidate("chunk-second", 0.80, content="d" * 80, document_id=3),
    )

    first, first_decisions = _select_ask_candidates_relevance_first(
        related,
        chunks,
        limit=4,
        dedupe_min_hash_prefix=16,
        question=question,
    )
    second, second_decisions = _select_ask_candidates_relevance_first(
        tuple(reversed(related)),
        tuple(reversed(chunks)),
        limit=4,
        dedupe_min_hash_prefix=16,
        question=question,
    )

    assert [candidate.chunk_id for candidate in first] == [
        "structured-exact",
        "chunk-strong",
        "chunk-second",
        "structured-related-a",
    ]
    assert [candidate.chunk_id for candidate in second] == [
        "structured-exact",
        "chunk-strong",
        "chunk-second",
        "structured-related-a",
    ]
    for decisions in (first_decisions, second_decisions):
        by_chunk = {decision["chunk_id"]: decision for decision in decisions}
        assert by_chunk["structured-exact"]["selection_exact_identifier_match"] is True
        assert by_chunk["structured-related-a"]["selection_family_rank"] == 1
        assert by_chunk["structured-related-z"]["selection_family_rank"] == 1
        assert (
            by_chunk["structured-related-a"]["selection_relative_score"]
            == by_chunk["structured-related-z"]["selection_relative_score"]
        )

    context = ContextBuilder(
        token_budget=60,
        max_chunk_tokens=100,
        dedupe_min_hash_prefix=16,
        selection_policy="optimized_v1",
    ).build(first, debug=True)
    assert [source.candidate.chunk_id for source in context.sources] == [
        "structured-exact"
    ]
    assert {item["chunk_id"] for item in context.omitted} == {
        "chunk-strong",
        "chunk-second",
        "structured-related-a",
    }


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


def test_backfilled_candidates_still_respect_insufficient_budget() -> None:
    selected, _ = _select_ask_candidates_relevance_first(
        (),
        (
            _missing_candidate("orphan", 0.99),
            _candidate("valid", 0.80, content="x" * 80),
        ),
        limit=1,
        dedupe_min_hash_prefix=16,
    )

    result = ContextBuilder(
        token_budget=1,
        max_chunk_tokens=100,
        dedupe_min_hash_prefix=16,
        selection_policy="optimized_v1",
    ).build(selected, debug=True)

    assert result.sources == ()
    assert result.omitted == ({"chunk_id": "valid", "reason": "budget"},)


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
