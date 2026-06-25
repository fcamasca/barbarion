"""SQL explicito de persistencia para la ingesta H2."""

from __future__ import annotations

import json
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
