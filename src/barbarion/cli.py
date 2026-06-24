"""Punto de entrada mínimo de la línea de comandos de Barbarion."""

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser raíz sin provocar efectos secundarios."""
    return argparse.ArgumentParser(
        prog="barbarion",
        description=(
            "Agente AI on-premise para sistemas legacy Oracle/PLSQL y PowerBuilder."
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Procesa los argumentos y devuelve el código de salida del proceso."""
    parser = build_parser()
    parser.parse_args(argv)
    return 0
