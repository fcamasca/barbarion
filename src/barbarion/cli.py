"""Punto de entrada de la línea de comandos de Barbarion."""

import argparse
import logging
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from barbarion import __version__
from barbarion.application.ingest import IngestionService
from barbarion.bootstrap import DirectoryResult, initialize_directories
from barbarion.config import ConfigError, Settings, load_settings, settings_display_items
from barbarion.database import DatabaseError, initialize_database
from barbarion.doctor import DoctorReport, run_doctor_checks
from barbarion.domain.models import IngestionMode
from barbarion.domain.models import IngestionOutcome
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
                "Error de ingesta stage=%s code=%s recoverable=%s",
                outcome.error.stage.value,
                outcome.error.error_code,
                outcome.error.recoverable,
            )
    if outcome.status.value == "interrupted":
        return 130
    if outcome.status.value == "failed":
        return 1
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
    print(f"ultimo_run = {stats.latest_run_id if stats.latest_run_id is not None else 'ninguno'}")
    print(f"ultimo_estado = {stats.latest_run_status or 'ninguno'}")
    print(f"archivos_vigentes = {stats.files_current}")
    print(f"documentos_vigentes = {stats.documents_current}")
    print(f"chunks_vigentes = {stats.chunks_current}")
    if stats.artifact_kinds:
        print("artefactos = " + ", ".join(f"{kind}:{count}" for kind, count in stats.artifact_kinds))
    else:
        print("artefactos = ninguno")
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

    return parser


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
