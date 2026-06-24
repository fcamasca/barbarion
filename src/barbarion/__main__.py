"""Punto de entrada para ejecutar ``python -m barbarion``."""

from barbarion.cli import main


def run() -> None:
    """Ejecuta la aplicación de línea de comandos."""
    raise SystemExit(main())


if __name__ == "__main__":
    run()
