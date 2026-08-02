"""Pruebas CLI para `barbarion impact`."""

import json
from pathlib import Path

import pytest

from barbarion import cli
from tests.integration.test_describe_cli import (
    _RecordingLlmProvider,
    _enable_anthropic,
    _prepare_workspace,
    _seed_graph,
)


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


def test_impact_with_llm_failure_preserves_exact_deterministic_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _prepare_workspace(tmp_path)
    _enable_anthropic(config)
    _seed_graph(tmp_path / "data" / "barbarion.db")
    provider = _RecordingLlmProvider("unused", fail=True)
    configured_providers: list[str] = []

    def build_provider(settings):  # noqa: ANN001, ANN202
        configured_providers.append(settings.llm.provider)
        return provider

    monkeypatch.setattr(cli, "_build_llm_provider", build_provider)
    base_arguments = [
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
    ]

    assert cli.main([*base_arguments, "--no-llm"]) == 0
    deterministic = json.loads(capsys.readouterr().out)
    assert cli.main([*base_arguments, "--with-llm"]) == 0
    fallback = json.loads(capsys.readouterr().out)

    deterministic_contract = {
        key: value
        for key, value in deterministic.items()
        if key not in {"limitations", "no_llm"}
    }
    fallback_contract = {
        key: value
        for key, value in fallback.items()
        if key not in {"limitations", "no_llm"}
    }
    assert fallback_contract == deterministic_contract
    assert fallback["no_llm"] is True
    assert fallback["limitations"] == [
        *deterministic["limitations"],
        "LLM no disponible; salida deterministica",
    ]
    assert configured_providers == ["anthropic"]
    assert len(provider.calls) == 1


@pytest.mark.parametrize("command", ["describe", "impact"])
def test_h4_no_llm_wins_without_building_provider_even_if_with_llm_is_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    config = _prepare_workspace(tmp_path)
    _enable_anthropic(config)
    _seed_graph(tmp_path / "data" / "barbarion.db")

    def unexpected_provider(_settings):  # noqa: ANN001, ANN202
        raise AssertionError("--no-llm no debe componer un proveedor")

    monkeypatch.setattr(cli, "_build_llm_provider", unexpected_provider)

    assert cli.main(
        [
            "--config",
            str(config),
            command,
            "pkg.root",
            "--with-llm",
            "--no-llm",
            "--format",
            "json",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["no_llm"] is True
