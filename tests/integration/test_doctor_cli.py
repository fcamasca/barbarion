"""Pruebas de integración del comando `barbarion doctor`."""

import logging
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from barbarion import cli
from barbarion.doctor import OllamaProbeResult, run_doctor_checks
from barbarion.logging_config import LOGGER_NAME, LOG_FILENAME


@pytest.fixture(autouse=True)
def isolate_barbarion_logger() -> Iterator[None]:
    """Evita que handlers globales sobrevivan entre pruebas de CLI."""
    logger = logging.getLogger(LOGGER_NAME)
    original_handlers = list(logger.handlers)
    original_level = logger.level
    original_propagate = logger.propagate
    logger.handlers.clear()

    yield

    for handler in tuple(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.handlers[:] = original_handlers
    logger.setLevel(original_level)
    logger.propagate = original_propagate


def write_config(tmp_path: Path) -> Path:
    """Crea la configuración mínima de una ejecución integrada."""
    source = tmp_path / "barbarion.toml"
    source.write_text(
        'ollama_timeout_seconds = 0.1\n',
        encoding="utf-8",
    )
    return source


def use_ollama_result(
    monkeypatch: pytest.MonkeyPatch,
    *,
    available: bool,
) -> None:
    """Sustituye únicamente el probe para mantener el resto del flujo real."""
    detail = "Ollama disponible." if available else "Ollama no disponible."

    def deterministic_checks(settings: object, directories: object):
        """Ejecuta checks reales con un probe determinista."""
        return run_doctor_checks(
            settings,
            directories,
            ollama_probe=lambda url, timeout: OllamaProbeResult(
                available,
                detail,
            ),
        )

    monkeypatch.setattr(cli, "run_doctor_checks", deterministic_checks)


def test_doctor_success_initializes_resources_and_renders_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_config(tmp_path)
    use_ollama_result(monkeypatch, available=True)

    exit_code = cli.main(["--config", str(source), "doctor"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert [line.split()[0] for line in captured.out.splitlines()[:7]] == [
        "PASS"
    ] * 7
    assert "Resumen: 7 PASS, 0 WARN, 0 FAIL" in captured.out
    assert "Inicio del diagnóstico." in captured.err
    assert (tmp_path / "data").is_dir()
    assert (tmp_path / "output").is_dir()
    assert (tmp_path / "logs").is_dir()
    database_path = tmp_path / "data" / "barbarion.db"
    assert database_path.is_file()
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall() == [(1,), (2,), (3,)]
    log_content = (tmp_path / "logs" / LOG_FILENAME).read_text(
        encoding="utf-8"
    )
    assert "Configuración cargada" in log_content
    assert "Resultado del diagnóstico: éxito." in log_content


def test_doctor_ollama_warning_keeps_exit_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_config(tmp_path)
    use_ollama_result(monkeypatch, available=False)

    exit_code = cli.main(["--config", str(source), "doctor"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "WARN  Ollama" in captured.out
    assert "Resumen: 6 PASS, 1 WARN, 0 FAIL" in captured.out
    assert "WARNING barbarion WARN Ollama" in captured.err


def test_doctor_required_failure_returns_one_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_config(tmp_path)
    (tmp_path / "data").write_text("bloqueo", encoding="utf-8")
    use_ollama_result(monkeypatch, available=True)

    exit_code = cli.main(["--config", str(source), "doctor"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "FAIL  Directorio de datos" in captured.out
    assert "FAIL  SQLite" in captured.out
    assert "Resumen: 5 PASS, 0 WARN, 2 FAIL" in captured.out
    assert "Traceback" not in captured.err
    assert "Resultado del diagnóstico: fallo requerido." in captured.err


def test_repeated_doctor_does_not_duplicate_log_handlers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_config(tmp_path)
    use_ollama_result(monkeypatch, available=True)

    assert cli.main(["--config", str(source), "doctor"]) == 0
    capsys.readouterr()
    assert cli.main(["--config", str(source), "doctor"]) == 0
    capsys.readouterr()

    log_content = (tmp_path / "logs" / LOG_FILENAME).read_text(
        encoding="utf-8"
    )
    assert log_content.count("Inicio del diagnóstico.") == 2
    assert log_content.count("Resultado del diagnóstico: éxito.") == 2

def test_logging_setup_error_returns_one_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_config(tmp_path)

    def failed_logging(settings: object) -> logging.Logger:
        """Simula un fallo operativo al configurar el archivo de log."""
        del settings
        raise OSError("archivo de log no disponible")

    monkeypatch.setattr(cli, "configure_logging", failed_logging)

    exit_code = cli.main(["--config", str(source), "doctor"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Error operativo: archivo de log no disponible" in captured.err
    assert "Traceback" not in captured.err
