from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from barbarion.application.ingest import IngestionService
from barbarion.config import Settings, load_settings
from barbarion.domain.models import (
    Confidence,
    DiscoveredFile,
    ErrorStage,
    ExtractionContext,
    ExtractionResult,
    FileFingerprint,
    IngestionMode,
    IngestionRunStatus,
    LogicalUnit,
    PipelineError,
    SourceFile,
)
from barbarion.infrastructure.parsers.base import BaseParser
from barbarion.infrastructure.parsers.registry import ParserRegistry
from barbarion.infrastructure.sqlite import SQLiteIngestionError, SQLiteIngestionRepository
from barbarion.database import initialize_database
import sqlite3


def make_file(root: Path, relative: str, content: str) -> DiscoveredFile:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    stat = path.stat()
    return DiscoveredFile(
        root=root,
        relative_path=PurePosixPath(relative),
        runtime_path=path,
        extension=path.suffix,
        size_bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
    )


class FakeDiscovery:
    def __init__(self, items):
        self.items = tuple(items)

    def discover(self, roots, extensions, ignore_patterns, max_file_size_mb):
        return self.items


class InterruptingDiscovery:
    def discover(self, roots, extensions, ignore_patterns, max_file_size_mb):
        raise KeyboardInterrupt


class FakeFingerprint:
    def fingerprint(self, discovered_file: DiscoveredFile) -> FileFingerprint:
        return FileFingerprint(
            size_bytes=discovered_file.size_bytes,
            mtime_ns=discovered_file.mtime_ns,
            sha256=("a" if discovered_file.relative_path.name.startswith("ok") else "b") * 64,
        )


class FailingRepository:
    def __init__(self) -> None:
        self.finished = None
        self.reconciled = False

    def begin_run(self, *, domain, mode, roots, config_sha256):
        return 1

    def get_file_state(self, *, domain, discovered_file):
        return None

    def replace_document(self, **kwargs):
        raise SQLiteIngestionError("DATABASE_WRITE_FAILED: sin espacio")

    def mark_seen(self, **kwargs):
        raise AssertionError("no esperado")

    def record_skipped(self, **kwargs):
        raise AssertionError("no esperado")

    def record_error(self, **kwargs):
        raise AssertionError("no esperado")

    def reconcile_deleted(self, **kwargs):
        self.reconciled = True
        return 0

    def finish_run(self, *, run_id, outcome):
        self.finished = outcome

    def current_metrics(self):
        raise AssertionError("no esperado")


class FakeParser(BaseParser):
    parser_id = "text"
    parser_version = "1"
    supported_extensions = (".txt",)

    def extract(
        self,
        source: SourceFile,
        context: ExtractionContext,
    ) -> ExtractionResult:
        if source.discovered.relative_path.name.startswith("bad"):
            raise ValueError("fixture corrupto")
        text = source.discovered.runtime_path.read_text(encoding="utf-8")
        return ExtractionResult(
            text=text,
            title=source.discovered.relative_path.name,
            encoding="utf-8",
            units=(
                LogicalUnit(
                    unit_type="file",
                    name=source.discovered.relative_path.name,
                    confidence=Confidence.HIGH,
                    start_line=1,
                    end_line=1,
                ),
            ),
        )


def settings_for(tmp_path: Path, root: Path) -> Settings:
    settings = load_settings(environ={}, cwd=tmp_path)
    ingestion = replace(
        settings.ingestion,
        paths=(root,),
        extensions=(".txt",),
        chunk_size=500,
        chunk_overlap=0,
    )
    return replace(settings, ingestion=ingestion, database_path=tmp_path / "barbarion.db")


def test_ingestion_service_processes_valid_files_and_records_recoverable_errors(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sources"
    ok = make_file(root, "ok.txt", "contenido valido")
    bad = make_file(root, "bad.txt", "contenido corrupto")
    settings = settings_for(tmp_path, root)
    initialize_database(settings.database_path)
    repository = SQLiteIngestionRepository(settings.database_path, domain=settings.domain)
    discovery_error = PipelineError(
        stage=ErrorStage.DISCOVERY,
        error_code="FILE_DISAPPEARED",
        message="archivo desaparecido",
        recoverable=True,
        relative_path=PurePosixPath("missing.txt"),
    )
    service = IngestionService(
        settings=settings,
        discovery=FakeDiscovery((ok, bad, discovery_error)),
        fingerprint=FakeFingerprint(),
        repository=repository,
        parser_registry=ParserRegistry([FakeParser()]),
    )

    outcome = service.run(mode=IngestionMode.INCREMENTAL)

    assert outcome.status == IngestionRunStatus.COMPLETED_WITH_ERRORS
    assert outcome.metrics.processed_files == 1
    assert outcome.metrics.error_count == 2
    assert outcome.metrics.chunk_count == 1
    with sqlite3.connect(settings.database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM files WHERE status = 'error'"
        ).fetchone() == (1,)


def test_ingestion_service_does_not_reconcile_after_root_error(tmp_path: Path) -> None:
    root = tmp_path / "sources"
    old_file = make_file(root, "ok.txt", "viejo")
    settings = settings_for(tmp_path, root)
    initialize_database(settings.database_path)
    repository = SQLiteIngestionRepository(settings.database_path, domain=settings.domain)
    first_service = IngestionService(
        settings=settings,
        discovery=FakeDiscovery((old_file,)),
        fingerprint=FakeFingerprint(),
        repository=repository,
        parser_registry=ParserRegistry([FakeParser()]),
    )
    first_service.run(mode=IngestionMode.INCREMENTAL)

    root_error = PipelineError(
        stage=ErrorStage.DISCOVERY,
        error_code="ROOT_NOT_FOUND",
        message="root fallida",
        recoverable=True,
        relative_path=PurePosixPath(root.name),
    )
    second_service = IngestionService(
        settings=settings,
        discovery=FakeDiscovery((root_error,)),
        fingerprint=FakeFingerprint(),
        repository=repository,
        parser_registry=ParserRegistry([FakeParser()]),
    )

    outcome = second_service.run(mode=IngestionMode.INCREMENTAL)

    assert outcome.status == IngestionRunStatus.COMPLETED_WITH_ERRORS
    assert repository.current_metrics().processed_files == 1


def test_ingestion_service_does_not_reconcile_after_interrupt(tmp_path: Path) -> None:
    root = tmp_path / "sources"
    old_file = make_file(root, "ok.txt", "viejo")
    settings = settings_for(tmp_path, root)
    initialize_database(settings.database_path)
    repository = SQLiteIngestionRepository(settings.database_path, domain=settings.domain)
    first_service = IngestionService(
        settings=settings,
        discovery=FakeDiscovery((old_file,)),
        fingerprint=FakeFingerprint(),
        repository=repository,
        parser_registry=ParserRegistry([FakeParser()]),
    )
    first_service.run(mode=IngestionMode.INCREMENTAL)

    interrupted_service = IngestionService(
        settings=settings,
        discovery=InterruptingDiscovery(),
        fingerprint=FakeFingerprint(),
        repository=repository,
        parser_registry=ParserRegistry([FakeParser()]),
    )

    outcome = interrupted_service.run(mode=IngestionMode.INCREMENTAL)

    assert outcome.status == IngestionRunStatus.INTERRUPTED
    assert repository.current_metrics().processed_files == 1


def test_ingestion_service_marks_database_errors_as_fatal(tmp_path: Path) -> None:
    root = tmp_path / "sources"
    ok = make_file(root, "ok.txt", "contenido valido")
    settings = settings_for(tmp_path, root)
    repository = FailingRepository()
    service = IngestionService(
        settings=settings,
        discovery=FakeDiscovery((ok,)),
        fingerprint=FakeFingerprint(),
        repository=repository,
        parser_registry=ParserRegistry([FakeParser()]),
    )

    outcome = service.run(mode=IngestionMode.INCREMENTAL)

    assert outcome.status == IngestionRunStatus.FAILED
    assert outcome.error is not None
    assert outcome.error.error_code == "DATABASE_WRITE_FAILED"
    assert repository.reconciled is False
