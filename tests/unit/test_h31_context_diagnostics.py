from __future__ import annotations

import hashlib

from barbarion.application.rag import ContextBuilder
from barbarion.domain.rag import RetrievalCandidate


def _candidate(
    chunk_id: str,
    content: str,
    *,
    document_id: int = 1,
    ordinal: int = 0,
    score: float = 0.9,
    start_line: int | None = None,
    end_line: int | None = None,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id,
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        combined_score=score,
        source={
            "document_id": document_id,
            "ordinal": ordinal,
            "relative_path": f"synthetic/{chunk_id}.txt",
            "content": content,
            "start_line": start_line,
            "end_line": end_line,
        },
    )


def _builder(*, threshold: float = 0.0, budget: int = 6000) -> ContextBuilder:
    return ContextBuilder(
        token_budget=budget,
        max_chunk_tokens=1200,
        dedupe_min_hash_prefix=16,
        threshold=threshold,
    )


def test_report_only_diagnostics_do_not_change_context_or_selection() -> None:
    candidates = (
        _candidate("a", "inicio y evidencia compartida", ordinal=0),
        _candidate("b", "evidencia compartida y final", ordinal=1),
    )

    normal = _builder().build(candidates, debug=False)
    diagnosed = _builder().build(candidates, debug=True)

    assert diagnosed.sources == normal.sources
    assert diagnosed.omitted == normal.omitted
    assert diagnosed.rendered_context == normal.rendered_context
    assert diagnosed.token_estimate == normal.token_estimate
    assert diagnosed.debug["selection_policy"] == "baseline_v1"
    assert diagnosed.debug["redundancy_report"]["mode"] == "report_only"


def test_diagnostics_distinguish_chunk_id_and_exact_content_duplicates() -> None:
    original = _candidate("same-id", "contenido alfa")
    duplicate_id = _candidate("same-id", "contenido beta", ordinal=1)
    duplicate_content = _candidate("copy", "contenido alfa", document_id=2)

    result = _builder().build((original, duplicate_id, duplicate_content), debug=True)
    decisions = result.debug["evidence_decisions"]
    report = result.debug["redundancy_report"]

    assert [decision["action"] for decision in decisions] == [
        "selected",
        "omitted",
        "omitted",
    ]
    assert decisions[1]["reasons"] == ("duplicate_chunk_id",)
    assert decisions[2]["reasons"] == ("duplicate_content",)
    assert report["exact_duplicate_count"] == 2
    assert report["exact_duplicate_prompt_tokens_est_local"] == 0
    assert all(
        item["included_in_context"] is False
        for item in report["exact_duplicate_candidates"]
    )


def test_overlap_is_measured_only_for_selected_chunks_of_same_document() -> None:
    shared = "segmento compartido"
    candidates = (
        _candidate("left", f"inicio {shared}", ordinal=0),
        _candidate("right", f"{shared} final", ordinal=1),
        _candidate("other", f"{shared} externo", document_id=2),
    )

    result = _builder().build(candidates, debug=True)
    report = result.debug["redundancy_report"]

    assert report["overlap_chars"] == len(shared)
    assert report["overlap_tokens_est_local"] == 5
    assert len(report["overlap_pairs"]) == 1
    assert report["overlap_pairs"][0]["effect"] == "report_only"


def test_optimized_trims_only_exact_overlap_with_contiguous_ranges() -> None:
    shared = "segmento exactamente compartido " * 4
    candidates = (
        _candidate(
            "left",
            f"inicio {shared}",
            ordinal=0,
            start_line=1,
            end_line=10,
            score=0.9,
        ),
        _candidate(
            "right",
            f"{shared}final",
            ordinal=1,
            start_line=8,
            end_line=16,
            score=0.8,
        ),
    )

    result = ContextBuilder(
        token_budget=1000,
        max_chunk_tokens=1200,
        dedupe_min_hash_prefix=16,
        selection_policy="optimized_v1",
    ).build(candidates, debug=True)
    report = result.debug["redundancy_report"]

    right = next(
        source for source in result.sources
        if source.candidate.chunk_id == "right"
    )
    assert right.content == "final"
    assert right.overlap_trimmed_chars == len(shared)
    assert report["mode"] == "trim_overlap_v1"
    assert report["trimmed_overlap_chars"] == len(shared)
    assert report["overlap_chars"] == 0


def test_optimized_does_not_trim_without_range_continuity() -> None:
    shared = "segmento exactamente compartido"
    candidates = (
        _candidate(
            "left",
            f"inicio {shared}",
            ordinal=0,
            start_line=1,
            end_line=5,
        ),
        _candidate(
            "right",
            f"{shared} final",
            ordinal=1,
            start_line=20,
            end_line=25,
        ),
    )

    result = ContextBuilder(
        token_budget=1000,
        max_chunk_tokens=1200,
        dedupe_min_hash_prefix=16,
        selection_policy="optimized_v1",
    ).build(candidates, debug=True)

    assert all(source.overlap_trimmed_chars == 0 for source in result.sources)
    assert result.debug["redundancy_report"]["mode"] == "report_only"


def test_exact_overlap_trim_releases_budget_for_additional_evidence() -> None:
    shared = "S" * 400
    candidates = (
        _candidate(
            "left",
            "A" * 200 + shared,
            ordinal=0,
            start_line=1,
            end_line=20,
            score=0.9,
        ),
        _candidate(
            "right",
            shared + "B" * 200,
            ordinal=1,
            start_line=10,
            end_line=30,
            score=0.8,
        ),
        _candidate(
            "additional",
            "evidencia adicional util " * 12,
            document_id=2,
            ordinal=0,
            start_line=1,
            end_line=10,
            score=0.7,
        ),
    )
    baseline = ContextBuilder(
        token_budget=300,
        max_chunk_tokens=1200,
        dedupe_min_hash_prefix=16,
        selection_policy="baseline_v1",
    ).build(candidates)
    optimized = ContextBuilder(
        token_budget=300,
        max_chunk_tokens=1200,
        dedupe_min_hash_prefix=16,
        selection_policy="optimized_v1",
    ).build(candidates, debug=True)

    assert len(baseline.sources) == 2
    assert {source.candidate.chunk_id for source in optimized.sources} == {
        "left",
        "right",
        "additional",
    }
    report = optimized.debug["redundancy_report"]
    assert report["trimmed_overlap_chars"] == 400
    assert report["trimmed_overlap_tokens_est_local"] == 100


def test_every_candidate_has_a_stable_selection_or_omission_reason() -> None:
    result = _builder(threshold=0.5, budget=1).build(
        (
            _candidate("low", "debajo", score=0.1),
            _candidate("missing", "", score=0.8),
            _candidate("budget", "contenido que no cabe", score=0.9),
        ),
        debug=True,
    )

    decisions = result.debug["evidence_decisions"]
    assert len(decisions) == 3
    assert [decision["action"] for decision in decisions] == [
        "omitted",
        "omitted",
        "omitted",
    ]
    assert [decision["reasons"] for decision in decisions] == [
        ("threshold",),
        ("missing_content",),
        ("budget",),
    ]
    assert all(decision["contribution_tokens_est_local"] == 0 for decision in decisions)
