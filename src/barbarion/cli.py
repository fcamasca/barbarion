"""Punto de entrada de la línea de comandos de Barbarion."""

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from barbarion import __version__
from barbarion.application.ingest import IngestionService
from barbarion.application.rag import (
    AskService,
    CitationValidator,
    ContextBuilder,
    IndexService,
    PromptBuilder,
    SearchService,
)
from barbarion.bootstrap import DirectoryResult, initialize_directories
from barbarion.config import ConfigError, Settings, load_settings, settings_display_items
from barbarion.database import DatabaseError, initialize_database
from barbarion.doctor import DoctorReport, run_doctor_checks
from barbarion.domain.models import IngestionMode
from barbarion.domain.models import IngestionOutcome
from barbarion.domain.models import IngestionRunStatus
from barbarion.domain.rag import (
    AnswerResult,
    EmbeddingRunMode,
    EmbeddingRunStatus,
    IndexRunSummary,
    IndexScope,
    RetrievalFilter,
    RetrievalMode,
    SearchRequest,
    SearchResponse,
)
from barbarion.infrastructure.embeddings import OllamaEmbeddingProvider
from barbarion.infrastructure.filesystem import LocalFilesystemDiscovery
from barbarion.infrastructure.fingerprint import LocalFingerprintCalculator
from barbarion.infrastructure.parsers import (
    DocxParser,
    MarkdownParser,
    OracleParser,
    PdfParser,
    PowerBuilderParser,
    TextParser,
)
from barbarion.infrastructure.parsers.registry import ParserRegistry
from barbarion.infrastructure.sqlite import SQLiteIngestionRepository
from barbarion.infrastructure.sqlite import SQLiteRagRepository
from barbarion.infrastructure.sqlite_vec import SQLiteVecStore
from barbarion.infrastructure.llm import OllamaLlmProvider
from barbarion.logging_config import configure_logging


class SpanishArgumentParser(argparse.ArgumentParser):
    """Parser que presenta ayuda y errores básicos."""

    def format_usage(self) -> str:
        """Devuelve la línea de uso con su etiqueta."""
        return super().format_usage().replace("usage:", "uso:", 1)

    def format_help(self) -> str:
        """Devuelve la ayuda con su etiqueta de uso."""
        return super().format_help().replace("usage:", "uso:", 1)

    def error(self, message: str) -> None:
        """Finaliza con un error breve y estable."""
        del message
        self.print_usage(sys.stderr)
        self.exit(
            2,
            f"{self.prog}: error: argumentos inválidos. "
            f"Usa '{self.prog} --help' para consultar la ayuda.\n",
        )


def _add_help_option(parser: argparse.ArgumentParser) -> None:
    """Añade la opción de ayuda localizada a un parser."""
    options = parser.add_argument_group("opciones")
    options.add_argument(
        "-h",
        "--help",
        action="help",
        help="muestra esta ayuda y finaliza",
    )


def _show_config(args: argparse.Namespace) -> int:
    """Muestra la configuración efectiva sin modificar el entorno."""
    settings = load_settings(args.config)
    for key, value in settings_display_items(settings):
        print(f"{key} = {value}")
    return 0


def _run_doctor(args: argparse.Namespace) -> int:
    """Orquesta bootstrap, logging, checks y presentación del diagnóstico."""
    settings = load_settings(args.config)
    directory_results = initialize_directories(settings)
    logger = _configure_doctor_logging(settings, directory_results)

    if logger is not None:
        source = settings.config_source or "valores predeterminados"
        logger.info("Inicio del diagnóstico.")
        logger.info("Configuración cargada desde %s.", source)

    report = run_doctor_checks(settings, directory_results)
    _render_doctor_report(report)
    if logger is not None:
        _log_doctor_report(logger, report)
    return report.exit_code


def _run_ingest(args: argparse.Namespace) -> int:
    """Ejecuta ingesta o estadisticas segun las opciones recibidas."""
    if args.stats:
        if args.path or args.full or args.incremental:
            print(
                "Error de argumentos: --stats no se combina con ejecucion.",
                file=sys.stderr,
            )
            return 2
        return _show_ingestion_stats(args)

    settings = _settings_with_ingest_paths(load_settings(args.config), args.path)
    missing = _missing_ingest_resources(settings)
    if missing:
        print(
            "Recursos de Barbarion no inicializados. Ejecuta 'barbarion doctor' "
            "antes de iniciar la ingesta.",
            file=sys.stderr,
        )
        for path in missing:
            print(f"Falta: {path}", file=sys.stderr)
        return 1

    initialize_database(settings.database_path)
    logger = _configure_ingest_logging(settings)
    if logger is not None:
        logger.info("Inicio de ingesta mode=%s roots=%s", _mode(args).value, args.path or "config")
    service = _build_ingestion_service(settings, logger=logger)
    outcome = service.run(mode=_mode(args))
    _render_ingestion_outcome(outcome)
    if logger is not None:
        logger.info(
            "Fin de ingesta status=%s discovered=%s processed=%s unchanged=%s "
            "skipped=%s deleted=%s errors=%s chunks=%s duration_ms=%s",
            outcome.status.value,
            outcome.metrics.discovered_files,
            outcome.metrics.processed_files,
            outcome.metrics.unchanged_files,
            outcome.metrics.skipped_files,
            outcome.metrics.deleted_files,
            outcome.metrics.error_count,
            outcome.metrics.chunk_count,
            outcome.metrics.duration_ms,
        )
        if outcome.error is not None:
            logger.error(
                "Error de ingesta stage=%s path=%s code=%s exception_type=%s "
                "technical_message=%s recoverable=%s",
                outcome.error.stage.value,
                (
                    outcome.error.relative_path.as_posix()
                    if outcome.error.relative_path is not None
                    else "n/a"
                ),
                outcome.error.error_code,
                outcome.error.exception_type or "n/a",
                outcome.error.details.get("technical_message", "n/a"),
                outcome.error.recoverable,
            )
    if outcome.status.value == "interrupted":
        return 130
    if outcome.status in {
        IngestionRunStatus.FAILED,
        IngestionRunStatus.COMPLETED_WITH_ERRORS,
    }:
        return 1
    return 0


def _run_index(args: argparse.Namespace) -> int:
    """Ejecuta indexacion RAG incremental."""
    settings = load_settings(args.config)
    if not settings.database_path.exists():
        print(
            "No hay base SQLite de Barbarion. Ejecuta 'barbarion doctor' e "
            "ingesta el corpus antes de indexar.",
            file=sys.stderr,
        )
        return 1
    initialize_database(settings.database_path)
    service = _build_index_service(settings)
    summary = service.run(
        mode=EmbeddingRunMode.INCREMENTAL,
        dry_run=args.dry_run,
        delete_obsolete=True,
    )
    _render_index_summary(summary)
    return _index_exit_code(summary)


def _run_reindex(args: argparse.Namespace) -> int:
    """Ejecuta reindexacion RAG completa o parcial."""
    if not args.full and args.path is None and args.document is None and args.chunk_id is None:
        print(
            "Error de argumentos: reindex requiere --full, --path, --document "
            "o --chunk-id.",
            file=sys.stderr,
        )
        return 2
    settings = load_settings(args.config)
    if not settings.database_path.exists():
        print(
            "No hay base SQLite de Barbarion. Ejecuta 'barbarion doctor' e "
            "ingesta el corpus antes de reindexar.",
            file=sys.stderr,
        )
        return 1
    initialize_database(settings.database_path)
    scope = _index_scope(args)
    mode = EmbeddingRunMode.FULL if args.full else EmbeddingRunMode.PARTIAL
    service = _build_index_service(settings)
    summary = service.run(
        mode=mode,
        scope=scope,
        dry_run=args.dry_run,
        delete_obsolete=args.delete_obsolete,
    )
    _render_index_summary(summary)
    return _index_exit_code(summary)


def _run_search(args: argparse.Namespace) -> int:
    """Ejecuta busqueda RAG desde CLI."""
    settings = load_settings(args.config)
    if not settings.database_path.exists():
        print("No hay base SQLite de Barbarion. Ejecuta ingesta e indexacion.", file=sys.stderr)
        return 1
    initialize_database(settings.database_path)
    service = _build_search_service(settings)
    request = _search_request(args, settings)
    response = service.search(request)
    _render_search_response(response, args.format)
    return 0


def _run_ask(args: argparse.Namespace) -> int:
    """Ejecuta pregunta RAG desde CLI."""
    settings = load_settings(args.config)
    if not settings.database_path.exists():
        print("No hay base SQLite de Barbarion. Ejecuta ingesta e indexacion.", file=sys.stderr)
        return 1
    initialize_database(settings.database_path)
    service = _build_ask_service(settings)
    result = service.ask(
        args.question,
        mode=RetrievalMode(args.mode),
        filters=_retrieval_filter(args),
        top_k=args.top_k,
        candidate_k=args.candidate_k,
        threshold=args.threshold,
        no_llm=args.no_llm,
        debug=args.debug,
    )
    _render_answer_result(result, args.format)
    return 0 if result.citations_valid else 1


def _run_embeddings(args: argparse.Namespace) -> int:
    """Muestra estado de manifests de embeddings."""
    settings = load_settings(args.config)
    if not settings.database_path.exists():
        print("No hay base SQLite de Barbarion. Ejecuta 'barbarion doctor'.")
        return 0
    repository = SQLiteRagRepository(settings.database_path)
    summaries = repository.embedding_summaries()
    if args.format == "json":
        print(
            json.dumps(
                {"manifests": [_embedding_summary_json(item) for item in summaries]},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    print("Embeddings RAG")
    if not summaries:
        print("manifests = ninguno")
        return 0
    for item in summaries:
        print(
            f"- id={item.id} estado={item.status} proveedor={item.provider} "
            f"modelo={item.model} dimension={item.dimension} "
            f"version={item.version[:12]} vector_store={item.vector_provider}/"
            f"{item.vector_table}"
        )
        print(
            f"  indexed={item.indexed} stale={item.stale} "
            f"deleted={item.deleted} error={item.error}"
        )
    return 0


def _run_stats(args: argparse.Namespace) -> int:
    """Muestra estadisticas H2 + H3 sin mutar la DB."""
    settings = load_settings(args.config)
    if not settings.database_path.exists():
        print("No hay base SQLite de Barbarion. Ejecuta 'barbarion doctor'.")
        return 0
    ingestion = SQLiteIngestionRepository(
        settings.database_path,
        domain=settings.domain,
    ).inventory_stats()
    rag = SQLiteRagRepository(settings.database_path).rag_inventory_stats()
    if args.format == "json":
        print(
            json.dumps(
                {
                    "ingestion": {
                        "latest_run_id": ingestion.latest_run_id,
                        "latest_run_status": ingestion.latest_run_status,
                        "files_current": ingestion.files_current,
                        "documents_current": ingestion.documents_current,
                        "chunks_current": ingestion.chunks_current,
                        "artifact_kinds": list(ingestion.artifact_kinds),
                    },
                    "rag": _rag_stats_json(rag),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    print("Estadisticas de ingesta")
    _render_ingestion_stats(ingestion)
    print()
    print("Estadisticas RAG")
    _render_rag_stats(rag)
    return 0


def _show_ingestion_stats(args: argparse.Namespace) -> int:
    """Muestra estadisticas persistidas sin crear ni escanear recursos."""
    settings = load_settings(args.config)
    if not settings.database_path.exists():
        print("No hay base SQLite de Barbarion. Ejecuta 'barbarion doctor'.")
        return 0
    repository = SQLiteIngestionRepository(settings.database_path, domain=settings.domain)
    stats = repository.inventory_stats()
    print("Estadisticas de ingesta")
    _render_ingestion_stats(stats)
    return 0


def _render_ingestion_stats(stats) -> None:
    print(f"ultimo_run = {stats.latest_run_id if stats.latest_run_id is not None else 'ninguno'}")
    print(f"ultimo_estado = {stats.latest_run_status or 'ninguno'}")
    print(f"archivos_vigentes = {stats.files_current}")
    print(f"documentos_vigentes = {stats.documents_current}")
    print(f"chunks_vigentes = {stats.chunks_current}")
    if stats.artifact_kinds:
        print("artefactos = " + ", ".join(f"{kind}:{count}" for kind, count in stats.artifact_kinds))
    else:
        print("artefactos = ninguno")


def _render_rag_stats(stats) -> None:
    print(f"manifests = {stats.manifests}")
    print(f"manifests_activos = {stats.active_manifests}")
    print(f"chunks_indexed = {stats.indexed_chunks}")
    print(f"chunks_stale = {stats.stale_chunks}")
    print(f"chunks_deleted = {stats.deleted_chunks}")
    print(f"chunks_error = {stats.error_chunks}")
    print(f"consultas = {stats.query_count}")
    print(f"ultima_consulta = {stats.latest_query_id if stats.latest_query_id is not None else 'ninguna'}")
    print(f"ultimo_estado_consulta = {stats.latest_query_status or 'ninguno'}")


def _embedding_summary_json(item) -> dict[str, object]:
    return {
        "id": item.id,
        "version": item.version,
        "provider": item.provider,
        "model": item.model,
        "dimension": item.dimension,
        "distance": item.distance,
        "normalize": item.normalize,
        "vector_provider": item.vector_provider,
        "vector_table": item.vector_table,
        "status": item.status,
        "counts": {
            "indexed": item.indexed,
            "stale": item.stale,
            "deleted": item.deleted,
            "error": item.error,
        },
    }


def _rag_stats_json(stats) -> dict[str, object]:
    return {
        "manifests": stats.manifests,
        "active_manifests": stats.active_manifests,
        "indexed_chunks": stats.indexed_chunks,
        "stale_chunks": stats.stale_chunks,
        "deleted_chunks": stats.deleted_chunks,
        "error_chunks": stats.error_chunks,
        "query_count": stats.query_count,
        "latest_query_id": stats.latest_query_id,
        "latest_query_status": stats.latest_query_status,
        "avg_candidate_count": stats.avg_candidate_count,
    }


def _index_scope(args: argparse.Namespace) -> IndexScope | None:
    if args.full:
        return None
    path_prefix = None if args.path is None else args.path.replace("\\", "/")
    return IndexScope(
        path_prefix=path_prefix,
        document_id=args.document,
        chunk_id=args.chunk_id,
    )


def _build_index_service(settings: Settings) -> IndexService:
    vector_table = f"{settings.vector_store.table_prefix}_vectors"
    return IndexService(
        settings=settings,
        repository=SQLiteRagRepository(
            settings.database_path,
            vector_provider=settings.vector_store.provider,
            vector_table=vector_table,
        ),
        embedding_provider=OllamaEmbeddingProvider(
            base_url=settings.ollama_url,
            model=settings.embeddings.model,
            timeout_seconds=settings.embeddings.timeout_seconds,
        ),
        vector_store=SQLiteVecStore(
            settings.database_path,
            table_prefix=settings.vector_store.table_prefix,
        ),
    )


def _build_search_service(settings: Settings) -> SearchService:
    vector_table = f"{settings.vector_store.table_prefix}_vectors"
    return SearchService(
        settings=settings,
        repository=SQLiteRagRepository(
            settings.database_path,
            vector_provider=settings.vector_store.provider,
            vector_table=vector_table,
        ),
        embedding_provider=OllamaEmbeddingProvider(
            base_url=settings.ollama_url,
            model=settings.embeddings.model,
            timeout_seconds=settings.embeddings.timeout_seconds,
        ),
        vector_store=SQLiteVecStore(
            settings.database_path,
            table_prefix=settings.vector_store.table_prefix,
        ),
    )


def _build_ask_service(settings: Settings) -> AskService:
    return AskService(
        search_service=_build_search_service(settings),
        context_builder=ContextBuilder(
            token_budget=settings.rag.context_token_budget,
            max_chunk_tokens=settings.rag.max_chunk_tokens,
            dedupe_min_hash_prefix=settings.rag.dedupe_min_hash_prefix,
            threshold=settings.retrieval.similarity_threshold,
        ),
        prompt_builder=PromptBuilder(),
        citation_validator=CitationValidator(),
        llm_provider=OllamaLlmProvider(
            base_url=settings.ollama_url,
            model=settings.llm.model,
            temperature=settings.llm.temperature,
        ),
        settings=settings,
    )


def _search_request(args: argparse.Namespace, settings: Settings) -> SearchRequest:
    return SearchRequest(
        query=args.query,
        mode=RetrievalMode(args.mode),
        filters=_retrieval_filter(args),
        top_k=args.top_k,
        candidate_k=args.candidate_k,
        similarity_threshold=args.threshold,
        vector_weight=settings.retrieval.vector_weight,
        keyword_weight=settings.retrieval.keyword_weight,
        debug=args.debug,
    )


def _retrieval_filter(args: argparse.Namespace) -> RetrievalFilter:
    return RetrievalFilter(
        domain=args.domain,
        artifact_kind=args.artifact_kind,
        language=args.language,
        document_id=args.document,
        folder=args.folder,
        extension=args.extension,
    )


def _render_search_response(response: SearchResponse, output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(_search_response_json(response), ensure_ascii=False, indent=2))
        return
    if output_format == "markdown":
        print("## Resultados")
        for candidate in response.candidates:
            print(_candidate_markdown(candidate))
        return
    print(f"Busqueda RAG: {response.mode.value}")
    print(f"Query: {response.query_id if response.query_id is not None else 'sin registro'}")
    for candidate in response.candidates:
        print(_candidate_text(candidate))


def _render_answer_result(result: AnswerResult, output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(_answer_result_json(result), ensure_ascii=False, indent=2))
        return
    if output_format == "markdown":
        print(result.answer)
        print("\n## Fuentes")
        for source in result.context.sources:
            print(_source_markdown(source))
        return
    print(result.answer)
    print("\nFuentes:")
    for source in result.context.sources:
        print(_source_text(source))


def _search_response_json(response: SearchResponse) -> dict[str, object]:
    return {
        "query_id": response.query_id,
        "mode": response.mode.value,
        "results": [_candidate_json(candidate) for candidate in response.candidates],
        "debug": dict(response.debug),
    }


def _answer_result_json(result: AnswerResult) -> dict[str, object]:
    return {
        "query_id": result.query_id,
        "status": result.status.value,
        "no_llm": result.no_llm,
        "citations_valid": result.citations_valid,
        "answer": result.answer,
        "sources": [_source_json(source) for source in result.context.sources],
        "omitted": list(result.context.omitted),
        "metrics": {
            "context_precision": result.context.metrics.context_precision,
            "context_recall": result.context.metrics.context_recall,
            "duplicate_ratio": result.context.metrics.duplicate_ratio,
            "token_waste": result.context.metrics.token_waste,
        },
        "debug": dict(result.debug),
    }


def _candidate_json(candidate) -> dict[str, object]:
    return {
        "chunk_id": candidate.chunk_id,
        "score": candidate.combined_score,
        "vector_score": candidate.vector_score,
        "keyword_score": candidate.keyword_score,
        "source": dict(candidate.source),
    }


def _source_json(source) -> dict[str, object]:
    return {
        "source_id": source.source_id,
        "chunk_id": source.candidate.chunk_id,
        "score": source.candidate.combined_score,
        "source": dict(source.candidate.source),
        "token_estimate": source.token_estimate,
    }


def _candidate_text(candidate) -> str:
    source = candidate.source
    location = _location_text(source)
    return (
        f"- score={candidate.combined_score:.3f} chunk={candidate.chunk_id} "
        f"{source.get('relative_path')}{location}"
    )


def _candidate_markdown(candidate) -> str:
    source = candidate.source
    return (
        f"- `{source.get('relative_path')}` chunk `{candidate.chunk_id}` "
        f"score `{candidate.combined_score:.3f}`{_location_text(source)}"
    )


def _source_text(source) -> str:
    candidate = source.candidate
    return (
        f"- [{source.source_id}] {candidate.source.get('relative_path')} "
        f"chunk={candidate.chunk_id} score={candidate.combined_score:.3f}"
        f"{_location_text(candidate.source)}"
    )


def _source_markdown(source) -> str:
    candidate = source.candidate
    return (
        f"- [{source.source_id}] `{candidate.source.get('relative_path')}`, "
        f"chunk `{candidate.chunk_id}`, score `{candidate.combined_score:.3f}`"
        f"{_location_text(candidate.source)}"
    )


def _location_text(source) -> str:
    start_line = source.get("start_line")
    end_line = source.get("end_line")
    if start_line is not None and end_line is not None:
        return f" lineas={start_line}-{end_line}"
    page_start = source.get("page_start")
    page_end = source.get("page_end")
    if page_start is not None and page_end is not None:
        return f" paginas={page_start}-{page_end}"
    return ""


def _render_index_summary(summary: IndexRunSummary) -> None:
    prefix = "Dry-run de indexacion RAG" if summary.dry_run else "Indexacion RAG"
    print(f"{prefix}: {summary.status.value}")
    if summary.run_id is not None:
        print(f"Run: {summary.run_id}")
    print(f"Nuevos: {summary.new_chunks}")
    print(f"Actualizados: {summary.updated_chunks}")
    print(f"Sin cambios: {summary.unchanged_chunks}")
    print(f"Eliminados: {summary.deleted_chunks}")
    print(f"Fallidos: {summary.failed_chunks}")
    print(f"Duracion: {summary.duration_ms} ms")


def _index_exit_code(summary: IndexRunSummary) -> int:
    if summary.status == EmbeddingRunStatus.INTERRUPTED:
        return 130
    if summary.status in {
        EmbeddingRunStatus.FAILED,
        EmbeddingRunStatus.COMPLETED_WITH_ERRORS,
    }:
        return 1
    return 0


def _settings_with_ingest_paths(settings: Settings, paths: Sequence[str] | None) -> Settings:
    if not paths:
        return settings
    resolved = tuple(Path(path).expanduser().resolve(strict=False) for path in paths)
    ingestion = replace(settings.ingestion, paths=resolved)
    return replace(settings, ingestion=ingestion)


def _missing_ingest_resources(settings: Settings) -> list[Path]:
    required = [settings.data_dir, settings.output_dir, settings.logs_dir, settings.database_path]
    return [path for path in required if not path.exists()]


def _mode(args: argparse.Namespace) -> IngestionMode:
    return IngestionMode.FULL if args.full else IngestionMode.INCREMENTAL


def _configure_ingest_logging(settings: Settings) -> logging.Logger | None:
    if not settings.logs_dir.exists():
        return None
    return configure_logging(settings)


def _build_ingestion_service(
    settings: Settings,
    *,
    logger: logging.Logger | None = None,
) -> IngestionService:
    registry = ParserRegistry(
        [
            OracleParser(),
            PowerBuilderParser(),
            MarkdownParser(),
            TextParser(),
            PdfParser(),
            DocxParser(),
        ]
    )
    return IngestionService(
        settings=settings,
        discovery=LocalFilesystemDiscovery(),
        fingerprint=LocalFingerprintCalculator(),
        repository=SQLiteIngestionRepository(
            settings.database_path,
            domain=settings.domain,
        ),
        parser_registry=registry,
        logger=logger,
    )


def _render_ingestion_outcome(outcome: IngestionOutcome) -> None:
    metrics = outcome.metrics
    print(f"Ingesta finalizada: {outcome.status.value}")
    print(f"Descubiertos: {metrics.discovered_files}")
    print(f"Procesados: {metrics.processed_files}")
    print(f"Sin cambios: {metrics.unchanged_files}")
    print(f"Omitidos: {metrics.skipped_files}")
    print(f"Eliminados: {metrics.deleted_files}")
    print(f"Errores: {metrics.error_count}")
    print(f"Chunks creados: {metrics.chunk_count}")
    print(f"Datos procesados: {metrics.processed_bytes} bytes")
    print(f"Duracion: {metrics.duration_ms or 0} ms")


def _configure_doctor_logging(
    settings: Settings,
    directory_results: tuple[DirectoryResult, ...],
) -> logging.Logger | None:
    """Configura logging solo cuando su directorio quedó disponible."""
    logs_result = next(
        (result for result in directory_results if "logs" in result.roles),
        None,
    )
    if logs_result is None or not logs_result.success:
        return None
    return configure_logging(settings)



def _render_doctor_report(report: DoctorReport) -> None:
    """Presenta checks y resumen en stdout con columnas estables."""
    name_width = max(len(check.name) for check in report.checks)
    for check in report.checks:
        print(f"{check.status:<5} {check.name:<{name_width}} {check.detail}")
    print()
    print(
        f"Resumen: {report.summary.pass_count} PASS, "
        f"{report.summary.warn_count} WARN, "
        f"{report.summary.fail_count} FAIL"
    )


def _log_doctor_report(logger: logging.Logger, report: DoctorReport) -> None:
    """Registra cada resultado con el nivel correspondiente."""
    log_methods = {
        "PASS": logger.info,
        "WARN": logger.warning,
        "FAIL": logger.error,
    }
    for check in report.checks:
        log_methods[check.status](
            "%s %s: %s",
            check.status,
            check.name,
            check.detail,
        )

    if report.summary.success:
        logger.info("Resultado del diagnóstico: éxito.")
    else:
        logger.error("Resultado del diagnóstico: fallo requerido.")


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser raíz sin provocar efectos secundarios."""
    parser = SpanishArgumentParser(
        prog="barbarion",
        description=(
            "Agente AI on-premise para sistemas legacy Oracle/PLSQL y PowerBuilder."
        ),
        add_help=False,
    )
    options = parser.add_argument_group("opciones")
    options.add_argument(
        "-h",
        "--help",
        action="help",
        help="muestra esta ayuda y finaliza",
    )
    options.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="muestra la versión instalada y finaliza",
    )
    options.add_argument(
        "--config",
        metavar="RUTA",
        help="usa el archivo TOML indicado",
    )

    commands = parser.add_subparsers(
        dest="command",
        title="comandos",
        metavar="COMANDO",
        required=True,
    )

    doctor_parser = commands.add_parser(
        "doctor",
        help="diagnostica el entorno local",
        description="Diagnostica el entorno local de Barbarion.",
        add_help=False,
    )
    _add_help_option(doctor_parser)
    doctor_parser.set_defaults(handler=_run_doctor)

    config_parser = commands.add_parser(
        "config",
        help="consulta la configuración efectiva",
        description="Consulta la configuración de Barbarion.",
        add_help=False,
    )
    _add_help_option(config_parser)
    config_commands = config_parser.add_subparsers(
        dest="config_command",
        title="subcomandos",
        metavar="SUBCOMANDO",
        required=True,
    )
    show_parser = config_commands.add_parser(
        "show",
        help="muestra la configuración efectiva",
        description="Muestra la configuración efectiva de Barbarion.",
        add_help=False,
    )
    _add_help_option(show_parser)
    show_parser.set_defaults(handler=_show_config)

    ingest_parser = commands.add_parser(
        "ingest",
        help="ingesta corpus local autorizado",
        description="Ejecuta ingesta local o consulta estadisticas persistidas.",
        add_help=False,
    )
    _add_help_option(ingest_parser)
    ingest_parser.add_argument(
        "--path",
        action="append",
        metavar="RUTA",
        help="root de ingesta; puede repetirse y reemplaza paths configurados",
    )
    mode_group = ingest_parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--incremental",
        action="store_true",
        help="ejecuta ingesta incremental",
    )
    mode_group.add_argument(
        "--full",
        action="store_true",
        help="reprocesa todos los archivos descubiertos",
    )
    ingest_parser.add_argument(
        "--stats",
        action="store_true",
        help="muestra estadisticas persistidas sin ejecutar ingesta",
    )
    ingest_parser.set_defaults(handler=_run_ingest)

    index_parser = commands.add_parser(
        "index",
        help="indexa chunks vigentes para RAG",
        description="Ejecuta indexacion RAG incremental.",
        add_help=False,
    )
    _add_help_option(index_parser)
    index_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="muestra alcance sin escribir ni llamar modelos",
    )
    index_parser.set_defaults(handler=_run_index)

    reindex_parser = commands.add_parser(
        "reindex",
        help="reconstruye total o parcialmente el indice RAG",
        description="Ejecuta reindexacion RAG completa o parcial.",
        add_help=False,
    )
    _add_help_option(reindex_parser)
    reindex_parser.add_argument(
        "--full",
        action="store_true",
        help="reindexa todos los chunks vigentes",
    )
    reindex_parser.add_argument(
        "--path",
        metavar="RUTA",
        help="limita la reindexacion por prefijo de ruta persistida",
    )
    reindex_parser.add_argument(
        "--document",
        type=int,
        metavar="ID",
        help="limita la reindexacion a un documento",
    )
    reindex_parser.add_argument(
        "--chunk-id",
        metavar="ID",
        help="limita la reindexacion a un chunk",
    )
    reindex_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="muestra alcance sin escribir ni llamar modelos",
    )
    reindex_parser.add_argument(
        "--delete-obsolete",
        action="store_true",
        help="elimina vectores obsoletos durante una reindexacion completa",
    )
    reindex_parser.set_defaults(handler=_run_reindex)

    search_parser = commands.add_parser(
        "search",
        help="busca evidencia RAG",
        description="Busca evidencia RAG local en modo semantic, keyword o hybrid.",
        add_help=False,
    )
    _add_help_option(search_parser)
    _add_query_arguments(search_parser, positional_name="query")
    search_parser.set_defaults(handler=_run_search)

    ask_parser = commands.add_parser(
        "ask",
        help="responde una pregunta con evidencia",
        description="Responde una pregunta usando contexto RAG local.",
        add_help=False,
    )
    _add_help_option(ask_parser)
    _add_query_arguments(ask_parser, positional_name="question")
    ask_parser.add_argument(
        "--no-llm",
        action="store_true",
        help="muestra contexto y fuentes sin invocar LLM",
    )
    ask_parser.set_defaults(handler=_run_ask)

    embeddings_parser = commands.add_parser(
        "embeddings",
        help="muestra manifests de embeddings",
        description="Muestra manifests, versiones y conteos de embeddings RAG.",
        add_help=False,
    )
    _add_help_option(embeddings_parser)
    embeddings_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="formato de salida",
    )
    embeddings_parser.set_defaults(handler=_run_embeddings)

    stats_parser = commands.add_parser(
        "stats",
        help="muestra estadisticas locales",
        description="Muestra estadisticas H2 y H3 sin mutar SQLite.",
        add_help=False,
    )
    _add_help_option(stats_parser)
    stats_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="formato de salida",
    )
    stats_parser.set_defaults(handler=_run_stats)

    return parser


def _add_query_arguments(parser: argparse.ArgumentParser, *, positional_name: str) -> None:
    parser.add_argument(positional_name, metavar="TEXTO", help="consulta o pregunta")
    parser.add_argument(
        "--mode",
        choices=[mode.value for mode in RetrievalMode],
        default="hybrid",
        help="modo de recuperacion",
    )
    parser.add_argument("--top-k", type=int, default=10, help="cantidad final")
    parser.add_argument(
        "--candidate-k",
        type=int,
        default=50,
        help="cantidad inicial de candidatos",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.0,
        help="score minimo aceptado",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json", "markdown"),
        default="text",
        help="formato de salida",
    )
    parser.add_argument("--domain", help="filtra por dominio")
    parser.add_argument("--artifact-kind", help="filtra por tipo de artefacto")
    parser.add_argument("--language", help="filtra por lenguaje")
    parser.add_argument("--document", type=int, help="filtra por documento")
    parser.add_argument("--folder", help="filtra por carpeta")
    parser.add_argument("--extension", help="filtra por extension")
    parser.add_argument("--debug", action="store_true", help="incluye debug RAG")


def main(argv: Sequence[str] | None = None) -> int:
    """Procesa los argumentos y devuelve el código de salida del proceso."""
    try:
        parser = build_parser()
        args = parser.parse_args(argv)
        return args.handler(args)
    except ConfigError as error:
        print(f"Error de configuración: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"Error operativo: {error}", file=sys.stderr)
        return 1
    except DatabaseError as error:
        print(f"Error de base de datos: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Operación interrumpida por el usuario.", file=sys.stderr)
        return 130
