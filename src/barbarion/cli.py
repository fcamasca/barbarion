"""Punto de entrada de la línea de comandos de Barbarion."""

import argparse
import json
import logging
import os
import platform
import re
import signal
import shutil
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from barbarion import __version__
from barbarion.application.ingest import IngestionService
from barbarion.application.local_models import (
    InstallModelResult,
    InstallModelService,
    ListModelsService,
    ModelDetailsView,
    ModelListResult,
    ModelValidationResult,
    SelectModelResult,
    SelectModelService,
    ShowModelService,
    ValidateModelService,
)
from barbarion.application.model_benchmark import (
    ModelBenchmarkService,
    ModelBenchmarkSetupError,
)
from barbarion.application.model_benchmark_context import ModelBenchmarkRagAdapter
from barbarion.application.model_benchmark_dataset import (
    ModelBenchmarkDatasetError,
    load_model_benchmark_dataset,
)
from barbarion.application.model_benchmark_reporting import (
    BenchmarkModelMetadata,
    BenchmarkReportConditions,
    recommend_model,
    write_model_benchmark_report,
)
from barbarion.application.model_benchmark_scoring import aggregate_model_benchmark
from barbarion.application.rag import (
    AskService,
    CitationValidator,
    ContextBuilder,
    DataDrivenEvidenceRetriever,
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
from barbarion.application.spec_mode import (
    DocumentEvidenceCollector,
    SpecCreateRequest,
    SpecCreateService,
    SpecReviewer,
    SpecSynthesizer,
    SpecValidator,
    TechnicalImpactCollector,
    RequirementAnalyzer,
)
from barbarion.bootstrap import DirectoryResult, initialize_directories
from barbarion.config import ConfigError, Settings, load_settings, settings_display_items
from barbarion.database import DatabaseError, initialize_database
from barbarion.doctor import DoctorReport, run_doctor_checks
from barbarion.domain.models import IngestionMode
from barbarion.domain.models import IngestionOutcome
from barbarion.domain.models import IngestionRunStatus
from barbarion.domain.models import Confidence
from barbarion.domain.local_models import LocalModelProviderError
from barbarion.domain.local_models import LocalModelErrorCode, PullProgress
from barbarion.domain.model_benchmark import (
    BenchmarkRunStatus,
    ModelBenchmarkRunResult,
)
from barbarion.domain.ports import LlmProviderPort
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
from barbarion.domain.spec_mode import SpecRequest
from barbarion.infrastructure.anthropic import (
    ANTHROPIC_API_KEY_ENV_VAR,
    AnthropicLlmProvider,
    AnthropicUsage,
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
from barbarion.infrastructure.ollama_models import OllamaModelClient
from barbarion.infrastructure.model_config import (
    ModelConfigEditError,
    TomlLlmModelEditor,
)
from barbarion.infrastructure.markdown import (
    SafeSpecWriter,
    SpecDocumentReader,
    render_component_markdown,
    render_impact_markdown,
    render_inventory_markdown,
    render_spec_markdown,
    safe_component_filename,
    safe_impact_filename,
    safe_inventory_filename,
    safe_spec_slug,
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


def _positive_float(value: str) -> float:
    """Valida un numero positivo para timeouts CLI."""
    try:
        parsed = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("debe ser un numero positivo") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("debe ser un numero positivo")
    return parsed


def _show_config(args: argparse.Namespace) -> int:
    """Muestra la configuración efectiva sin modificar el entorno."""
    settings = load_settings(args.config)
    for key, value in settings_display_items(settings):
        print(f"{key} = {value}")
    return 0


def _run_models_list(args: argparse.Namespace) -> int:
    """Lista modelos Ollama mediante una vista estrictamente acotada."""
    settings = load_settings(args.config)
    service = ListModelsService(
        OllamaModelClient(settings.ollama_url),
        settings.llm.model,
    )
    try:
        result = service.run(timeout_seconds=settings.ollama_timeout_seconds)
    except LocalModelProviderError as error:
        _print_local_model_error(error)
        return 1
    _render_models_list(result, args.format)
    return 0


def _run_models_show(args: argparse.Namespace) -> int:
    """Muestra metadata allowlist de un modelo Ollama."""
    settings = load_settings(args.config)
    service = ShowModelService(
        OllamaModelClient(settings.ollama_url),
        settings.llm.model,
    )
    try:
        result = service.run(
            args.model,
            timeout_seconds=settings.ollama_timeout_seconds,
        )
    except LocalModelProviderError as error:
        _print_local_model_error(error)
        return 1
    _render_model_details(result, args.format)
    return 0


def _run_models_install(args: argparse.Namespace) -> int:
    """Instala un modelo sin ejecutar shell ni modificar configuracion."""
    settings = load_settings(args.config)
    timeout = args.timeout or settings.llm.timeout_seconds
    service = InstallModelService(OllamaModelClient(settings.ollama_url))
    progress = _CliPullProgress()
    try:
        result = service.run(
            args.model,
            timeout_seconds=timeout,
            dry_run=args.dry_run,
            on_progress=progress.update,
        )
    except ValueError as error:
        print(f"Error de argumentos: {error}", file=sys.stderr)
        return 2
    except LocalModelProviderError as error:
        if error.code is LocalModelErrorCode.INTERRUPTED:
            print("Solicitud interrumpida.", file=sys.stderr)
            print(
                "Barbarion dejo de esperar la descarga. "
                "Ollama podria continuarla localmente.",
                file=sys.stderr,
            )
            return 130
        _print_local_model_error(error)
        return 1
    _render_model_install(result)
    return 0


def _run_models_validate(args: argparse.Namespace) -> int:
    """Valida readiness de generacion sin atribuir calidad funcional."""
    settings = load_settings(args.config)
    if settings.llm.provider != "ollama" and args.model is None:
        print(
            "OLLAMA_MODEL_REQUIRED: models validate pertenece a H1.1 local; "
            "indica explicitamente un modelo Ollama cuando el proveedor activo "
            "es Anthropic.",
            file=sys.stderr,
        )
        return 1
    timeout = args.timeout or settings.llm.timeout_seconds
    service = ValidateModelService(
        OllamaModelClient(settings.ollama_url),
        settings.llm.model,
        think=settings.llm.think,
    )
    try:
        result = service.run(args.model, timeout_seconds=timeout)
    except ValueError as error:
        print(f"Error de argumentos: {error}", file=sys.stderr)
        return 2
    _render_model_validation(result, args.format)
    return 0 if result.generation_ready else 1


def _run_models_select(args: argparse.Namespace) -> int:
    """Selecciona el modelo activo sin instalarlo ni alterar embeddings."""
    settings = load_settings(args.config)
    validator = ValidateModelService(
        OllamaModelClient(settings.ollama_url),
        settings.llm.model,
        think=settings.llm.think,
    )
    service = SelectModelService(validator, TomlLlmModelEditor())
    try:
        result = service.run(
            settings,
            args.model,
            timeout_seconds=settings.llm.timeout_seconds,
            dry_run=args.dry_run,
        )
    except ValueError as error:
        print(f"Error de argumentos: {error}", file=sys.stderr)
        return 2
    except ModelConfigEditError as error:
        print(f"{error.code}: {error.detail}", file=sys.stderr)
        return 1
    except LocalModelProviderError as error:
        _print_local_model_error(error)
        return 1
    _render_model_selection(result)
    return 0


def _render_model_selection(result: SelectModelResult) -> None:
    """Muestra solo ruta y resumen del cambio, nunca el TOML completo."""
    print("Seleccion de modelo local")
    print(f"configuracion = {result.config_path}")
    print(f"modelo_anterior = {result.previous_model}")
    print(f"modelo_nuevo = {result.new_model}")
    print(f"cambio = {'si' if result.changed else 'no'}")
    print(f"dry_run = {'si' if result.dry_run else 'no'}")
    print(
        "generation_ready_validado = "
        f"{'si' if result.generation_validated else 'no'}"
    )
    if result.dry_run:
        print("accion = no se escribio el archivo ni se ejecuto generacion")


def _run_models_benchmark(args: argparse.Namespace) -> int:
    """Ejecuta una comparacion local secuencial sobre contexto sintetico."""
    settings = load_settings(args.config)
    timeout = args.timeout or settings.llm.timeout_seconds
    try:
        dataset = load_model_benchmark_dataset(args.dataset)
        adapter = ModelBenchmarkRagAdapter(
            context_builder=ContextBuilder(
                token_budget=settings.rag.context_token_budget,
                max_chunk_tokens=settings.rag.max_chunk_tokens,
                dedupe_min_hash_prefix=settings.rag.dedupe_min_hash_prefix,
                threshold=0,
            ),
            prompt_builder=PromptBuilder(),
            citation_validator=CitationValidator(),
        )
        client = OllamaModelClient(settings.ollama_url)
        result = ModelBenchmarkService(
            client,
            adapter,
        ).run(
            run_id=_benchmark_run_id(),
            dataset=dataset,
            model_names=args.models,
            timeout_seconds=timeout,
        )
        conditions = _benchmark_report_conditions(
            client,
            result,
            timeout_seconds=timeout,
            metadata_timeout=settings.ollama_timeout_seconds,
        )
        artifacts = write_model_benchmark_report(
            result,
            conditions,
            Path(args.output) if args.output else settings.output_dir,
        )
    except ModelBenchmarkDatasetError as error:
        print(f"MODEL_DATASET_INVALID: {error}", file=sys.stderr)
        return 2
    except ModelBenchmarkSetupError as error:
        print(f"{error.code}: {error.detail}", file=sys.stderr)
        return (
            2
            if error.code in {"MODEL_BENCHMARK_INCOMPLETE", "MODEL_DATASET_INVALID"}
            else 1
        )
    except OSError as error:
        print(f"MODEL_BENCHMARK_INCOMPLETE: no se pudo escribir el resultado: {error}", file=sys.stderr)
        return 1
    _render_benchmark_summary(result, artifacts)
    if result.status is BenchmarkRunStatus.INTERRUPTED:
        print(
            "Benchmark interrumpido; se guardo un resultado parcial no reanudable.",
            file=sys.stderr,
        )
        return 130
    return 1 if result.status is BenchmarkRunStatus.COMPLETED_WITH_ERRORS else 0


def _benchmark_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


def _benchmark_report_conditions(
    client: OllamaModelClient,
    result: ModelBenchmarkRunResult,
    *,
    timeout_seconds: float,
    metadata_timeout: float,
) -> BenchmarkReportConditions:
    metadata: list[BenchmarkModelMetadata] = []
    ollama_version: str | None = None
    if result.status is BenchmarkRunStatus.INTERRUPTED:
        metadata = [
            BenchmarkModelMetadata(
                model=model,
                diagnostic_code="MODEL_BENCHMARK_INCOMPLETE",
            )
            for model in result.models
        ]
    else:
        try:
            ollama_version = client.server_version(timeout_seconds=metadata_timeout)
        except LocalModelProviderError:
            ollama_version = None
        for model in result.models:
            try:
                details = client.show_model(model, timeout_seconds=metadata_timeout)
            except LocalModelProviderError as error:
                metadata.append(
                    BenchmarkModelMetadata(
                        model=model,
                        diagnostic_code=error.code.value,
                    )
                )
                continue
            metadata.append(
                BenchmarkModelMetadata(
                    model=model,
                    format=_bounded_report_text(details.format),
                    family=_bounded_report_text(details.family),
                    parameter_size=_bounded_report_text(details.parameter_size),
                    quantization_level=_bounded_report_text(
                        details.quantization_level
                    ),
                    capabilities=tuple(
                        value
                        for value in (
                            _bounded_report_text(item)
                            for item in details.capabilities[:20]
                        )
                        if value is not None
                    ),
                )
            )
    return BenchmarkReportConditions(
        generated_at_utc=datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        barbarion_version=__version__,
        python_version=platform.python_version(),
        platform_system=platform.system() or "unknown",
        platform_release=platform.release() or "unknown",
        platform_machine=platform.machine() or "unknown",
        ollama_version=ollama_version,
        timeout_seconds=timeout_seconds,
        model_metadata=tuple(metadata),
    )


def _bounded_report_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= 128 else normalized[:125] + "..."


def _render_benchmark_summary(
    result: ModelBenchmarkRunResult,
    artifacts: tuple[Path, Path],
) -> None:
    print("Benchmark de modelos locales")
    print(f"run_id = {result.run_id}")
    print(f"estado = {result.status.value}")
    print(f"unidades_planificadas = {result.planned_units}")
    print(f"unidades_confirmadas = {len(result.units)}")
    print(f"unidades_fallidas = {result.failed_units}")
    aggregates = aggregate_model_benchmark(result)
    for item in aggregates:
        print(
            f"modelo = {item.model}; aceptacion = "
            f"{item.acceptance_rate if item.acceptance_rate is not None else 'null'}; "
            f"quality = {item.mean_quality_score if item.mean_quality_score is not None else 'null'}; "
            f"latencia_mediana_ms = {item.median_duration_ms if item.median_duration_ms is not None else 'null'}"
        )
    recommendation = recommend_model(result, aggregates)
    print(f"candidato_informativo = {recommendation.candidate or 'ninguno'}")
    print("seleccion_automatica = no")
    print(f"resultado_json = {artifacts[0]}")
    print(f"resultado_markdown = {artifacts[1]}")


def _render_model_validation(
    result: ModelValidationResult,
    output_format: str,
) -> None:
    diagnostic = _safe_validation_diagnostic(result.diagnostic)
    payload = {
        "model": result.model,
        "active": result.active,
        "available": result.available,
        "installed": result.installed,
        "generation_ready": result.generation_ready,
        "benchmark_eligible": result.benchmark_eligible,
        "duration_ms": result.duration_ms,
        "diagnostic_code": result.diagnostic_code,
        "diagnostic": diagnostic,
    }
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print("Validacion de modelo local")
    print(f"modelo = {result.model}")
    print(f"activo = {'si' if result.active else 'no'}")
    for field_name in (
        "available",
        "installed",
        "generation_ready",
        "benchmark_eligible",
    ):
        print(
            f"{field_name} = "
            f"{'si' if getattr(result, field_name) else 'no'}"
        )
    print(f"duracion_ms = {result.duration_ms}")
    if result.diagnostic_code is not None:
        print(f"diagnostico_codigo = {result.diagnostic_code}")
    if diagnostic is not None:
        print(f"diagnostico = {diagnostic}")
    if result.generation_ready:
        print(
            "alcance = la sonda acredita generacion minima; "
            "no acredita calidad RAG"
        )


def _safe_validation_diagnostic(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= 300 else normalized[:297] + "..."


@dataclass(slots=True)
class _CliPullProgress:
    """Reduce eventos de pull a cambios de estado o tramos de diez por ciento."""

    last_status: str | None = None
    last_bucket: int | None = None

    def update(self, progress: PullProgress) -> None:
        percent = progress.percent
        bucket = int(percent // 10) if percent is not None else None
        if progress.status == self.last_status and bucket == self.last_bucket:
            return
        self.last_status = progress.status
        self.last_bucket = bucket
        suffix = f" {percent:.0f}%" if percent is not None else ""
        print(f"Ollama: {_safe_progress_status(progress.status)}{suffix}", file=sys.stderr)


def _safe_progress_status(value: str) -> str:
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= 120 else normalized[:117] + "..."


def _render_model_install(result: InstallModelResult) -> None:
    print("Instalacion de modelo local")
    print(f"modelo = {result.model}")
    if result.already_installed:
        state = "ya instalado"
    elif result.dry_run:
        state = "se solicitaría la descarga"
    else:
        state = "instalado y confirmado"
    print(f"estado = {state}")
    print(f"pull_solicitado = {'si' if result.pull_requested else 'no'}")
    print(f"presencia_final = {'confirmada' if result.final_present else 'pendiente'}")
    if result.final_status is not None:
        print(f"estado_ollama = {_safe_progress_status(result.final_status)}")


def _render_models_list(result: ModelListResult, output_format: str) -> None:
    if output_format == "json":
        print(
            json.dumps(
                {
                    "active_model": result.active_model,
                    "active_model_installed": result.active_model_installed,
                    "models": [
                        {
                            "name": item.name,
                            "size_bytes": item.size_bytes,
                            "modified_at": item.modified_at,
                            "digest": item.digest,
                            "active": item.active,
                            "metadata_truncated": item.metadata_truncated,
                        }
                        for item in result.models
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    print("Modelos locales Ollama")
    print(f"modelo_activo = {result.active_model}")
    print(
        "modelo_activo_instalado = "
        f"{'si' if result.active_model_installed else 'no'}"
    )
    print(f"modelos_instalados = {len(result.models)}")
    if not result.models:
        print("- ninguno")
        return
    for item in result.models:
        active = " [activo]" if item.active else ""
        print(f"- {item.name}{active}")
        print(
            f"  tamano_bytes={_optional_cli(item.size_bytes)} "
            f"modificado={_optional_cli(item.modified_at)} "
            f"digest={_short_digest(item.digest)}"
        )
        if item.metadata_truncated:
            print("  metadata=truncada")


def _render_model_details(result: ModelDetailsView, output_format: str) -> None:
    payload = {
        "name": result.name,
        "active": result.active,
        "format": result.format,
        "family": result.family,
        "parameter_size": result.parameter_size,
        "quantization_level": result.quantization_level,
        "capabilities": list(result.capabilities),
        "metadata_truncated": result.metadata_truncated,
    }
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print("Detalle de modelo local")
    for key in (
        "name",
        "active",
        "format",
        "family",
        "parameter_size",
        "quantization_level",
    ):
        value = payload[key]
        if key == "active":
            value = "si" if value else "no"
        print(f"{key} = {_optional_cli(value)}")
    capabilities = result.capabilities
    print(
        "capabilities = "
        + (", ".join(capabilities) if capabilities else "no disponible")
    )
    if result.metadata_truncated:
        print("metadata = truncada")


def _print_local_model_error(error: LocalModelProviderError) -> None:
    detail = " ".join(error.detail.split())
    if len(detail) > 300:
        detail = detail[:297] + "..."
    print(f"Error de modelos locales [{error.code.value}]: {detail}", file=sys.stderr)


def _optional_cli(value: object | None) -> str:
    return "no disponible" if value is None else str(value)


def _short_digest(value: str | None) -> str:
    if value is None:
        return "no disponible"
    return value if len(value) <= 16 else value[:16] + "..."


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
        counter_labels: Mapping[str, str] | None = None,
        error_detail_command: str | None = "barbarion embeddings --errors",
    ) -> None:
        self._stream = stream or sys.stderr
        self._title = title
        self._counter_labels = {
            "new": "Nuevos",
            "update": "Actualizados",
            "unchanged": "Sin cambios",
            "delete": "Eliminados",
            "errores": "Errores",
            **(counter_labels or {}),
        }
        self._error_detail_command = error_detail_command
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
            _progress_counter_line(self._counter_labels["new"], counters["new"]),
            _progress_counter_line(
                self._counter_labels["update"],
                counters["update"],
            ),
            _progress_counter_line(
                self._counter_labels["unchanged"],
                counters["unchanged"],
            ),
            _progress_counter_line(
                self._counter_labels["delete"],
                counters["delete"],
            ),
            _progress_errors_line(
                self._counter_labels["errores"],
                counters["errores"],
                detail_command=self._error_detail_command,
            ),
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
                progress=ConsoleProgressReporter(
                    title="Barbarion Analyze",
                    counter_labels={
                        "new": "Simbolos",
                        "update": "Referencias",
                        "unchanged": "Resueltas",
                        "delete": "Ambiguas",
                        "errores": "No resueltas",
                    },
                    error_detail_command=None,
                ),
                cancellation=cancellation,
            )
            summaries.append(summary)
            if summary.status == AnalysisRunStatus.INTERRUPTED:
                break
    for summary in summaries:
        _render_analyze_summary(summary)
        _log_data_driven_analyze_summary(settings, summary)
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
    service = _build_describe_service(
        settings,
        with_llm=args.with_llm and not args.no_llm,
    )
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
    service = _build_impact_service(
        settings,
        with_llm=args.with_llm and not args.no_llm,
    )
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


def _run_spec_create(args: argparse.Namespace) -> int:
    """Orquesta `barbarion spec create` sin alojar logica de Spec Mode."""
    settings = load_settings(args.config)
    if not settings.database_path.exists():
        print(
            "No hay base SQLite de Barbarion. Ejecuta ingesta, indexacion RAG "
            "y analyze antes de crear una spec. Flujo sugerido: doctor, ingest, "
            "index, analyze y luego spec create.",
            file=sys.stderr,
        )
        return 1
    initialize_database(settings.database_path)
    spec_request = SpecRequest(
        requirement=args.requirement,
        name=args.name,
        retrieval_mode=args.mode,
        depth=args.depth,
        top_k=args.top_k,
        no_llm=args.no_llm,
        overwrite=args.overwrite,
        output_path=args.output,
        debug=args.debug,
    )
    output_dir = _spec_output_dir(settings, args.output, spec_request)
    service = _build_spec_create_service(settings)
    try:
        result = service.create(
            SpecCreateRequest(
                spec_request=spec_request,
                output_dir=output_dir,
            )
        )
    except (FileExistsError, ValueError) as error:
        print(f"Error operativo: {error}", file=sys.stderr)
        return 1
    if args.debug:
        _render_spec_debug(result, spec_request)
    if not result.review.can_render:
        print("Review de SpecDraft fallo; no se escribieron archivos.", file=sys.stderr)
        _render_review_issues(result.review.issues)
        print(
            "Accion sugerida: revisa evidencia, reglas detectadas y preguntas "
            "abiertas antes de reintentar.",
            file=sys.stderr,
        )
        return 1
    if not result.validation.valid:
        print("Validacion de Markdown fallo; no se escribieron archivos.", file=sys.stderr)
        print(result.validation.to_text(), file=sys.stderr)
        print(
            "Accion sugerida: corrige los issues estructurales reportados por "
            "SpecValidator.",
            file=sys.stderr,
        )
        return 1
    _render_spec_create_summary(result)
    return 0


def _run_spec_validate(args: argparse.Namespace) -> int:
    """Valida una spec H5 existente sin regenerarla ni reinterpretarla."""
    try:
        documents = SpecDocumentReader().read(Path(args.path))
    except (OSError, UnicodeError) as error:
        print(f"Error operativo: {error}", file=sys.stderr)
        return 1

    result = SpecValidator().validate(documents)
    strict_valid = result.valid and (not args.strict or not result.warnings)

    if args.format == "json":
        payload = result.to_jsonable()
        payload["strict"] = args.strict
        payload["strict_valid"] = strict_valid
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(result.to_text())
        if result.valid and args.strict and result.warnings:
            print(
                "Modo strict: advertencias tratadas como error.",
                file=sys.stderr,
            )
    return 0 if strict_valid else 1


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
    configure_logging(settings)
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
        _render_anthropic_usage(service)
        print("Operacion interrumpida por el usuario.", file=sys.stderr)
        if settings.llm.provider == "anthropic":
            print(
                "Barbarion dejo de esperar; Anthropic podria continuar "
                "procesando la solicitud remota.",
                file=sys.stderr,
            )
        return 130
    except TimeoutError:
        _render_anthropic_usage(service)
        _print_llm_error(
            "El proveedor LLM no respondio dentro del timeout configurado.",
            provider=settings.llm.provider,
        )
        return 1
    except LlmProviderError as error:
        _render_anthropic_usage(service)
        _print_llm_error(
            _llm_error_message(error, provider=settings.llm.provider),
            provider=settings.llm.provider,
        )
        return 1
    output_result = result
    if args.debug:
        _render_ask_diagnostics(
            result,
            settings=settings,
            mode=RetrievalMode(args.mode),
        )
        output_result = replace(result, debug={})
    _render_answer_result(output_result, args.format)
    _render_anthropic_usage(service)
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
    """Serializa estadisticas tecnicas con una seccion Data-Driven aditiva.

    Args:
        stats: Metricas persistidas devueltas por el repositorio SQLite.

    Returns:
        Contrato JSON compatible con conteos generales y de configuracion.
    """
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
        "data_driven": {
            "files": stats.configuration_files,
            "symbols_active": stats.configuration_symbols_active,
            "references_active": stats.configuration_references_active,
            "relations": {
                "resolved": stats.configuration_relations_resolved,
                "ambiguous": stats.configuration_relations_ambiguous,
                "unresolved": stats.configuration_relations_unresolved,
                "dynamic": stats.configuration_relations_dynamic,
                "external": stats.configuration_relations_external,
            },
        },
    }


def _render_reverse_engineering_stats(stats) -> None:
    """Presenta estadisticas generales y Data-Driven cuando existen.

    Args:
        stats: Metricas persistidas devueltas por el repositorio SQLite.
    """
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
    if any(
        (
            stats.configuration_files,
            stats.configuration_symbols_active,
            stats.configuration_references_active,
        )
    ):
        print(f"data_driven.archivos = {stats.configuration_files}")
        print(f"data_driven.simbolos_active = {stats.configuration_symbols_active}")
        print(
            "data_driven.referencias_active = "
            f"{stats.configuration_references_active}"
        )
        print(
            "data_driven.relaciones_resolved = "
            f"{stats.configuration_relations_resolved}"
        )
        print(
            "data_driven.relaciones_ambiguous = "
            f"{stats.configuration_relations_ambiguous}"
        )
        print(
            "data_driven.relaciones_unresolved = "
            f"{stats.configuration_relations_unresolved}"
        )
        print(
            "data_driven.relaciones_dynamic = "
            f"{stats.configuration_relations_dynamic}"
        )
        print(
            "data_driven.relaciones_external = "
            f"{stats.configuration_relations_external}"
        )


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


def _build_spec_create_service(settings: Settings) -> SpecCreateService:
    """Construye el orquestador H5 con dependencias locales existentes."""
    context_builder = ContextBuilder(
        token_budget=settings.rag.context_token_budget,
        max_chunk_tokens=settings.rag.max_chunk_tokens,
        dedupe_min_hash_prefix=settings.rag.dedupe_min_hash_prefix,
        threshold=settings.retrieval.similarity_threshold,
    )
    return SpecCreateService(
        analyzer=RequirementAnalyzer(),
        evidence_collector=DocumentEvidenceCollector(
            search_service=_build_search_service(settings),
            context_builder=context_builder,
        ),
        impact_collector=TechnicalImpactCollector(
            impact_service=_build_impact_service(settings, with_llm=False),
        ),
        synthesizer=SpecSynthesizer(),
        reviewer=SpecReviewer(),
        renderer=lambda draft: render_spec_markdown(draft),
        validator=SpecValidator(),
        writer=SafeSpecWriter(),
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


def _build_llm_provider(
    settings: Settings,
    *,
    environ: Mapping[str, str] | None = None,
) -> LlmProviderPort:
    """Construye una de las dos implementaciones LLM admitidas.

    Args:
        settings: Configuracion efectiva de Barbarion.

    Returns:
        Proveedor generativo seleccionado.
    """
    if settings.llm.provider == "ollama":
        return OllamaLlmProvider(
            base_url=settings.ollama_url,
            model=settings.llm.model,
            temperature=settings.llm.temperature,
            think=settings.llm.think,
            num_ctx=settings.llm.num_ctx,
        )

    if settings.llm.provider == "anthropic":
        if settings.llm.max_output_tokens is None:
            raise ConfigError(
                "La configuracion Anthropic requiere 'llm.max_output_tokens'."
            )
        environment = os.environ if environ is None else environ
        return AnthropicLlmProvider(
            model=settings.llm.model,
            temperature=settings.llm.temperature,
            max_output_tokens=settings.llm.max_output_tokens,
            _api_key_resolver=lambda: environment.get(
                ANTHROPIC_API_KEY_ENV_VAR
            ),
        )

    raise ConfigError(
        f"Proveedor LLM no soportado: '{settings.llm.provider}'."
    )


def _build_ask_service(settings: Settings) -> AskService:
    search_service = _build_search_service(settings)
    return AskService(
        search_service=search_service,
        context_builder=ContextBuilder(
            token_budget=settings.rag.context_token_budget,
            max_chunk_tokens=settings.rag.max_chunk_tokens,
            dedupe_min_hash_prefix=settings.rag.dedupe_min_hash_prefix,
            threshold=settings.retrieval.similarity_threshold,
            selection_policy=settings.rag.context_selection_policy,
        ),
        prompt_builder=PromptBuilder(),
        citation_validator=CitationValidator(),
        llm_provider=_build_llm_provider(settings),
        settings=settings,
        structured_retriever=DataDrivenEvidenceRetriever(
            repository=SQLiteReverseEngineeringRepository(settings.database_path),
            rag_repository=search_service.repository,
            domain=settings.domain,
        ),
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


def _render_ask_diagnostics(
    result: AnswerResult,
    *,
    settings: Settings,
    mode: RetrievalMode,
) -> None:
    """Muestra diagnostico detallado de `ask --debug` en stderr.

    Args:
        result: Resultado de `AskService.ask` con debug efimero.
        settings: Configuracion efectiva usada por la ejecucion.
        mode: Modo de retrieval solicitado por CLI.
    """
    debug = dict(result.debug)
    print("=== QUERY ===", file=sys.stderr)
    print(_mask_secrets(result.question), file=sys.stderr)
    print("", file=sys.stderr)

    print("=== MODEL ===", file=sys.stderr)
    print(f"llm_provider={settings.llm.provider}", file=sys.stderr)
    print(f"llm_model={settings.llm.model}", file=sys.stderr)
    print("", file=sys.stderr)
    print(f"embedding_provider={settings.embeddings.provider}", file=sys.stderr)
    print(f"embedding_model={settings.embeddings.model}", file=sys.stderr)
    print("", file=sys.stderr)

    print("=== RETRIEVAL ===", file=sys.stderr)
    print(f"mode={mode.value}", file=sys.stderr)
    print("", file=sys.stderr)
    print(
        f"retrieved_chunks={debug.get('retrieved_chunks', len(result.context.sources))}",
        file=sys.stderr,
    )
    print(
        f"reranked_chunks={debug.get('reranked_chunks', len(result.context.sources))}",
        file=sys.stderr,
    )
    print("", file=sys.stderr)
    for source in result.context.sources:
        print(
            f"[{source.source_id}] score={source.candidate.combined_score:.3f}",
            file=sys.stderr,
        )
    print("", file=sys.stderr)

    print("=== CONTEXT STATS ===", file=sys.stderr)
    print(f"retrieved_chunks={len(result.context.sources)}", file=sys.stderr)
    print(f"prompt_chars={debug.get('prompt_chars', 0)}", file=sys.stderr)
    if "prompt_tokens_est_local" in debug:
        print(
            f"prompt_tokens_est_local={debug['prompt_tokens_est_local']}",
            file=sys.stderr,
        )
    elif "prompt_tokens_est" in debug:
        print(
            f"prompt_tokens_est={debug['prompt_tokens_est']}",
            file=sys.stderr,
        )
    _render_prompt_composition_metrics(debug.get("prompt_composition"))
    print("", file=sys.stderr)

    _render_h31_observability(debug.get("observability"))

    print("=== CHUNKS ===", file=sys.stderr)
    for source in result.context.sources:
        _render_ask_debug_chunk(source)
    if not result.context.sources:
        print("no recuperados", file=sys.stderr)
        print("", file=sys.stderr)

    print("=== PROMPT ===", file=sys.stderr)
    _render_debug_prompt(debug.get("prompt"))
    print("", file=sys.stderr)

    print("=== LLM RESPONSE ===", file=sys.stderr)
    _render_debug_text(debug.get("llm_response"), max_chars=4000)
    print("", file=sys.stderr)

    print("=== VALIDATION ===", file=sys.stderr)
    _render_validation_debug(debug.get("validation"))
    print("", file=sys.stderr)

    print("=== REPAIR ATTEMPT ===", file=sys.stderr)
    _render_debug_text(debug.get("repair_prompt"), max_chars=4000)
    print("", file=sys.stderr)

    print("=== REPAIR RESPONSE ===", file=sys.stderr)
    _render_debug_text(debug.get("repair_response"), max_chars=4000)
    print("", file=sys.stderr)

    print("=== REPAIR VALIDATION ===", file=sys.stderr)
    _render_validation_debug(debug.get("repair_validation"))
    print("", file=sys.stderr)

    _render_ask_debug_summary(result, debug)


def _render_prompt_composition_metrics(value: object) -> None:
    """Muestra tamaños por componente sin revelar su contenido."""
    if not isinstance(value, Mapping):
        return
    print(f"prompt_estimator_id={value.get('estimator_id')}", file=sys.stderr)
    print(f"prompt_utf8_bytes={value.get('utf8_bytes')}", file=sys.stderr)
    components = value.get("components")
    if not isinstance(components, (list, tuple)):
        return
    for component in components:
        if not isinstance(component, Mapping):
            continue
        source_id = component.get("source_id") or "-"
        print(
            "prompt_component "
            f"kind={component.get('kind')} source_id={source_id} "
            f"chars={component.get('chars')} "
            f"utf8_bytes={component.get('utf8_bytes')} "
            f"tokens_est_local={component.get('tokens_est_local')}",
            file=sys.stderr,
        )


def _render_h31_observability(value: object) -> None:
    """Renderiza el resumen H3.1 sin revelar texto controlado o evidencia."""
    if not isinstance(value, Mapping):
        return
    print("=== H3.1 OBSERVABILITY ===", file=sys.stderr)
    for key in ("schema_version", "selection_policy", "estimator_id"):
        print(f"{key}={value.get(key)}", file=sys.stderr)
    context = value.get("context")
    if isinstance(context, Mapping):
        for key in (
            "selected_sources",
            "omitted_candidates",
            "chars",
            "tokens_est_local",
        ):
            print(f"context_{key}={context.get(key)}", file=sys.stderr)
    for stage in ("generation", "repair"):
        composition = value.get(stage)
        if not isinstance(composition, Mapping):
            print(f"{stage}_tokens_est_local=null", file=sys.stderr)
            continue
        print(
            f"{stage}_chars={composition.get('chars')} "
            f"{stage}_utf8_bytes={composition.get('utf8_bytes')} "
            f"{stage}_tokens_est_local={composition.get('tokens_est_local')}",
            file=sys.stderr,
        )
    budget = value.get("input_budget")
    if isinstance(budget, Mapping):
        for key in (
            "configured_tokens_est_local",
            "fixed_overhead_tokens_est_local",
            "evidence_budget_tokens_est_local",
            "final_prompt_tokens_est_local",
            "result",
        ):
            print(f"input_budget_{key}={budget.get(key)}", file=sys.stderr)
    repair_budget = value.get("repair_input_budget")
    if isinstance(repair_budget, Mapping):
        for key in (
            "configured_tokens_est_local",
            "initial_prompt_tokens_est_local",
            "final_prompt_tokens_est_local",
            "original_evidence_tokens_est_local",
            "final_evidence_tokens_est_local",
            "trimmed_evidence_tokens_est_local",
            "same_sources",
            "result",
        ):
            print(
                f"repair_input_budget_{key}={repair_budget.get(key)}",
                file=sys.stderr,
            )
    _render_decision_metrics("candidate", value.get("candidate_selection"))
    _render_decision_metrics("context", value.get("context_decisions"))
    redundancy = value.get("redundancy")
    if isinstance(redundancy, Mapping):
        for key in (
            "exact_duplicate_count",
            "exact_duplicate_prompt_tokens_est_local",
            "overlap_chars",
            "overlap_tokens_est_local",
            "trimmed_overlap_chars",
            "trimmed_overlap_tokens_est_local",
        ):
            print(f"redundancy_{key}={redundancy.get(key)}", file=sys.stderr)
    citation = value.get("citation_coverage")
    if isinstance(citation, Mapping):
        print(
            "citation_coverage "
            f"selected={citation.get('selected_source_count')} "
            f"cited={citation.get('cited_source_count')} "
            "uncited_ids="
            f"{_format_debug_list(citation.get('uncited_selected_source_ids'))}",
            file=sys.stderr,
        )
    provider_usage = value.get("provider_usage")
    if isinstance(provider_usage, Mapping):
        for key in (
            "provider_input_tokens",
            "provider_output_tokens",
            "provider_total_tokens",
            "provider_request_count",
            "provider_elapsed_seconds",
        ):
            metric = provider_usage.get(key)
            print(
                f"{key}={'null' if metric is None else metric}",
                file=sys.stderr,
            )
    print("", file=sys.stderr)


def _render_decision_metrics(prefix: str, value: object) -> None:
    if not isinstance(value, (list, tuple)):
        return
    for decision in value:
        if not isinstance(decision, Mapping):
            continue
        family = decision.get("selection_family")
        relative_score = decision.get("selection_relative_score")
        exact_identifier_match = decision.get(
            "selection_exact_identifier_match"
        )
        family_trace = (
            f" family={family} relative_score={relative_score}"
            f" exact_identifier_match={exact_identifier_match}"
            if family is not None
            else ""
        )
        print(
            f"{prefix}_decision chunk_id={decision.get('chunk_id')} "
            f"action={decision.get('action')} "
            f"reasons={_format_debug_list(decision.get('reasons'))} "
            f"score={decision.get('combined_score')}"
            f"{family_trace}",
            file=sys.stderr,
        )


def _render_ask_debug_chunk(source) -> None:
    """Muestra una fuente recuperada con snippet truncado.

    Args:
        source: Fuente de contexto seleccionada para `ask`.
    """
    candidate = source.candidate
    print(f"[{source.source_id}]", file=sys.stderr)
    print(f"archivo={candidate.source.get('relative_path')}", file=sys.stderr)
    print(f"lineas={_source_line_range(source)}", file=sys.stderr)
    print(f"score={candidate.combined_score:.3f}", file=sys.stderr)
    print(f"chunk_id={candidate.chunk_id}", file=sys.stderr)
    print("", file=sys.stderr)
    print(_truncate_debug_text(_mask_secrets(source.content), 500), file=sys.stderr)
    print("", file=sys.stderr)


def _render_debug_prompt(value: object) -> None:
    """Muestra inicio y final de un prompt sin imprimirlo completo si es largo."""
    if not isinstance(value, str) or not value:
        print("no ejecutada", file=sys.stderr)
        return
    text = _mask_secrets(value)
    if len(text) <= 4000:
        print("----- BEGIN -----", file=sys.stderr)
        print(text, file=sys.stderr)
        print("----- END BEGIN -----", file=sys.stderr)
        return
    print("----- BEGIN -----", file=sys.stderr)
    print(text[:2000], file=sys.stderr)
    print("----- END BEGIN -----", file=sys.stderr)
    print("", file=sys.stderr)
    print("[TRUNCATED]", file=sys.stderr)
    print("", file=sys.stderr)
    print("----- FINAL -----", file=sys.stderr)
    print(text[-2000:], file=sys.stderr)
    print("----- END FINAL -----", file=sys.stderr)


def _render_debug_text(value: object, *, max_chars: int) -> None:
    """Muestra texto de debug truncado y enmascarado.

    Args:
        value: Valor a mostrar si es texto.
        max_chars: Longitud maxima a imprimir.
    """
    if not isinstance(value, str) or not value:
        print("no ejecutada", file=sys.stderr)
        return
    print(_truncate_debug_text(_mask_secrets(value), max_chars), file=sys.stderr)


def _render_validation_debug(value: object) -> None:
    """Muestra el resultado estructurado de una validacion de citas."""
    if not isinstance(value, Mapping):
        print("expected_citations: []", file=sys.stderr)
        print("", file=sys.stderr)
        print("found_citations: []", file=sys.stderr)
        print("", file=sys.stderr)
        print("valid_citations: []", file=sys.stderr)
        print("", file=sys.stderr)
        print("missing_citations: []", file=sys.stderr)
        print("", file=sys.stderr)
        print("invalid_citations: []", file=sys.stderr)
        print("", file=sys.stderr)
        print("result: NOT_EXECUTED", file=sys.stderr)
        print("", file=sys.stderr)
        print("reason:", file=sys.stderr)
        print("no ejecutada", file=sys.stderr)
        return
    for key in (
        "expected_citations",
        "found_citations",
        "valid_citations",
        "missing_citations",
        "invalid_citations",
        "unsupported_claims",
        "contradiction_claims",
    ):
        print(f"{key}: {_format_debug_list(value.get(key))}", file=sys.stderr)
        print("", file=sys.stderr)
    print(f"result: {value.get('result')}", file=sys.stderr)
    print("", file=sys.stderr)
    print("reason:", file=sys.stderr)
    print(_mask_secrets(str(value.get("reason") or "")), file=sys.stderr)


def _render_ask_debug_summary(result: AnswerResult, debug: Mapping[str, object]) -> None:
    """Muestra el resumen final del diagnostico RAG."""
    retrieval_pass = bool(result.context.sources)
    generation_pass = result.no_llm or bool(debug.get("llm_response"))
    validation_pass = result.citations_valid
    repair_attempted = bool(debug.get("citation_repair_attempted"))
    repair_value = "NOT_EXECUTED"
    if repair_attempted:
        repair_value = "PASS" if debug.get("citation_repair_valid") else "FAIL"
    final_accepted = result.citations_valid
    reason = _ask_debug_reason(
        result,
        retrieval_pass=retrieval_pass,
        generation_pass=generation_pass,
        repair_value=repair_value,
        debug=debug,
    )
    print("=== SUMMARY ===", file=sys.stderr)
    print(f"retrieval: {'PASS' if retrieval_pass else 'FAIL'}", file=sys.stderr)
    print(f"generation: {'PASS' if generation_pass else 'FAIL'}", file=sys.stderr)
    print(f"validation: {'PASS' if validation_pass else 'FAIL'}", file=sys.stderr)
    print(f"repair: {repair_value}", file=sys.stderr)
    print("", file=sys.stderr)
    print(f"final_result: {'ACCEPTED' if final_accepted else 'REJECTED'}", file=sys.stderr)
    print("", file=sys.stderr)
    print("reason:", file=sys.stderr)
    print(reason, file=sys.stderr)


def _ask_debug_reason(
    result: AnswerResult,
    *,
    retrieval_pass: bool,
    generation_pass: bool,
    repair_value: str,
    debug: Mapping[str, object],
) -> str:
    """Calcula una causa principal compacta para el resumen de debug."""
    if not retrieval_pass:
        return "no se recupero evidencia sobre el umbral configurado"
    if result.no_llm:
        return "modo --no-llm; no se invoco el modelo generativo"
    if not generation_pass:
        return "no se obtuvo respuesta del LLM"
    if result.citations_valid:
        if repair_value == "PASS":
            return "la respuesta original fallo la validacion y la reparacion fue aceptada"
        return "la respuesta del LLM incluyo citas validas"
    validation = debug.get("repair_validation") or debug.get("validation")
    if isinstance(validation, Mapping) and validation.get("reason"):
        return _mask_secrets(str(validation["reason"]))
    return "la respuesta final no incluyo citas validas"


def _format_debug_list(value: object) -> str:
    if not isinstance(value, (list, tuple)):
        return "[]"
    return "[" + ", ".join(str(item) for item in value) + "]"


def _truncate_debug_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n[TRUNCATED]"


def _mask_secrets(text: str) -> str:
    return re.sub(
        r"(?i)\b(password|token|api_key|secret|authorization)\s*=\s*([^\s;,&]+)",
        lambda match: f"{match.group(1)}=********",
        text,
    )


def _source_line_range(source) -> str:
    start = source.candidate.source.get("start_line")
    end = source.candidate.source.get("end_line")
    if start is None or end is None:
        return "n/a"
    return f"{start}-{end}" if start != end else str(start)


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
    metadata = dict(source.candidate.source)
    return {
        "source_id": source.source_id,
        "chunk_id": source.candidate.chunk_id,
        "score": source.candidate.combined_score,
        "content": source.content,
        "relative_path": metadata.get("relative_path"),
        "start_line": metadata.get("start_line"),
        "end_line": metadata.get("end_line"),
        "source": metadata,
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


def _print_llm_error(message: str, *, provider: str = "ollama") -> None:
    print(f"Error: {message}", file=sys.stderr)
    print("", file=sys.stderr)
    print("Sugerencias:", file=sys.stderr)
    print("- ejecuta nuevamente la pregunta;", file=sys.stderr)
    print("- usa --no-llm para inspeccionar el contexto;", file=sys.stderr)
    print("- aumenta [llm].timeout_seconds en barbarion.toml;", file=sys.stderr)
    print("- verifica el modelo configurado en [llm].model;", file=sys.stderr)
    if provider == "anthropic":
        print(
            "- verifica ANTHROPIC_API_KEY, permisos y estado de la cuenta.",
            file=sys.stderr,
        )
    else:
        print("- prueba: ollama run llama3.1:8b", file=sys.stderr)


def _llm_error_message(
    error: LlmProviderError,
    *,
    provider: str = "ollama",
) -> str:
    message = str(error)
    if provider == "anthropic":
        mappings = (
            (
                "ANTHROPIC_API_KEY_MISSING",
                "No se encontro ANTHROPIC_API_KEY en el entorno.",
            ),
            (
                "ANTHROPIC_AUTHENTICATION_ERROR",
                "Anthropic rechazo la autenticacion. Revisa ANTHROPIC_API_KEY.",
            ),
            (
                "ANTHROPIC_BILLING_ERROR",
                "La cuenta Anthropic no permite procesar la solicitud.",
            ),
            (
                "ANTHROPIC_PERMISSION_ERROR",
                "La credencial no tiene permiso para el modelo Anthropic.",
            ),
            (
                "ANTHROPIC_MODEL_NOT_FOUND",
                "El modelo Anthropic configurado no esta disponible.",
            ),
            (
                "ANTHROPIC_REQUEST_TOO_LARGE",
                "El prompt excede el tamano admitido por Anthropic.",
            ),
            (
                "ANTHROPIC_REQUEST_INVALID",
                "Anthropic rechazo la solicitud generativa.",
            ),
            (
                "ANTHROPIC_RATE_LIMITED",
                "Anthropic aplico un limite de solicitudes; reintenta manualmente.",
            ),
            (
                "ANTHROPIC_TIMEOUT",
                "Anthropic no respondio dentro del timeout configurado.",
            ),
            (
                "ANTHROPIC_OVERLOADED",
                "Anthropic esta temporalmente sobrecargado.",
            ),
            (
                "ANTHROPIC_UNAVAILABLE",
                "No se pudo contactar el servicio Anthropic.",
            ),
            (
                "ANTHROPIC_LLM_TRUNCATED",
                "Anthropic alcanzo max_output_tokens; aumenta el limite.",
            ),
            (
                "ANTHROPIC_RESPONSE_INVALID",
                "Anthropic devolvio una respuesta invalida.",
            ),
            (
                "ANTHROPIC_HTTP_ERROR",
                "Anthropic devolvio un error HTTP.",
            ),
        )
        rendered = next(
            (detail for code, detail in mappings if code in message),
            "No se pudo generar la respuesta con Anthropic.",
        )
        request_id = re.search(
            r"\[request-id=([A-Za-z0-9._:-]{1,128})\]",
            message,
        )
        if request_id is not None:
            rendered += f" Request ID: {request_id.group(1)}."
        return rendered
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


def _render_anthropic_usage(service: object) -> None:
    """Muestra uso remoto en stderr sin alterar formatos de respuesta."""
    provider = getattr(service, "llm_provider", None)
    if not isinstance(provider, AnthropicLlmProvider):
        return
    usage = provider.usage_snapshot()
    if usage is None or not _has_token_usage(usage):
        return
    if usage.input_tokens is not None:
        print(f"provider_input_tokens={usage.input_tokens}", file=sys.stderr)
        print(f"Input tokens : {usage.input_tokens:,}", file=sys.stderr)
    if usage.output_tokens is not None:
        print(f"provider_output_tokens={usage.output_tokens}", file=sys.stderr)
        print(f"Output tokens: {usage.output_tokens:,}", file=sys.stderr)
    if usage.total_tokens is not None:
        print(f"provider_total_tokens={usage.total_tokens}", file=sys.stderr)
        print(f"Total tokens : {usage.total_tokens:,}", file=sys.stderr)
    print(f"provider_request_count={usage.request_count}", file=sys.stderr)
    print(f"Elapsed time : {usage.elapsed_seconds:.2f}s", file=sys.stderr)


def _has_token_usage(usage: AnthropicUsage) -> bool:
    """Indica si Anthropic entrego al menos un contador presentable."""
    return any(
        value is not None
        for value in (
            usage.input_tokens,
            usage.output_tokens,
            usage.total_tokens,
        )
    )


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
    """Presenta conteos generales y Data-Driven de una corrida de analisis.

    Args:
        summary: Resultado estructurado devuelto por `AnalyzeService`.
    """
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
    metrics = summary.data_driven
    if metrics.files_identified:
        print("Configuraciones Data-Driven:")
        print(f"Archivos DML identificados: {metrics.files_identified}")
        print(f"Sentencias procesadas: {metrics.statements_processed}")
        print(f"Sentencias soportadas: {metrics.statements_supported}")
        print(f"Sentencias omitidas: {metrics.statements_omitted}")
        print(f"Sentencias con error: {metrics.statements_failed}")
        print(f"Registros extraidos: {metrics.records_extracted}")
        print(f"Simbolos Data-Driven: {metrics.symbols_generated}")
        print(f"Referencias Data-Driven: {metrics.references_detected}")
        print(f"Configuraciones reconciliadas: {metrics.configurations_reconciled}")
        print(f"Relaciones Data-Driven resueltas: {metrics.relations_resolved}")
        print(f"Relaciones Data-Driven ambiguas: {metrics.relations_ambiguous}")
        print(f"Relaciones Data-Driven dinamicas: {metrics.relations_dynamic}")
        print(f"Relaciones Data-Driven externas: {metrics.relations_external}")
        print(f"Relaciones Data-Driven no resueltas: {metrics.relations_unresolved}")
        print(f"Advertencias Data-Driven: {metrics.warning_count}")
        print(f"Diagnosticos Data-Driven: {len(metrics.diagnostics)}")
        for diagnostic in metrics.diagnostics:
            print(
                f"- {diagnostic.severity} {diagnostic.relative_path} "
                f"lineas={diagnostic.start_line}-{diagnostic.end_line} "
                f"motivo={diagnostic.reason} "
                f"accion={_data_driven_diagnostic_action(diagnostic.reason)}"
            )
    if summary.stage_durations_ms:
        stages = ", ".join(
            f"{name}={duration} ms"
            for name, duration in summary.stage_durations_ms
        )
        print(f"Duracion por etapa: {stages}")
    print(f"Duracion: {summary.duration_ms} ms")


def _data_driven_diagnostic_action(reason: str) -> str:
    """Devuelve una accion operativa breve para un diagnostico DML.

    Args:
        reason: Codigo estable emitido por el parser Data-Driven.

    Returns:
        Sugerencia en espanol apta para mostrarse en una sola linea de CLI.
    """
    actions = {
        "column_value_mismatch": "alinear columnas y valores",
        "malformed_insert": "corregir la estructura INSERT VALUES",
        "malformed_update": "corregir la estructura UPDATE SET WHERE",
        "max_literal_chars": "revisar el literal o el limite configurado",
        "max_statements_per_file": "dividir el archivo o revisar el limite",
        "missing_default_column_order": "declarar columnas o default_column_order",
        "missing_identity": "agregar las columnas de identidad requeridas",
        "missing_identity_where": "agregar la identidad completa al WHERE",
        "undeclared_table": "declarar la tabla o corregir el patron del archivo",
        "unsupported_statement": "usar INSERT VALUES o UPDATE SET WHERE soportado",
    }
    return actions.get(reason, "revisar la sentencia y la declaracion TOML")


def _log_data_driven_analyze_summary(
    settings: Settings,
    summary: AnalyzeSummary,
) -> None:
    """Registra metricas y diagnosticos Data-Driven sin incluir contenido DML.

    Args:
        settings: Configuracion efectiva que define el archivo de log local.
        summary: Resultado estructurado devuelto por `AnalyzeService`.
    """
    metrics = summary.data_driven
    if not metrics.files_identified:
        return
    logger = configure_logging(settings)
    logger.info(
        "analyze_data_driven run_id=%s status=%s files=%s statements=%s "
        "supported=%s omitted=%s failed=%s records=%s symbols=%s references=%s "
        "reconciled=%s resolved=%s ambiguous=%s dynamic=%s external=%s "
        "unresolved=%s warnings=%s duration_ms=%s stages=%s",
        summary.run_id,
        summary.status.value,
        metrics.files_identified,
        metrics.statements_processed,
        metrics.statements_supported,
        metrics.statements_omitted,
        metrics.statements_failed,
        metrics.records_extracted,
        metrics.symbols_generated,
        metrics.references_detected,
        metrics.configurations_reconciled,
        metrics.relations_resolved,
        metrics.relations_ambiguous,
        metrics.relations_dynamic,
        metrics.relations_external,
        metrics.relations_unresolved,
        metrics.warning_count,
        summary.duration_ms,
        dict(summary.stage_durations_ms),
    )
    for diagnostic in metrics.diagnostics:
        log_diagnostic = (
            logger.error if diagnostic.severity == "error" else logger.warning
        )
        log_diagnostic(
            "analyze_data_driven_diagnostic severity=%s path=%s lines=%s-%s reason=%s",
            diagnostic.severity,
            diagnostic.relative_path,
            diagnostic.start_line,
            diagnostic.end_line,
            diagnostic.reason,
        )


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
    payload: dict[str, object] = {
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
    configuration = _configuration_symbol_json(symbol)
    if configuration:
        payload["configuration"] = configuration
    return payload


def _inventory_item_text(item: InventoryItem) -> str:
    symbol = item.symbol
    line_range = _inventory_line_range(symbol.start_line, symbol.end_line)
    configuration = _configuration_symbol_text(symbol)
    suffix = f" {configuration}" if configuration else ""
    return (
        f"- {symbol.normalized_name} tipo={symbol.symbol_type} "
        f"tecnologia={symbol.technology} estado={symbol.status.value} "
        f"confianza={symbol.confidence.value} archivo={item.relative_path or 'n/a'} "
        f"chunk={symbol.chunk_id or 'n/a'} lineas={line_range} "
        f"refs={item.reference_count} out={item.outgoing_relations} "
        f"in={item.incoming_relations}{suffix}"
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
    data_driven_edges = _data_driven_impact_edges(impact)
    if data_driven_edges:
        lines.append("relaciones:")
        lines.extend(_impact_edge_text(edge) for edge in data_driven_edges)
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


def _spec_output_dir(
    settings: Settings,
    requested_output: str | None,
    request: SpecRequest,
) -> Path:
    """Resuelve el directorio de salida de una spec H5."""
    slug = safe_spec_slug(request.name or request.requirement)
    if requested_output is None:
        return settings.output_dir / "specs" / slug
    requested = Path(requested_output).expanduser()
    if requested.name in {"", ".", ".."}:
        raise ValueError("La ruta de salida de spec no es valida.")
    if requested.is_absolute():
        return requested
    return settings.output_dir / requested


def _render_spec_create_summary(result) -> None:
    """Presenta resumen de `spec create` sin recalcular validaciones."""
    print(f"Spec escrita: {result.output_dir}")
    print(f"Documentos: {len(result.written_paths)}")
    for path in result.written_paths:
        print(f"- {path.name}")
    review_status = "degradado" if result.review.degraded else "ok"
    print(f"Review: {review_status}")
    print("Validacion Markdown: ok")
    print(f"Evidencia: {len(result.draft.evidence)}")
    print(f"Componentes afectados: {len(result.draft.affected_components)}")
    print(f"Reglas detectadas: {len(result.draft.existing_rules)}")
    print(f"Preguntas abiertas: {len(result.draft.open_questions)}")
    if result.review.degraded:
        print(f"Advertencias Review: {len(result.review.issues)}")
    if result.validation.warnings:
        print(f"Advertencias validacion: {len(result.validation.warnings)}")
    print(f"Siguiente paso: barbarion spec validate {result.output_dir}")


def _render_spec_debug(result, request: SpecRequest) -> None:
    """Emite observabilidad de Spec Mode en stderr sin contaminar stdout."""
    metrics = {
        "comando": "spec create",
        "mode": request.retrieval_mode,
        "depth": request.depth,
        "top_k": request.top_k,
        "no_llm": request.no_llm,
        "stages": (
            "interpretacion,recuperacion_h3,impacto_h4,"
            "specdraft,review,markdown,validacion,escritura"
        ),
        "review": "degradado" if result.review.degraded else "ok",
        "review_issues": len(result.review.issues),
        "validation_errors": len(result.validation.errors),
        "validation_warnings": len(result.validation.warnings),
        "evidence": len(result.draft.evidence),
        "components": len(result.draft.affected_components),
        "rules": len(result.draft.existing_rules),
        "open_questions": len(result.draft.open_questions),
        "documents": len(result.documents),
        "written": len(result.written_paths),
    }
    print("Observabilidad spec mode:", file=sys.stderr)
    for key, value in metrics.items():
        print(f"- {key}={value}", file=sys.stderr)


def _render_review_issues(issues) -> None:
    """Presenta issues de Review en stderr."""
    for issue in issues:
        location = f" en {issue.draft_section}" if issue.draft_section else ""
        related = f" ({', '.join(issue.related_ids)})" if issue.related_ids else ""
        print(
            f"- {issue.severity.value} {issue.code}{location}: "
            f"{issue.message}{related}",
            file=sys.stderr,
        )


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
    payload: dict[str, object] = {
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
    configuration = _configuration_symbol_json(symbol)
    if configuration:
        payload["configuration"] = configuration
    return payload


def _configuration_symbol_json(symbol: TechnicalSymbol) -> dict[str, object]:
    """Construye metadata Data-Driven segura para JSON de CLI.

    Args:
        symbol: Simbolo reverse engineering que puede provenir de configuracion.

    Returns:
        Diccionario con metadata declarativa o vacio para otras tecnologias.
    """
    if symbol.technology != "configuration":
        return {}
    keys = (
        "configuration_name",
        "record_id",
        "table",
        "operation",
        "identity_values",
        "display_values",
        "declared_columns",
        "configured_metadata",
    )
    return {
        key: _json_safe_metadata_value(symbol.metadata[key])
        for key in keys
        if key in symbol.metadata
    }


def _json_safe_metadata_value(value: object) -> object:
    """Convierte metadata congelada a tipos JSON simples.

    Args:
        value: Valor extraido de metadata de simbolo.

    Returns:
        Valor serializable por `json.dumps`.
    """
    if isinstance(value, tuple):
        return [_json_safe_metadata_value(item) for item in value]
    if isinstance(value, list):
        return [_json_safe_metadata_value(item) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe_metadata_value(item)
            for key, item in value.items()
        }
    return value


def _configuration_symbol_text(symbol: TechnicalSymbol) -> str:
    """Construye un sufijo textual breve para simbolos Data-Driven.

    Args:
        symbol: Simbolo reverse engineering que puede provenir de configuracion.

    Returns:
        Texto `configuracion=...` o cadena vacia para otras tecnologias.
    """
    if symbol.technology != "configuration":
        return ""
    parts = []
    for label, key in (
        ("configuracion", "configuration_name"),
        ("tabla", "table"),
        ("registro", "record_id"),
    ):
        value = symbol.metadata.get(key)
        if isinstance(value, str) and value:
            parts.append(f"{label}={value}")
    display_values = symbol.metadata.get("display_values")
    if isinstance(display_values, (list, tuple)) and display_values:
        parts.append(
            "valores="
            + ",".join(_truncate_visual_value(str(item)) for item in display_values)
        )
    return " ".join(parts)


def _data_driven_impact_edges(impact: ImpactAnalysis) -> tuple[DependencyEdge, ...]:
    """Selecciona relaciones Data-Driven relevantes para salida textual.

    Args:
        impact: Resultado de impacto renderizado por CLI.

    Returns:
        Aristas de impacto cuando la semilla u otro extremo es Data-Driven.
    """
    walk = impact.walk
    if walk is None:
        return ()
    symbol = impact.resolution.symbol
    if symbol is not None and symbol.technology == "configuration":
        return walk.edges
    return tuple(
        edge
        for edge in walk.edges
        if (
            edge.source_symbol is not None
            and edge.source_symbol.technology == "configuration"
        )
        or (
            edge.target_symbol is not None
            and edge.target_symbol.technology == "configuration"
        )
    )


def _impact_edge_text(edge: DependencyEdge) -> str:
    """Renderiza una arista de impacto en una linea textual estable.

    Args:
        edge: Arista calculada por `DependencyWalkService`.

    Returns:
        Linea con origen, destino, tipo y estado de resolucion.
    """
    source = (
        edge.source_symbol.normalized_name
        if edge.source_symbol is not None
        else edge.relation.source_symbol_id or "origen_desconocido"
    )
    target = (
        edge.target_symbol.normalized_name
        if edge.target_symbol is not None
        else edge.target_key or edge.relation.target_key or "destino_desconocido"
    )
    return (
        f"- {source} -> {target} tipo={edge.relation.relation_type} "
        f"estado={edge.relation.resolution_status.value}"
    )


def _truncate_visual_value(value: str, *, limit: int = 80) -> str:
    """Trunca valores largos solo para visualizacion humana.

    Args:
        value: Texto completo almacenado en metadata.
        limit: Longitud maxima antes de agregar indicador de truncamiento.

    Returns:
        Texto original o version abreviada con indicador `truncado`.
    """
    if len(value) <= limit:
        return value
    return value[: limit - 15].rstrip() + "... (truncado)"


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


def _progress_counter_line(label: str, count: int) -> str:
    return f"{label:<13}: {count}"


def _progress_errors_line(
    label: str,
    errors: int,
    *,
    detail_command: str | None,
) -> str:
    line = _progress_counter_line(label, errors)
    if errors > 0 and detail_command is not None:
        return f"{line}  Detalle disponible en: {detail_command}"
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

    models_parser = commands.add_parser(
        "models",
        help="administra modelos locales Ollama",
        description="Consulta y administra modelos locales de Ollama.",
        add_help=False,
    )
    _add_help_option(models_parser)
    models_commands = models_parser.add_subparsers(
        dest="models_command",
        title="subcomandos",
        metavar="SUBCOMANDO",
        required=True,
    )
    models_list_parser = models_commands.add_parser(
        "list",
        help="lista modelos instalados",
        description="Lista modelos instalados en la instancia Ollama local.",
        add_help=False,
    )
    _add_help_option(models_list_parser)
    models_list_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="formato de salida",
    )
    models_list_parser.set_defaults(handler=_run_models_list)

    models_show_parser = models_commands.add_parser(
        "show",
        help="muestra metadata acotada de un modelo",
        description="Muestra metadata segura de un modelo Ollama local.",
        add_help=False,
    )
    _add_help_option(models_show_parser)
    models_show_parser.add_argument(
        "model",
        metavar="MODELO",
        help="nombre exacto del modelo instalado",
    )
    models_show_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="formato de salida",
    )
    models_show_parser.set_defaults(handler=_run_models_show)

    models_install_parser = models_commands.add_parser(
        "install",
        help="instala explicitamente un modelo",
        description="Solicita a Ollama la instalacion de un modelo local.",
        add_help=False,
    )
    _add_help_option(models_install_parser)
    models_install_parser.add_argument(
        "model",
        metavar="MODELO",
        help="identificador de modelo aceptado por Ollama",
    )
    models_install_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="informa si el pull seria necesario sin descargar",
    )
    models_install_parser.add_argument(
        "--timeout",
        type=_positive_float,
        metavar="SEGUNDOS",
        help="timeout de inactividad; por defecto usa llm.timeout_seconds",
    )
    models_install_parser.set_defaults(handler=_run_models_install)

    models_validate_parser = models_commands.add_parser(
        "validate",
        help="valida disponibilidad y generacion minima",
        description="Valida readiness de generacion de un modelo Ollama local.",
        add_help=False,
    )
    _add_help_option(models_validate_parser)
    models_validate_parser.add_argument(
        "model",
        nargs="?",
        metavar="MODELO",
        help="modelo exacto; por defecto usa [llm].model",
    )
    models_validate_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="formato de salida",
    )
    models_validate_parser.add_argument(
        "--timeout",
        type=_positive_float,
        metavar="SEGUNDOS",
        help="timeout; por defecto usa llm.timeout_seconds",
    )
    models_validate_parser.set_defaults(handler=_run_models_validate)

    models_select_parser = models_commands.add_parser(
        "select",
        help="selecciona el modelo generativo activo",
        description="Valida y selecciona [llm].model de forma atomica.",
        add_help=False,
    )
    _add_help_option(models_select_parser)
    models_select_parser.add_argument(
        "model",
        metavar="MODELO",
        help="nombre exacto de un modelo instalado",
    )
    models_select_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="muestra el cambio sin escribir ni ejecutar generacion",
    )
    models_select_parser.set_defaults(handler=_run_models_select)

    models_benchmark_parser = models_commands.add_parser(
        "benchmark",
        help="compara modelos locales con casos sinteticos",
        description="Ejecuta un benchmark secuencial y reproducible.",
        add_help=False,
    )
    _add_help_option(models_benchmark_parser)
    models_benchmark_parser.add_argument(
        "--models",
        nargs="+",
        required=True,
        metavar="MODELO",
        help="dos o mas modelos exactos; el limite superior actual es 10",
    )
    models_benchmark_parser.add_argument(
        "--dataset",
        metavar="RUTA",
        help="dataset JSON sintetico; por defecto usa el recurso v1",
    )
    models_benchmark_parser.add_argument(
        "--timeout",
        type=_positive_float,
        metavar="SEGUNDOS",
        help="timeout por generacion entre 1 y 3600 segundos",
    )
    models_benchmark_parser.add_argument(
        "--output",
        metavar="DIRECTORIO_PADRE",
        help="directorio padre; por defecto usa output_dir",
    )
    models_benchmark_parser.set_defaults(handler=_run_models_benchmark)

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
        choices=(
            "oracle",
            "powerbuilder",
            "configuration",
            "document",
            "unknown",
        ),
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
        choices=(
            "oracle",
            "powerbuilder",
            "configuration",
            "document",
            "unknown",
        ),
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

    spec_parser = commands.add_parser(
        "spec",
        help="genera y valida specs Markdown H5",
        description="Genera y valida specs Markdown H5.",
        add_help=False,
    )
    _add_help_option(spec_parser)
    spec_commands = spec_parser.add_subparsers(
        dest="spec_command",
        title="subcomandos",
        metavar="SUBCOMANDO",
        required=True,
    )
    spec_create_parser = spec_commands.add_parser(
        "create",
        help="crea una spec Markdown H5",
        description="Crea una spec Markdown H5 desde un requerimiento funcional.",
        add_help=False,
    )
    _add_help_option(spec_create_parser)
    spec_create_parser.add_argument(
        "requirement",
        metavar="REQUERIMIENTO",
        help="requerimiento funcional a especificar",
    )
    spec_create_parser.add_argument(
        "--name",
        metavar="NOMBRE",
        help="nombre logico de la spec; si falta se genera desde el requerimiento",
    )
    spec_create_parser.add_argument(
        "--output",
        metavar="RUTA",
        help="directorio de salida; por defecto output/specs/<nombre>",
    )
    spec_create_parser.add_argument(
        "--mode",
        choices=[mode.value for mode in RetrievalMode],
        default="hybrid",
        help="modo de recuperacion RAG",
    )
    spec_create_parser.add_argument(
        "--depth",
        type=int,
        choices=range(0, 6),
        default=1,
        metavar="N",
        help="profundidad de impacto H4 0..5",
    )
    spec_create_parser.add_argument(
        "--top-k",
        type=_positive_int,
        default=12,
        metavar="N",
        help="cantidad maxima de fuentes RAG",
    )
    spec_create_parser.add_argument(
        "--no-llm",
        action="store_true",
        help="genera la spec con sintesis deterministica",
    )
    spec_create_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="permite reemplazar los cuatro Markdown esperados",
    )
    spec_create_parser.add_argument(
        "--debug",
        action="store_true",
        help="muestra metricas operativas en stderr",
    )
    spec_create_parser.set_defaults(handler=_run_spec_create)

    spec_validate_parser = spec_commands.add_parser(
        "validate",
        help="valida una spec Markdown H5 existente",
        description="Valida una carpeta de spec Markdown H5 ya renderizada.",
        add_help=False,
    )
    _add_help_option(spec_validate_parser)
    spec_validate_parser.add_argument(
        "path",
        metavar="RUTA",
        help="carpeta que contiene requirements.md, design.md, tasks.md y test-plan.md",
    )
    spec_validate_parser.add_argument(
        "--strict",
        action="store_true",
        help="trata advertencias del validador como codigo de salida fallido",
    )
    spec_validate_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="formato del reporte de validacion",
    )
    spec_validate_parser.set_defaults(handler=_run_spec_validate)

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
    _configure_stdio_encoding()
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


def _configure_stdio_encoding() -> None:
    """Fija UTF-8 en streams redirigidos y preserva la consola Windows real."""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream.isatty():
                continue
        except (AttributeError, OSError, ValueError):
            pass
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="strict")
        except (OSError, ValueError):
            continue
