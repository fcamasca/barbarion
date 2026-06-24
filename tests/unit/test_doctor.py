"""Pruebas de checks y resumen del diagnóstico local."""

import io
import json
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from barbarion.bootstrap import initialize_directories
from barbarion.config import Settings, load_settings
from barbarion.database import DatabaseError, DatabaseStatus
from barbarion.doctor import (
    OllamaProbeResult,
    probe_ollama,
    run_doctor_checks,
)


def prepared_settings(tmp_path: Path) -> Settings:
    """Crea una configuración aislada para el diagnóstico."""
    return load_settings(environ={}, cwd=tmp_path)


def available_probe(url: str, timeout: float) -> OllamaProbeResult:
    """Simula una instancia de Ollama disponible."""
    return OllamaProbeResult(True, f"Disponible en {url} con timeout {timeout}.")


def unavailable_probe(url: str, timeout: float) -> OllamaProbeResult:
    """Simula una instancia de Ollama ausente."""
    return OllamaProbeResult(False, f"No disponible en {url} tras {timeout}.")


def test_all_checks_pass_in_stable_order(tmp_path: Path) -> None:
    settings = prepared_settings(tmp_path)
    directories = initialize_directories(settings)

    report = run_doctor_checks(
        settings,
        directories,
        ollama_probe=available_probe,
        python_version=(3, 12, 7),
    )

    assert [check.name for check in report.checks] == [
        "Python",
        "Configuración",
        "Directorio de datos",
        "Directorio de salida",
        "Directorio de logs",
        "SQLite",
        "Ollama",
    ]
    assert [check.status for check in report.checks] == ["PASS"] * 7
    assert report.summary.pass_count == 7
    assert report.summary.warn_count == 0
    assert report.summary.fail_count == 0
    assert report.summary.success is True
    assert report.exit_code == 0


def test_unavailable_ollama_is_warning_and_does_not_fail(tmp_path: Path) -> None:
    settings = prepared_settings(tmp_path)
    report = run_doctor_checks(
        settings,
        initialize_directories(settings),
        ollama_probe=unavailable_probe,
    )

    ollama = report.checks[-1]
    assert ollama.name == "Ollama"
    assert ollama.status == "WARN"
    assert ollama.required is False
    assert report.summary.warn_count == 1
    assert report.summary.success is True
    assert report.exit_code == 0


@pytest.mark.parametrize("version", [(3, 11, 9), (3, 13, 0)])
def test_unsupported_python_is_required_failure(
    version: tuple[int, int, int],
    tmp_path: Path,
) -> None:
    settings = prepared_settings(tmp_path)

    report = run_doctor_checks(
        settings,
        initialize_directories(settings),
        ollama_probe=available_probe,
        python_version=version,
    )

    python_check = report.checks[0]
    assert python_check.status == "FAIL"
    assert python_check.required is True
    assert report.summary.fail_count == 1
    assert report.summary.success is False
    assert report.exit_code == 1


def test_failed_directory_prevents_database_initialization(
    tmp_path: Path,
) -> None:
    settings = prepared_settings(tmp_path)
    settings.data_dir.write_text("bloqueo", encoding="utf-8")
    directories = initialize_directories(settings)

    def unexpected_database_call(path: object) -> DatabaseStatus:
        """Falla si el diagnóstico intenta abrir SQLite."""
        del path
        raise AssertionError("SQLite no debía inicializarse")

    report = run_doctor_checks(
        settings,
        directories,
        ollama_probe=available_probe,
        database_initializer=unexpected_database_call,
    )

    checks = {check.name: check for check in report.checks}
    assert checks["Directorio de datos"].status == "FAIL"
    assert checks["SQLite"].status == "FAIL"
    assert report.exit_code == 1


def test_database_error_is_required_failure(tmp_path: Path) -> None:
    settings = prepared_settings(tmp_path)

    def failed_database(path: object) -> DatabaseStatus:
        """Simula una base que no puede inicializarse."""
        del path
        raise DatabaseError("base bloqueada")

    report = run_doctor_checks(
        settings,
        initialize_directories(settings),
        ollama_probe=available_probe,
        database_initializer=failed_database,
    )

    sqlite_check = report.checks[-2]
    assert sqlite_check.status == "FAIL"
    assert sqlite_check.detail == "base bloqueada"
    assert report.exit_code == 1


def test_config_check_reports_file_source(tmp_path: Path) -> None:
    source = tmp_path / "barbarion.toml"
    source.write_text('domain = "legacy"\n', encoding="utf-8")
    settings = load_settings(source, environ={}, cwd=tmp_path)

    report = run_doctor_checks(
        settings,
        initialize_directories(settings),
        ollama_probe=available_probe,
    )

    config_check = report.checks[1]
    assert config_check.status == "PASS"
    assert config_check.detail == str(source)


class FakeResponse(io.BytesIO):
    """Respuesta HTTP mínima compatible con `urlopen`."""

    def __init__(self, payload: bytes, status: int = 200) -> None:
        super().__init__(payload)
        self.status = status

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        del args


def test_probe_ollama_accepts_valid_tags_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(
        request: urllib.request.Request,
        *,
        timeout: float,
    ) -> FakeResponse:
        """Captura endpoint y timeout sin usar la red."""
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return FakeResponse(json.dumps({"models": []}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = probe_ollama("http://127.0.0.1:11434", 2.5)

    assert result.available is True
    assert captured == {
        "url": "http://127.0.0.1:11434/api/tags",
        "timeout": 2.5,
    }


@pytest.mark.parametrize(
    "payload",
    [
        b"no-json",
        json.dumps({"unexpected": []}).encode(),
        json.dumps({"models": {}}).encode(),
    ],
)
def test_probe_ollama_rejects_invalid_response(
    payload: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *args, **kwargs: FakeResponse(payload),
    )

    result = probe_ollama("http://127.0.0.1:11434", 2.0)

    assert result.available is False
    assert "no válida" in result.detail or "no está disponible" in result.detail


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("tiempo agotado"),
        urllib.error.URLError("conexión rechazada"),
    ],
)
def test_probe_ollama_converts_connection_errors_to_unavailable(
    error: Exception,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_urlopen(*args: object, **kwargs: object) -> FakeResponse:
        """Simula un error esperado de conexión."""
        del args, kwargs
        raise error

    monkeypatch.setattr(urllib.request, "urlopen", failing_urlopen)

    result = probe_ollama("http://127.0.0.1:11434", 2.0)

    assert result.available is False
    assert "no está disponible" in result.detail


def test_checks_do_not_print(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = prepared_settings(tmp_path)

    run_doctor_checks(
        settings,
        initialize_directories(settings),
        ollama_probe=available_probe,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
