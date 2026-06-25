"""Pruebas smoke del ejecutable instalado de Barbarion."""

import json
import os
import sqlite3
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


class OllamaTagsHandler(BaseHTTPRequestHandler):
    """Servidor mínimo que representa `GET /api/tags` de Ollama."""

    def do_GET(self) -> None:
        """Responde con una colección vacía de modelos."""
        if self.path != "/api/tags":
            self.send_error(404)
            return

        payload = json.dumps({"models": []}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        """Silencia la salida del servidor falso durante las pruebas."""
        del format, args


@pytest.fixture
def ollama_url() -> Iterator[str]:
    """Expone un endpoint local y lo cierra al finalizar la prueba."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), OllamaTagsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    yield f"http://{host}:{port}"

    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def installed_cli() -> Path:
    """Localiza el entry point junto al intérprete del entorno activo."""
    scripts_dir = Path(sys.executable).parent
    executable_name = "barbarion.exe" if os.name == "nt" else "barbarion"
    executable = scripts_dir / executable_name
    assert executable.is_file(), (
        "Barbarion debe instalarse en modo editable antes de ejecutar smoke tests."
    )
    return executable


def run_barbarion(
    *args: str,
    cwd: Path,
    timeout: float = 15,
) -> subprocess.CompletedProcess[str]:
    """Ejecuta el entry point instalado con un entorno controlado."""
    environment = os.environ.copy()
    environment.pop("BARBARION_CONFIG", None)
    environment["PYTHONUTF8"] = "1"
    return subprocess.run(
        [str(installed_cli()), *args],
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )


def write_config(tmp_path: Path, ollama_url: str) -> Path:
    """Crea una configuración portable para el flujo smoke."""
    source = tmp_path / "barbarion.toml"
    source.write_text(
        "\n".join(
            [
                'domain = "smoke"',
                'data_dir = "./data"',
                'output_dir = "./output"',
                'logs_dir = "./logs"',
                'database_path = "./data/barbarion.db"',
                'log_level = "INFO"',
                f'ollama_url = "{ollama_url}"',
                "ollama_timeout_seconds = 1.0",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return source


def test_help_from_installed_cli_has_no_side_effects(tmp_path: Path) -> None:
    result = run_barbarion("--help", cwd=tmp_path)

    assert result.returncode == 0
    assert "uso: barbarion" in result.stdout
    assert "doctor" in result.stdout
    assert "config" in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_version_from_installed_cli_has_no_side_effects(tmp_path: Path) -> None:
    result = run_barbarion("--version", cwd=tmp_path)

    assert result.returncode == 0
    assert result.stdout.strip() == "barbarion 0.1.0"
    assert list(tmp_path.iterdir()) == []


def test_config_show_has_no_operational_side_effects(
    tmp_path: Path,
    ollama_url: str,
) -> None:
    source = write_config(tmp_path, ollama_url)

    result = run_barbarion(
        "--config",
        str(source),
        "config",
        "show",
        cwd=tmp_path,
    )

    assert result.returncode == 0
    assert "origen = archivo" in result.stdout
    assert "domain = smoke" in result.stdout
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "barbarion.toml"
    ]


def test_doctor_initializes_all_resources(
    tmp_path: Path,
    ollama_url: str,
) -> None:
    source = write_config(tmp_path, ollama_url)

    result = run_barbarion(
        "--config",
        str(source),
        "doctor",
        cwd=tmp_path,
    )

    assert result.returncode == 0
    assert "PASS  SQLite" in result.stdout
    assert "PASS  Ollama" in result.stdout
    assert "Resumen: 7 PASS, 0 WARN, 0 FAIL" in result.stdout
    assert (tmp_path / "data").is_dir()
    assert (tmp_path / "output").is_dir()
    assert (tmp_path / "logs" / "barbarion.log").is_file()
    assert (tmp_path / "data" / "barbarion.db").is_file()


def test_repeated_doctor_is_idempotent(
    tmp_path: Path,
    ollama_url: str,
) -> None:
    source = write_config(tmp_path, ollama_url)
    command = ("--config", str(source), "doctor")
    first = run_barbarion(*command, cwd=tmp_path)
    sentinel = tmp_path / "data" / "sentinel.txt"
    sentinel.write_text("preservar", encoding="utf-8")

    second = run_barbarion(*command, cwd=tmp_path)

    assert first.returncode == 0
    assert second.returncode == 0
    assert sentinel.read_text(encoding="utf-8") == "preservar"
    with sqlite3.connect(tmp_path / "data" / "barbarion.db") as connection:
        rows = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    assert rows == [(1,), (2,)]
    log_content = (tmp_path / "logs" / "barbarion.log").read_text(
        encoding="utf-8"
    )
    assert log_content.count("Inicio del diagnóstico.") == 2


def test_missing_explicit_config_returns_two_without_side_effects(
    tmp_path: Path,
) -> None:
    result = run_barbarion(
        "--config",
        str(tmp_path / "missing.toml"),
        "doctor",
        cwd=tmp_path,
    )

    assert result.returncode == 2
    assert "Error de configuración:" in result.stderr
    assert "Traceback" not in result.stderr
    assert list(tmp_path.iterdir()) == []
