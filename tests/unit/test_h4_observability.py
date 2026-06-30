"""Pruebas H4-T11 para observabilidad y errores operativos."""

import json
from pathlib import Path

from barbarion import cli
from tests.integration.test_describe_cli import _prepare_workspace, _seed_graph


def test_stats_includes_reverse_engineering_metrics(
    tmp_path: Path,
    capsys: object,
) -> None:
    """Verifica que `stats` expone conteos reverse engineering read-only."""
    config = _prepare_workspace(tmp_path)
    _seed_graph(tmp_path / "data" / "barbarion.db")

    exit_code = cli.main(["--config", str(config), "stats", "--format", "json"])
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    payload = json.loads(captured.out)
    metrics = payload["reverse_engineering"]
    assert metrics["latest_run_status"] == "running"
    assert metrics["symbols"]["active"] == 5
    assert metrics["relations"]["active"] == 2
    assert metrics["relations"]["resolved"] == 2


def test_reverse_engineering_debug_goes_to_stderr_without_breaking_json(
    tmp_path: Path,
    capsys: object,
) -> None:
    """Comprueba que `--debug` no contamina stdout estructurado."""
    config = _prepare_workspace(tmp_path)
    _seed_graph(tmp_path / "data" / "barbarion.db")

    exit_code = cli.main(
        [
            "--config",
            str(config),
            "impact",
            "pkg.root",
            "--depth",
            "1",
            "--format",
            "json",
            "--debug",
            "--no-llm",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    payload = json.loads(captured.out)
    assert payload["template_version"] == "impact.v1"
    assert "Observabilidad reverse engineering" in captured.err
    assert "comando=impact" in captured.err
    assert "edges=2" in captured.err


def test_operational_write_error_returns_one_without_traceback(
    tmp_path: Path,
    monkeypatch: object,
    capsys: object,
) -> None:
    """Los errores esperados de escritura deben ser amigables y sin traceback."""
    config = _prepare_workspace(tmp_path)
    _seed_graph(tmp_path / "data" / "barbarion.db")

    def fail_write(*args: object, **kwargs: object) -> Path:
        """Simula un error operativo esperado del filesystem."""
        del args, kwargs
        raise OSError("disco sin espacio")

    monkeypatch.setattr(cli, "write_text_artifact", fail_write)

    exit_code = cli.main(
        [
            "--config",
            str(config),
            "describe",
            "pkg.root",
            "--format",
            "markdown",
            "--output",
            "component.md",
            "--no-llm",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Error operativo: disco sin espacio" in captured.err
    assert "Traceback" not in captured.err
