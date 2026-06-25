from __future__ import annotations

import sqlite3
from pathlib import Path, PurePosixPath

import pytest

from barbarion.database import initialize_database
from barbarion.domain.models import (
    ChunkCandidate,
    DiscoveredFile,
    ErrorStage,
    FileFingerprint,
    IngestionMode,
    LogicalUnit,
    Confidence,
    NormalizedDocument,
    PipelineError,
)
from barbarion.infrastructure.sqlite import SQLiteIngestionError, SQLiteIngestionRepository


SOURCE_SHA = "a" * 64
CONTENT_SHA = "b" * 64
CHUNK_SHA = "c" * 64
CHUNK_ID = "d" * 64
OTHER_CHUNK_ID = "e" * 64


def discovered(root: Path, name: str = "pkg/body.sql") -> DiscoveredFile:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("select 1;", encoding="utf-8")
    stat = path.stat()
    return DiscoveredFile(
        root=root,
        relative_path=PurePosixPath(name),
        runtime_path=path,
        extension=path.suffix,
        size_bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
    )


def document(text: str = "select 1;") -> NormalizedDocument:
    return NormalizedDocument(
        text=text,
        units=(
            LogicalUnit(
                unit_type="file",
                name="body.sql",
                confidence=Confidence.HIGH,
                start_line=1,
                end_line=1,
            ),
        ),
        source_sha256=SOURCE_SHA,
        content_sha256=CONTENT_SHA,
        metadata={
            "normalizer_version": "1",
            "title": "body.sql",
            "warnings": (),
        },
    )


def chunk(chunk_id: str = CHUNK_ID, content: str = "select 1;") -> ChunkCandidate:
    return ChunkCandidate(
        ordinal=0,
        chunk_id=chunk_id,
        chunk_type="file",
        content=content,
        content_sha256=CHUNK_SHA,
        start_line=1,
        end_line=1,
        metadata={
            "chunker_version": "1",
            "logical_unit_confidence": "high",
        },
    )


def repository(tmp_path: Path) -> tuple[SQLiteIngestionRepository, Path]:
    db_path = tmp_path / "barbarion.db"
    initialize_database(db_path)
    return SQLiteIngestionRepository(db_path, domain="default"), db_path


def begin_run(repo: SQLiteIngestionRepository, root: Path) -> int:
    return repo.begin_run(
        domain="default",
        mode=IngestionMode.INCREMENTAL,
        roots=(root,),
        config_sha256="f" * 64,
    )


def fingerprint(file: DiscoveredFile) -> FileFingerprint:
    return FileFingerprint(
        size_bytes=file.size_bytes,
        mtime_ns=file.mtime_ns,
        sha256=SOURCE_SHA,
    )


def test_replace_document_persists_file_document_and_chunks(tmp_path: Path) -> None:
    repo, db_path = repository(tmp_path)
    root = tmp_path / "sources"
    file = discovered(root)
    run_id = begin_run(repo, root)

    repo.replace_document(
        run_id=run_id,
        discovered_file=file,
        fingerprint=fingerprint(file),
        processing_signature="sig",
        parser_id="oracle",
        parser_version="1",
        encoding="utf-8",
        document=document(),
        chunks=(chunk(),),
    )

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT status, sha256 FROM files").fetchone() == (
            "processed",
            SOURCE_SHA,
        )
        assert connection.execute("SELECT normalized_text FROM documents").fetchone() == (
            "select 1;",
        )
        assert connection.execute("SELECT id, ordinal FROM chunks").fetchone() == (
            CHUNK_ID,
            0,
        )


def test_replace_document_is_atomic_on_chunk_failure(tmp_path: Path) -> None:
    repo, db_path = repository(tmp_path)
    root = tmp_path / "sources"
    file = discovered(root)
    run_id = begin_run(repo, root)
    repo.replace_document(
        run_id=run_id,
        discovered_file=file,
        fingerprint=fingerprint(file),
        processing_signature="sig",
        parser_id="oracle",
        parser_version="1",
        encoding="utf-8",
        document=document("version 1"),
        chunks=(chunk(CHUNK_ID, "version 1"),),
    )

    with pytest.raises(SQLiteIngestionError):
        repo.replace_document(
            run_id=run_id,
            discovered_file=file,
            fingerprint=fingerprint(file),
            processing_signature="sig",
            parser_id="oracle",
            parser_version="1",
            encoding="utf-8",
            document=document("version 2"),
            chunks=(
                chunk(CHUNK_ID, "version 2"),
                chunk(CHUNK_ID, "duplicado"),
            ),
        )

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT normalized_text FROM documents").fetchone() == (
            "version 1",
        )
        assert connection.execute("SELECT COUNT(*) FROM chunks").fetchone() == (1,)


def test_error_is_recorded_separately_after_failed_replacement(tmp_path: Path) -> None:
    repo, db_path = repository(tmp_path)
    root = tmp_path / "sources"
    file = discovered(root)
    run_id = begin_run(repo, root)
    error = PipelineError(
        stage=ErrorStage.PERSISTENCE,
        error_code="DATABASE_WRITE_FAILED",
        message="fallo controlado",
        recoverable=False,
        relative_path=file.relative_path,
    )

    repo.record_error(run_id=run_id, error=error, discovered_file=file)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT error_code, message FROM errors"
        ).fetchone() == ("DATABASE_WRITE_FAILED", "fallo controlado")
        assert connection.execute("SELECT status FROM files").fetchone() == ("error",)


def test_reconcile_deleted_marks_tombstone_and_cascades_children(
    tmp_path: Path,
) -> None:
    repo, db_path = repository(tmp_path)
    root = tmp_path / "sources"
    file = discovered(root)
    first_run = begin_run(repo, root)
    repo.replace_document(
        run_id=first_run,
        discovered_file=file,
        fingerprint=fingerprint(file),
        processing_signature="sig",
        parser_id="oracle",
        parser_version="1",
        encoding="utf-8",
        document=document(),
        chunks=(chunk(),),
    )
    second_run = begin_run(repo, root)

    deleted = repo.reconcile_deleted(
        run_id=second_run,
        domain="default",
        completed_roots=(root,),
    )

    assert deleted == 1
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT status FROM files").fetchone() == ("deleted",)
        assert connection.execute("SELECT COUNT(*) FROM documents").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM chunks").fetchone() == (0,)


def test_reconcile_ignores_incomplete_roots(tmp_path: Path) -> None:
    repo, db_path = repository(tmp_path)
    root = tmp_path / "sources"
    file = discovered(root)
    first_run = begin_run(repo, root)
    repo.replace_document(
        run_id=first_run,
        discovered_file=file,
        fingerprint=fingerprint(file),
        processing_signature="sig",
        parser_id="oracle",
        parser_version="1",
        encoding="utf-8",
        document=document(),
        chunks=(chunk(OTHER_CHUNK_ID),),
    )
    second_run = begin_run(repo, root)

    assert repo.reconcile_deleted(
        run_id=second_run,
        domain="default",
        completed_roots=(),
    ) == 0

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT status FROM files").fetchone() == ("processed",)
