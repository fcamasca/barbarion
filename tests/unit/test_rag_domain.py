"""Pruebas de contratos puros H3 RAG."""

from types import MappingProxyType

import pytest

from barbarion.domain.rag import (
    ContextQualityMetrics,
    EmbeddingManifest,
    EmbeddingRequest,
    EmbeddingVector,
    H4SymbolMetadata,
    RetrievalCandidate,
    RetrievalMode,
    SearchRequest,
    combine_hybrid_candidates,
    embedding_version,
)


VALID_SHA = "a" * 64
OTHER_SHA = "b" * 64


def test_embedding_version_is_stable_and_changes_by_dimension() -> None:
    first = embedding_version(
        provider="ollama",
        model="nomic-embed-text",
        dimension=768,
        distance="cosine",
        normalize=True,
    )
    second = embedding_version(
        provider="ollama",
        model="nomic-embed-text",
        dimension=768,
        distance="cosine",
        normalize=True,
    )
    different = embedding_version(
        provider="ollama",
        model="nomic-embed-text",
        dimension=384,
        distance="cosine",
        normalize=True,
    )

    assert first == second
    assert first != different
    assert len(first) == 64


def test_embedding_manifest_derives_version() -> None:
    manifest = EmbeddingManifest(
        provider="ollama",
        model="nomic-embed-text",
        dimension=768,
    )

    assert manifest.version is not None
    assert len(manifest.version) == 64


def test_embedding_request_and_vector_validate_values() -> None:
    request = EmbeddingRequest(
        texts=("select 1",),
        input_kind="chunk",
        embedding_version=VALID_SHA,
    )
    vector = EmbeddingVector(
        text_index=0,
        values=(0.1, 0.2),
        provider="ollama",
        model="nomic-embed-text",
    )

    assert request.texts == ("select 1",)
    assert vector.dimension == 2


def test_retrieval_candidate_keeps_h4_metadata_and_freezes_source() -> None:
    metadata = H4SymbolMetadata(
        symbol_name="order_total",
        symbol_kind="variable",
        package_name="PKG_COSTOS",
    )
    candidate = RetrievalCandidate(
        chunk_id="chunk-1",
        content_sha256=OTHER_SHA,
        combined_score=0.9,
        vector_score=0.8,
        keyword_score=0.7,
        metadata=metadata,
        source={"path": "pkg/orders.sql"},
    )

    assert candidate.metadata.symbol_name == "order_total"
    assert isinstance(candidate.source, MappingProxyType)


def test_context_quality_metrics_accept_optional_scores() -> None:
    metrics = ContextQualityMetrics(
        context_precision=0.5,
        context_recall=None,
        duplicate_ratio=0.1,
        token_waste=0.2,
    )

    assert metrics.context_precision == 0.5
    assert metrics.context_recall is None


def test_combine_hybrid_candidates_deduplicates_and_keeps_scores() -> None:
    vector = RetrievalCandidate(
        chunk_id="chunk-1",
        content_sha256=OTHER_SHA,
        combined_score=0.8,
        vector_score=0.8,
    )
    keyword = RetrievalCandidate(
        chunk_id="chunk-1",
        content_sha256=OTHER_SHA,
        combined_score=0.6,
        keyword_score=0.6,
    )

    combined = combine_hybrid_candidates(
        (vector,),
        (keyword,),
        vector_weight=0.5,
        keyword_weight=0.5,
        top_k=5,
    )

    assert len(combined) == 1
    assert combined[0].vector_score == 0.8
    assert combined[0].keyword_score == 0.6
    assert combined[0].source["retrieval_mode"] == "hybrid"


@pytest.mark.parametrize(
    "factory",
    [
        lambda: EmbeddingManifest("ollama", "model", 0),
        lambda: EmbeddingRequest((), "chunk", VALID_SHA),
        lambda: EmbeddingRequest(("ok",), "chunk", "bad"),
        lambda: EmbeddingVector(-1, (0.1,), "ollama", "model"),
        lambda: EmbeddingVector(0, (), "ollama", "model"),
        lambda: RetrievalCandidate("chunk", "bad", 0.5),
        lambda: RetrievalCandidate("chunk", OTHER_SHA, 1.5),
        lambda: ContextQualityMetrics(context_precision=2),
        lambda: SearchRequest("", RetrievalMode.SEMANTIC),
        lambda: SearchRequest("ok", RetrievalMode.HYBRID, top_k=5, candidate_k=4),
        lambda: SearchRequest(
            "ok",
            RetrievalMode.HYBRID,
            vector_weight=0,
            keyword_weight=0,
        ),
    ],
)
def test_invalid_rag_models_are_rejected(factory: object) -> None:
    with pytest.raises(ValueError):
        factory()
