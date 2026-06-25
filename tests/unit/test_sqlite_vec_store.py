"""Pruebas del vector store local inicial."""

from pathlib import Path

import pytest

from barbarion.database import initialize_database
from barbarion.domain.rag import (
    EmbeddingManifest,
    H4SymbolMetadata,
    RetrievalFilter,
    VectorMetadata,
    VectorStoreError,
)
from barbarion.infrastructure.sqlite_vec import SQLiteVecStore


SHA = "c" * 64


def metadata(
    *,
    domain: str = "default",
    extension: str = ".sql",
    document_id: int = 1,
    symbol_name: str | None = None,
) -> VectorMetadata:
    """Construye metadata filtrable para pruebas."""
    return VectorMetadata(
        content_sha256=SHA,
        domain=domain,
        artifact_kind="oracle",
        language="plsql",
        document_id=document_id,
        file_id=10,
        relative_path="pkg/demo.sql",
        folder="pkg",
        extension=extension,
        symbols=H4SymbolMetadata(symbol_name=symbol_name, symbol_kind="procedure"),
    )


def test_sqlite_vec_store_upsert_search_and_delete(tmp_path: Path) -> None:
    path = tmp_path / "barbarion.db"
    initialize_database(path)
    store = SQLiteVecStore(path)
    manifest = EmbeddingManifest("fake", "sha256", 3)

    store.upsert(
        manifest=manifest,
        chunk_id="chunk-a",
        vector=(1.0, 0.0, 0.0),
        metadata=metadata(symbol_name="PROC_A"),
    )
    store.upsert(
        manifest=manifest,
        chunk_id="chunk-b",
        vector=(0.0, 1.0, 0.0),
        metadata=metadata(document_id=2, symbol_name="PROC_B"),
    )

    results = store.search(
        manifest=manifest,
        query_vector=(1.0, 0.0, 0.0),
        filters=RetrievalFilter(domain="default"),
        top_k=2,
    )

    assert [result.chunk_id for result in results] == ["chunk-a", "chunk-b"]
    assert results[0].combined_score == 1.0
    assert results[0].metadata.symbol_name == "PROC_A"
    assert results[0].source["relative_path"] == "pkg/demo.sql"

    store.delete(manifest=manifest, chunk_id="chunk-a")
    after_delete = store.search(
        manifest=manifest,
        query_vector=(1.0, 0.0, 0.0),
        filters=RetrievalFilter(domain="default"),
        top_k=2,
    )

    assert [result.chunk_id for result in after_delete] == ["chunk-b"]


def test_sqlite_vec_store_filters_results(tmp_path: Path) -> None:
    path = tmp_path / "barbarion.db"
    initialize_database(path)
    store = SQLiteVecStore(path)
    manifest = EmbeddingManifest("fake", "sha256", 2)
    store.upsert(
        manifest=manifest,
        chunk_id="sql",
        vector=(1.0, 0.0),
        metadata=metadata(extension=".sql"),
    )
    store.upsert(
        manifest=manifest,
        chunk_id="doc",
        vector=(1.0, 0.0),
        metadata=metadata(extension=".md", document_id=3),
    )

    results = store.search(
        manifest=manifest,
        query_vector=(1.0, 0.0),
        filters=RetrievalFilter(domain="default", extension=".md"),
        top_k=10,
    )

    assert [result.chunk_id for result in results] == ["doc"]


def test_sqlite_vec_store_upsert_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "barbarion.db"
    initialize_database(path)
    store = SQLiteVecStore(path)
    manifest = EmbeddingManifest("fake", "sha256", 2)

    store.upsert(
        manifest=manifest,
        chunk_id="same",
        vector=(1.0, 0.0),
        metadata=metadata(),
    )
    store.upsert(
        manifest=manifest,
        chunk_id="same",
        vector=(0.0, 1.0),
        metadata=metadata(symbol_name="UPDATED"),
    )

    results = store.search(
        manifest=manifest,
        query_vector=(0.0, 1.0),
        filters=RetrievalFilter(domain="default"),
        top_k=10,
    )

    assert [result.chunk_id for result in results] == ["same"]
    assert results[0].combined_score == 1.0
    assert results[0].metadata.symbol_name == "UPDATED"


def test_sqlite_vec_store_rejects_dimension_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "barbarion.db"
    initialize_database(path)
    store = SQLiteVecStore(path)
    manifest = EmbeddingManifest("fake", "sha256", 3)

    with pytest.raises(VectorStoreError, match="DIMENSION"):
        store.upsert(
            manifest=manifest,
            chunk_id="bad",
            vector=(1.0, 0.0),
            metadata=metadata(),
        )
