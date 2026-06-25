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
        symbol_name="COSTO_AMORT_DIA",
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
        source={"path": "pkg/costos.sql"},
    )

    assert candidate.metadata.symbol_name == "COSTO_AMORT_DIA"
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
    ],
)
def test_invalid_rag_models_are_rejected(factory: object) -> None:
    with pytest.raises(ValueError):
        factory()
