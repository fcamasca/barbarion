from __future__ import annotations

import logging
import json
import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from barbarion.application.ingest import IngestionService
from barbarion.config import (
    DataDrivenConfiguration,
    DataDrivenSettings,
    Settings,
    load_settings,
)
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
        self.recorded_error = None
        self.recorded_file = None

    def begin_run(self, *, domain, mode, roots, config_sha256):
        return 1

    def get_file_state(self, *, domain, discovered_file):
        return None

    def replace_document(self, **kwargs):
        try:
            raise sqlite3.IntegrityError("UNIQUE constraint failed: chunks.id")
        except sqlite3.IntegrityError as exc:
            raise SQLiteIngestionError(
                "DATABASE_WRITE_FAILED: UNIQUE constraint failed: chunks.id"
            ) from exc

    def mark_seen(self, **kwargs):
        raise AssertionError("no esperado")

    def record_skipped(self, **kwargs):
        raise AssertionError("no esperado")

    def record_error(self, **kwargs):
        self.recorded_error = kwargs["error"]
        self.recorded_file = kwargs.get("discovered_file")

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


class FakeSqlParser(FakeParser):
    parser_id = "oracle"
    supported_extensions = (".sql",)


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


def data_driven_settings_for(tmp_path: Path, root: Path) -> Settings:
    settings = load_settings(environ={}, cwd=tmp_path)
    ingestion = replace(
        settings.ingestion,
        paths=(root,),
        extensions=(".sql",),
        chunk_size=500,
        chunk_overlap=0,
    )
    data_driven = DataDrivenSettings(
        enabled=True,
        file_patterns=("config/**/*.sql",),
        max_statements_per_file=10_000,
        max_literal_chars=200_000,
        token_patterns=(),
        configurations=(
            DataDrivenConfiguration(
                name="pricing_rules",
                symbol_type="configuration_record",
                tables=("APP_CFG.PRICING_RULES",),
                identity_columns=("RULE_ID",),
                file_patterns=(),
                default_column_order=(),
                name_columns=(),
                description_columns=(),
                rule_columns=(),
                formula_columns=(),
                variable_columns=(),
                parameter_columns=(),
                mapping_columns=(),
                reference_columns=(),
                parent_columns=(),
                sequence_columns=(),
                status_columns=(),
                effective_from_columns=(),
                effective_to_columns=(),
                metadata_columns=(),
            ),
        ),
    )
    return replace(
        settings,
        ingestion=ingestion,
        data_driven=data_driven,
        database_path=tmp_path / "barbarion.db",
    )


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


def test_ingestion_service_classifies_declared_sql_as_configuration(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sources"
    source = make_file(
        root,
        "config/pricing/rules.sql",
        "INSERT INTO APP_CFG.PRICING_RULES (RULE_ID, RULE_NAME) VALUES ('R1', 'Base');",
    )
    settings = data_driven_settings_for(tmp_path, root)
    initialize_database(settings.database_path)
    repository = SQLiteIngestionRepository(settings.database_path, domain=settings.domain)
    service = IngestionService(
        settings=settings,
        discovery=FakeDiscovery((source,)),
        fingerprint=FakeFingerprint(),
        repository=repository,
        parser_registry=ParserRegistry([FakeSqlParser()]),
    )

    outcome = service.run(mode=IngestionMode.INCREMENTAL)

    assert outcome.status == IngestionRunStatus.COMPLETED
    with sqlite3.connect(settings.database_path) as connection:
        connection.row_factory = sqlite3.Row
        file_row = connection.execute(
            "SELECT artifact_kind FROM files WHERE relative_path = ?",
            ("config/pricing/rules.sql",),
        ).fetchone()
        document_row = connection.execute(
            "SELECT metadata_json FROM documents"
        ).fetchone()
        chunk_row = connection.execute(
            "SELECT metadata_json FROM chunks"
        ).fetchone()

    document_metadata = json.loads(document_row["metadata_json"])
    chunk_metadata = json.loads(chunk_row["metadata_json"])
    assert file_row["artifact_kind"] == "configuration"
    assert document_metadata["artifact_kind"] == "configuration"
    assert document_metadata["data_driven_configuration_names"] == ["pricing_rules"]
    assert document_metadata["data_driven_tables"] == ["APP_CFG.PRICING_RULES"]
    assert chunk_metadata["artifact_kind"] == "configuration"
    assert chunk_metadata["data_driven_configuration_names"] == ["pricing_rules"]


def test_ingestion_service_keeps_undeclared_sql_as_oracle(tmp_path: Path) -> None:
    root = tmp_path / "sources"
    source = make_file(
        root,
        "oracle/package.sql",
        "INSERT INTO APP_CFG.PRICING_RULES (RULE_ID) VALUES ('R1');",
    )
    settings = data_driven_settings_for(tmp_path, root)
    initialize_database(settings.database_path)
    repository = SQLiteIngestionRepository(settings.database_path, domain=settings.domain)
    service = IngestionService(
        settings=settings,
        discovery=FakeDiscovery((source,)),
        fingerprint=FakeFingerprint(),
        repository=repository,
        parser_registry=ParserRegistry([FakeSqlParser()]),
    )

    outcome = service.run(mode=IngestionMode.INCREMENTAL)

    assert outcome.status == IngestionRunStatus.COMPLETED
    with sqlite3.connect(settings.database_path) as connection:
        connection.row_factory = sqlite3.Row
        file_row = connection.execute(
            "SELECT artifact_kind FROM files WHERE relative_path = ?",
            ("oracle/package.sql",),
        ).fetchone()
        document_row = connection.execute(
            "SELECT metadata_json FROM documents"
        ).fetchone()
    document_metadata = json.loads(document_row["metadata_json"])
    assert file_row["artifact_kind"] == "oracle"
    assert "data_driven_configuration_names" not in document_metadata


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


def test_ingestion_service_marks_database_errors_as_fatal(
    tmp_path: Path,
    caplog,
) -> None:
    root = tmp_path / "sources"
    ok = make_file(root, "ok.txt", "contenido valido")
    settings = settings_for(tmp_path, root)
    repository = FailingRepository()
    logger = logging.getLogger("tests.ingestion.fatal")
    service = IngestionService(
        settings=settings,
        discovery=FakeDiscovery((ok,)),
        fingerprint=FakeFingerprint(),
        repository=repository,
        parser_registry=ParserRegistry([FakeParser()]),
        logger=logger,
    )

    with caplog.at_level(logging.DEBUG, logger=logger.name):
        outcome = service.run(mode=IngestionMode.INCREMENTAL)

    assert outcome.status == IngestionRunStatus.FAILED
    assert outcome.error is not None
    assert outcome.error.error_code == "DATABASE_WRITE_FAILED"
    assert outcome.error.relative_path == PurePosixPath("ok.txt")
    assert outcome.error.exception_type == "IntegrityError"
    assert outcome.error.details["technical_message"] == "UNIQUE constraint failed: chunks.id"
    assert outcome.metrics.error_count == 1
    assert repository.recorded_error == outcome.error
    assert repository.recorded_file == ok
    assert repository.reconciled is False
    assert "exception_type=IntegrityError" in caplog.text
    assert "technical_message=UNIQUE constraint failed: chunks.id" in caplog.text
    assert "Traceback de ingesta fatal" in caplog.text
