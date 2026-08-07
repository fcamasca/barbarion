"""Integracion de configuracion y resolucion de target H3.2-T03."""

from __future__ import annotations

from pathlib import Path

import pytest

from barbarion import cli
from barbarion.application.privacy import resolve_inference_target
from barbarion.config import load_settings
from barbarion.domain.privacy import InferenceExecution


@pytest.mark.parametrize(
    ("name", "root", "llm", "execution", "platform", "shown"),
    (
        (
            "anthropic",
            "",
            '[llm]\nprovider = "anthropic"\nmodel = "synthetic"\n',
            InferenceExecution.REMOTE,
            "direct_api",
            "auto",
        ),
        (
            "ollama-local",
            'ollama_url = "http://127.0.0.1:11434"\n',
            '[llm]\nprovider = "ollama"\nmodel = "synthetic"\nexecution = "local"\n',
            InferenceExecution.LOCAL,
            "local_runtime",
            "local",
        ),
        (
            "ollama-cloud",
            'ollama_url = "https://ollama.com"\n',
            '[llm]\nprovider = "ollama"\nmodel = "synthetic"\n',
            InferenceExecution.REMOTE,
            "ollama_cloud",
            "auto",
        ),
    ),
)
def test_h32_int002_config_show_and_target_resolution_are_consistent(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    name: str,
    root: str,
    llm: str,
    execution: InferenceExecution,
    platform: str,
    shown: str,
) -> None:
    source = tmp_path / f"{name}.toml"
    source.write_text(root + llm, encoding="utf-8")

    assert cli.main(["--config", str(source), "config", "show"]) == 0
    output = capsys.readouterr().out
    settings = load_settings(source, environ={}, cwd=tmp_path)
    target = resolve_inference_target(settings)

    assert f"llm.execution = {shown}" in output
    assert target.execution is execution
    assert target.platform == platform
