"""Punto de entrada mínimo de la línea de comandos de Barbarion."""

import argparse
import sys
from collections.abc import Sequence

from barbarion import __version__


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


def _pending_command(args: argparse.Namespace) -> int:
    """Informa que un comando se conectará en una tarea posterior."""
    command_label = getattr(args, "command_label", "")
    print(
        f"El comando '{command_label}' todavía no está implementado.",
        file=sys.stderr,
    )
    return 2


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
    doctor_parser.set_defaults(
        handler=_pending_command,
        command_label="doctor",
    )

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
    show_parser.set_defaults(
        handler=_pending_command,
        command_label="config show",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Procesa los argumentos y devuelve el código de salida del proceso."""
    try:
        parser = build_parser()
        args = parser.parse_args(argv)
        return args.handler(args)
    except KeyboardInterrupt:
        print("Operación interrumpida por el usuario.", file=sys.stderr)
        return 130
