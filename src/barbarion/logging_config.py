"""Configuración local y repetible del logging de Barbarion."""

import logging
import sys
from pathlib import Path
from typing import TextIO

from barbarion.config import Settings

LOGGER_NAME = "barbarion"
LOG_FILENAME = "barbarion.log"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_MANAGED_ATTRIBUTE = "_barbarion_managed"


def configure_logging(
    settings: Settings,
    *,
    stream: TextIO | None = None,
    console_level: int | None = None,
) -> logging.Logger:
    """Configura consola y archivo sin duplicar handlers propios.

    `console_level` permite que una interfaz reduzca ruido en pantalla sin
    perder eventos admitidos por el nivel configurado en el archivo local.
    """
    logger = logging.getLogger(LOGGER_NAME)
    _remove_managed_handlers(logger)

    level = getattr(logging, settings.log_level)
    formatter = logging.Formatter(LOG_FORMAT)

    console_handler = logging.StreamHandler(
        stream if stream is not None else sys.stderr
    )
    effective_console_level = level if console_level is None else console_level
    _configure_handler(console_handler, effective_console_level, formatter)

    log_path = Path(settings.logs_dir) / LOG_FILENAME
    file_handler = logging.FileHandler(
        log_path,
        encoding="utf-8",
        delay=True,
    )
    _configure_handler(file_handler, level, formatter)

    logger.setLevel(min(level, effective_console_level))
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    logger.propagate = False
    return logger


def _configure_handler(
    handler: logging.Handler,
    level: int,
    formatter: logging.Formatter,
) -> None:
    """Marca y configura un handler administrado por Barbarion."""
    handler.setLevel(level)
    handler.setFormatter(formatter)
    setattr(handler, _MANAGED_ATTRIBUTE, True)


def _remove_managed_handlers(logger: logging.Logger) -> None:
    """Retira y cierra únicamente handlers creados por este módulo."""
    for handler in tuple(logger.handlers):
        if getattr(handler, _MANAGED_ATTRIBUTE, False):
            logger.removeHandler(handler)
            handler.close()
