"""Pruebas del servicio de indexacion H3."""

import sqlite3
from pathlib import Path

from barbarion.application.rag import IndexService
from barbarion.config import load_settings
from barbarion.database import initialize_database
from barbarion.domain.rag import EmbeddingRunMode, EmbeddingRunStatus, IndexScope
from barbarion.infrastructure.embeddings import DeterministicFakeEmbeddingProvider
from barbarion.infrastructure.sqlite import SQLiteRagRepository
from barbarion.infrastructure.sqlite_vec import SQLiteVecStore


SHA_SOURCE = "a" * 64
SHA_DOC = "b" * 64
SHA_CHUNK_1 = "c" * 64
SHA_CHUNK_2 = "d" * 64


class CountingProvider(DeterministicFakeEmbeddingProvider):
    """Fake deterministic provider que cuenta invocaciones."""

    def __init__(self) -> None:
        object.__setattr__(self, "dimension", 4)
        object.__setattr__(self, "provider", "fake")
        object.__setattr__(self, "model", "sha256")
        object.__setattr__(self, "normalize", True)
        object.__setattr__(self, "calls", 0)

    def embed(self, request):  # type: ignore[override]
        object.__setattr__(self, "calls", self.calls + len(request.texts))
        return super().embed(request)


def seed_chunks(path: Path) -> None:
    """Inserta un corpus H2 minimo vigente."""
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO ingestion_runs(
                id, domain, mode, status, roots_json, config_sha256, started_at
            )
            VALUES (1, 'default', 'incremental', 'completed', '[]', ?, ?)
            """,
            ("f" * 64, "2026-01-01T00:00:00+00:00"),
        )
        connection.execute(
            """
            INSERT INTO files(
                id, domain, source_root, relative_path, extension, artifact_kind,
                media_type, size_bytes, modified_at_ns, sha256, status,
                first_seen_run_id, last_seen_run_id, created_at, updated_at
            )
            VALUES (
                1, 'default', 'root', 'pkg/demo.sql', '.sql', 'oracle',
                'text/plain', 10, 1, ?, 'processed', 1, 1, ?, ?
            )
            """,
            (
                SHA_SOURCE,
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO documents(
                id, file_id, source_sha256, parser_id, parser_version,
                normalizer_version, normalized_text, content_sha256,
                metadata_json, warnings_json, extracted_at
            )
            VALUES (1, 1, ?, 'oracle', '1', '1', 'texto', ?, '{}', '[]', ?)
            """,
            (SHA_SOURCE, SHA_DOC, "2026-01-01T00:00:00+00:00"),
        )
        connection.execute(
            """
            INSERT INTO chunks(
                id, document_id, ordinal, chunk_type, content, content_sha256,
                object_type, object_name, metadata_json, chunker_version, created_at
            )
            VALUES
                ('chunk-1', 1, 0, 'procedure', 'procedure demo is begin null; end;', ?, 'procedure', 'demo', ?, '1', ?),
                ('chunk-2', 1, 1, 'procedure', 'select COSTO_AMORT_DIA from dual;', ?, 'procedure', 'costos', '{}', '1', ?)
            """,
            (
                SHA_CHUNK_1,
                '{"symbol_name":"demo","symbol_kind":"procedure","package_name":"pkg_demo"}',
                "2026-01-01T00:00:00+00:00",
                SHA_CHUNK_2,
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.commit()


def service_for(tmp_path: Path, provider: CountingProvider | None = None) -> tuple[IndexService, CountingProvider]:
    db_path = tmp_path / "barbarion.db"
    initialize_database(db_path)
    seed_chunks(db_path)
    settings = load_settings(environ={}, cwd=tmp_path)
    provider = CountingProvider() if provider is None else provider
    service = IndexService(
        settings=settings,
        repository=SQLiteRagRepository(db_path),
        embedding_provider=provider,
        vector_store=SQLiteVecStore(db_path),
    )
    return service, provider


def test_index_service_indexes_new_chunks(tmp_path: Path) -> None:
    service, provider = service_for(tmp_path)

    summary = service.run()

    assert summary.status == EmbeddingRunStatus.COMPLETED
    assert summary.new_chunks == 2
    assert summary.updated_chunks == 0
    assert summary.unchanged_chunks == 0
    assert provider.calls == 3  # probe inicial + dos chunks


def test_index_service_skips_unchanged_without_embedding_calls(tmp_path: Path) -> None:
    service, provider = service_for(tmp_path)
    first = service.run()
    object.__setattr__(provider, "calls", 0)

    second = service.run()

    assert first.new_chunks == 2
    assert second.status == EmbeddingRunStatus.COMPLETED
    assert second.unchanged_chunks == 2
    assert second.new_chunks == 0
    assert provider.calls == 0


def test_index_service_dry_run_does_not_write_or_embed(tmp_path: Path) -> None:
    service, provider = service_for(tmp_path)

    summary = service.run(dry_run=True)

    assert summary.dry_run is True
    assert summary.new_chunks == 2
    assert provider.calls == 0
    with sqlite3.connect(tmp_path / "barbarion.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM embedding_runs").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM embedding_manifests").fetchone() == (0,)


def test_index_service_full_reindexes_existing_chunks(tmp_path: Path) -> None:
    service, provider = service_for(tmp_path)
    service.run()
    object.__setattr__(provider, "calls", 0)

    summary = service.run(mode=EmbeddingRunMode.FULL)

    assert summary.status == EmbeddingRunStatus.COMPLETED
    assert summary.new_chunks == 2
    assert summary.unchanged_chunks == 0
    assert provider.calls == 2


def test_index_service_scope_limits_chunks(tmp_path: Path) -> None:
    service, _provider = service_for(tmp_path)

    summary = service.run(
        scope=IndexScope(chunk_id="chunk-1"),
        dry_run=True,
    )

    assert summary.new_chunks == 1
