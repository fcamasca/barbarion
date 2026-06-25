"""Pruebas del árbol y los códigos base de la CLI."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from barbarion import __version__
from barbarion import cli


def run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Ejecuta la CLI como módulo en un proceso aislado."""
    environment = os.environ.copy()
    environment.pop("BARBARION_CONFIG", None)
    return subprocess.run(
        [sys.executable, "-m", "barbarion", *args],
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    ("args", "expected_text"),
    [
        (("--help",), "comandos:"),
        (("config", "--help"), "subcomandos:"),
        (("config", "show", "--help"), "Muestra la configuración efectiva"),
        (("doctor", "--help"), "Diagnostica el entorno local"),
    ],
)
def test_help_is_in_spanish_and_has_no_side_effects(
    args: tuple[str, ...],
    expected_text: str,
    tmp_path: Path,
) -> None:
    result = run_cli(*args, cwd=tmp_path)

    assert result.returncode == 0
    assert "uso:" in result.stdout
    assert "muestra esta ayuda y finaliza" in result.stdout
    assert expected_text in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_version_uses_package_version_without_side_effects(tmp_path: Path) -> None:
    result = run_cli("--version", cwd=tmp_path)

    assert result.returncode == 0
    assert result.stdout.strip() == f"barbarion {__version__}"
    assert list(tmp_path.iterdir()) == []


def test_invalid_arguments_return_two_without_traceback() -> None:
    result = run_cli("comando-inexistente")

    assert result.returncode == 2
    assert "argumentos inválidos" in result.stderr
    assert "Traceback" not in result.stderr



def test_keyboard_interrupt_returns_130(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class InterruptedParser:
        """Doble mínimo que simula una interrupción durante el parsing."""

        def parse_args(self, args: object) -> object:
            """Interrumpe el flujo antes de producir argumentos."""
            del args
            raise KeyboardInterrupt

    monkeypatch.setattr(cli, "build_parser", InterruptedParser)

    assert cli.main([]) == 130
    assert "Operación interrumpida por el usuario." in capsys.readouterr().err

def test_config_show_uses_defaults_without_side_effects(tmp_path: Path) -> None:
    result = run_cli("config", "show", cwd=tmp_path)

    assert result.returncode == 0
    lines = result.stdout.splitlines()
    assert lines[0] == "origen = valores predeterminados"
    assert lines[1] == "archivo_configuracion = ninguno"
    assert f"data_dir = {tmp_path / 'data'}" in lines
    assert f"database_path = {tmp_path / 'data' / 'barbarion.db'}" in lines
    assert "ingestion.max_file_size_mb = 50" in lines
    assert list(tmp_path.iterdir()) == []


def test_config_show_uses_file_and_stable_field_order(tmp_path: Path) -> None:
    source = tmp_path / "settings.toml"
    source.write_text('domain = "legacy"\nlog_level = "debug"\n', encoding="utf-8")

    result = run_cli("--config", str(source), "config", "show", cwd=tmp_path)

    assert result.returncode == 0
    lines = result.stdout.splitlines()
    keys = [line.partition(" = ")[0] for line in lines]
    assert keys == [
        "origen",
        "archivo_configuracion",
        "domain",
        "data_dir",
        "output_dir",
        "logs_dir",
        "database_path",
        "log_level",
        "ollama_url",
        "ollama_timeout_seconds",
        "ingestion.paths",
        "ingestion.extensions",
        "ingestion.chunk_size",
        "ingestion.chunk_overlap",
        "ingestion.ignore_patterns",
        "ingestion.max_file_size_mb",
        "ingestion.max_extracted_chars",
        "ingestion.max_pdf_pages",
        "ingestion.encodings",
    ]
    assert lines[0] == "origen = archivo"
    assert lines[1] == f"archivo_configuracion = {source}"
    assert "domain = legacy" in lines
    assert "log_level = DEBUG" in lines
    assert "ingestion.chunk_size = 4000" in lines
    assert "ingestion.max_file_size_mb = 50" in lines
    assert list(tmp_path.iterdir()) == [source]


def test_config_show_reports_invalid_file_without_traceback(tmp_path: Path) -> None:
    result = run_cli(
        "--config",
        str(tmp_path / "missing.toml"),
        "config",
        "show",
        cwd=tmp_path,
    )

    assert result.returncode == 2
    assert "Error de configuración:" in result.stderr
    assert "no existe" in result.stderr
    assert "Traceback" not in result.stderr
    assert list(tmp_path.iterdir()) == []
