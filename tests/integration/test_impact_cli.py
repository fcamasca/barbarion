"""Pruebas CLI para `barbarion impact`."""

import json
from pathlib import Path

import pytest

from barbarion import cli
from tests.integration.test_describe_cli import _prepare_workspace, _seed_graph


def test_impact_cli_rejects_invalid_node_limit(capsys: object) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(["impact", "pkg.root", "--node-limit", "0"])
    captured = capsys.readouterr()

    assert error.value.code == 2
    assert "argumentos inv" in captured.err


def test_impact_cli_json_direction_and_cross_technology(
    tmp_path: Path,
    capsys: object,
) -> None:
    config = _prepare_workspace(tmp_path)
    _seed_graph(tmp_path / "data" / "barbarion.db")

    exit_code = cli.main(
        [
            "--config",
            str(config),
            "impact",
            "pkg.root",
            "--direction",
            "both",
            "--depth",
            "1",
            "--format",
            "json",
            "--no-llm",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    payload = json.loads(captured.out)
    assert payload["template_version"] == "impact.v1"
    assert payload["walk"]["direction"] == "both"
    assert len(payload["consumers"]) == 1
    assert len(payload["dependencies"]) == 1
    assert len(payload["cross_technology"]) == 1


def test_impact_cli_markdown_output_is_safe(
    tmp_path: Path,
    capsys: object,
) -> None:
    config = _prepare_workspace(tmp_path)
    _seed_graph(tmp_path / "data" / "barbarion.db")
    output_path = tmp_path / "output" / "impact.md"

    first = cli.main(
        [
            "--config",
            str(config),
            "impact",
            "pkg.root",
            "--format",
            "markdown",
            "--output",
            str(output_path),
            "--no-llm",
        ]
    )
    first_capture = capsys.readouterr()
    second = cli.main(
        [
            "--config",
            str(config),
            "impact",
            "pkg.root",
            "--format",
            "markdown",
            "--output",
            str(output_path),
            "--no-llm",
        ]
    )
    second_capture = capsys.readouterr()

    assert first == 0, first_capture.err
    content = output_path.read_text(encoding="utf-8")
    assert "# Analisis de impacto" in content
    assert "template_version: impact.v1" in content
    assert second == 1
    assert "El archivo ya existe" in second_capture.err
