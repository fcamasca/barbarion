"""Pruebas del árbol y los códigos base de la CLI."""

import subprocess
import sys
from pathlib import Path

import pytest

from barbarion import __version__
from barbarion import cli


def run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Ejecuta la CLI como módulo en un proceso aislado."""
    return subprocess.run(
        [sys.executable, "-m", "barbarion", *args],
        cwd=cwd,
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


@pytest.mark.parametrize("args", [("doctor",), ("config", "show")])
def test_pending_commands_are_explicit(args: tuple[str, ...]) -> None:
    result = run_cli(*args)

    assert result.returncode == 2
    assert "todavía no está implementado" in result.stderr
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
