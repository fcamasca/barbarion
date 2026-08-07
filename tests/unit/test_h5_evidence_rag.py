"""Pruebas de recuperacion documental H5 sobre contratos H3."""

import pytest

from barbarion.application.rag import ContextBuilder
from barbarion.application.spec_mode import (
    DocumentEvidenceCollector,
    DocumentEvidenceRequest,
    RequirementAnalyzer,
)
from barbarion.domain.rag import RetrievalCandidate, RetrievalFilter, RetrievalMode
from barbarion.domain.spec_mode import EvidenceSourceType


SHA_A = "a" * 64
SHA_B = "b" * 64


class FakeSearchService:
    """Fake que expone la misma entrada relevante que SearchService."""

    def __init__(self, candidates: tuple[RetrievalCandidate, ...]) -> None:
        self.candidates = candidates
        self.requests = []

    def search(self, request):
        self.requests.append(request)
        return type("SearchResponse", (), {"candidates": self.candidates})()


def candidate(
    chunk_id: str,
    sha: str,
    score: float,
    *,
    document_id: int,
    ordinal: int,
    content: str,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id,
        content_sha256=sha,
        combined_score=score,
        source={
            "document_id": document_id,
            "ordinal": ordinal,
            "relative_path": "sources/oracle/pkg_credito.sql",
            "start_line": 10 + ordinal,
            "end_line": 20 + ordinal,
            "content": content,
        },
    )


@pytest.mark.parametrize("selection_policy", ["baseline_v1", "optimized_v1"])
def test_document_evidence_collector_delegates_to_h3_services(
    selection_policy: str,
) -> None:
    intent = RequirementAnalyzer().analyze(
        "Validar limite de credito antes de aprobar pedidos en pkg_credito"
    )
    search = FakeSearchService(
        (
            candidate(
                "chunk-2",
                SHA_B,
                0.7,
                document_id=2,
                ordinal=2,
                content="regla secundaria",
            ),
            candidate(
                "chunk-1",
                SHA_A,
                0.9,
                document_id=1,
                ordinal=1,
                content="validar limite_credito antes de aprobar",
            ),
        )
    )
    builder = ContextBuilder(
        token_budget=200,
        max_chunk_tokens=80,
        dedupe_min_hash_prefix=8,
        threshold=0.0,
        selection_policy=selection_policy,
    )

    result = DocumentEvidenceCollector(search, builder).collect(
        DocumentEvidenceRequest(
            intent=intent,
            mode=RetrievalMode.KEYWORD,
            filters=RetrievalFilter(extension=".sql"),
            top_k=2,
            candidate_k=2,
            debug=True,
        )
    )

    assert search.requests[0].mode == RetrievalMode.KEYWORD
    assert search.requests[0].filters.extension == ".sql"
    assert search.requests[0].query.startswith("pkg credito limite de credito")
    assert [item.chunk_id for item in result.evidence] == ["chunk-1", "chunk-2"]
    assert [source.source_id for source in result.context.sources] == ["F1", "F2"]
    assert result.evidence[0].source_type == EvidenceSourceType.CHUNK
    assert result.evidence[0].citation == (
        "[F1] sources/oracle/pkg_credito.sql lineas=11-21"
    )
    assert result.evidence[0].metadata["context_source_id"] == "F1"
    assert result.insufficient_evidence is False


def test_document_evidence_collector_reports_insufficient_evidence() -> None:
    intent = RequirementAnalyzer().analyze("Validar limite de credito")
    search = FakeSearchService(())
    builder = ContextBuilder(
        token_budget=200,
        max_chunk_tokens=80,
        dedupe_min_hash_prefix=8,
        threshold=0.0,
    )

    result = DocumentEvidenceCollector(search, builder).collect(
        DocumentEvidenceRequest(intent=intent, mode=RetrievalMode.KEYWORD)
    )

    assert result.evidence == ()
    assert result.context.sources == ()
    assert result.insufficient_evidence is True


def test_document_evidence_request_validates_limits() -> None:
    intent = RequirementAnalyzer().analyze("Validar limite de credito")

    try:
        DocumentEvidenceRequest(intent=intent, top_k=0)
    except ValueError as exc:
        assert "top_k" in str(exc)
    else:
        raise AssertionError("top_k invalido debio fallar")

    try:
        DocumentEvidenceRequest(intent=intent, top_k=5, candidate_k=4)
    except ValueError as exc:
        assert "candidate_k" in str(exc)
    else:
        raise AssertionError("candidate_k invalido debio fallar")
