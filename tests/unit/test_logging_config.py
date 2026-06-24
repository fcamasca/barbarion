"""Pruebas de configuración del logging local."""

import io
import logging
from dataclasses import replace
from pathlib import Path
from typing import Iterator

import pytest

from barbarion.bootstrap import initialize_directories
from barbarion.config import Settings, load_settings
from barbarion.logging_config import (
    LOGGER_NAME,
    LOG_FILENAME,
    configure_logging,
)


@pytest.fixture(autouse=True)
def isolate_barbarion_logger() -> Iterator[None]:
    """Aísla el logger global para que las pruebas no compartan handlers."""
    logger = logging.getLogger(LOGGER_NAME)
    original_handlers = list(logger.handlers)
    original_level = logger.level
    original_propagate = logger.propagate
    original_disabled = logger.disabled
    logger.handlers.clear()
    logger.disabled = False

    yield

    for handler in tuple(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.handlers[:] = original_handlers
    logger.setLevel(original_level)
    logger.propagate = original_propagate
    logger.disabled = original_disabled


def prepared_settings(tmp_path: Path, *, level: str = "INFO") -> Settings:
    """Crea directorios y devuelve una configuración lista para logging."""
    settings = replace(
        load_settings(environ={}, cwd=tmp_path),
        log_level=level,
    )
    results = initialize_directories(settings)
    assert all(result.success for result in results)
    return settings


def file_handler_for(logger: logging.Logger) -> logging.FileHandler:
    """Obtiene el único handler de archivo configurado."""
    handlers = [
        handler
        for handler in logger.handlers
        if isinstance(handler, logging.FileHandler)
    ]
    assert len(handlers) == 1
    return handlers[0]


def test_info_is_written_to_console_and_file(tmp_path: Path) -> None:
    settings = prepared_settings(tmp_path)
    console = io.StringIO()
    logger = configure_logging(settings, stream=console)

    logger.info("inicio de prueba")

    log_path = settings.logs_dir / LOG_FILENAME
    assert "INFO barbarion inicio de prueba" in console.getvalue()
    assert "INFO barbarion inicio de prueba" in log_path.read_text(
        encoding="utf-8"
    )


def test_log_file_creation_is_delayed_until_first_record(tmp_path: Path) -> None:
    settings = prepared_settings(tmp_path)
    logger = configure_logging(settings, stream=io.StringIO())
    handler = file_handler_for(logger)
    log_path = settings.logs_dir / LOG_FILENAME

    assert handler.encoding.lower().replace("-", "") == "utf8"
    assert handler.delay is True
    assert handler.stream is None
    assert log_path.exists() is False

    logger.warning("primer registro")

    assert log_path.is_file()


def test_error_level_filters_lower_levels(tmp_path: Path) -> None:
    settings = prepared_settings(tmp_path, level="ERROR")
    console = io.StringIO()
    logger = configure_logging(settings, stream=console)

    logger.info("no visible")
    logger.error("error visible")

    content = (settings.logs_dir / LOG_FILENAME).read_text(encoding="utf-8")
    assert "no visible" not in console.getvalue()
    assert "no visible" not in content
    assert "error visible" in console.getvalue()
    assert "error visible" in content


def test_reconfiguration_does_not_duplicate_managed_handlers(
    tmp_path: Path,
) -> None:
    settings = prepared_settings(tmp_path)
    console = io.StringIO()

    configure_logging(settings, stream=console)
    logger = configure_logging(settings, stream=console)
    logger.info("una sola vez")

    assert console.getvalue().count("una sola vez") == 1
    content = (settings.logs_dir / LOG_FILENAME).read_text(encoding="utf-8")
    assert content.count("una sola vez") == 1
    assert len(logger.handlers) == 2


def test_external_handler_is_preserved(tmp_path: Path) -> None:
    settings = prepared_settings(tmp_path)
    logger = logging.getLogger(LOGGER_NAME)
    external_handler = logging.NullHandler()
    logger.addHandler(external_handler)

    configure_logging(settings, stream=io.StringIO())

    assert external_handler in logger.handlers
    assert len(logger.handlers) == 3


def test_unicode_is_written_as_utf8(tmp_path: Path) -> None:
    settings = prepared_settings(tmp_path)
    logger = configure_logging(settings, stream=io.StringIO())

    logger.info("diagnóstico: configuración válida")

    content = (settings.logs_dir / LOG_FILENAME).read_text(encoding="utf-8")
    assert "diagnóstico: configuración válida" in content


def test_root_logger_is_not_modified(tmp_path: Path) -> None:
    settings = prepared_settings(tmp_path)
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    original_propagate = root_logger.propagate

    logger = configure_logging(settings, stream=io.StringIO())

    assert logger.propagate is False
    assert list(root_logger.handlers) == original_handlers
    assert root_logger.level == original_level
    assert root_logger.propagate == original_propagate
