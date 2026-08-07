"""Integracion T08: bloqueo CLI antes de prompt, credencial y provider."""

from __future__ import annotations

import pytest

from barbarion import cli
from barbarion.application.rag import PromptBuilder
from tests.integration.test_h3_rag_cli import prepare
from tests.unit.test_h32_privacy_preflight_baseline import RecordingLlm


def test_h32_int006_remote_without_local_evidence_blocks_before_prompt(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config, _ = prepare(tmp_path)
    config.write_text(
        config.read_text(encoding="utf-8")
        + "\n[llm]\n"
        + 'provider = "anthropic"\n'
        + 'model = "synthetic-remote"\n'
        + "max_output_tokens = 1024\n",
        encoding="utf-8",
    )
    assert cli.main(["--config", str(config), "ingest"]) == 0
    capsys.readouterr()
    provider = RecordingLlm("no debe generarse")
    prompt_built = False

    def forbidden_build(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        nonlocal prompt_built
        prompt_built = True
        raise AssertionError("PromptBuilder.build no debe ejecutarse en BLOCK")

    monkeypatch.setattr(cli, "_build_llm_provider", lambda settings: provider)
    monkeypatch.setattr(PromptBuilder, "build", forbidden_build)

    exit_code = cli.main(
        [
            "--config",
            str(config),
            "ask",
            "order_total",
            "--mode",
            "keyword",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert provider.prompts == []
    assert prompt_built is False
    assert "No se envio contexto al proveedor remoto." in captured.err
    assert "Traceback" not in captured.err
