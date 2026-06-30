"""Punto de entrada de la línea de comandos de Barbarion."""

import argparse
import json
import logging
import signal
import shutil
import sys
import time
from collections.abc import Sequence
from contextlib import contextmanager
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
from barbarion.application.reverse_engineering import (
    AnalyzeScope,
    AnalyzeService,
    AnalyzeSummary,
    DependencyWalkService,
    DescribeRequest,
    DescribeService,
    ImpactRequest,
    ImpactService,
    InventoryRequest,
    InventoryService,
    ObjectRequest,
)
from barbarion.application.reporting import generate_rag_report
from barbarion.bootstrap import DirectoryResult, initialize_directories
from barbarion.config import ConfigError, Settings, load_settings, settings_display_items
from barbarion.database import DatabaseError, initialize_database
from barbarion.doctor import DoctorReport, run_doctor_checks
from barbarion.domain.models import IngestionMode
from barbarion.domain.models import IngestionOutcome
from barbarion.domain.models import IngestionRunStatus
from barbarion.domain.models import Confidence
from barbarion.domain.progress import ProgressSnapshot, ProgressStage
from barbarion.domain.rag import (
    AnswerResult,
    EmbeddingRunMode,
    EmbeddingRunStatus,
    IndexRunSummary,
    IndexScope,
    LlmProviderError,
    RetrievalFilter,
    RetrievalMode,
    SearchRequest,
    SearchResponse,
)
from barbarion.domain.reverse_engineering import (
    AnalysisRunMode,
    AnalysisRunStatus,
    ComponentDescription,
    DependencyDirection,
    DependencyEdge,
    DependencyFilters,
    ImpactAnalysis,
    Inventory,
    InventoryFilters,
    InventoryItem,
    ResolutionStatus,
    SymbolStatus,
    TechnicalSymbol,
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
from barbarion.infrastructure.sqlite import SQLiteReverseEngineeringRepository
from barbarion.infrastructure.sqlite_vec import SQLiteVecStore
from barbarion.infrastructure.llm import OllamaLlmProvider
from barbarion.infrastructure.markdown import (
    render_component_markdown,
    render_impact_markdown,
    render_inventory_markdown,
    safe_component_filename,
    safe_impact_filename,
    safe_inventory_filename,
    write_text_artifact,
)
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


def _positive_int(value: str) -> int:
    """Valida enteros positivos para opciones CLI.

    Args:
        value: Valor textual recibido por `argparse`.

    Returns:
        Entero positivo validado.

    Raises:
        argparse.ArgumentTypeError: Si el valor no es un entero positivo.
    """
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("debe ser un entero positivo") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("debe ser un entero positivo")
    return parsed


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
    cancellation = CliCancellationToken()
    with _index_cancellation_context(cancellation):
        summary = service.run(
            mode=EmbeddingRunMode.INCREMENTAL,
            dry_run=args.dry_run,
            delete_obsolete=True,
            progress=ConsoleProgressReporter(),
            cancellation=cancellation,
        )
    _log_index_error_summary(settings, summary)
    _render_index_summary(summary)
    return _index_exit_code(summary)


class CliCancellationToken:
    """Token cooperativo activado por Ctrl+C."""

    def __init__(self) -> None:
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True


class ConsoleProgressReporter:
    """Reporter de progreso simple para CLI, sin dependencias externas."""

    def __init__(
        self,
        stream=None,
        *,
        min_interval_seconds: float = 0.25,
        title: str = "Barbarion Index",
    ) -> None:
        self._stream = stream or sys.stderr
        self._title = title
        self._started_at = time.monotonic()
        self._last_emit_at = 0.0
        self._min_interval_seconds = min_interval_seconds
        self._last_stage = ""
        self._block_active = False

    def start(self, stages: tuple[ProgressStage, ...]) -> None:
        del stages
        self._started_at = time.monotonic()
        self._last_emit_at = 0.0
        self._last_stage = ""
        self._block_active = False

    def stage(self, snapshot: ProgressSnapshot) -> None:
        now = time.monotonic()
        if not self._should_emit(snapshot, now):
            return
        stage_percent = _progress_percent(snapshot.current, snapshot.total)
        global_percent = _progress_percent(snapshot.global_current, snapshot.global_total)
        counters = _progress_counter_values(snapshot.counters)
        block = (
            self._title,
            "Ctrl+C cancela de forma segura; puedes reanudar luego.",
            "",
            (
                f"Global  {_progress_bar(snapshot.global_current, snapshot.global_total)} "
                f"{global_percent}"
            ),
            "",
            (
                f"Etapa   {_progress_bar(snapshot.current, snapshot.total)} "
                f"{stage_percent}"
            ),
            _progress_stage_label(snapshot.stage_label),
            "",
            (
                f"Procesados : {snapshot.current} / "
                f"{_progress_total(snapshot.total)}"
            ),
            "",
            f"Nuevos       : {counters['new']}",
            f"Actualizados : {counters['update']}",
            f"Sin cambios  : {counters['unchanged']}",
            f"Eliminados   : {counters['delete']}",
            _progress_errors_line(counters["errores"]),
        )
        self._write_block(tuple(_fit_progress_line(line) for line in block))
        self._last_stage = snapshot.stage_key
        self._last_emit_at = now

    def finish(self, status: str) -> None:
        self._block_active = False
        print(f"Progreso finalizado: {status}", file=self._stream)

    def _should_emit(self, snapshot: ProgressSnapshot, now: float) -> bool:
        if snapshot.stage_key != self._last_stage:
            return True
        if snapshot.total is not None and snapshot.current >= snapshot.total:
            return True
        return now - self._last_emit_at >= self._min_interval_seconds

    def _write_block(self, lines: tuple[str, ...]) -> None:
        if _is_interactive_stream(self._stream):
            if self._block_active:
                self._stream.write(f"\x1b[{len(lines)}F")
            for line in lines:
                self._stream.write(f"\r\x1b[2K{line}\n")
            self._stream.flush()
            self._block_active = True
            return
        for line in lines:
            print(line, file=self._stream)


@contextmanager
def _index_cancellation_context(token: CliCancellationToken):
    previous = signal.getsignal(signal.SIGINT)

    def _handle_sigint(signum, frame):  # noqa: ANN001
        del signum, frame
        if not token.cancelled:
            token.cancel()
            print(
                "\nCancelacion solicitada. Cerrando la unidad actual de forma segura...",
                file=sys.stderr,
            )
        else:
            print(
                "\nCancelacion ya solicitada. Esperando cierre seguro...",
                file=sys.stderr,
            )

    signal.signal(signal.SIGINT, _handle_sigint)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)


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
    cancellation = CliCancellationToken()
    with _index_cancellation_context(cancellation):
        summary = service.run(
            mode=mode,
            scope=scope,
            dry_run=args.dry_run,
            delete_obsolete=args.delete_obsolete,
            progress=ConsoleProgressReporter(),
            cancellation=cancellation,
        )
    _log_index_error_summary(settings, summary)
    _render_index_summary(summary)
    return _index_exit_code(summary)


def _run_analyze(args: argparse.Namespace) -> int:
    """Ejecuta analisis reverse engineering sobre chunks ya ingeridos."""
    settings = load_settings(args.config)
    if not settings.database_path.exists():
        print(
            "No hay base SQLite de Barbarion. Ejecuta 'barbarion doctor' e "
            "ingesta el corpus antes de analizar.",
            file=sys.stderr,
        )
        return 1
    initialize_database(settings.database_path)
    service = _build_analyze_service(settings)
    mode = AnalysisRunMode.FULL if args.full else AnalysisRunMode.INCREMENTAL
    path_prefixes = _analyze_path_prefixes(args.path)
    if path_prefixes:
        mode = AnalysisRunMode.PARTIAL
    cancellation = CliCancellationToken()
    summaries: list[AnalyzeSummary] = []
    with _index_cancellation_context(cancellation):
        for path_prefix in path_prefixes or (None,):
            summary = service.run(
                mode=mode,
                scope=AnalyzeScope(path_prefix=path_prefix),
                dry_run=args.dry_run,
                progress=ConsoleProgressReporter(title="Barbarion Analyze"),
                cancellation=cancellation,
            )
            summaries.append(summary)
            if summary.status == AnalysisRunStatus.INTERRUPTED:
                break
    for summary in summaries:
        _render_analyze_summary(summary)
    return _analyze_exit_code(tuple(summaries))


def _run_inventory(args: argparse.Namespace) -> int:
    """Consulta inventario reverse engineering desde SQLite y lo presenta.

    Args:
        args: Argumentos parseados por `argparse` para el comando
            `inventory`.

    Returns:
        Codigo de salida CLI: 0 si se genera la salida, 1 ante errores
        operativos esperados.
    """
    settings = load_settings(args.config)
    if not settings.database_path.exists():
        print(
            "No hay base SQLite de Barbarion. Ejecuta 'barbarion doctor' e "
            "ingesta el corpus antes de consultar inventario.",
            file=sys.stderr,
        )
        return 1
    initialize_database(settings.database_path)
    service = _build_inventory_service(settings)
    request = InventoryRequest(filters=_inventory_filters(args))
    started = time.monotonic()
    inventory = service.inventory(request)
    content = _render_inventory(inventory, args.format)
    duration_ms = int((time.monotonic() - started) * 1000)
    if args.debug:
        _render_operation_debug(
            "inventory",
            {
                "format": args.format,
                "duration_ms": duration_ms,
                "files": inventory.summary.files,
                "symbols": inventory.summary.symbols,
                "references": inventory.summary.references,
                "relations": inventory.summary.relations,
                "items": len(inventory.items),
            },
        )
    if args.output is not None:
        output_path = _inventory_output_path(settings, args.output, inventory)
        try:
            written = write_text_artifact(
                output_path,
                content,
                overwrite=args.overwrite,
            )
        except FileExistsError as error:
            print(f"Error operativo: {error}", file=sys.stderr)
            return 1
        print(f"Inventario escrito: {written}")
        return 0
    print(content)
    return 0


def _run_describe(args: argparse.Namespace) -> int:
    """Describe un componente reverse engineering y renderiza la salida solicitada.

    Args:
        args: Argumentos parseados por `argparse` para el comando `describe`.

    Returns:
        Codigo de salida CLI: 0 si se genera la salida, 1 ante errores
        operativos esperados.
    """
    settings = load_settings(args.config)
    if not settings.database_path.exists():
        print(
            "No hay base SQLite de Barbarion. Ejecuta 'barbarion doctor' e "
            "ingesta el corpus antes de describir componentes.",
            file=sys.stderr,
        )
        return 1
    initialize_database(settings.database_path)
    service = _build_describe_service(settings, with_llm=args.with_llm)
    request = DescribeRequest(
        target=_object_request(args),
        depth=args.depth,
        no_llm=not args.with_llm or args.no_llm,
        include_rag=args.include_rag,
    )
    started = time.monotonic()
    description = service.describe(request)
    content = _render_description(description, args.format)
    duration_ms = int((time.monotonic() - started) * 1000)
    if args.debug:
        _render_operation_debug(
            "describe",
            {
                "format": args.format,
                "duration_ms": duration_ms,
                "resolution_status": description.resolution.status,
                "candidates": len(description.resolution.candidates),
                "outgoing_edges": (
                    len(description.outgoing.edges)
                    if description.outgoing is not None
                    else 0
                ),
                "incoming_edges": (
                    len(description.incoming.edges)
                    if description.incoming is not None
                    else 0
                ),
                "evidence": len(description.evidence),
                "limitations": len(description.limitations),
                "no_llm": description.no_llm,
            },
        )
    if args.output is not None:
        output_path = _description_output_path(settings, args.output, description)
        try:
            written = write_text_artifact(
                output_path,
                content,
                overwrite=args.overwrite,
            )
        except FileExistsError as error:
            print(f"Error operativo: {error}", file=sys.stderr)
            return 1
        print(f"Ficha escrita: {written}")
        return 0
    print(content)
    return 0


def _run_impact(args: argparse.Namespace) -> int:
    """Analiza impacto reverse engineering y renderiza la salida solicitada.

    Args:
        args: Argumentos parseados por `argparse` para el comando `impact`.

    Returns:
        Codigo de salida CLI: 0 si se genera la salida, 1 ante errores
        operativos esperados.
    """
    settings = load_settings(args.config)
    if not settings.database_path.exists():
        print(
            "No hay base SQLite de Barbarion. Ejecuta 'barbarion doctor' e "
            "ingesta el corpus antes de analizar impacto.",
            file=sys.stderr,
        )
        return 1
    initialize_database(settings.database_path)
    service = _build_impact_service(settings, with_llm=args.with_llm)
    request = ImpactRequest(
        target=_object_request(args),
        direction=DependencyDirection(args.direction),
        depth=args.depth,
        node_limit=args.node_limit,
        no_llm=not args.with_llm or args.no_llm,
        include_rag=args.include_rag,
        filters=_dependency_filters(args),
    )
    started = time.monotonic()
    impact = service.analyze(request)
    content = _render_impact(impact, args.format)
    duration_ms = int((time.monotonic() - started) * 1000)
    if args.debug:
        _render_operation_debug(
            "impact",
            {
                "format": args.format,
                "duration_ms": duration_ms,
                "resolution_status": impact.resolution.status,
                "direction": args.direction,
                "depth": args.depth,
                "nodes": len(impact.walk.nodes) if impact.walk is not None else 0,
                "edges": len(impact.walk.edges) if impact.walk is not None else 0,
                "consumers": len(impact.consumers),
                "dependencies": len(impact.dependencies),
                "cross_technology": len(impact.cross_technology),
                "risks": len(impact.risks),
                "to_confirm": len(impact.to_confirm),
                "limitations": len(impact.limitations),
                "no_llm": impact.no_llm,
            },
        )
    if args.output is not None:
        output_path = _impact_output_path(settings, args.output, impact)
        try:
            written = write_text_artifact(
                output_path,
                content,
                overwrite=args.overwrite,
            )
        except FileExistsError as error:
            print(f"Error operativo: {error}", file=sys.stderr)
            return 1
        print(f"Impacto escrito: {written}")
        return 0
    print(content)
    return 0


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
    try:
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
    except KeyboardInterrupt:
        print("Operacion interrumpida por el usuario.", file=sys.stderr)
        return 130
    except TimeoutError:
        _print_llm_error("Ollama no respondio dentro del timeout configurado.")
        return 1
    except LlmProviderError as error:
        _print_llm_error(_llm_error_message(error))
        return 1
    _render_answer_result(result, args.format)
    return 0 if result.citations_valid else 1


def _run_embeddings(args: argparse.Namespace) -> int:
    """Muestra estado de manifests de embeddings."""
    settings = load_settings(args.config)
    if not settings.database_path.exists():
        print("No hay base SQLite de Barbarion. Ejecuta 'barbarion doctor'.")
        return 0
    repository = SQLiteRagRepository(settings.database_path)
    if args.errors:
        return _render_embedding_errors(repository, args.run)
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
    """Muestra estadisticas ingesta + RAG sin mutar la DB."""
    settings = load_settings(args.config)
    if not settings.database_path.exists():
        print("No hay base SQLite de Barbarion. Ejecuta 'barbarion doctor'.")
        return 0
    ingestion = SQLiteIngestionRepository(
        settings.database_path,
        domain=settings.domain,
    ).inventory_stats()
    rag = SQLiteRagRepository(settings.database_path).rag_inventory_stats()
    reverse_engineering = SQLiteReverseEngineeringRepository(settings.database_path).stats()
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
                    "reverse_engineering": _reverse_engineering_stats_json(
                        reverse_engineering
                    ),
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
    print()
    print("Estadisticas reverse engineering")
    _render_reverse_engineering_stats(reverse_engineering)
    return 0


def _run_generate_report(args: argparse.Namespace) -> int:
    """Genera evidencia tecnica local del cierre RAG."""
    summary = generate_rag_report(
        dataset_path=Path(args.dataset),
        output_dir=Path(args.output),
        test_summary=args.test_summary,
        smoke_summary=args.smoke_summary,
        metadata={
            "command": "barbarion generate-report",
            "version": __version__,
        },
    )
    print("Reporte RAG generado")
    print(f"Directorio: {summary.output_dir}")
    print(f"metrics.json: {summary.metrics_path}")
    print(f"topk-report.md: {summary.topk_report_path}")
    print(f"smoke-report.md: {summary.smoke_report_path}")
    print(f"benchmark.md: {summary.benchmark_path}")
    print(f"historico: {summary.history_path}")
    print(f"recall@5 = {summary.recall_at_5:.3f}")
    print(f"recall@10 = {summary.recall_at_10:.3f}")
    print(f"mrr = {summary.mrr:.3f}")
    return 0


def _render_embedding_errors(
    repository: SQLiteRagRepository,
    run_id: int | None,
) -> int:
    details = repository.embedding_error_details(run_id=run_id)
    selected_run_id = run_id or repository.latest_embedding_error_run_id()
    print("Errores de embeddings RAG")
    if selected_run_id is None:
        print("Run: ninguno")
        print("Errores: 0")
        return 0
    print(f"Run: {selected_run_id}")
    print(f"Errores: {len(details)}")
    if not details:
        return 0
    print()
    for index, item in enumerate(details, start=1):
        print(f"{index}. chunk_id={item.chunk_id}")
        print(f"   error={item.error_code}")
        print(f"   mensaje={item.error_message}")
        print()
    return 0


def _log_index_error_summary(settings: Settings, summary: IndexRunSummary) -> None:
    if summary.failed_chunks <= 0 or summary.run_id is None:
        return
    logger = configure_logging(settings)
    repository = SQLiteRagRepository(settings.database_path)
    error_code = repository.dominant_embedding_error_code(run_id=summary.run_id)
    logger.warning(
        "index run_id=%s status=%s failed_chunks=%s error_code=%s",
        summary.run_id,
        summary.status.value,
        summary.failed_chunks,
        error_code or "desconocido",
    )


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


def _reverse_engineering_stats_json(stats) -> dict[str, object]:
    return {
        "latest_run_id": stats.latest_run_id,
        "latest_run_status": stats.latest_run_status,
        "latest_run_duration_ms": stats.latest_run_duration_ms,
        "symbols": {
            "active": stats.symbols_active,
            "stale": stats.symbols_stale,
            "deleted": stats.symbols_deleted,
            "ambiguous": stats.symbols_ambiguous,
        },
        "references_total": stats.references_total,
        "relations": {
            "active": stats.relations_active,
            "resolved": stats.relations_resolved,
            "ambiguous": stats.relations_ambiguous,
            "unresolved": stats.relations_unresolved,
            "dynamic": stats.relations_dynamic,
            "external": stats.relations_external,
        },
    }


def _render_reverse_engineering_stats(stats) -> None:
    latest = (
        "ninguno"
        if stats.latest_run_id is None
        else f"{stats.latest_run_id} ({stats.latest_run_status})"
    )
    print(f"ultimo_run = {latest}")
    print(f"duracion_ms = {stats.latest_run_duration_ms if stats.latest_run_duration_ms is not None else 'n/a'}")
    print(f"simbolos_active = {stats.symbols_active}")
    print(f"simbolos_stale = {stats.symbols_stale}")
    print(f"simbolos_deleted = {stats.symbols_deleted}")
    print(f"simbolos_ambiguous = {stats.symbols_ambiguous}")
    print(f"referencias = {stats.references_total}")
    print(f"relaciones_active = {stats.relations_active}")
    print(f"relaciones_resolved = {stats.relations_resolved}")
    print(f"relaciones_ambiguous = {stats.relations_ambiguous}")
    print(f"relaciones_unresolved = {stats.relations_unresolved}")
    print(f"relaciones_dynamic = {stats.relations_dynamic}")
    print(f"relaciones_external = {stats.relations_external}")


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


def _build_analyze_service(settings: Settings) -> AnalyzeService:
    return AnalyzeService(
        settings=settings,
        repository=SQLiteReverseEngineeringRepository(settings.database_path),
    )


def _build_inventory_service(settings: Settings) -> InventoryService:
    """Construye el servicio de inventario reverse engineering.

    Args:
        settings: Configuracion efectiva de Barbarion.

    Returns:
        Servicio de inventario conectado al repositorio SQLite reverse engineering.
    """
    return InventoryService(
        repository=SQLiteReverseEngineeringRepository(settings.database_path),
    )


def _build_describe_service(
    settings: Settings,
    *,
    with_llm: bool = False,
) -> DescribeService:
    """Construye el servicio de descripcion sobre SQLite.

    Args:
        settings: Configuracion efectiva de Barbarion.
        with_llm: Indica si se debe cablear un proveedor LLM local.

    Returns:
        Servicio `describe` conectado a repositorios locales.
    """
    repository = SQLiteReverseEngineeringRepository(settings.database_path)
    return DescribeService(
        repository=repository,
        dependency_walk_service=DependencyWalkService(repository),
        search_service=_build_search_service(settings),
        context_builder=ContextBuilder(
            token_budget=settings.rag.context_token_budget,
            max_chunk_tokens=settings.rag.max_chunk_tokens,
            dedupe_min_hash_prefix=settings.rag.dedupe_min_hash_prefix,
            threshold=settings.retrieval.similarity_threshold,
        ),
        llm_provider=_build_llm_provider(settings) if with_llm else None,
        llm_timeout_seconds=settings.llm.timeout_seconds,
    )


def _build_impact_service(
    settings: Settings,
    *,
    with_llm: bool = False,
) -> ImpactService:
    """Construye el servicio de impacto sobre SQLite.

    Args:
        settings: Configuracion efectiva de Barbarion.
        with_llm: Indica si se debe cablear un proveedor LLM local.

    Returns:
        Servicio `impact` conectado a repositorios locales.
    """
    repository = SQLiteReverseEngineeringRepository(settings.database_path)
    return ImpactService(
        repository=repository,
        dependency_walk_service=DependencyWalkService(repository),
        search_service=_build_search_service(settings),
        context_builder=ContextBuilder(
            token_budget=settings.rag.context_token_budget,
            max_chunk_tokens=settings.rag.max_chunk_tokens,
            dedupe_min_hash_prefix=settings.rag.dedupe_min_hash_prefix,
            threshold=settings.retrieval.similarity_threshold,
        ),
        llm_provider=_build_llm_provider(settings) if with_llm else None,
        llm_timeout_seconds=settings.llm.timeout_seconds,
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


def _build_llm_provider(settings: Settings) -> OllamaLlmProvider:
    """Construye el proveedor LLM local configurado.

    Args:
        settings: Configuracion efectiva de Barbarion.

    Returns:
        Proveedor Ollama local.
    """
    return OllamaLlmProvider(
        base_url=settings.ollama_url,
        model=settings.llm.model,
        temperature=settings.llm.temperature,
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
        llm_provider=_build_llm_provider(settings),
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
        _render_answer_debug(result, markdown=True)
        print(result.answer)
        print("\n## Fuentes")
        for source in result.context.sources:
            print(_source_markdown(source))
        return
    _render_answer_debug(result, markdown=False)
    print(result.answer)
    print("\nFuentes:")
    for source in result.context.sources:
        print(_source_text(source))


def _render_answer_debug(result: AnswerResult, *, markdown: bool) -> None:
    if not result.debug:
        return
    keys = (
        "sources",
        "context_chars",
        "context_tokens_est",
        "prompt_chars",
        "llm_timeout_seconds",
        "truncated_sources",
    )
    if markdown:
        print("## Debug")
        for key in keys:
            print(f"- {key}={result.debug.get(key)}")
        print()
        return
    print("Debug:")
    for key in keys:
        print(f"{key}={result.debug.get(key)}")
    print()


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
        "original_token_estimate": source.original_token_estimate,
        "content_truncated": source.content_truncated,
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
        f"{_location_text(candidate.source)} "
        f"contenido_truncado={str(source.content_truncated).lower()}"
    )


def _source_markdown(source) -> str:
    candidate = source.candidate
    return (
        f"- [{source.source_id}] `{candidate.source.get('relative_path')}`, "
        f"chunk `{candidate.chunk_id}`, score `{candidate.combined_score:.3f}`"
        f"{_location_text(candidate.source)}, "
        f"contenido_truncado `{str(source.content_truncated).lower()}`"
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


def _print_llm_error(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
    print("", file=sys.stderr)
    print("Sugerencias:", file=sys.stderr)
    print("- ejecuta nuevamente la pregunta;", file=sys.stderr)
    print("- usa --no-llm para inspeccionar el contexto;", file=sys.stderr)
    print("- aumenta [llm].timeout_seconds en barbarion.toml;", file=sys.stderr)
    print("- verifica el modelo configurado en [llm].model;", file=sys.stderr)
    print("- prueba: ollama run llama3.1:8b", file=sys.stderr)


def _llm_error_message(error: LlmProviderError) -> str:
    message = str(error)
    if "TIMEOUT" in message:
        return "Ollama no respondio dentro del timeout configurado."
    if "MODEL_NOT_FOUND" in message:
        return "El modelo LLM configurado no esta disponible en Ollama."
    if "RESPONSE_INVALID" in message:
        return "Ollama devolvio una respuesta invalida."
    if "UNAVAILABLE" in message:
        return "No se pudo contactar Ollama local."
    if "HTTP_ERROR" in message:
        return "Ollama devolvio un error HTTP."
    return "No se pudo generar la respuesta con el LLM local."


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
    print(f"Procesados: {summary.processed_chunks}")
    print(f"Pendientes: {summary.pending_chunks}")
    print(f"Embeddings generados: {summary.embeddings_generated}")
    print(f"Vectores persistidos: {summary.vectors_persisted}")
    print(f"Duracion: {summary.duration_ms} ms")


def _render_analyze_summary(summary: AnalyzeSummary) -> None:
    prefix = "Dry-run de analisis tecnico" if summary.dry_run else "Analisis tecnico"
    print(f"{prefix}: {summary.status.value}")
    print(f"Run: {summary.run_id if summary.run_id is not None else 'ninguno'}")
    print(f"Archivos: {summary.files_scanned}")
    print(f"Chunks: {summary.chunks_scanned}")
    print(f"Simbolos: {summary.symbols_detected}")
    print(f"Referencias: {summary.references_detected}")
    print(f"Relaciones resueltas: {summary.relations_resolved}")
    print(f"Relaciones ambiguas: {summary.relations_ambiguous}")
    print(f"Relaciones no resueltas: {summary.relations_unresolved}")
    print(f"Duracion: {summary.duration_ms} ms")


def _inventory_filters(args: argparse.Namespace) -> InventoryFilters:
    """Construye filtros reverse engineering desde argumentos de CLI.

    Args:
        args: Argumentos parseados para `barbarion inventory`.

    Returns:
        Filtros estructurados para la consulta de inventario.
    """
    return InventoryFilters(
        technology=args.technology,
        symbol_type=args.symbol_type,
        name=args.name,
        path=args.path.replace("\\", "/") if args.path else None,
        status=SymbolStatus(args.status) if args.status else None,
        confidence=Confidence(args.confidence) if args.confidence else None,
    )


def _render_inventory(inventory: Inventory, output_format: str) -> str:
    """Renderiza inventario reverse engineering en text, JSON o Markdown.

    Args:
        inventory: Resultado estructurado de inventario.
        output_format: Formato solicitado por CLI.

    Returns:
        Contenido listo para stdout o escritura a archivo.
    """
    if output_format == "json":
        return json.dumps(_inventory_json(inventory), ensure_ascii=False, indent=2)
    if output_format == "markdown":
        return render_inventory_markdown(inventory)
    lines = [
        "Inventario tecnico",
        f"archivos = {inventory.summary.files}",
        f"simbolos = {inventory.summary.symbols}",
        f"referencias = {inventory.summary.references}",
        f"relaciones = {inventory.summary.relations}",
    ]
    if not inventory.items:
        lines.append("sin simbolos para los filtros indicados")
        return "\n".join(lines)
    lines.extend(_inventory_item_text(item) for item in inventory.items)
    return "\n".join(lines)


def _inventory_output_path(
    settings: Settings,
    requested_output: str,
    inventory: Inventory,
) -> Path:
    """Resuelve una ruta de salida de inventario.

    Args:
        settings: Configuracion efectiva con `output_dir`.
        requested_output: Ruta o directorio solicitado por el usuario.
        inventory: Inventario usado para nombre seguro cuando se pasa un
            directorio.

    Returns:
        Ruta absoluta o relativa a `output_dir` lista para escritura.
    """
    requested = Path(requested_output)
    if requested_output.endswith(("/", "\\")) or requested.suffix == "":
        requested = requested / safe_inventory_filename(inventory.filters)
    if requested.is_absolute():
        return requested
    return settings.output_dir / requested


def _inventory_json(inventory: Inventory) -> dict[str, object]:
    return {
        "template_version": "inventory.v1",
        "filters": {
            "technology": inventory.filters.technology,
            "type": inventory.filters.symbol_type,
            "name": inventory.filters.name,
            "path": inventory.filters.path,
            "status": (
                inventory.filters.status.value if inventory.filters.status else None
            ),
            "confidence": (
                inventory.filters.confidence.value
                if inventory.filters.confidence
                else None
            ),
        },
        "summary": {
            "files": inventory.summary.files,
            "symbols": inventory.summary.symbols,
            "references": inventory.summary.references,
            "relations": inventory.summary.relations,
        },
        "items": [_inventory_item_json(item) for item in inventory.items],
    }


def _inventory_item_json(item: InventoryItem) -> dict[str, object]:
    symbol = item.symbol
    return {
        "symbol_id": symbol.symbol_id,
        "original_name": symbol.original_name,
        "normalized_name": symbol.normalized_name,
        "type": symbol.symbol_type,
        "technology": symbol.technology,
        "status": symbol.status.value,
        "confidence": symbol.confidence.value,
        "file_id": symbol.file_id,
        "relative_path": item.relative_path,
        "chunk_id": symbol.chunk_id,
        "start_line": symbol.start_line,
        "end_line": symbol.end_line,
        "container_name": symbol.container_name,
        "counts": {
            "references": item.reference_count,
            "outgoing_relations": item.outgoing_relations,
            "incoming_relations": item.incoming_relations,
        },
    }


def _inventory_item_text(item: InventoryItem) -> str:
    symbol = item.symbol
    line_range = _inventory_line_range(symbol.start_line, symbol.end_line)
    return (
        f"- {symbol.normalized_name} tipo={symbol.symbol_type} "
        f"tecnologia={symbol.technology} estado={symbol.status.value} "
        f"confianza={symbol.confidence.value} archivo={item.relative_path or 'n/a'} "
        f"chunk={symbol.chunk_id or 'n/a'} lineas={line_range} "
        f"refs={item.reference_count} out={item.outgoing_relations} "
        f"in={item.incoming_relations}"
    )


def _inventory_line_range(start_line: int | None, end_line: int | None) -> str:
    if start_line is None or end_line is None:
        return "n/a"
    if start_line == end_line:
        return str(start_line)
    return f"{start_line}-{end_line}"


def _object_request(args: argparse.Namespace) -> ObjectRequest:
    """Construye una solicitud comun de objeto desde argumentos CLI.

    Args:
        args: Argumentos parseados para `describe` o `impact`.

    Returns:
        Solicitud normalizada de resolucion de objeto.
    """
    return ObjectRequest(
        query=args.object,
        symbol_id=args.symbol_id,
        symbol_type=args.symbol_type,
    )


def _dependency_filters(args: argparse.Namespace) -> DependencyFilters:
    """Construye filtros de dependencia desde argumentos CLI.

    Args:
        args: Argumentos parseados para `impact`.

    Returns:
        Filtros estructurados para el recorrido de dependencias.
    """
    return DependencyFilters(
        technology=args.technology,
        relation_type=args.relation_type,
        resolution_status=(
            ResolutionStatus(args.resolution_status)
            if args.resolution_status
            else None
        ),
        min_confidence=(
            Confidence(args.min_confidence)
            if args.min_confidence
            else None
        ),
    )


def _render_description(
    description: ComponentDescription,
    output_format: str,
) -> str:
    """Renderiza una descripcion en text, JSON o Markdown.

    Args:
        description: DTO producido por `DescribeService`.
        output_format: Formato solicitado por CLI.

    Returns:
        Contenido listo para stdout o escritura a archivo.
    """
    if output_format == "json":
        return json.dumps(_description_json(description), ensure_ascii=False, indent=2)
    if output_format == "markdown":
        return render_component_markdown(description)
    lines = [
        "Ficha de componente",
        f"estado = {description.resolution.status}",
        f"resumen = {description.summary}",
    ]
    symbol = description.resolution.symbol
    if symbol is not None:
        lines.extend(
            [
                f"nombre = {symbol.normalized_name}",
                f"tipo = {symbol.symbol_type}",
                f"tecnologia = {symbol.technology}",
                f"confianza = {symbol.confidence.value}",
            ]
        )
    if description.resolution.candidates:
        lines.append("candidatos:")
        lines.extend(
            f"- {candidate.normalized_name} tipo={candidate.symbol_type} "
            f"tecnologia={candidate.technology} id={candidate.symbol_id}"
            for candidate in description.resolution.candidates
        )
    lines.append(f"responsabilidades = {len(description.responsibilities)}")
    lines.append(f"evidencia = {len(description.evidence)}")
    lines.extend(f"- {value}" for value in description.to_confirm)
    return "\n".join(lines)


def _render_impact(impact: ImpactAnalysis, output_format: str) -> str:
    """Renderiza un impacto en text, JSON o Markdown.

    Args:
        impact: DTO producido por `ImpactService`.
        output_format: Formato solicitado por CLI.

    Returns:
        Contenido listo para stdout o escritura a archivo.
    """
    if output_format == "json":
        return json.dumps(_impact_json(impact), ensure_ascii=False, indent=2)
    if output_format == "markdown":
        return render_impact_markdown(impact)
    walk = impact.walk
    lines = [
        "Analisis de impacto",
        f"estado = {impact.resolution.status}",
        f"resumen = {impact.summary}",
        f"direccion = {walk.direction.value if walk else 'n/a'}",
        f"profundidad = {walk.max_depth if walk else 'n/a'}",
        f"consumidores = {len(impact.consumers)}",
        f"dependencias = {len(impact.dependencies)}",
        f"indirectos = {len(impact.indirect)}",
        f"cruces_tecnologia = {len(impact.cross_technology)}",
    ]
    if impact.risks:
        lines.append("riesgos:")
        lines.extend(f"- {risk}" for risk in impact.risks)
    if impact.to_confirm:
        lines.append("por_confirmar:")
        lines.extend(f"- {value}" for value in impact.to_confirm)
    return "\n".join(lines)


def _description_output_path(
    settings: Settings,
    requested_output: str,
    description: ComponentDescription,
) -> Path:
    """Resuelve una ruta de salida de ficha de componente.

    Args:
        settings: Configuracion efectiva con `output_dir`.
        requested_output: Ruta o directorio solicitado por el usuario.
        description: DTO usado para nombre seguro cuando se pasa un directorio.

    Returns:
        Ruta absoluta o relativa a `output_dir` lista para escritura.
    """
    requested = Path(requested_output)
    if requested_output.endswith(("/", "\\")) or requested.suffix == "":
        requested = requested / safe_component_filename(description)
    if requested.is_absolute():
        return requested
    return settings.output_dir / requested


def _impact_output_path(
    settings: Settings,
    requested_output: str,
    impact: ImpactAnalysis,
) -> Path:
    """Resuelve una ruta de salida de analisis de impacto.

    Args:
        settings: Configuracion efectiva con `output_dir`.
        requested_output: Ruta o directorio solicitado por el usuario.
        impact: DTO usado para nombre seguro cuando se pasa un directorio.

    Returns:
        Ruta absoluta o relativa a `output_dir` lista para escritura.
    """
    requested = Path(requested_output)
    if requested_output.endswith(("/", "\\")) or requested.suffix == "":
        requested = requested / safe_impact_filename(impact)
    if requested.is_absolute():
        return requested
    return settings.output_dir / requested


def _description_json(description: ComponentDescription) -> dict[str, object]:
    return {
        "template_version": "component.v1",
        "resolution": _resolution_json(description.resolution),
        "summary": description.summary,
        "no_llm": description.no_llm,
        "responsibilities": list(description.responsibilities),
        "outgoing": _walk_json(description.outgoing),
        "incoming": _walk_json(description.incoming),
        "evidence": [_evidence_json(item) for item in description.evidence],
        "inferences": list(description.inferences),
        "to_confirm": list(description.to_confirm),
        "limitations": list(description.limitations),
        "rag_sources": list(description.rag_sources),
    }


def _impact_json(impact: ImpactAnalysis) -> dict[str, object]:
    return {
        "template_version": "impact.v1",
        "resolution": _resolution_json(impact.resolution),
        "summary": impact.summary,
        "no_llm": impact.no_llm,
        "walk": _walk_json(impact.walk),
        "consumers": [_edge_json(edge) for edge in impact.consumers],
        "dependencies": [_edge_json(edge) for edge in impact.dependencies],
        "indirect": [_edge_json(edge) for edge in impact.indirect],
        "cross_technology": [_edge_json(edge) for edge in impact.cross_technology],
        "risks": list(impact.risks),
        "to_confirm": list(impact.to_confirm),
        "evidence": [_evidence_json(item) for item in impact.evidence],
        "limitations": list(impact.limitations),
        "rag_sources": list(impact.rag_sources),
    }


def _resolution_json(resolution) -> dict[str, object]:
    return {
        "query": resolution.query,
        "status": resolution.status,
        "symbol": (
            _symbol_json(resolution.symbol)
            if resolution.symbol is not None
            else None
        ),
        "candidates": [_symbol_json(symbol) for symbol in resolution.candidates],
    }


def _walk_json(walk) -> dict[str, object] | None:
    if walk is None:
        return None
    return {
        "seed_symbol_id": walk.seed_symbol_id,
        "direction": walk.direction.value,
        "max_depth": walk.max_depth,
        "node_limit": walk.node_limit,
        "limit_reached": walk.limit_reached,
        "nodes": [
            {"symbol": _symbol_json(node.symbol), "depth": node.depth}
            for node in walk.nodes
        ],
        "edges": [_edge_json(edge) for edge in walk.edges],
        "cycles": [list(cycle) for cycle in walk.cycles],
    }


def _edge_json(edge: DependencyEdge) -> dict[str, object]:
    return {
        "relation_id": edge.relation.relation_id,
        "reference_id": edge.relation.reference_id,
        "relation_type": edge.relation.relation_type,
        "classification": edge.relation.classification.value,
        "resolution_status": edge.relation.resolution_status.value,
        "confidence": edge.relation.confidence.value,
        "direction": edge.direction.value,
        "depth": edge.depth,
        "source_symbol": (
            _symbol_json(edge.source_symbol)
            if edge.source_symbol is not None
            else None
        ),
        "target_symbol": (
            _symbol_json(edge.target_symbol)
            if edge.target_symbol is not None
            else None
        ),
        "target_key": edge.target_key,
        "candidate_symbol_ids": list(edge.candidate_symbol_ids),
        "is_cycle": edge.is_cycle,
    }


def _symbol_json(symbol: TechnicalSymbol) -> dict[str, object]:
    return {
        "symbol_id": symbol.symbol_id,
        "original_name": symbol.original_name,
        "normalized_name": symbol.normalized_name,
        "type": symbol.symbol_type,
        "technology": symbol.technology,
        "status": symbol.status.value,
        "confidence": symbol.confidence.value,
        "file_id": symbol.file_id,
        "document_id": symbol.document_id,
        "chunk_id": symbol.chunk_id,
        "container_name": symbol.container_name,
        "start_line": symbol.start_line,
        "end_line": symbol.end_line,
    }


def _evidence_json(item) -> dict[str, object]:
    return {
        "source": item.source,
        "detail": item.detail,
        "reference_id": item.reference_id,
        "relation_id": item.relation_id,
        "chunk_id": item.chunk_id,
    }


def _render_operation_debug(command: str, metrics: dict[str, object]) -> None:
    """Muestra metricas operativas sin contaminar stdout estructurado.

    Args:
        command: Nombre del comando observado.
        metrics: Pares clave-valor estables para diagnostico.
    """
    print("Observabilidad reverse engineering", file=sys.stderr)
    print(f"comando={command}", file=sys.stderr)
    for key, value in metrics.items():
        print(f"{key}={value}", file=sys.stderr)


def _progress_percent(current: int, total: int | None) -> str:
    if total is None or total <= 0:
        return "n/a"
    return f"{min(100, int((current / total) * 100)):3d}%"


def _progress_bar(current: int, total: int | None, *, width: int = 24) -> str:
    if total is None or total <= 0:
        return "[" + ("?" * width) + "]"
    filled = min(width, int((max(0, current) / total) * width))
    return "[" + ("#" * filled) + ("-" * (width - filled)) + "]"


def _progress_total(total: int | None) -> str:
    return "?" if total is None else str(total)


def _progress_stage_label(label: str) -> str:
    aliases = {
        "Descubriendo chunks": "Descubriendo",
        "Planificando indexacion": "Planificando",
        "Generando embeddings": "Generando embeddings",
        "Persistiendo vectores": "Persistiendo vectores",
        "Actualizando metadata": "Actualizando metadata",
        "Finalizando": "Finalizando",
    }
    return aliases.get(label, label)


def _progress_counter_values(counters: dict[str, int]) -> dict[str, int]:
    return {
        "new": counters.get("new", 0),
        "update": counters.get("update", 0),
        "unchanged": counters.get("unchanged", 0),
        "delete": counters.get("delete", 0),
        "errores": counters.get("errores", 0),
    }


def _progress_errors_line(errors: int) -> str:
    line = f"Errores      : {errors}"
    if errors > 0:
        return f"{line}  Detalle disponible en: barbarion embeddings --errors"
    return line


def _fit_progress_line(line: str) -> str:
    width = shutil.get_terminal_size(fallback=(120, 20)).columns
    if width <= 20 or len(line) < width:
        return line
    return line[: max(0, width - 4)].rstrip() + "..."


def _is_interactive_stream(stream) -> bool:
    isatty = getattr(stream, "isatty", None)
    return bool(isatty is not None and isatty())


def _index_exit_code(summary: IndexRunSummary) -> int:
    if summary.status == EmbeddingRunStatus.INTERRUPTED:
        return 130
    if summary.status in {
        EmbeddingRunStatus.FAILED,
        EmbeddingRunStatus.COMPLETED_WITH_ERRORS,
    }:
        return 1
    return 0


def _analyze_exit_code(summaries: tuple[AnalyzeSummary, ...]) -> int:
    if any(summary.status == AnalysisRunStatus.INTERRUPTED for summary in summaries):
        return 130
    if any(summary.status == AnalysisRunStatus.FAILED for summary in summaries):
        return 1
    return 0


def _analyze_path_prefixes(paths: Sequence[str] | None) -> tuple[str, ...]:
    if not paths:
        return ()
    return tuple(str(Path(path).as_posix()).strip("/") for path in paths)


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

    analyze_parser = commands.add_parser(
        "analyze",
        help="analiza simbolos y relaciones de reverse engineering",
        description="Ejecuta analisis reverse engineering incremental sobre chunks ingeridos.",
        add_help=False,
    )
    _add_help_option(analyze_parser)
    analyze_parser.add_argument(
        "--full",
        action="store_true",
        help="analiza todos los chunks vigentes",
    )
    analyze_parser.add_argument(
        "--path",
        action="append",
        metavar="PREFIJO",
        help="limita el analisis por prefijo de ruta persistida; puede repetirse",
    )
    analyze_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="calcula alcance y resultados esperados sin escribir SQLite",
    )
    analyze_parser.set_defaults(handler=_run_analyze)

    inventory_parser = commands.add_parser(
        "inventory",
        help="consulta inventario tecnico",
        description="Consulta inventario tecnico desde SQLite.",
        add_help=False,
    )
    _add_help_option(inventory_parser)
    inventory_parser.add_argument(
        "--technology",
        choices=("oracle", "powerbuilder", "document", "unknown"),
        help="filtra por tecnologia",
    )
    inventory_parser.add_argument(
        "--type",
        dest="symbol_type",
        metavar="TIPO",
        help="filtra por tipo tecnico de simbolo",
    )
    inventory_parser.add_argument(
        "--name",
        metavar="TEXTO",
        help="filtra por nombre original o normalizado",
    )
    inventory_parser.add_argument(
        "--path",
        metavar="PREFIJO",
        help="filtra por prefijo de ruta persistida",
    )
    inventory_parser.add_argument(
        "--status",
        choices=tuple(status.value for status in SymbolStatus),
        help="filtra por estado del simbolo",
    )
    inventory_parser.add_argument(
        "--confidence",
        choices=tuple(confidence.value for confidence in Confidence),
        help="filtra por confianza",
    )
    inventory_parser.add_argument(
        "--format",
        choices=("text", "json", "markdown"),
        default="text",
        help="formato de salida",
    )
    inventory_parser.add_argument(
        "--output",
        metavar="RUTA",
        help="escribe la salida en un archivo",
    )
    inventory_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="permite sobrescribir el archivo de salida",
    )
    inventory_parser.add_argument(
        "--debug",
        action="store_true",
        help="muestra metricas operativas en stderr",
    )
    inventory_parser.set_defaults(handler=_run_inventory)

    describe_parser = commands.add_parser(
        "describe",
        help="describe un componente tecnico",
        description="Describe un componente desde simbolos y relaciones persistidas.",
        add_help=False,
    )
    _add_help_option(describe_parser)
    describe_parser.add_argument("object", metavar="OBJETO", help="objeto tecnico")
    describe_parser.add_argument(
        "--type",
        dest="symbol_type",
        metavar="TIPO",
        help="tipo tecnico usado para desambiguar",
    )
    describe_parser.add_argument(
        "--id",
        dest="symbol_id",
        metavar="SYMBOL_ID",
        help="identificador exacto de simbolo",
    )
    describe_parser.add_argument(
        "--depth",
        type=int,
        choices=range(0, 6),
        default=1,
        metavar="N",
        help="profundidad de dependencias 0..5",
    )
    describe_parser.add_argument(
        "--include-rag",
        action="store_true",
        help="incluye fuentes RAG complementarias",
    )
    describe_parser.add_argument(
        "--with-llm",
        action="store_true",
        help="intenta sintetizar con LLM local",
    )
    describe_parser.add_argument(
        "--no-llm",
        action="store_true",
        help="fuerza salida deterministica sin LLM",
    )
    describe_parser.add_argument(
        "--format",
        choices=("text", "json", "markdown"),
        default="text",
        help="formato de salida",
    )
    describe_parser.add_argument(
        "--output",
        metavar="RUTA",
        help="escribe la salida en un archivo",
    )
    describe_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="permite sobrescribir el archivo de salida",
    )
    describe_parser.add_argument(
        "--debug",
        action="store_true",
        help="muestra metricas operativas en stderr",
    )
    describe_parser.set_defaults(handler=_run_describe)

    impact_parser = commands.add_parser(
        "impact",
        help="analiza impacto tecnico",
        description="Analiza impacto desde relaciones persistidas.",
        add_help=False,
    )
    _add_help_option(impact_parser)
    impact_parser.add_argument("object", metavar="OBJETO", help="objeto tecnico")
    impact_parser.add_argument(
        "--type",
        dest="symbol_type",
        metavar="TIPO",
        help="tipo tecnico usado para desambiguar",
    )
    impact_parser.add_argument(
        "--id",
        dest="symbol_id",
        metavar="SYMBOL_ID",
        help="identificador exacto de simbolo",
    )
    impact_parser.add_argument(
        "--direction",
        choices=tuple(direction.value for direction in DependencyDirection),
        default=DependencyDirection.BOTH.value,
        help="direccion del recorrido",
    )
    impact_parser.add_argument(
        "--depth",
        type=int,
        choices=range(0, 6),
        default=2,
        metavar="N",
        help="profundidad de dependencias 0..5",
    )
    impact_parser.add_argument(
        "--node-limit",
        type=_positive_int,
        default=500,
        metavar="N",
        help="limite maximo de nodos visitados",
    )
    impact_parser.add_argument(
        "--technology",
        choices=("oracle", "powerbuilder", "document", "unknown"),
        help="filtra relaciones por tecnologia participante",
    )
    impact_parser.add_argument(
        "--relation-type",
        metavar="TIPO",
        help="filtra por tipo de relacion",
    )
    impact_parser.add_argument(
        "--resolution-status",
        choices=tuple(status.value for status in ResolutionStatus),
        help="filtra por estado de resolucion",
    )
    impact_parser.add_argument(
        "--min-confidence",
        choices=tuple(confidence.value for confidence in Confidence),
        help="filtra por confianza minima",
    )
    impact_parser.add_argument(
        "--include-rag",
        action="store_true",
        help="incluye fuentes RAG complementarias",
    )
    impact_parser.add_argument(
        "--with-llm",
        action="store_true",
        help="intenta sintetizar con LLM local",
    )
    impact_parser.add_argument(
        "--no-llm",
        action="store_true",
        help="fuerza salida deterministica sin LLM",
    )
    impact_parser.add_argument(
        "--format",
        choices=("text", "json", "markdown"),
        default="text",
        help="formato de salida",
    )
    impact_parser.add_argument(
        "--output",
        metavar="RUTA",
        help="escribe la salida en un archivo",
    )
    impact_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="permite sobrescribir el archivo de salida",
    )
    impact_parser.add_argument(
        "--debug",
        action="store_true",
        help="muestra metricas operativas en stderr",
    )
    impact_parser.set_defaults(handler=_run_impact)

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
    embeddings_parser.add_argument(
        "--errors",
        action="store_true",
        help="muestra errores de indexacion persistidos en SQLite",
    )
    embeddings_parser.add_argument(
        "--run",
        type=int,
        metavar="ID",
        help="muestra errores de un run de indexacion especifico",
    )
    embeddings_parser.set_defaults(handler=_run_embeddings)

    stats_parser = commands.add_parser(
        "stats",
        help="muestra estadisticas locales",
        description="Muestra estadisticas ingesta y RAG sin mutar SQLite.",
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

    report_parser = commands.add_parser(
        "generate-report",
        help="genera evidencia tecnica RAG",
        description="Genera reportes locales de cierre tecnico RAG.",
        add_help=False,
    )
    _add_help_option(report_parser)
    report_parser.add_argument(
        "--dataset",
        default="tests/fixtures/rag_evaluation.json",
        help="dataset de evaluacion RAG",
    )
    report_parser.add_argument(
        "--output",
        default="reports/rag",
        help="directorio de salida de reportes",
    )
    report_parser.add_argument(
        "--test-summary",
        default="pytest no ejecutado por generate-report",
        help="resumen de suite a registrar",
    )
    report_parser.add_argument(
        "--smoke-summary",
        default="smoke no ejecutado por generate-report",
        help="resumen smoke a registrar",
    )
    report_parser.set_defaults(handler=_run_generate_report)

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
