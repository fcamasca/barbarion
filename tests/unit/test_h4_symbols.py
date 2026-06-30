"""Pruebas H4-T02 para catalogo de simbolos."""

import sqlite3
from pathlib import Path

from barbarion.application.reverse_engineering import SymbolCatalogService
from barbarion.config import load_settings
from barbarion.database import initialize_database
from barbarion.domain.reverse_engineering import H4AnalysisRunStatus
from barbarion.infrastructure.sqlite import SQLiteReverseEngineeringRepository
from tests.unit.test_rag_index_service import SHA_CHUNK_1, SHA_DOC, SHA_SOURCE, seed_chunks


def test_h4_symbol_catalog_builds_active_symbols_without_duplicates(
    tmp_path: Path,
) -> None:
    path = tmp_path / "barbarion.db"
    initialize_database(path)
    seed_chunks(path)
    _seed_h4_symbol_sources(path)
    repository = SQLiteReverseEngineeringRepository(path)
    service = SymbolCatalogService(
        settings=load_settings(environ={}, cwd=tmp_path),
        repository=repository,
    )

    summary = service.run()

    assert summary.status == H4AnalysisRunStatus.COMPLETED
    assert summary.sources_scanned == 6
    assert summary.symbols_detected == 5
    assert summary.duplicates_skipped == 1
    assert summary.unknown_symbols == 1
    run = repository.analysis_run(summary.run_id)
    assert run is not None
    assert run.symbols_detected == 5

    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            """
            SELECT normalized_name, symbol_type, technology, container_name,
                   confidence, status, file_id, chunk_id
            FROM h4_symbols
            ORDER BY technology, normalized_name, symbol_type, chunk_id
            """
        ).fetchall()

    assert rows == [
        (
            "docs/readme.md#chunk-unknown",
            "unknown",
            "document",
            None,
            "low",
            "active",
            3,
            "chunk-unknown",
        ),
        (
            "demo",
            "procedure",
            "oracle",
            "pkg_demo",
            "high",
            "active",
            1,
            "chunk-1",
        ),
        (
            "orders",
            "procedure",
            "oracle",
            None,
            "high",
            "active",
            1,
            "chunk-2",
        ),
        (
            "clicked",
            "event",
            "powerbuilder",
            "w_cliente",
            "high",
            "active",
            2,
            "pb-event",
        ),
        (
            "w_cliente",
            "window",
            "powerbuilder",
            None,
            "medium",
            "active",
            2,
            "pb-window",
        ),
    ]


def _seed_h4_symbol_sources(path: Path) -> None:
    """Extiende el corpus H2 minimo con simbolos H4 sinteticos."""
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO chunks(
                id, document_id, ordinal, chunk_type, content, content_sha256,
                start_line, end_line, object_type, object_name, metadata_json,
                chunker_version, created_at
            )
            VALUES (
                'chunk-duplicate', 1, 2, 'procedure', 'procedure demo duplicate;',
                ?, 9, 12, 'procedure', 'demo',
                '{"format":"oracle","package_name":"pkg_demo"}', '1', ?
            )
            """,
            (SHA_CHUNK_1, "2026-01-01T00:00:00+00:00"),
        )
        connection.execute(
            """
            INSERT INTO files(
                id, domain, source_root, relative_path, extension, artifact_kind,
                media_type, size_bytes, modified_at_ns, sha256, status,
                first_seen_run_id, last_seen_run_id, created_at, updated_at
            )
            VALUES (
                2, 'default', 'root', 'pb/w_cliente.srw', '.srw', 'powerbuilder',
                'text/plain', 20, 2, ?, 'processed', 1, 1, ?, ?
            )
            """,
            (
                "2" * 64,
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
            VALUES (2, 2, ?, 'powerbuilder', '1', '1', 'texto', ?, '{}', '[]', ?)
            """,
            ("2" * 64, "3" * 64, "2026-01-01T00:00:00+00:00"),
        )
        connection.execute(
            """
            INSERT INTO chunks(
                id, document_id, ordinal, chunk_type, content, content_sha256,
                start_line, end_line, object_type, object_name, metadata_json,
                chunker_version, created_at
            )
            VALUES
                (
                    'pb-window', 2, 0, 'window', 'window w_cliente',
                    ?, 1, 20, 'window', 'w_cliente',
                    '{"format":"powerbuilder","logical_unit_confidence":"medium"}',
                    '1', ?
                ),
                (
                    'pb-event', 2, 1, 'event', 'event clicked',
                    ?, 5, 9, 'event', 'clicked',
                    '{"format":"powerbuilder","parent_name":"w_cliente"}',
                    '1', ?
                )
            """,
            (
                "4" * 64,
                "2026-01-01T00:00:00+00:00",
                "5" * 64,
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO files(
                id, domain, source_root, relative_path, extension, artifact_kind,
                media_type, size_bytes, modified_at_ns, sha256, status,
                first_seen_run_id, last_seen_run_id, created_at, updated_at
            )
            VALUES (
                3, 'default', 'root', 'docs/readme.md', '.md', 'markdown',
                'text/markdown', 15, 3, ?, 'processed', 1, 1, ?, ?
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
            VALUES (3, 3, ?, 'markdown', '1', '1', 'texto', ?, '{}', '[]', ?)
            """,
            (SHA_SOURCE, SHA_DOC, "2026-01-01T00:00:00+00:00"),
        )
        connection.execute(
            """
            INSERT INTO chunks(
                id, document_id, ordinal, chunk_type, content, content_sha256,
                metadata_json, chunker_version, created_at
            )
            VALUES (
                'chunk-unknown', 3, 0, 'file', 'texto sin metadata simbolica',
                ?, '{}', '1', ?
            )
            """,
            ("6" * 64, "2026-01-01T00:00:00+00:00"),
        )
        connection.commit()
