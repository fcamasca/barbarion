"""Pruebas de contratos puros RAG."""

from types import MappingProxyType

import pytest

from barbarion.domain.rag import (
    CandidateOrigin,
    CandidateOriginKind,
    ContextQualityMetrics,
    EmbeddingManifest,
    EmbeddingRequest,
    EmbeddingVector,
    GraphCandidateStatus,
    GraphCandidateTrace,
    GraphExpansionLimits,
    GraphPath,
    GraphSeed,
    SymbolMetadata,
    RetrievalCandidate,
    RetrievalMode,
    SeedOrigin,
    SearchRequest,
    combine_hybrid_candidates,
    embedding_version,
)
from barbarion.domain.reverse_engineering import DependencyDirection


VALID_SHA = "a" * 64
OTHER_SHA = "b" * 64


def test_graph_contracts_preserve_seed_origin_path_and_limits() -> None:
    seed = GraphSeed(
        seed_id="seed-1",
        chunk_id="chunk-1",
        symbol_id="symbol-1",
        retrieval_score=0.8,
        origin=SeedOrigin.H3_CHUNK,
        source_candidate_id="candidate-1",
    )
    path = GraphPath(
        nodes=("symbol-1", "symbol-2"),
        relations=("relation-1",),
        direction=DependencyDirection.OUTGOING,
        depth=1,
    )
    origin = CandidateOrigin(
        kind=CandidateOriginKind.GRAPH_EXPANSION,
        seed_ids=(seed.seed_id,),
        relation_ids=path.relations,
        path=path,
    )
    trace = GraphCandidateTrace(
        candidate_id="chunk-2",
        origin=origin,
        discovered_at_depth=1,
        dedupe_key="chunk-2",
        status=GraphCandidateStatus.ACCEPTED,
    )
    limits = GraphExpansionLimits(
        max_depth=2,
        max_seeds=3,
        max_neighbors_per_seed=4,
        max_candidates=10,
    )

    assert trace.origin.path == path
    assert trace.status == GraphCandidateStatus.ACCEPTED
    assert limits.max_candidates == 10


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: GraphPath(
                nodes=("a", "b"),
                relations=(),
                direction=DependencyDirection.OUTGOING,
                depth=0,
            ),
            "nodes",
        ),
        (
            lambda: GraphPath(
                nodes=("a", "b", "a"),
                relations=("r1", "r2"),
                direction=DependencyDirection.OUTGOING,
                depth=2,
            ),
            "nodes",
        ),
        (
            lambda: CandidateOrigin(kind=CandidateOriginKind.GRAPH_EXPANSION),
            "graph_expansion",
        ),
        (
            lambda: GraphExpansionLimits(
                max_depth=0,
                max_seeds=1,
                max_neighbors_per_seed=1,
                max_candidates=1,
            ),
            "max_depth",
        ),
    ],
)
def test_graph_contracts_reject_invalid_invariants(factory, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


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
    metadata = SymbolMetadata(
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
