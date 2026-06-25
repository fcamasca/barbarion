"""Pruebas del servicio de busqueda H3."""

import sqlite3
from pathlib import Path

from barbarion.application.rag import IndexService, SearchService
from barbarion.config import load_settings
from barbarion.database import initialize_database
from barbarion.domain.rag import RetrievalFilter, RetrievalMode, SearchRequest
from barbarion.infrastructure.embeddings import DeterministicFakeEmbeddingProvider
from barbarion.infrastructure.sqlite import SQLiteRagRepository
from barbarion.infrastructure.sqlite_vec import SQLiteVecStore
from tests.unit.test_rag_index_service import seed_chunks


class SearchProvider(DeterministicFakeEmbeddingProvider):
    """Fake deterministico con identidad estable para manifests."""

    def __init__(self) -> None:
        object.__setattr__(self, "dimension", 4)
        object.__setattr__(self, "provider", "fake")
        object.__setattr__(self, "model", "sha256")
        object.__setattr__(self, "normalize", True)


def service_for(tmp_path: Path) -> SearchService:
    """Construye indice y servicio de busqueda sobre SQLite temporal."""
    db_path = tmp_path / "barbarion.db"
    initialize_database(db_path)
    seed_chunks(db_path)
    settings = load_settings(environ={}, cwd=tmp_path)
    repository = SQLiteRagRepository(db_path)
    provider = SearchProvider()
    vector_store = SQLiteVecStore(db_path)
    IndexService(
        settings=settings,
        repository=repository,
        embedding_provider=provider,
        vector_store=vector_store,
    ).run()
    return SearchService(
        settings=settings,
        repository=repository,
        embedding_provider=provider,
        vector_store=vector_store,
    )


def test_semantic_search_uses_vectors_and_logs_query(tmp_path: Path) -> None:
    service = service_for(tmp_path)

    response = service.search(
        SearchRequest(
            query="procedure demo",
            mode=RetrievalMode.SEMANTIC,
            top_k=1,
            candidate_k=2,
            debug=True,
        )
    )

    assert response.query_id is not None
    assert len(response.candidates) == 1
    assert response.candidates[0].vector_score is not None
    assert response.candidates[0].source["retrieval_mode"] == "semantic"
    assert "snippet" in response.candidates[0].source
    assert response.debug["vector_candidates"] >= 1
    with sqlite3.connect(tmp_path / "barbarion.db") as connection:
        row = connection.execute(
            "SELECT mode, candidate_count, status FROM rag_queries"
        ).fetchone()
    assert row == ("semantic", 1, "completed")


def test_keyword_search_finds_identifier_with_stable_ranking(tmp_path: Path) -> None:
    service = service_for(tmp_path)

    response = service.search(
        SearchRequest(
            query="COSTO_AMORT_DIA",
            mode=RetrievalMode.KEYWORD,
            filters=RetrievalFilter(extension=".sql"),
            top_k=5,
            candidate_k=5,
        )
    )

    assert [candidate.chunk_id for candidate in response.candidates] == ["chunk-2"]
    assert response.candidates[0].keyword_score == 1.0
    assert response.candidates[0].source["relative_path"] == "pkg/demo.sql"


def test_hybrid_search_deduplicates_and_preserves_scores(tmp_path: Path) -> None:
    service = service_for(tmp_path)

    response = service.search(
        SearchRequest(
            query="COSTO_AMORT_DIA",
            mode=RetrievalMode.HYBRID,
            top_k=5,
            candidate_k=5,
            vector_weight=0.5,
            keyword_weight=0.5,
        )
    )

    chunk_ids = [candidate.chunk_id for candidate in response.candidates]
    assert len(chunk_ids) == len(set(chunk_ids))
    assert "chunk-2" in chunk_ids
    matching = next(
        candidate for candidate in response.candidates if candidate.chunk_id == "chunk-2"
    )
    assert matching.vector_score is not None
    assert matching.keyword_score is not None
    assert matching.source["retrieval_mode"] == "hybrid"


def test_search_without_manifest_allows_keyword_only(tmp_path: Path) -> None:
    db_path = tmp_path / "barbarion.db"
    initialize_database(db_path)
    seed_chunks(db_path)
    settings = load_settings(environ={}, cwd=tmp_path)
    service = SearchService(
        settings=settings,
        repository=SQLiteRagRepository(db_path),
        embedding_provider=SearchProvider(),
        vector_store=SQLiteVecStore(db_path),
    )

    response = service.search(
        SearchRequest(
            query="COSTO_AMORT_DIA",
            mode=RetrievalMode.KEYWORD,
            top_k=3,
            candidate_k=3,
        )
    )

    assert [candidate.chunk_id for candidate in response.candidates] == ["chunk-2"]
    assert response.query_id is not None


def test_empty_search_records_insufficient_evidence(tmp_path: Path) -> None:
    service = service_for(tmp_path)

    response = service.search(
        SearchRequest(
            query="NO_EXISTE_EN_CORPUS",
            mode=RetrievalMode.KEYWORD,
            top_k=3,
            candidate_k=3,
        )
    )

    assert response.candidates == ()
    with sqlite3.connect(tmp_path / "barbarion.db") as connection:
        status = connection.execute(
            "SELECT status FROM rag_queries ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
    assert status == "insufficient_evidence"
