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

from tests.support.h2_corpus import build_h2_corpus


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
    if not executable.is_file():
        pytest.skip(
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


def write_ingest_config(tmp_path: Path, ollama_url: str, corpus: Path) -> Path:
    """Crea configuracion smoke con paths de ingesta explicitos."""
    source = write_config(tmp_path, ollama_url)
    with source.open("a", encoding="utf-8") as output:
        output.write(
            "\n".join(
                [
                    "",
                    "[ingestion]",
                    f'paths = ["{corpus.as_posix()}"]',
                    "chunk_size = 500",
                    "chunk_overlap = 0",
                    'encodings = ["utf-8", "cp1252", "latin-1"]',
                    "",
                ]
            )
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
    assert result.stdout.strip() == "barbarion 0.4.0"
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
    assert "Resumen: 8 PASS, 0 WARN, 0 FAIL" in result.stdout
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
    assert rows == [(1,), (2,), (3,), (4,)]
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


def test_ingest_help_from_installed_cli_has_no_side_effects(tmp_path: Path) -> None:
    result = run_barbarion("ingest", "--help", cwd=tmp_path)

    assert result.returncode == 0
    assert "uso:" in result.stdout
    assert "--path RUTA" in result.stdout
    assert "--stats" in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_h3_help_from_installed_cli_has_no_side_effects(tmp_path: Path) -> None:
    for command in ("index", "reindex", "search", "ask", "embeddings", "stats"):
        result = run_barbarion(command, "--help", cwd=tmp_path)
        assert result.returncode == 0
        assert "uso:" in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_ingest_requires_doctor_bootstrap(
    tmp_path: Path,
    ollama_url: str,
) -> None:
    corpus = build_h2_corpus(tmp_path / "corpus")
    source = write_ingest_config(tmp_path, ollama_url, corpus)

    result = run_barbarion("--config", str(source), "ingest", cwd=tmp_path)

    assert result.returncode == 1
    assert "Ejecuta 'barbarion doctor'" in result.stderr
    assert not (tmp_path / "data").exists()


def test_ingest_incremental_full_and_stats_from_installed_cli(
    tmp_path: Path,
    ollama_url: str,
) -> None:
    corpus = build_h2_corpus(tmp_path / "corpus")
    ad_hoc = tmp_path / "ad_hoc"
    ad_hoc.mkdir()
    (ad_hoc / "extra.txt").write_text("archivo ad hoc", encoding="utf-8")
    source = write_ingest_config(tmp_path, ollama_url, corpus)

    doctor = run_barbarion("--config", str(source), "doctor", cwd=tmp_path)
    first = run_barbarion(
        "--config",
        str(source),
        "ingest",
        "--path",
        str(corpus),
        "--path",
        str(ad_hoc),
        cwd=tmp_path,
    )
    second = run_barbarion("--config", str(source), "ingest", cwd=tmp_path)
    full = run_barbarion("--config", str(source), "ingest", "--full", cwd=tmp_path)
    database_path = tmp_path / "data" / "barbarion.db"
    before = database_path.stat()
    stats = run_barbarion("--config", str(source), "ingest", "--stats", cwd=tmp_path)
    h3_stats = run_barbarion("--config", str(source), "stats", cwd=tmp_path)
    embeddings = run_barbarion("--config", str(source), "embeddings", cwd=tmp_path)
    dry_index = run_barbarion(
        "--config",
        str(source),
        "index",
        "--dry-run",
        cwd=tmp_path,
    )
    after_read_only = database_path.stat()
    search = run_barbarion(
        "--config",
        str(source),
        "search",
        "Manual",
        "--mode",
        "keyword",
        cwd=tmp_path,
    )
    ask = run_barbarion(
        "--config",
        str(source),
        "ask",
        "Que documentos hablan de Manual?",
        "--mode",
        "keyword",
        "--no-llm",
        cwd=tmp_path,
    )
    invalid = run_barbarion(
        "--config",
        str(source),
        "ingest",
        "--stats",
        "--path",
        str(corpus),
        cwd=tmp_path,
    )

    assert doctor.returncode == 0
    assert first.returncode == 0
    assert "Ingesta finalizada: completed" in first.stdout
    assert second.returncode == 0
    assert "Procesados: 0" in second.stdout
    assert full.returncode == 0
    assert "Ingesta finalizada: completed" in full.stdout
    assert stats.returncode == 0
    assert "Estadisticas de ingesta" in stats.stdout
    assert h3_stats.returncode == 0
    assert "Estadisticas RAG" in h3_stats.stdout
    assert embeddings.returncode == 0
    assert "Embeddings RAG" in embeddings.stdout
    assert dry_index.returncode == 0
    assert "Dry-run de indexacion RAG" in dry_index.stdout
    assert search.returncode == 0
    assert "Busqueda RAG: keyword" in search.stdout
    assert ask.returncode == 0
    assert "Modo sin LLM" in ask.stdout
    assert before.st_size == after_read_only.st_size
    assert before.st_mtime_ns == after_read_only.st_mtime_ns
    assert invalid.returncode == 2
    assert "--stats no se combina" in invalid.stderr
