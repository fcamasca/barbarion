"""Punto de entrada de la línea de comandos de Barbarion."""

import argparse
import logging
import sys
from collections.abc import Sequence

from barbarion import __version__
from barbarion.bootstrap import DirectoryResult, initialize_directories
from barbarion.config import (
    ConfigError,
    Settings,
    load_settings,
    settings_display_items,
)
from barbarion.doctor import DoctorReport, run_doctor_checks
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
    except KeyboardInterrupt:
        print("Operación interrumpida por el usuario.", file=sys.stderr)
        return 130
