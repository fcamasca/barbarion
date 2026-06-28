"""SQL explicito de persistencia para la ingesta H2."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from barbarion.domain.ingestion import (
    CHUNKER_VERSION,
    NORMALIZER_VERSION,
    PersistedFileState,
    canonical_chunk_metadata,
)
from barbarion.domain.models import (
    ChunkCandidate,
    DiscoveredFile,
    ErrorStage,
    FileFingerprint,
    FileStatus,
    IngestionMetrics,
    IngestionMode,
    IngestionOutcome,
    IngestionRunStatus,
    NormalizedDocument,
    PipelineError,
)
from barbarion.domain.rag import (
    ChunkEmbeddingState,
    ChunkEmbeddingStatus,
    ContextQualityMetrics,
    EmbeddingManifest,
    EmbeddingManifestStatus,
    EmbeddingRunMode,
    EmbeddingRunStatus,
    H4SymbolMetadata,
    IndexScope,
    IndexableChunk,
    RagQueryStatus,
    RetrievalCandidate,
    RetrievalFilter,
    RetrievalMode,
    SearchTimings,
    VectorMetadata,
)


DATABASE_LOCKED = "DATABASE_LOCKED"
DATABASE_WRITE_FAILED = "DATABASE_WRITE_FAILED"

INGESTION_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS ingestion_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        domain TEXT NOT NULL,
        mode TEXT NOT NULL CHECK (mode IN ('incremental', 'full')),
        status TEXT NOT NULL CHECK (
            status IN (
                'running',
                'completed',
                'completed_with_errors',
                'failed',
                'interrupted'
            )
        ),
        roots_json TEXT NOT NULL,
        config_sha256 TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        discovered_files INTEGER NOT NULL DEFAULT 0 CHECK (discovered_files >= 0),
        processed_files INTEGER NOT NULL DEFAULT 0 CHECK (processed_files >= 0),
        unchanged_files INTEGER NOT NULL DEFAULT 0 CHECK (unchanged_files >= 0),
        skipped_files INTEGER NOT NULL DEFAULT 0 CHECK (skipped_files >= 0),
        deleted_files INTEGER NOT NULL DEFAULT 0 CHECK (deleted_files >= 0),
        error_count INTEGER NOT NULL DEFAULT 0 CHECK (error_count >= 0),
        source_bytes INTEGER NOT NULL DEFAULT 0 CHECK (source_bytes >= 0),
        processed_bytes INTEGER NOT NULL DEFAULT 0 CHECK (processed_bytes >= 0),
        chunk_count INTEGER NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
        duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ingestion_runs_started_at
    ON ingestion_runs(started_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ingestion_runs_status
    ON ingestion_runs(status)
    """,
    """
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY,
        domain TEXT NOT NULL,
        source_root TEXT NOT NULL,
        relative_path TEXT NOT NULL,
        extension TEXT NOT NULL,
        artifact_kind TEXT NOT NULL,
        media_type TEXT NOT NULL,
        size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
        modified_at_ns INTEGER NOT NULL CHECK (modified_at_ns >= 0),
        sha256 TEXT,
        fingerprint_version INTEGER NOT NULL DEFAULT 1 CHECK (
            fingerprint_version > 0
        ),
        processing_signature TEXT,
        parser_id TEXT,
        parser_version TEXT,
        encoding TEXT,
        status TEXT NOT NULL CHECK (
            status IN ('pending', 'processed', 'skipped', 'error', 'deleted')
        ),
        skip_reason TEXT,
        first_seen_run_id INTEGER NOT NULL REFERENCES ingestion_runs(id),
        last_seen_run_id INTEGER NOT NULL REFERENCES ingestion_runs(id),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        processed_at TEXT,
        deleted_at TEXT,
        UNIQUE(domain, source_root, relative_path)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_files_status
    ON files(status)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_files_artifact_kind
    ON files(artifact_kind)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_files_sha256
    ON files(sha256)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_files_last_seen_run_id
    ON files(last_seen_run_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_files_source_root_last_seen_run_id
    ON files(source_root, last_seen_run_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY,
        file_id INTEGER NOT NULL UNIQUE REFERENCES files(id) ON DELETE CASCADE,
        source_sha256 TEXT NOT NULL,
        parser_id TEXT NOT NULL,
        parser_version TEXT NOT NULL,
        normalizer_version TEXT NOT NULL,
        title TEXT,
        normalized_text TEXT NOT NULL,
        content_sha256 TEXT NOT NULL,
        metadata_json TEXT NOT NULL,
        warnings_json TEXT NOT NULL,
        extracted_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_documents_content_sha256
    ON documents(content_sha256)
    """,
    """
    CREATE TABLE IF NOT EXISTS chunks (
        id TEXT PRIMARY KEY,
        document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
        chunk_type TEXT NOT NULL,
        content TEXT NOT NULL,
        content_sha256 TEXT NOT NULL,
        start_line INTEGER CHECK (start_line IS NULL OR start_line > 0),
        end_line INTEGER CHECK (end_line IS NULL OR end_line > 0),
        start_char INTEGER CHECK (start_char IS NULL OR start_char > 0),
        end_char INTEGER CHECK (end_char IS NULL OR end_char > 0),
        page_start INTEGER CHECK (page_start IS NULL OR page_start > 0),
        page_end INTEGER CHECK (page_end IS NULL OR page_end > 0),
        object_type TEXT,
        object_name TEXT,
        metadata_json TEXT NOT NULL,
        chunker_version TEXT NOT NULL,
        created_at TEXT NOT NULL,
        CHECK ((start_line IS NULL AND end_line IS NULL) OR end_line >= start_line),
        CHECK ((start_char IS NULL AND end_char IS NULL) OR end_char >= start_char),
        CHECK ((page_start IS NULL AND page_end IS NULL) OR page_end >= page_start),
        UNIQUE(document_id, ordinal, chunker_version)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_chunks_document_ordinal
    ON chunks(document_id, ordinal)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_chunks_object
    ON chunks(object_type, object_name)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_chunks_content_sha256
    ON chunks(content_sha256)
    """,
    """
    CREATE TABLE IF NOT EXISTS errors (
        id INTEGER PRIMARY KEY,
        run_id INTEGER NOT NULL REFERENCES ingestion_runs(id) ON DELETE CASCADE,
        file_id INTEGER REFERENCES files(id) ON DELETE SET NULL,
        stage TEXT NOT NULL,
        error_code TEXT NOT NULL,
        message TEXT NOT NULL,
        exception_type TEXT,
        recoverable INTEGER NOT NULL CHECK (recoverable IN (0, 1)),
        details_json TEXT NOT NULL,
        occurred_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_errors_run_id
    ON errors(run_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_errors_file_id
    ON errors(file_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_errors_error_code
    ON errors(error_code)
    """,
)

RAG_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS embedding_manifests (
        id INTEGER PRIMARY KEY,
        version TEXT NOT NULL UNIQUE,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        dimension INTEGER NOT NULL CHECK (dimension > 0),
        distance TEXT NOT NULL,
        normalize INTEGER NOT NULL CHECK (normalize IN (0, 1)),
        vector_provider TEXT NOT NULL,
        vector_table TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('active', 'obsolete', 'failed')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_embedding_manifests_status
    ON embedding_manifests(status)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_embedding_manifests_provider_model
    ON embedding_manifests(provider, model)
    """,
    """
    CREATE TABLE IF NOT EXISTS embedding_runs (
        id INTEGER PRIMARY KEY,
        manifest_id INTEGER NOT NULL REFERENCES embedding_manifests(id),
        mode TEXT NOT NULL CHECK (mode IN ('incremental', 'full', 'partial')),
        status TEXT NOT NULL CHECK (
            status IN (
                'running',
                'completed',
                'completed_with_errors',
                'failed',
                'interrupted'
            )
        ),
        scope_json TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        new_chunks INTEGER NOT NULL DEFAULT 0 CHECK (new_chunks >= 0),
        updated_chunks INTEGER NOT NULL DEFAULT 0 CHECK (updated_chunks >= 0),
        unchanged_chunks INTEGER NOT NULL DEFAULT 0 CHECK (unchanged_chunks >= 0),
        deleted_chunks INTEGER NOT NULL DEFAULT 0 CHECK (deleted_chunks >= 0),
        failed_chunks INTEGER NOT NULL DEFAULT 0 CHECK (failed_chunks >= 0),
        duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
        embedding_ms INTEGER CHECK (embedding_ms IS NULL OR embedding_ms >= 0),
        vector_ms INTEGER CHECK (vector_ms IS NULL OR vector_ms >= 0)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_embedding_runs_manifest_id
    ON embedding_runs(manifest_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_embedding_runs_started_at
    ON embedding_runs(started_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS chunk_embeddings (
        chunk_id TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
        manifest_id INTEGER NOT NULL REFERENCES embedding_manifests(id),
        content_sha256 TEXT NOT NULL,
        status TEXT NOT NULL CHECK (
            status IN ('indexed', 'stale', 'deleted', 'error')
        ),
        vector_ref TEXT NOT NULL,
        last_run_id INTEGER REFERENCES embedding_runs(id),
        error_code TEXT,
        error_message TEXT,
        symbol_name TEXT,
        symbol_kind TEXT,
        parent_symbol TEXT,
        package_name TEXT,
        procedure_name TEXT,
        class_name TEXT,
        event_name TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY(chunk_id, manifest_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_manifest_status
    ON chunk_embeddings(manifest_id, status)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_symbols
    ON chunk_embeddings(symbol_name, symbol_kind)
    """,
    """
    CREATE TABLE IF NOT EXISTS rag_queries (
        id INTEGER PRIMARY KEY,
        manifest_id INTEGER REFERENCES embedding_manifests(id),
        query_text_sha256 TEXT NOT NULL,
        mode TEXT NOT NULL CHECK (mode IN ('semantic', 'keyword', 'hybrid')),
        top_k INTEGER NOT NULL CHECK (top_k > 0),
        filters_json TEXT NOT NULL,
        candidate_count INTEGER NOT NULL DEFAULT 0 CHECK (candidate_count >= 0),
        context_sources INTEGER NOT NULL DEFAULT 0 CHECK (context_sources >= 0),
        vector_ms INTEGER CHECK (vector_ms IS NULL OR vector_ms >= 0),
        keyword_ms INTEGER CHECK (keyword_ms IS NULL OR keyword_ms >= 0),
        ranking_ms INTEGER CHECK (ranking_ms IS NULL OR ranking_ms >= 0),
        context_ms INTEGER CHECK (context_ms IS NULL OR context_ms >= 0),
        llm_ms INTEGER CHECK (llm_ms IS NULL OR llm_ms >= 0),
        context_precision REAL CHECK (
            context_precision IS NULL
            OR (context_precision >= 0 AND context_precision <= 1)
        ),
        context_recall REAL CHECK (
            context_recall IS NULL
            OR (context_recall >= 0 AND context_recall <= 1)
        ),
        duplicate_ratio REAL CHECK (
            duplicate_ratio IS NULL
            OR (duplicate_ratio >= 0 AND duplicate_ratio <= 1)
        ),
        token_waste REAL CHECK (
            token_waste IS NULL OR (token_waste >= 0 AND token_waste <= 1)
        ),
        status TEXT NOT NULL CHECK (
            status IN ('completed', 'insufficient_evidence', 'error')
        ),
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_rag_queries_created_at
    ON rag_queries(created_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS symbol_occurrences (
        id INTEGER PRIMARY KEY,
        chunk_id TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
        symbol_name TEXT,
        symbol_kind TEXT,
        line_start INTEGER CHECK (line_start IS NULL OR line_start > 0),
        line_end INTEGER CHECK (line_end IS NULL OR line_end > 0),
        CHECK ((line_start IS NULL AND line_end IS NULL) OR line_end >= line_start)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_symbol_occurrences_chunk_id
    ON symbol_occurrences(chunk_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_symbol_occurrences_symbol
    ON symbol_occurrences(symbol_name, symbol_kind)
    """,
)


class SQLiteIngestionError(RuntimeError):
    """Error de persistencia SQLite durante ingesta."""


@dataclass(frozen=True, slots=True)
class InventoryStats:
    """Resumen persistido consultable sin reescanear filesystem."""

    latest_run_id: int | None
    latest_run_status: str | None
    files_current: int
    documents_current: int
    chunks_current: int
    artifact_kinds: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class SQLiteIngestionRepository:
    """Repositorio H2 respaldado por SQLite local."""

    database_path: Path
    domain: str = "default"

    def begin_run(
        self,
        *,
        domain: str,
        mode: IngestionMode,
        roots: Sequence[Path],
        config_sha256: str,
    ) -> int:
        now = _utc_now()
        roots_json = _canonical_json([str(root) for root in roots])
        with self._connect() as connection:
            cursor = _execute_with_retries(
                connection,
                """
                INSERT INTO ingestion_runs(
                    domain, mode, status, roots_json, config_sha256, started_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    domain,
                    mode.value,
                    IngestionRunStatus.RUNNING.value,
                    roots_json,
                    config_sha256,
                    now,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def get_file_state(
        self,
        *,
        domain: str,
        discovered_file: DiscoveredFile,
    ) -> PersistedFileState | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT size_bytes, modified_at_ns, sha256, status, processing_signature
                FROM files
                WHERE domain = ? AND source_root = ? AND relative_path = ?
                """,
                (
                    domain,
                    _source_root(discovered_file),
                    discovered_file.relative_path.as_posix(),
                ),
            ).fetchone()
        if row is None:
            return None
        return PersistedFileState(
            size_bytes=int(row["size_bytes"]),
            mtime_ns=int(row["modified_at_ns"]),
            sha256=row["sha256"],
            status=FileStatus(row["status"]),
            processing_signature=row["processing_signature"],
        )

    def replace_document(
        self,
        *,
        run_id: int,
        discovered_file: DiscoveredFile,
        fingerprint: FileFingerprint,
        processing_signature: str,
        parser_id: str,
        parser_version: str,
        encoding: str | None,
        document: NormalizedDocument,
        chunks: Sequence[ChunkCandidate],
    ) -> None:
        if fingerprint.sha256 is None:
            raise SQLiteIngestionError("DATABASE_WRITE_FAILED: falta SHA-256.")
        if not chunks:
            raise SQLiteIngestionError("DATABASE_WRITE_FAILED: faltan chunks.")
        now = _utc_now()
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                file_id = self._upsert_file(
                    connection,
                    run_id=run_id,
                    discovered_file=discovered_file,
                    fingerprint=fingerprint,
                    processing_signature=processing_signature,
                    parser_id=parser_id,
                    parser_version=parser_version,
                    encoding=encoding,
                    status=FileStatus.PROCESSED,
                    now=now,
                )
                connection.execute("DELETE FROM documents WHERE file_id = ?", (file_id,))
                cursor = connection.execute(
                    """
                    INSERT INTO documents(
                        file_id, source_sha256, parser_id, parser_version,
                        normalizer_version, title, normalized_text, content_sha256,
                        metadata_json, warnings_json, extracted_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        file_id,
                        document.source_sha256,
                        parser_id,
                        parser_version,
                        str(document.metadata.get("normalizer_version", NORMALIZER_VERSION)),
                        str(document.metadata.get("title") or ""),
                        document.text,
                        document.content_sha256,
                        _canonical_json(document.metadata),
                        _canonical_json(document.metadata.get("warnings", ())),
                        now,
                    ),
                )
                document_id = int(cursor.lastrowid)
                for chunk in chunks:
                    if chunk.chunk_id is None:
                        raise SQLiteIngestionError(
                            "DATABASE_WRITE_FAILED: chunk sin ID determinista."
                        )
                    connection.execute(
                        """
                        INSERT INTO chunks(
                            id, document_id, ordinal, chunk_type, content,
                            content_sha256, start_line, end_line, start_char,
                            end_char, page_start, page_end, object_type,
                            object_name, metadata_json, chunker_version, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            chunk.chunk_id,
                            document_id,
                            chunk.ordinal,
                            chunk.chunk_type,
                            chunk.content,
                            chunk.content_sha256,
                            chunk.start_line,
                            chunk.end_line,
                            chunk.start_char,
                            chunk.end_char,
                            chunk.page_start,
                            chunk.page_end,
                            chunk.object_type,
                            chunk.object_name,
                            canonical_chunk_metadata(chunk.metadata),
                            str(chunk.metadata.get("chunker_version", CHUNKER_VERSION)),
                            now,
                        ),
                    )
                connection.commit()
            except Exception as exc:
                connection.rollback()
                if isinstance(exc, SQLiteIngestionError):
                    raise
                raise SQLiteIngestionError(f"{DATABASE_WRITE_FAILED}: {exc}") from exc

    def mark_seen(
        self,
        *,
        run_id: int,
        discovered_file: DiscoveredFile,
        state: PersistedFileState,
    ) -> None:
        self.mark_seen_many(run_id=run_id, seen_files=((discovered_file, state),))

    def mark_seen_many(
        self,
        *,
        run_id: int,
        seen_files: Sequence[tuple[DiscoveredFile, PersistedFileState]],
    ) -> None:
        if not seen_files:
            return
        now = _utc_now()
        parameters = [
            (
                discovered_file.size_bytes,
                discovered_file.mtime_ns,
                run_id,
                now,
                self.domain,
                _source_root(discovered_file),
                discovered_file.relative_path.as_posix(),
            )
            for discovered_file, _state in seen_files
        ]
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.executemany(
                    """
                    UPDATE files
                    SET size_bytes = ?, modified_at_ns = ?, last_seen_run_id = ?,
                        updated_at = ?, deleted_at = NULL
                    WHERE domain = ? AND source_root = ? AND relative_path = ?
                    """,
                    parameters,
                )
                connection.commit()
            except Exception as exc:
                connection.rollback()
                raise SQLiteIngestionError(f"{DATABASE_WRITE_FAILED}: {exc}") from exc

    def record_skipped(
        self,
        *,
        run_id: int,
        discovered_file: DiscoveredFile,
        error: PipelineError,
    ) -> None:
        now = _utc_now()
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                file_id = self._upsert_file(
                    connection,
                    run_id=run_id,
                    discovered_file=discovered_file,
                    fingerprint=FileFingerprint(
                        size_bytes=discovered_file.size_bytes,
                        mtime_ns=discovered_file.mtime_ns,
                        sha256=None,
                    ),
                    processing_signature=None,
                    parser_id=None,
                    parser_version=None,
                    encoding=None,
                    status=FileStatus.SKIPPED,
                    now=now,
                    skip_reason=error.error_code,
                )
                connection.execute("DELETE FROM documents WHERE file_id = ?", (file_id,))
                self._insert_error(connection, run_id=run_id, file_id=file_id, error=error)
                connection.commit()
            except Exception as exc:
                connection.rollback()
                raise SQLiteIngestionError(f"{DATABASE_WRITE_FAILED}: {exc}") from exc

    def record_error(
        self,
        *,
        run_id: int,
        error: PipelineError,
        discovered_file: DiscoveredFile | None = None,
    ) -> None:
        now = _utc_now()
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                file_id = None
                if discovered_file is not None:
                    file_id = self._file_id(connection, discovered_file)
                    if file_id is None:
                        file_id = self._upsert_file(
                            connection,
                            run_id=run_id,
                            discovered_file=discovered_file,
                            fingerprint=FileFingerprint(
                                size_bytes=discovered_file.size_bytes,
                                mtime_ns=discovered_file.mtime_ns,
                                sha256=None,
                            ),
                            processing_signature=None,
                            parser_id=None,
                            parser_version=None,
                            encoding=None,
                            status=FileStatus.ERROR,
                            now=now,
                            skip_reason=error.error_code,
                        )
                    else:
                        connection.execute(
                            """
                            UPDATE files
                            SET status = 'error', skip_reason = ?, updated_at = ?,
                                last_seen_run_id = ?
                            WHERE id = ?
                            """,
                            (error.error_code, now, run_id, file_id),
                        )
                self._insert_error(connection, run_id=run_id, file_id=file_id, error=error)
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def reconcile_deleted(
        self,
        *,
        run_id: int,
        domain: str,
        completed_roots: Sequence[Path],
    ) -> int:
        deleted = 0
        now = _utc_now()
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                for root in completed_roots:
                    rows = connection.execute(
                        """
                        SELECT id
                        FROM files
                        WHERE domain = ?
                          AND source_root = ?
                          AND last_seen_run_id <> ?
                          AND status <> 'deleted'
                        """,
                        (domain, str(Path(root).resolve(strict=False)), run_id),
                    ).fetchall()
                    for row in rows:
                        file_id = int(row["id"])
                        connection.execute("DELETE FROM documents WHERE file_id = ?", (file_id,))
                        connection.execute(
                            """
                            UPDATE files
                            SET status = 'deleted', deleted_at = ?, updated_at = ?,
                                last_seen_run_id = ?
                            WHERE id = ?
                            """,
                            (now, now, run_id, file_id),
                        )
                        deleted += 1
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return deleted

    def finish_run(
        self,
        *,
        run_id: int,
        outcome: IngestionOutcome,
    ) -> None:
        with self._connect() as connection:
            _execute_with_retries(
                connection,
                """
                UPDATE ingestion_runs
                SET status = ?, finished_at = ?, discovered_files = ?,
                    processed_files = ?, unchanged_files = ?, skipped_files = ?,
                    deleted_files = ?, error_count = ?, source_bytes = ?,
                    processed_bytes = ?, chunk_count = ?, duration_ms = ?
                WHERE id = ?
                """,
                (
                    outcome.status.value,
                    _utc_now(),
                    outcome.metrics.discovered_files,
                    outcome.metrics.processed_files,
                    outcome.metrics.unchanged_files,
                    outcome.metrics.skipped_files,
                    outcome.metrics.deleted_files,
                    outcome.metrics.error_count,
                    outcome.metrics.source_bytes,
                    outcome.metrics.processed_bytes,
                    outcome.metrics.chunk_count,
                    outcome.metrics.duration_ms,
                    run_id,
                ),
            )
            connection.commit()

    def current_metrics(self) -> IngestionMetrics:
        with self._connect() as connection:
            files = connection.execute(
                "SELECT COUNT(*) FROM files WHERE status = 'processed'"
            ).fetchone()[0]
            chunks = connection.execute(
                """
                SELECT COUNT(*)
                FROM chunks
                JOIN documents ON documents.id = chunks.document_id
                JOIN files ON files.id = documents.file_id
                WHERE files.status = 'processed'
                  AND documents.source_sha256 = files.sha256
                """
            ).fetchone()[0]
        return IngestionMetrics(processed_files=int(files), chunk_count=int(chunks))

    def inventory_stats(self) -> InventoryStats:
        """Consulta inventario vigente usando solo metadata persistida."""

        with self._connect_readonly() as connection:
            latest_run = connection.execute(
                """
                SELECT id, status
                FROM ingestion_runs
                ORDER BY started_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
            files_current = connection.execute(
                "SELECT COUNT(*) FROM files WHERE status = 'processed'"
            ).fetchone()[0]
            documents_current = connection.execute(
                """
                SELECT COUNT(*)
                FROM documents
                JOIN files ON files.id = documents.file_id
                WHERE files.status = 'processed'
                  AND documents.source_sha256 = files.sha256
                """
            ).fetchone()[0]
            chunks_current = connection.execute(
                """
                SELECT COUNT(*)
                FROM chunks
                JOIN documents ON documents.id = chunks.document_id
                JOIN files ON files.id = documents.file_id
                WHERE files.status = 'processed'
                  AND documents.source_sha256 = files.sha256
                """
            ).fetchone()[0]
            artifact_kinds = tuple(
                (str(row["artifact_kind"]), int(row["count"]))
                for row in connection.execute(
                    """
                    SELECT artifact_kind, COUNT(*) AS count
                    FROM files
                    WHERE status = 'processed'
                    GROUP BY artifact_kind
                    ORDER BY artifact_kind
                    """
                ).fetchall()
            )
        return InventoryStats(
            latest_run_id=None if latest_run is None else int(latest_run["id"]),
            latest_run_status=None if latest_run is None else str(latest_run["status"]),
            files_current=int(files_current),
            documents_current=int(documents_current),
            chunks_current=int(chunks_current),
            artifact_kinds=artifact_kinds,
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _connect_readonly(self) -> sqlite3.Connection:
        uri = self.database_path.resolve(strict=False).as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _upsert_file(
        self,
        connection: sqlite3.Connection,
        *,
        run_id: int,
        discovered_file: DiscoveredFile,
        fingerprint: FileFingerprint,
        processing_signature: str | None,
        parser_id: str | None,
        parser_version: str | None,
        encoding: str | None,
        status: FileStatus,
        now: str,
        skip_reason: str | None = None,
    ) -> int:
        row = connection.execute(
            """
            SELECT id FROM files
            WHERE domain = ? AND source_root = ? AND relative_path = ?
            """,
            (
                self.domain,
                _source_root(discovered_file),
                discovered_file.relative_path.as_posix(),
            ),
        ).fetchone()
        values = (
            self.domain,
            _source_root(discovered_file),
            discovered_file.relative_path.as_posix(),
            discovered_file.extension,
            _artifact_kind(discovered_file.extension),
            _media_type(discovered_file.extension),
            fingerprint.size_bytes,
            fingerprint.mtime_ns,
            fingerprint.sha256,
            fingerprint.version,
            processing_signature,
            parser_id,
            parser_version,
            encoding,
            status.value,
            skip_reason,
            run_id,
            now,
            now,
        )
        if row is None:
            cursor = connection.execute(
                """
                INSERT INTO files(
                    domain, source_root, relative_path, extension, artifact_kind,
                    media_type, size_bytes, modified_at_ns, sha256,
                    fingerprint_version, processing_signature, parser_id,
                    parser_version, encoding, status, skip_reason,
                    first_seen_run_id, last_seen_run_id, created_at, updated_at,
                    processed_at, deleted_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    *values[:17],
                    run_id,
                    *values[17:],
                    now if status == FileStatus.PROCESSED else None,
                ),
            )
            return int(cursor.lastrowid)
        file_id = int(row["id"])
        connection.execute(
            """
            UPDATE files
            SET extension = ?, artifact_kind = ?, media_type = ?,
                size_bytes = ?, modified_at_ns = ?, sha256 = ?,
                fingerprint_version = ?, processing_signature = ?,
                parser_id = ?, parser_version = ?, encoding = ?, status = ?,
                skip_reason = ?, last_seen_run_id = ?, updated_at = ?,
                processed_at = CASE WHEN ? = 'processed' THEN ? ELSE processed_at END,
                deleted_at = NULL
            WHERE id = ?
            """,
            (
                discovered_file.extension,
                _artifact_kind(discovered_file.extension),
                _media_type(discovered_file.extension),
                fingerprint.size_bytes,
                fingerprint.mtime_ns,
                fingerprint.sha256,
                fingerprint.version,
                processing_signature,
                parser_id,
                parser_version,
                encoding,
                status.value,
                skip_reason,
                run_id,
                now,
                status.value,
                now,
                file_id,
            ),
        )
        return file_id

    def _file_id(
        self,
        connection: sqlite3.Connection,
        discovered_file: DiscoveredFile,
    ) -> int | None:
        row = connection.execute(
            """
            SELECT id FROM files
            WHERE domain = ? AND source_root = ? AND relative_path = ?
            """,
            (
                self.domain,
                _source_root(discovered_file),
                discovered_file.relative_path.as_posix(),
            ),
        ).fetchone()
        return None if row is None else int(row["id"])

    def _insert_error(
        self,
        connection: sqlite3.Connection,
        *,
        run_id: int,
        file_id: int | None,
        error: PipelineError,
    ) -> None:
        connection.execute(
            """
            INSERT INTO errors(
                run_id, file_id, stage, error_code, message, exception_type,
                recoverable, details_json, occurred_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                file_id,
                error.stage.value,
                error.error_code,
                error.message,
                error.exception_type,
                1 if error.recoverable else 0,
                _canonical_json(error.details),
                _utc_now(),
            ),
        )


@dataclass(frozen=True, slots=True)
class PersistedEmbeddingManifest:
    """Manifest de embeddings persistido en SQLite."""

    id: int
    manifest: EmbeddingManifest
    vector_provider: str
    vector_table: str
    status: EmbeddingManifestStatus


@dataclass(frozen=True, slots=True)
class EmbeddingManifestSummary:
    """Resumen read-only de un manifest y sus chunks."""

    id: int
    version: str
    provider: str
    model: str
    dimension: int
    distance: str
    normalize: bool
    vector_provider: str
    vector_table: str
    status: str
    indexed: int
    stale: int
    deleted: int
    error: int


@dataclass(frozen=True, slots=True)
class EmbeddingErrorDetail:
    """Detalle read-only de un error de embedding persistido por chunk."""

    run_id: int
    chunk_id: str
    error_code: str
    error_message: str


@dataclass(frozen=True, slots=True)
class RagInventoryStats:
    """Metricas persistidas de RAG para CLI stats."""

    manifests: int
    active_manifests: int
    indexed_chunks: int
    stale_chunks: int
    deleted_chunks: int
    error_chunks: int
    query_count: int
    latest_query_id: int | None
    latest_query_status: str | None
    avg_candidate_count: float | None


@dataclass(frozen=True, slots=True)
class SQLiteRagRepository:
    """Repositorio minimo H3 respaldado por SQLite local."""

    database_path: Path
    vector_provider: str = "sqlite_vec"
    vector_table: str = "rag_chunk_vectors"

    def get_or_create_manifest(
        self,
        manifest: EmbeddingManifest,
        *,
        status: EmbeddingManifestStatus = EmbeddingManifestStatus.ACTIVE,
    ) -> PersistedEmbeddingManifest:
        """Obtiene o crea un manifest de embeddings por version canonica."""
        now = _utc_now()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, version, provider, model, dimension, distance,
                       normalize, vector_provider, vector_table, status
                FROM embedding_manifests
                WHERE version = ?
                """,
                (manifest.version,),
            ).fetchone()
            if row is None:
                cursor = connection.execute(
                    """
                    INSERT INTO embedding_manifests(
                        version, provider, model, dimension, distance, normalize,
                        vector_provider, vector_table, status, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        manifest.version,
                        manifest.provider,
                        manifest.model,
                        manifest.dimension,
                        manifest.distance,
                        1 if manifest.normalize else 0,
                        self.vector_provider,
                        self.vector_table,
                        status.value,
                        now,
                        now,
                    ),
                )
                connection.commit()
                manifest_id = int(cursor.lastrowid)
                return PersistedEmbeddingManifest(
                    id=manifest_id,
                    manifest=manifest,
                    vector_provider=self.vector_provider,
                    vector_table=self.vector_table,
                    status=status,
                )
        return _manifest_from_row(row)

    def find_active_manifest(
        self,
        *,
        provider: str,
        model: str,
        distance: str,
        normalize: bool,
    ) -> PersistedEmbeddingManifest | None:
        """Busca un manifest activo compatible con la configuracion."""
        with self._connect_readonly() as connection:
            row = connection.execute(
                """
                SELECT id, version, provider, model, dimension, distance,
                       normalize, vector_provider, vector_table, status
                FROM embedding_manifests
                WHERE provider = ?
                  AND model = ?
                  AND distance = ?
                  AND normalize = ?
                  AND status = 'active'
                ORDER BY id DESC
                LIMIT 1
                """,
                (provider, model, distance, 1 if normalize else 0),
            ).fetchone()
        return None if row is None else _manifest_from_row(row)

    def mark_other_manifests_obsolete(self, active_version: str) -> int:
        """Marca obsoletos los manifests activos que no coinciden con la version."""
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE embedding_manifests
                SET status = 'obsolete', updated_at = ?
                WHERE version <> ? AND status = 'active'
                """,
                (_utc_now(), active_version),
            )
            connection.commit()
            return int(cursor.rowcount)

    def list_manifests(self) -> tuple[PersistedEmbeddingManifest, ...]:
        """Lista manifests de embeddings en orden estable."""
        with self._connect_readonly() as connection:
            rows = connection.execute(
                """
                SELECT id, version, provider, model, dimension, distance,
                       normalize, vector_provider, vector_table, status
                FROM embedding_manifests
                ORDER BY id
                """
            ).fetchall()
        return tuple(_manifest_from_row(row) for row in rows)

    def embedding_summaries(self) -> tuple[EmbeddingManifestSummary, ...]:
        """Devuelve manifests y conteos por estado sin mutar SQLite."""
        with self._connect_readonly() as connection:
            rows = connection.execute(
                """
                SELECT
                    manifests.id,
                    manifests.version,
                    manifests.provider,
                    manifests.model,
                    manifests.dimension,
                    manifests.distance,
                    manifests.normalize,
                    manifests.vector_provider,
                    manifests.vector_table,
                    manifests.status,
                    COALESCE(SUM(CASE WHEN chunks.status = 'indexed' THEN 1 ELSE 0 END), 0) AS indexed,
                    COALESCE(SUM(CASE WHEN chunks.status = 'stale' THEN 1 ELSE 0 END), 0) AS stale,
                    COALESCE(SUM(CASE WHEN chunks.status = 'deleted' THEN 1 ELSE 0 END), 0) AS deleted,
                    COALESCE(SUM(CASE WHEN chunks.status = 'error' THEN 1 ELSE 0 END), 0) AS error
                FROM embedding_manifests AS manifests
                LEFT JOIN chunk_embeddings AS chunks
                  ON chunks.manifest_id = manifests.id
                GROUP BY manifests.id
                ORDER BY manifests.status = 'active' DESC, manifests.id DESC
                """
            ).fetchall()
        return tuple(_embedding_summary_from_row(row) for row in rows)

    def latest_embedding_error_run_id(self) -> int | None:
        """Devuelve el ultimo run con errores de indexacion."""
        with self._connect_readonly() as connection:
            row = connection.execute(
                """
                SELECT id
                FROM embedding_runs
                WHERE failed_chunks > 0
                   OR EXISTS (
                       SELECT 1
                       FROM chunk_embeddings
                       WHERE chunk_embeddings.last_run_id = embedding_runs.id
                         AND chunk_embeddings.status = 'error'
                   )
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        return None if row is None else int(row["id"])

    def embedding_error_details(
        self,
        *,
        run_id: int | None = None,
    ) -> tuple[EmbeddingErrorDetail, ...]:
        """Lista errores de indexacion persistidos en SQLite."""
        selected_run_id = run_id
        if selected_run_id is None:
            selected_run_id = self.latest_embedding_error_run_id()
        if selected_run_id is None:
            return ()
        with self._connect_readonly() as connection:
            rows = connection.execute(
                """
                SELECT last_run_id, chunk_id, error_code, error_message
                FROM chunk_embeddings
                WHERE status = 'error'
                  AND last_run_id = ?
                ORDER BY chunk_id
                """,
                (selected_run_id,),
            ).fetchall()
        return tuple(
            EmbeddingErrorDetail(
                run_id=int(row["last_run_id"]),
                chunk_id=str(row["chunk_id"]),
                error_code=str(row["error_code"] or ""),
                error_message=str(row["error_message"] or ""),
            )
            for row in rows
        )

    def dominant_embedding_error_code(self, *, run_id: int) -> str | None:
        """Devuelve el codigo de error mas frecuente de un run."""
        with self._connect_readonly() as connection:
            row = connection.execute(
                """
                SELECT error_code, COUNT(*) AS count
                FROM chunk_embeddings
                WHERE status = 'error'
                  AND last_run_id = ?
                  AND error_code IS NOT NULL
                GROUP BY error_code
                ORDER BY count DESC, error_code
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        return None if row is None else str(row["error_code"])

    def rag_inventory_stats(self) -> RagInventoryStats:
        """Devuelve metricas RAG persistidas para stats."""
        with self._connect_readonly() as connection:
            manifest_row = connection.execute(
                """
                SELECT
                    COUNT(*) AS manifests,
                    COALESCE(SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END), 0)
                        AS active_manifests
                FROM embedding_manifests
                """
            ).fetchone()
            chunk_row = connection.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN status = 'indexed' THEN 1 ELSE 0 END), 0) AS indexed,
                    COALESCE(SUM(CASE WHEN status = 'stale' THEN 1 ELSE 0 END), 0) AS stale,
                    COALESCE(SUM(CASE WHEN status = 'deleted' THEN 1 ELSE 0 END), 0) AS deleted,
                    COALESCE(SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END), 0) AS error
                FROM chunk_embeddings
                """
            ).fetchone()
            query_row = connection.execute(
                """
                SELECT
                    COUNT(*) AS query_count,
                    MAX(id) AS latest_query_id,
                    AVG(candidate_count) AS avg_candidate_count
                FROM rag_queries
                """
            ).fetchone()
            latest_query_status = None
            if query_row["latest_query_id"] is not None:
                latest_query_status = connection.execute(
                    "SELECT status FROM rag_queries WHERE id = ?",
                    (query_row["latest_query_id"],),
                ).fetchone()["status"]
        return RagInventoryStats(
            manifests=int(manifest_row["manifests"]),
            active_manifests=int(manifest_row["active_manifests"]),
            indexed_chunks=int(chunk_row["indexed"]),
            stale_chunks=int(chunk_row["stale"]),
            deleted_chunks=int(chunk_row["deleted"]),
            error_chunks=int(chunk_row["error"]),
            query_count=int(query_row["query_count"]),
            latest_query_id=(
                None
                if query_row["latest_query_id"] is None
                else int(query_row["latest_query_id"])
            ),
            latest_query_status=latest_query_status,
            avg_candidate_count=(
                None
                if query_row["avg_candidate_count"] is None
                else float(query_row["avg_candidate_count"])
            ),
        )

    def indexable_chunks(
        self,
        *,
        domain: str,
        scope: IndexScope | None = None,
    ) -> tuple[IndexableChunk, ...]:
        """Devuelve chunks vigentes de H2 con metadata filtrable."""
        clauses = [
            "files.status = 'processed'",
            "files.domain = ?",
            "documents.source_sha256 = files.sha256",
        ]
        parameters: list[object] = [domain]
        if scope is not None:
            if scope.path_prefix is not None:
                clauses.append("files.relative_path LIKE ?")
                parameters.append(f"{scope.path_prefix.rstrip('/')}%")
            if scope.document_id is not None:
                clauses.append("documents.id = ?")
                parameters.append(scope.document_id)
            if scope.chunk_id is not None:
                clauses.append("chunks.id = ?")
                parameters.append(scope.chunk_id)
        where = " AND ".join(clauses)
        with self._connect_readonly() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    chunks.id AS chunk_id,
                    chunks.content AS content,
                    chunks.content_sha256 AS content_sha256,
                    chunks.object_type AS object_type,
                    chunks.object_name AS object_name,
                    chunks.metadata_json AS chunk_metadata_json,
                    documents.id AS document_id,
                    files.id AS file_id,
                    files.domain AS domain,
                    files.artifact_kind AS artifact_kind,
                    files.relative_path AS relative_path,
                    files.extension AS extension
                FROM chunks
                JOIN documents ON documents.id = chunks.document_id
                JOIN files ON files.id = documents.file_id
                WHERE {where}
                ORDER BY files.relative_path, chunks.ordinal, chunks.id
                """,
                tuple(parameters),
            ).fetchall()
        return tuple(_indexable_chunk_from_row(row) for row in rows)

    def chunk_embedding_states(
        self,
        *,
        manifest_id: int,
        scope: IndexScope | None = None,
    ) -> dict[str, ChunkEmbeddingState]:
        """Devuelve estado persistido por chunk para un manifest."""
        clauses = ["manifest_id = ?"]
        parameters: list[object] = [manifest_id]
        if scope is not None and scope.chunk_id is not None:
            clauses.append("chunk_id = ?")
            parameters.append(scope.chunk_id)
        where = " AND ".join(clauses)
        with self._connect_readonly() as connection:
            rows = connection.execute(
                f"""
                SELECT chunk_id, content_sha256, status
                FROM chunk_embeddings
                WHERE {where}
                ORDER BY chunk_id
                """,
                tuple(parameters),
            ).fetchall()
        return {
            str(row["chunk_id"]): ChunkEmbeddingState(
                chunk_id=str(row["chunk_id"]),
                content_sha256=str(row["content_sha256"]),
                status=ChunkEmbeddingStatus(str(row["status"])),
            )
            for row in rows
        }

    def begin_embedding_run(
        self,
        *,
        manifest_id: int,
        mode: EmbeddingRunMode,
        scope: IndexScope | None,
    ) -> int:
        """Crea una corrida de indexacion H3."""
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO embedding_runs(
                    manifest_id, mode, status, scope_json, started_at
                )
                VALUES (?, ?, 'running', ?, ?)
                """,
                (
                    manifest_id,
                    mode.value,
                    _canonical_json(_scope_json(scope)),
                    _utc_now(),
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def record_chunk_indexed(
        self,
        *,
        run_id: int,
        manifest_id: int,
        chunk: IndexableChunk,
    ) -> None:
        """Marca un chunk como indexado para un manifest."""
        now = _utc_now()
        symbols = chunk.metadata.symbols
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO chunk_embeddings(
                    chunk_id, manifest_id, content_sha256, status, vector_ref,
                    last_run_id, symbol_name, symbol_kind, parent_symbol,
                    package_name, procedure_name, class_name, event_name,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, 'indexed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chunk_id, manifest_id) DO UPDATE SET
                    content_sha256 = excluded.content_sha256,
                    status = 'indexed',
                    vector_ref = excluded.vector_ref,
                    last_run_id = excluded.last_run_id,
                    error_code = NULL,
                    error_message = NULL,
                    symbol_name = excluded.symbol_name,
                    symbol_kind = excluded.symbol_kind,
                    parent_symbol = excluded.parent_symbol,
                    package_name = excluded.package_name,
                    procedure_name = excluded.procedure_name,
                    class_name = excluded.class_name,
                    event_name = excluded.event_name,
                    updated_at = excluded.updated_at
                """,
                (
                    chunk.chunk_id,
                    manifest_id,
                    chunk.metadata.content_sha256,
                    chunk.chunk_id,
                    run_id,
                    symbols.symbol_name,
                    symbols.symbol_kind,
                    symbols.parent_symbol,
                    symbols.package_name,
                    symbols.procedure_name,
                    symbols.class_name,
                    symbols.event_name,
                    now,
                    now,
                ),
            )
            connection.commit()

    def record_chunk_error(
        self,
        *,
        run_id: int,
        manifest_id: int,
        chunk: IndexableChunk,
        error_code: str,
        error_message: str,
    ) -> None:
        """Marca un chunk con error recuperable de indexacion."""
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO chunk_embeddings(
                    chunk_id, manifest_id, content_sha256, status, vector_ref,
                    last_run_id, error_code, error_message, created_at, updated_at
                )
                VALUES (?, ?, ?, 'error', ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chunk_id, manifest_id) DO UPDATE SET
                    content_sha256 = excluded.content_sha256,
                    status = 'error',
                    last_run_id = excluded.last_run_id,
                    error_code = excluded.error_code,
                    error_message = excluded.error_message,
                    updated_at = excluded.updated_at
                """,
                (
                    chunk.chunk_id,
                    manifest_id,
                    chunk.metadata.content_sha256,
                    chunk.chunk_id,
                    run_id,
                    error_code,
                    error_message,
                    now,
                    now,
                ),
            )
            connection.commit()

    def mark_chunk_deleted(
        self,
        *,
        run_id: int,
        manifest_id: int,
        chunk_id: str,
    ) -> None:
        """Marca un chunk como eliminado para un manifest."""
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE chunk_embeddings
                SET status = 'deleted', last_run_id = ?, updated_at = ?
                WHERE manifest_id = ? AND chunk_id = ?
                """,
                (run_id, _utc_now(), manifest_id, chunk_id),
            )
            connection.commit()

    def finish_embedding_run(
        self,
        *,
        run_id: int,
        status: EmbeddingRunStatus,
        new_chunks: int,
        updated_chunks: int,
        unchanged_chunks: int,
        deleted_chunks: int,
        failed_chunks: int,
        duration_ms: int,
    ) -> None:
        """Cierra una corrida de indexacion H3 con metricas."""
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE embedding_runs
                SET status = ?, finished_at = ?, new_chunks = ?,
                    updated_chunks = ?, unchanged_chunks = ?, deleted_chunks = ?,
                    failed_chunks = ?, duration_ms = ?
                WHERE id = ?
                """,
                (
                    status.value,
                    _utc_now(),
                    new_chunks,
                    updated_chunks,
                    unchanged_chunks,
                    deleted_chunks,
                    failed_chunks,
                    duration_ms,
                    run_id,
                ),
            )
            connection.commit()

    def keyword_search(
        self,
        *,
        domain: str,
        query: str,
        filters: RetrievalFilter,
        top_k: int,
    ) -> tuple[RetrievalCandidate, ...]:
        """Busca por keyword local con FTS5 si existe y fallback determinista."""
        if top_k <= 0:
            raise ValueError("top_k debe ser mayor que 0.")
        tokens = _keyword_tokens(query)
        if not tokens:
            return ()
        with self._connect() as connection:
            rows = _keyword_rows(
                connection,
                domain=domain,
                filters=filters,
                tokens=tokens,
            )
        candidates = []
        for row in rows:
            score = _keyword_score(str(row["content"]), tokens)
            if score <= 0:
                continue
            candidates.append(_candidate_from_chunk_row(row, keyword_score=score))
        candidates.sort(
            key=lambda item: (
                -float(item.keyword_score or 0),
                str(item.source.get("relative_path") or ""),
                int(item.source.get("ordinal") or 0),
                item.chunk_id,
            )
        )
        return tuple(candidates[:top_k])

    def enrich_candidates(
        self,
        candidates: tuple[RetrievalCandidate, ...],
        *,
        include_snippets: bool,
    ) -> tuple[RetrievalCandidate, ...]:
        """Completa metadata trazable desde SQLite para candidatos existentes."""
        if not candidates:
            return ()
        placeholders = ", ".join("?" for _ in candidates)
        with self._connect_readonly() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    chunks.id AS chunk_id,
                    chunks.content AS content,
                    chunks.content_sha256 AS content_sha256,
                    chunks.ordinal AS ordinal,
                    chunks.chunk_type AS chunk_type,
                    chunks.start_line AS start_line,
                    chunks.end_line AS end_line,
                    chunks.page_start AS page_start,
                    chunks.page_end AS page_end,
                    chunks.object_type AS object_type,
                    chunks.object_name AS object_name,
                    chunks.metadata_json AS chunk_metadata_json,
                    documents.id AS document_id,
                    files.id AS file_id,
                    files.domain AS domain,
                    files.artifact_kind AS artifact_kind,
                    files.relative_path AS relative_path,
                    files.extension AS extension
                FROM chunks
                JOIN documents ON documents.id = chunks.document_id
                JOIN files ON files.id = documents.file_id
                WHERE chunks.id IN ({placeholders})
                """,
                tuple(candidate.chunk_id for candidate in candidates),
            ).fetchall()
        by_id = {str(row["chunk_id"]): row for row in rows}
        enriched = []
        for candidate in candidates:
            row = by_id.get(candidate.chunk_id)
            if row is None:
                enriched.append(candidate)
                continue
            source = _source_from_chunk_row(row, include_content=include_snippets)
            source.update(dict(candidate.source))
            if include_snippets:
                source["snippet"] = _snippet(str(row["content"]))
            metadata = _symbols_from_chunk_metadata(str(row["chunk_metadata_json"]))
            enriched.append(
                RetrievalCandidate(
                    chunk_id=candidate.chunk_id,
                    content_sha256=str(row["content_sha256"]),
                    combined_score=candidate.combined_score,
                    vector_score=candidate.vector_score,
                    keyword_score=candidate.keyword_score,
                    metadata=metadata,
                    source=source,
                )
            )
        return tuple(enriched)

    def record_rag_query(
        self,
        *,
        manifest_id: int | None,
        query_text: str,
        mode: RetrievalMode,
        top_k: int,
        filters: RetrievalFilter,
        candidate_count: int,
        timings: SearchTimings,
        status: RagQueryStatus,
    ) -> int:
        """Registra una busqueda RAG para observabilidad local."""
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO rag_queries(
                    manifest_id, query_text_sha256, mode, top_k, filters_json,
                    candidate_count, vector_ms, keyword_ms, ranking_ms, status,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    manifest_id,
                    _sha256_text(query_text),
                    mode.value,
                    top_k,
                    _canonical_json(_filters_json(filters)),
                    candidate_count,
                    timings.vector_ms,
                    timings.keyword_ms,
                    timings.ranking_ms,
                    status.value,
                    _utc_now(),
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def update_rag_query_metrics(
        self,
        *,
        query_id: int | None,
        context_sources: int,
        context_ms: int | None,
        llm_ms: int | None,
        metrics: ContextQualityMetrics,
    ) -> None:
        """Completa metricas posteriores a search para ask/context."""
        if query_id is None:
            return
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE rag_queries
                SET context_sources = ?,
                    context_ms = ?,
                    llm_ms = ?,
                    context_precision = ?,
                    context_recall = ?,
                    duplicate_ratio = ?,
                    token_waste = ?
                WHERE id = ?
                """,
                (
                    context_sources,
                    context_ms,
                    llm_ms,
                    metrics.context_precision,
                    metrics.context_recall,
                    metrics.duplicate_ratio,
                    metrics.token_waste,
                    query_id,
                ),
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _connect_readonly(self) -> sqlite3.Connection:
        uri = self.database_path.resolve(strict=False).as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def _manifest_from_row(row: sqlite3.Row) -> PersistedEmbeddingManifest:
    manifest = EmbeddingManifest(
        provider=str(row["provider"]),
        model=str(row["model"]),
        dimension=int(row["dimension"]),
        distance=str(row["distance"]),
        normalize=bool(row["normalize"]),
        version=str(row["version"]),
    )
    return PersistedEmbeddingManifest(
        id=int(row["id"]),
        manifest=manifest,
        vector_provider=str(row["vector_provider"]),
        vector_table=str(row["vector_table"]),
        status=EmbeddingManifestStatus(str(row["status"])),
    )


def _embedding_summary_from_row(row: sqlite3.Row) -> EmbeddingManifestSummary:
    return EmbeddingManifestSummary(
        id=int(row["id"]),
        version=str(row["version"]),
        provider=str(row["provider"]),
        model=str(row["model"]),
        dimension=int(row["dimension"]),
        distance=str(row["distance"]),
        normalize=bool(row["normalize"]),
        vector_provider=str(row["vector_provider"]),
        vector_table=str(row["vector_table"]),
        status=str(row["status"]),
        indexed=int(row["indexed"]),
        stale=int(row["stale"]),
        deleted=int(row["deleted"]),
        error=int(row["error"]),
    )


def _indexable_chunk_from_row(row: sqlite3.Row) -> IndexableChunk:
    relative_path = str(row["relative_path"])
    folder = str(Path(relative_path).parent).replace("\\", "/")
    if folder == ".":
        folder = ""
    metadata_json = _loads_json_object(str(row["chunk_metadata_json"]))
    symbols = H4SymbolMetadata(
        symbol_name=_optional_text(metadata_json.get("symbol_name")),
        symbol_kind=_optional_text(metadata_json.get("symbol_kind")),
        parent_symbol=_optional_text(metadata_json.get("parent_symbol")),
        package_name=_optional_text(metadata_json.get("package_name")),
        procedure_name=_optional_text(metadata_json.get("procedure_name")),
        class_name=_optional_text(metadata_json.get("class_name")),
        event_name=_optional_text(metadata_json.get("event_name")),
    )
    return IndexableChunk(
        chunk_id=str(row["chunk_id"]),
        content=str(row["content"]),
        metadata=VectorMetadata(
            content_sha256=str(row["content_sha256"]),
            domain=str(row["domain"]),
            artifact_kind=str(row["artifact_kind"]),
            language=_language_for_artifact(str(row["artifact_kind"])),
            document_id=int(row["document_id"]),
            file_id=int(row["file_id"]),
            relative_path=relative_path,
            folder=folder,
            extension=str(row["extension"]),
            object_type=row["object_type"],
            object_name=row["object_name"],
            symbols=symbols,
        ),
    )


def _loads_json_object(raw_json: str) -> dict[str, Any]:
    try:
        value = json.loads(raw_json)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _language_for_artifact(artifact_kind: str) -> str | None:
    return {
        "oracle": "plsql",
        "powerbuilder": "powerscript",
        "markdown": "markdown",
        "pdf": "text",
        "docx": "text",
        "config": "config",
        "text": "text",
    }.get(artifact_kind)


def _scope_json(scope: IndexScope | None) -> dict[str, object | None]:
    if scope is None:
        return {"path_prefix": None, "document_id": None, "chunk_id": None}
    return {
        "path_prefix": scope.path_prefix,
        "document_id": scope.document_id,
        "chunk_id": scope.chunk_id,
    }


def _filters_json(filters: RetrievalFilter) -> dict[str, object | None]:
    return {
        "domain": filters.domain,
        "artifact_kind": filters.artifact_kind,
        "language": filters.language,
        "document_id": filters.document_id,
        "folder": filters.folder,
        "extension": filters.extension,
    }


def _keyword_tokens(query: str) -> tuple[str, ...]:
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\d+", query.lower())
    return tuple(dict.fromkeys(tokens))


def _keyword_rows(
    connection: sqlite3.Connection,
    *,
    domain: str,
    filters: RetrievalFilter,
    tokens: tuple[str, ...],
) -> tuple[sqlite3.Row, ...]:
    rows = _filtered_chunk_rows(connection, domain=domain, filters=filters)
    if not rows or not _fts5_available(connection):
        return rows
    connection.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS temp.rag_keyword_fts USING fts5(chunk_id UNINDEXED, content)"
    )
    connection.execute("DELETE FROM temp.rag_keyword_fts")
    connection.executemany(
        "INSERT INTO temp.rag_keyword_fts(chunk_id, content) VALUES (?, ?)",
        ((str(row["chunk_id"]), str(row["content"])) for row in rows),
    )
    fts_query = " OR ".join(f'"{token}"' for token in tokens)
    matched = connection.execute(
        "SELECT chunk_id FROM temp.rag_keyword_fts WHERE content MATCH ?",
        (fts_query,),
    ).fetchall()
    matched_ids = {str(row["chunk_id"]) for row in matched}
    return tuple(row for row in rows if str(row["chunk_id"]) in matched_ids)


def _fts5_available(connection: sqlite3.Connection) -> bool:
    try:
        connection.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS temp.rag_fts_probe USING fts5(value)"
        )
        connection.execute("DROP TABLE temp.rag_fts_probe")
    except sqlite3.OperationalError:
        return False
    return True


def _filtered_chunk_rows(
    connection: sqlite3.Connection,
    *,
    domain: str,
    filters: RetrievalFilter,
) -> tuple[sqlite3.Row, ...]:
    clauses = [
        "files.status = 'processed'",
        "files.domain = ?",
        "documents.source_sha256 = files.sha256",
    ]
    parameters: list[object] = [domain]
    if filters.domain is not None:
        clauses.append("files.domain = ?")
        parameters.append(filters.domain)
    if filters.artifact_kind is not None:
        clauses.append("files.artifact_kind = ?")
        parameters.append(filters.artifact_kind)
    if filters.document_id is not None:
        clauses.append("documents.id = ?")
        parameters.append(filters.document_id)
    if filters.folder is not None:
        clauses.append("files.relative_path LIKE ?")
        parameters.append(f"{filters.folder.rstrip('/')}%")
    if filters.extension is not None:
        clauses.append("files.extension = ?")
        parameters.append(filters.extension)
    if filters.language is not None:
        artifact_for_language = {
            "plsql": "oracle",
            "powerscript": "powerbuilder",
            "markdown": "markdown",
            "text": "text",
            "config": "config",
        }.get(filters.language)
        if artifact_for_language is not None:
            clauses.append("files.artifact_kind = ?")
            parameters.append(artifact_for_language)
    where = " AND ".join(clauses)
    return tuple(
        connection.execute(
            f"""
            SELECT
                chunks.id AS chunk_id,
                chunks.content AS content,
                chunks.content_sha256 AS content_sha256,
                chunks.ordinal AS ordinal,
                chunks.chunk_type AS chunk_type,
                chunks.start_line AS start_line,
                chunks.end_line AS end_line,
                chunks.page_start AS page_start,
                chunks.page_end AS page_end,
                chunks.object_type AS object_type,
                chunks.object_name AS object_name,
                chunks.metadata_json AS chunk_metadata_json,
                documents.id AS document_id,
                files.id AS file_id,
                files.domain AS domain,
                files.artifact_kind AS artifact_kind,
                files.relative_path AS relative_path,
                files.extension AS extension
            FROM chunks
            JOIN documents ON documents.id = chunks.document_id
            JOIN files ON files.id = documents.file_id
            WHERE {where}
            ORDER BY files.relative_path, chunks.ordinal, chunks.id
            """,
            tuple(parameters),
        ).fetchall()
    )


def _keyword_score(content: str, tokens: tuple[str, ...]) -> float:
    lowered = content.lower()
    matched = sum(1 for token in tokens if token in lowered)
    if matched == 0:
        return 0.0
    density_bonus = min(0.25, lowered.count(tokens[0]) / 20)
    return min(1.0, (matched / len(tokens)) + density_bonus)


def _candidate_from_chunk_row(
    row: sqlite3.Row,
    *,
    keyword_score: float,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=str(row["chunk_id"]),
        content_sha256=str(row["content_sha256"]),
        combined_score=keyword_score,
        keyword_score=keyword_score,
        metadata=_symbols_from_chunk_metadata(str(row["chunk_metadata_json"])),
        source={
            **_source_from_chunk_row(row, include_content=False),
            "retrieval_mode": RetrievalMode.KEYWORD.value,
        },
    )


def _source_from_chunk_row(
    row: sqlite3.Row,
    *,
    include_content: bool,
) -> dict[str, object | None]:
    relative_path = str(row["relative_path"])
    folder = str(Path(relative_path).parent).replace("\\", "/")
    if folder == ".":
        folder = ""
    source: dict[str, object | None] = {
        "domain": row["domain"],
        "artifact_kind": row["artifact_kind"],
        "language": _language_for_artifact(str(row["artifact_kind"])),
        "document_id": row["document_id"],
        "file_id": row["file_id"],
        "relative_path": relative_path,
        "folder": folder,
        "extension": row["extension"],
        "ordinal": row["ordinal"],
        "chunk_type": row["chunk_type"],
        "start_line": row["start_line"],
        "end_line": row["end_line"],
        "page_start": row["page_start"],
        "page_end": row["page_end"],
        "object_type": row["object_type"],
        "object_name": row["object_name"],
    }
    if include_content:
        source["content"] = row["content"]
    return source


def _symbols_from_chunk_metadata(raw_json: str) -> H4SymbolMetadata:
    metadata_json = _loads_json_object(raw_json)
    return H4SymbolMetadata(
        symbol_name=_optional_text(metadata_json.get("symbol_name")),
        symbol_kind=_optional_text(metadata_json.get("symbol_kind")),
        parent_symbol=_optional_text(metadata_json.get("parent_symbol")),
        package_name=_optional_text(metadata_json.get("package_name")),
        procedure_name=_optional_text(metadata_json.get("procedure_name")),
        class_name=_optional_text(metadata_json.get("class_name")),
        event_name=_optional_text(metadata_json.get("event_name")),
    )


def _snippet(content: str, *, limit: int = 240) -> str:
    compact = " ".join(content.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _sha256_text(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _execute_with_retries(
    connection: sqlite3.Connection,
    statement: str,
    parameters: Sequence[Any],
) -> sqlite3.Cursor:
    delays = (0.1, 0.25, 0.5)
    for attempt, delay in enumerate((*delays, 0.0)):
        try:
            return connection.execute(statement, tuple(parameters))
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == len(delays):
                raise SQLiteIngestionError(f"{DATABASE_LOCKED}: {exc}") from exc
            time.sleep(delay)
    raise SQLiteIngestionError(f"{DATABASE_LOCKED}: SQLite no respondio.")


def _source_root(discovered_file: DiscoveredFile) -> str:
    return str(discovered_file.root.resolve(strict=False))


def _artifact_kind(extension: str) -> str:
    if extension in {".sql", ".pks", ".pkb", ".prc", ".fnc", ".trg", ".pck", ".vw", ".vws", ".pkg", ".tps"}:
        return "oracle"
    if extension in {".srw", ".sru", ".srf", ".srm", ".srj", ".srd", ".pbl"}:
        return "powerbuilder"
    if extension == ".md":
        return "markdown"
    if extension == ".pdf":
        return "pdf"
    if extension == ".docx":
        return "docx"
    if extension in {".yaml", ".yml", ".json", ".ini"}:
        return "config"
    return "text"


def _media_type(extension: str) -> str:
    return {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".json": "application/json",
        ".md": "text/markdown",
    }.get(extension, "text/plain")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(value[key]) for key in sorted(value, key=lambda item: str(item))}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    return value
