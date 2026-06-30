"""Pruebas del repositorio SQLite RAG."""

import sqlite3
from pathlib import Path

from barbarion.database import initialize_database
from barbarion.domain.rag import (
    EmbeddingManifest,
    EmbeddingManifestStatus,
    EmbeddingRunMode,
)
from barbarion.infrastructure.sqlite import SQLiteRagRepository
from tests.unit.test_rag_index_service import seed_chunks


def test_get_or_create_manifest_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "barbarion.db"
    initialize_database(path)
    repository = SQLiteRagRepository(path)
    manifest = EmbeddingManifest(
        provider="ollama",
        model="nomic-embed-text",
        dimension=768,
    )

    first = repository.get_or_create_manifest(manifest)
    second = repository.get_or_create_manifest(manifest)

    assert first == second
    assert first.manifest.version == manifest.version
    assert first.vector_provider == "sqlite_vec"
    assert first.vector_table == "rag_chunk_vectors"
    assert first.status == EmbeddingManifestStatus.ACTIVE
    assert repository.list_manifests() == (first,)


def test_mark_other_manifests_obsolete(tmp_path: Path) -> None:
    path = tmp_path / "barbarion.db"
    initialize_database(path)
    repository = SQLiteRagRepository(path)
    active = repository.get_or_create_manifest(
        EmbeddingManifest("ollama", "model-a", 3)
    )
    other = repository.get_or_create_manifest(
        EmbeddingManifest("ollama", "model-b", 3)
    )

    changed = repository.mark_other_manifests_obsolete(active.manifest.version or "")
    manifests = repository.list_manifests()

    assert changed == 1
    assert manifests[0].status == EmbeddingManifestStatus.ACTIVE
    assert manifests[1].id == other.id
    assert manifests[1].status == EmbeddingManifestStatus.OBSOLETE


def test_symbol_occurrences_table_is_reserved_but_empty(tmp_path: Path) -> None:
    path = tmp_path / "barbarion.db"
    initialize_database(path)

    with sqlite3.connect(path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM symbol_occurrences").fetchone()

    assert count == (0,)


def test_embedding_error_details_are_read_from_sqlite(tmp_path: Path) -> None:
    path = tmp_path / "barbarion.db"
    initialize_database(path)
    seed_chunks(path)
    repository = SQLiteRagRepository(path)
    manifest = repository.get_or_create_manifest(
        EmbeddingManifest("fake", "sha256", 4)
    )
    run_id = repository.begin_embedding_run(
        manifest_id=manifest.id,
        mode=EmbeddingRunMode.INCREMENTAL,
        scope=None,
    )
    chunk = repository.indexable_chunks(domain="default")[0]
    repository.record_chunk_error(
        run_id=run_id,
        manifest_id=manifest.id,
        chunk=chunk,
        error_code="OLLAMA_EMBEDDINGS_UNAVAILABLE",
        error_message="no se pudo contactar Ollama local",
    )

    details = repository.embedding_error_details()

    assert repository.latest_embedding_error_run_id() == run_id
    assert repository.dominant_embedding_error_code(run_id=run_id) == "OLLAMA_EMBEDDINGS_UNAVAILABLE"
    assert len(details) == 1
    assert details[0].run_id == run_id
    assert details[0].chunk_id == chunk.chunk_id
    assert details[0].error_code == "OLLAMA_EMBEDDINGS_UNAVAILABLE"
    assert details[0].error_message == "no se pudo contactar Ollama local"
