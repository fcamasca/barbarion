"""Caso de uso secuencial de ingesta ingesta."""

from __future__ import annotations

import time
import logging
import fnmatch
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from barbarion.config import DataDrivenConfiguration
from barbarion.config import Settings
from barbarion.domain.ingestion import (
    IncrementalAction,
    PersistedFileState,
    ProcessingVersions,
    chunk_document,
    decide_incremental,
    normalize_extraction,
    processing_signature,
)
from barbarion.domain.models import (
    DiscoveredFile,
    ErrorStage,
    FileFingerprint,
    IngestionMetrics,
    IngestionMode,
    IngestionOutcome,
    IngestionRunStatus,
    PipelineError,
    SourceFile,
    ChunkCandidate,
    NormalizedDocument,
)
from barbarion.domain.ports import (
    DiscoveryPort,
    FingerprintPort,
    IngestionRepositoryPort,
)
from barbarion.infrastructure.parsers.registry import ParserRegistry

_DML_TABLE_RE = re.compile(
    r"""
    \b(?:INSERT\s+INTO|UPDATE)\s+
    (?P<table>
        (?:"[^"]+"|[A-Za-z][\w$#]*)
        (?:\s*\.\s*(?:"[^"]+"|[A-Za-z][\w$#]*))*
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


class ParserRegistryPort(Protocol):
    """Contrato minimo del registro usado por el servicio."""

    @property
    def parsers(self) -> tuple[object, ...]:
        """Parsers registrados."""

    def resolve(self, value: str | Path):
        """Resuelve parser por extension o ruta."""


@dataclass(frozen=True, slots=True)
class IngestionService:
    """Orquesta una corrida de ingesta local y secuencial."""

    settings: Settings
    discovery: DiscoveryPort
    fingerprint: FingerprintPort
    repository: IngestionRepositoryPort
    parser_registry: ParserRegistry
    logger: logging.Logger | None = None

    def run(
        self,
        *,
        mode: IngestionMode = IngestionMode.INCREMENTAL,
        roots: tuple[Path, ...] | None = None,
    ) -> IngestionOutcome:
        started = time.monotonic()
        effective_roots = self.settings.ingestion.paths if roots is None else roots
        versions = ProcessingVersions(
            parser_versions={
                parser.parser_id: parser.parser_version
                for parser in self.parser_registry.parsers
            }
        )
        signature = processing_signature(self.settings, versions)
        run_id = self.repository.begin_run(
            domain=self.settings.domain,
            mode=mode,
            roots=effective_roots,
            config_sha256=signature,
        )
        metrics = IngestionMetrics()
        completed_roots: set[Path] = {
            Path(root).expanduser().resolve(strict=False) for root in effective_roots
        }
        seen_files: list[tuple[DiscoveredFile, PersistedFileState]] = []
        current_file: DiscoveredFile | None = None
        interrupted = False

        try:
            items = self.discovery.discover(
                effective_roots,
                self.settings.ingestion.extensions,
                self.settings.ingestion.ignore_patterns,
                self.settings.ingestion.max_file_size_mb,
            )
            for item in items:
                if isinstance(item, PipelineError):
                    self._log_pipeline_error(item)
                    if item.error_code == "FILE_TOO_LARGE":
                        skipped_file = _discovered_from_error(item, effective_roots)
                        if skipped_file is not None:
                            self.repository.record_skipped(
                                run_id=run_id,
                                discovered_file=skipped_file,
                                error=item,
                            )
                            metrics = _replace(
                                metrics,
                                skipped_files=metrics.skipped_files + 1,
                            )
                        else:
                            self.repository.record_error(run_id=run_id, error=item)
                            metrics = _add_error(metrics)
                    else:
                        self.repository.record_error(run_id=run_id, error=item)
                        metrics = _add_error(metrics)
                    if item.error_code.startswith("ROOT_"):
                        completed_roots = _remove_unsafe_roots(completed_roots, item)
                    continue
                metrics = _add_discovered(metrics, item)
                current_file = item
                try:
                    metrics = self._process_file(
                        run_id=run_id,
                        discovered_file=item,
                        mode=mode,
                        processing_signature_value=signature,
                        metrics=metrics,
                        seen_files=seen_files,
                    )
                except KeyboardInterrupt:
                    interrupted = True
                    raise
                except Exception as exc:
                    if _is_fatal_error(exc):
                        raise
                    error = (
                        exc.to_pipeline_error()
                        if hasattr(exc, "to_pipeline_error")
                        else _pipeline_error(
                            ErrorStage.EXTRACTION,
                            "PARSER_FAILED",
                            "No se pudo procesar el archivo.",
                            item,
                            exc,
                        )
                    )
                    self._log_pipeline_error(error)
                    if error.error_code == "UNSUPPORTED_BINARY_PBL":
                        self.repository.record_skipped(
                            run_id=run_id,
                            discovered_file=item,
                            error=error,
                        )
                        metrics = _replace(
                            metrics,
                            skipped_files=metrics.skipped_files + 1,
                        )
                    else:
                        self.repository.record_error(
                            run_id=run_id,
                            error=error,
                            discovered_file=item,
                        )
                        metrics = _add_error(metrics)
                current_file = None
            if not interrupted:
                current_file = None
                _mark_seen_many(
                    self.repository,
                    run_id=run_id,
                    seen_files=tuple(seen_files),
                )
                deleted = self.repository.reconcile_deleted(
                    run_id=run_id,
                    domain=self.settings.domain,
                    completed_roots=tuple(sorted(completed_roots, key=str)),
                )
                metrics = _replace(metrics, deleted_files=metrics.deleted_files + deleted)
            status = (
                IngestionRunStatus.COMPLETED_WITH_ERRORS
                if metrics.error_count
                else IngestionRunStatus.COMPLETED
            )
            outcome = IngestionOutcome(
                status=status,
                metrics=_with_duration(metrics, started),
            )
            self.repository.finish_run(run_id=run_id, outcome=outcome)
            return outcome
        except KeyboardInterrupt as exc:
            outcome = IngestionOutcome(
                status=IngestionRunStatus.INTERRUPTED,
                metrics=_with_duration(metrics, started),
                error=PipelineError(
                    stage=ErrorStage.RECONCILIATION,
                    error_code="INGEST_INTERRUPTED",
                    message="La ingesta fue interrumpida.",
                    recoverable=False,
                    exception_type=type(exc).__name__,
                ),
            )
            self.repository.finish_run(run_id=run_id, outcome=outcome)
            return outcome
        except Exception as exc:
            error = _fatal_pipeline_error(exc, current_file)
            self._log_fatal_error(error, exc)
            metrics = _add_error(metrics)
            outcome = IngestionOutcome(
                status=IngestionRunStatus.FAILED,
                metrics=_with_duration(metrics, started),
                error=error,
            )
            try:
                self.repository.record_error(
                    run_id=run_id,
                    error=error,
                    discovered_file=current_file,
                )
            except Exception as record_exc:
                self._log_fatal_record_failure(record_exc)
            self.repository.finish_run(run_id=run_id, outcome=outcome)
            return outcome

    def _process_file(
        self,
        *,
        run_id: int,
        discovered_file: DiscoveredFile,
        mode: IngestionMode,
        processing_signature_value: str,
        metrics: IngestionMetrics,
        seen_files: list[tuple[DiscoveredFile, PersistedFileState]],
    ) -> IngestionMetrics:
        persisted = self.repository.get_file_state(
            domain=self.settings.domain,
            discovered_file=discovered_file,
        )
        decision = decide_incremental(
            discovered_file,
            processing_signature_value,
            mode=mode,
            persisted=persisted,
        )
        if decision.action == IncrementalAction.UNCHANGED and persisted is not None:
            seen_files.append((discovered_file, persisted))
            return _replace(metrics, unchanged_files=metrics.unchanged_files + 1)

        current_fingerprint = self.fingerprint.fingerprint(discovered_file)
        if decision.action == IncrementalAction.HASH_REQUIRED:
            decision = decide_incremental(
                discovered_file,
                processing_signature_value,
                mode=mode,
                persisted=persisted,
                fingerprint=current_fingerprint,
            )
            if decision.action == IncrementalAction.TOUCH and persisted is not None:
                seen_files.append((discovered_file, persisted))
                return _replace(metrics, unchanged_files=metrics.unchanged_files + 1)

        parser = self.parser_registry.resolve(discovered_file.extension)
        extraction = parser.extract(
            SourceFile(discovered=discovered_file, fingerprint=current_fingerprint),
            self._extraction_context(),
        )
        document = normalize_extraction(
            extraction,
            source_sha256=current_fingerprint.sha256 or "",
        )
        classification = _classify_data_driven_document(
            settings=self.settings,
            discovered_file=discovered_file,
            text=document.text,
        )
        document = _document_with_data_driven_metadata(document, classification)
        chunks = chunk_document(
            document,
            file_identity=discovered_file.relative_path.as_posix(),
            processing_signature=processing_signature_value,
            chunk_size=self.settings.ingestion.chunk_size,
            chunk_overlap=self.settings.ingestion.chunk_overlap,
        )
        chunks = _chunks_with_data_driven_metadata(chunks, classification)
        self.repository.replace_document(
            run_id=run_id,
            discovered_file=discovered_file,
            fingerprint=current_fingerprint,
            processing_signature=processing_signature_value,
            parser_id=parser.parser_id,
            parser_version=parser.parser_version,
            encoding=extraction.encoding,
            document=document,
            chunks=chunks,
            artifact_kind=classification.artifact_kind,
        )
        return _replace(
            metrics,
            processed_files=metrics.processed_files + 1,
            processed_bytes=metrics.processed_bytes + discovered_file.size_bytes,
            chunk_count=metrics.chunk_count + len(chunks),
        )

    def _extraction_context(self):
        from barbarion.domain.models import ExtractionContext

        return ExtractionContext(
            encodings=self.settings.ingestion.encodings,
            max_extracted_chars=self.settings.ingestion.max_extracted_chars,
            max_pdf_pages=self.settings.ingestion.max_pdf_pages,
        )

    def _log_pipeline_error(self, error: PipelineError) -> None:
        if self.logger is None:
            return
        self.logger.warning(
            "Error recuperable de ingesta stage=%s path=%s code=%s",
            error.stage.value,
            error.relative_path.as_posix() if error.relative_path is not None else "n/a",
            error.error_code,
        )

    def _log_fatal_error(self, error: PipelineError, exc: Exception) -> None:
        if self.logger is None:
            return
        self.logger.error(
            "Error fatal de ingesta stage=%s path=%s code=%s "
            "exception_type=%s technical_message=%s recoverable=%s",
            error.stage.value,
            error.relative_path.as_posix() if error.relative_path is not None else "n/a",
            error.error_code,
            error.exception_type or "n/a",
            error.details.get("technical_message", str(exc)),
            error.recoverable,
        )
        self.logger.debug(
            "Traceback de ingesta fatal",
            exc_info=(type(exc), exc, exc.__traceback__),
        )

    def _log_fatal_record_failure(self, exc: Exception) -> None:
        if self.logger is None:
            return
        root = _root_exception(exc)
        self.logger.error(
            "No se pudo persistir el error fatal de ingesta "
            "exception_type=%s technical_message=%s",
            type(root).__name__,
            str(root),
        )
        self.logger.debug(
            "Traceback al persistir error fatal",
            exc_info=(type(exc), exc, exc.__traceback__),
        )


def _pipeline_error(
    stage: ErrorStage,
    code: str,
    message: str,
    discovered_file: DiscoveredFile,
    exc: Exception,
) -> PipelineError:
    return PipelineError(
        stage=stage,
        error_code=code,
        message=message,
        recoverable=True,
        relative_path=discovered_file.relative_path,
        exception_type=type(exc).__name__,
    )


def _is_fatal_error(exc: Exception) -> bool:
    name = type(exc).__name__
    return name.endswith("SQLiteIngestionError") or "DATABASE_" in str(exc)


def _fatal_error_code(exc: Exception) -> str:
    text = str(exc)
    if ":" in text and text.split(":", 1)[0].startswith("DATABASE_"):
        return text.split(":", 1)[0]
    if type(exc).__name__.endswith("SQLiteIngestionError"):
        return "DATABASE_WRITE_FAILED"
    return "INGEST_FAILED"


def _fatal_pipeline_error(
    exc: Exception,
    discovered_file: DiscoveredFile | None,
) -> PipelineError:
    root = _root_exception(exc)
    details = {
        "technical_message": str(root),
        "wrapped_exception_type": type(exc).__name__,
        "wrapped_message": str(exc),
    }
    if root is not exc:
        details["root_exception_type"] = type(root).__name__
    return PipelineError(
        stage=ErrorStage.PERSISTENCE,
        error_code=_fatal_error_code(exc),
        message="La ingesta fallo por un error fatal de persistencia.",
        recoverable=False,
        relative_path=None if discovered_file is None else discovered_file.relative_path,
        exception_type=type(root).__name__,
        details=details,
    )


def _root_exception(exc: Exception) -> BaseException:
    current: BaseException = exc
    seen: set[int] = set()
    while current.__cause__ is not None and id(current.__cause__) not in seen:
        seen.add(id(current))
        current = current.__cause__
    return current


def _remove_unsafe_roots(
    completed_roots: set[Path],
    error: PipelineError,
) -> set[Path]:
    if error.relative_path is None:
        return completed_roots
    return {
        root
        for root in completed_roots
        if root.name != error.relative_path.name
        and str(root) != error.relative_path.as_posix()
    }


def _discovered_from_error(
    error: PipelineError,
    roots: tuple[Path, ...],
) -> DiscoveredFile | None:
    if error.relative_path is None:
        return None
    for root in roots:
        root_path = Path(root).expanduser().resolve(strict=False)
        runtime_path = root_path / error.relative_path
        if runtime_path.exists():
            stat = runtime_path.stat()
            return DiscoveredFile(
                root=root_path,
                relative_path=error.relative_path,
                runtime_path=runtime_path,
                extension=runtime_path.suffix,
                size_bytes=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
            )
    return None


def _mark_seen_many(
    repository: IngestionRepositoryPort,
    *,
    run_id: int,
    seen_files: tuple[tuple[DiscoveredFile, PersistedFileState], ...],
) -> None:
    if not seen_files:
        return
    mark_many = getattr(repository, "mark_seen_many", None)
    if callable(mark_many):
        mark_many(run_id=run_id, seen_files=seen_files)
        return
    for discovered_file, state in seen_files:
        repository.mark_seen(
            run_id=run_id,
            discovered_file=discovered_file,
            state=state,
        )


def _add_discovered(metrics: IngestionMetrics, file: DiscoveredFile) -> IngestionMetrics:
    return _replace(
        metrics,
        discovered_files=metrics.discovered_files + 1,
        source_bytes=metrics.source_bytes + file.size_bytes,
    )


def _add_error(metrics: IngestionMetrics) -> IngestionMetrics:
    return _replace(metrics, error_count=metrics.error_count + 1)


def _with_duration(metrics: IngestionMetrics, started: float) -> IngestionMetrics:
    return _replace(metrics, duration_ms=int((time.monotonic() - started) * 1000))


def _replace(metrics: IngestionMetrics, **changes: int | None) -> IngestionMetrics:
    values = {
        "discovered_files": metrics.discovered_files,
        "processed_files": metrics.processed_files,
        "unchanged_files": metrics.unchanged_files,
        "skipped_files": metrics.skipped_files,
        "deleted_files": metrics.deleted_files,
        "error_count": metrics.error_count,
        "source_bytes": metrics.source_bytes,
        "processed_bytes": metrics.processed_bytes,
        "chunk_count": metrics.chunk_count,
        "duration_ms": metrics.duration_ms,
    }
    values.update(changes)
    return IngestionMetrics(**values)


@dataclass(frozen=True, slots=True)
class _DataDrivenClassification:
    """Resultado de clasificar un documento como configuracion Data-Driven.

    Attributes:
        artifact_kind: Tipo de artefacto que debe persistirse para el archivo.
        configuration_names: Configuraciones declaradas que coincidieron.
        table_names: Tablas declaradas detectadas en sentencias DML.
    """

    artifact_kind: str | None = None
    configuration_names: tuple[str, ...] = ()
    table_names: tuple[str, ...] = ()


def _classify_data_driven_document(
    *,
    settings: Settings,
    discovered_file: DiscoveredFile,
    text: str,
) -> _DataDrivenClassification:
    """Clasifica un documento SQL contra declaraciones Data-Driven.

    La clasificacion exige que el archivo coincida con los patrones declarados y
    que el documento completo mencione una tabla configurada en sentencias DML.
    No parsea ni ejecuta SQL; solo identifica candidatos para etapas posteriores.

    Args:
        settings: Configuracion efectiva de la aplicacion.
        discovered_file: Archivo descubierto por la ingesta.
        text: Texto normalizado completo del documento.

    Returns:
        Clasificacion con nombres de configuracion y tablas coincidentes.
    """
    data_driven = settings.data_driven
    if (
        not data_driven.enabled
        or discovered_file.extension != ".sql"
        or not _matches_any_pattern(
            discovered_file.relative_path.as_posix(),
            data_driven.file_patterns,
        )
    ):
        return _DataDrivenClassification()

    referenced_tables = _referenced_dml_tables(text)
    if not referenced_tables:
        return _DataDrivenClassification()

    matched_configurations: list[str] = []
    matched_tables: list[str] = []
    for configuration in data_driven.configurations:
        if configuration.file_patterns and not _matches_any_pattern(
            discovered_file.relative_path.as_posix(),
            configuration.file_patterns,
        ):
            continue
        table = _matching_declared_table(configuration, referenced_tables)
        if table is None:
            continue
        matched_configurations.append(configuration.name)
        matched_tables.append(table)

    if not matched_configurations:
        return _DataDrivenClassification()
    return _DataDrivenClassification(
        artifact_kind="configuration",
        configuration_names=tuple(dict.fromkeys(matched_configurations)),
        table_names=tuple(dict.fromkeys(matched_tables)),
    )


def _document_with_data_driven_metadata(
    document: NormalizedDocument,
    classification: _DataDrivenClassification,
) -> NormalizedDocument:
    """Agrega metadata Data-Driven al documento cuando fue clasificado."""
    if classification.artifact_kind != "configuration":
        return document
    metadata = dict(document.metadata)
    metadata["artifact_kind"] = "configuration"
    metadata["data_driven_configuration_names"] = classification.configuration_names
    metadata["data_driven_tables"] = classification.table_names
    return replace(document, metadata=metadata)


def _chunks_with_data_driven_metadata(
    chunks: tuple[ChunkCandidate, ...],
    classification: _DataDrivenClassification,
) -> tuple[ChunkCandidate, ...]:
    """Propaga metadata Data-Driven a chunks usados solo como evidencia."""
    if classification.artifact_kind != "configuration":
        return chunks
    enriched: list[ChunkCandidate] = []
    for chunk in chunks:
        metadata = dict(chunk.metadata)
        metadata["artifact_kind"] = "configuration"
        metadata["data_driven_configuration_names"] = classification.configuration_names
        metadata["data_driven_tables"] = classification.table_names
        enriched.append(replace(chunk, metadata=metadata))
    return tuple(enriched)


def _matches_any_pattern(path: str, patterns: tuple[str, ...]) -> bool:
    """Evalua patrones de ruta de forma case-insensitive y estable."""
    normalized_path = path.replace("\\", "/").lower()
    return any(
        fnmatch.fnmatchcase(normalized_path, pattern.replace("\\", "/").lower())
        for pattern in patterns
    )


def _referenced_dml_tables(text: str) -> frozenset[str]:
    """Detecta nombres de tablas mencionadas en `INSERT` o `UPDATE`."""
    return frozenset(
        _normalize_table_name(match.group("table"))
        for match in _DML_TABLE_RE.finditer(text)
    )


def _matching_declared_table(
    configuration: DataDrivenConfiguration,
    referenced_tables: frozenset[str],
) -> str | None:
    """Devuelve la tabla declarada que coincide con el documento."""
    for table in configuration.tables:
        normalized = _normalize_table_name(table)
        unqualified = normalized.rsplit(".", 1)[-1]
        if normalized in referenced_tables or unqualified in referenced_tables:
            return table
    return None


def _normalize_table_name(table: str) -> str:
    parts = [part.strip().strip('"').lower() for part in table.split(".")]
    return ".".join(part for part in parts if part)
