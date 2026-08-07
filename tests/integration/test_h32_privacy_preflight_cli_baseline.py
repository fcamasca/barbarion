"""Integracion baseline previa al gate H3.2."""

from __future__ import annotations

import pytest

from barbarion import cli
from tests.integration.test_h3_rag_cli import prepare
from tests.unit.test_h32_privacy_preflight_baseline import RecordingLlm
from tests.support.privacy import passing_privacy_preflight


def test_h32_int001_cli_generation_and_repair_use_configured_provider(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """El ask CLI cruza la frontera solo para generation y repair."""
    config, _db_path = prepare(tmp_path)
    config.write_text(
        config.read_text(encoding="utf-8") + '\n[llm]\nexecution = "local"\n',
        encoding="utf-8",
    )
    assert cli.main(["--config", str(config), "ingest"]) == 0
    capsys.readouterr()

    provider = RecordingLlm(
        "Conclusion inicial sin cita.",
        "order_total se asigna al valor sintetico 10 [F1].",
    )
    monkeypatch.setattr(cli, "_build_llm_provider", lambda settings: provider)
    monkeypatch.setattr(
        cli,
        "_build_privacy_preflight",
        lambda settings: passing_privacy_preflight(),
    )

    exit_code = cli.main(
        [
            "--config",
            str(config),
            "ask",
            "order_total",
            "--mode",
            "keyword",
            "--debug",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert len(provider.prompts) == 2
    assert "order_total" in provider.prompts[0]
    assert "Respuesta original:\nConclusion inicial sin cita." in provider.prompts[1]
    assert "order_total se asigna al valor sintetico 10 [F1]." in captured.out
    assert "repair: PASS" in captured.err
