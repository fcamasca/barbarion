"""H3.2-INT-010..013: intentos de bypass y egress no autorizado."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from barbarion import cli
from barbarion.application.privacy import (
    PrivacyPreflightBlockedError,
    PrivacyPreflightService,
    UnavailableAccountPrivacyVerifier,
)
from barbarion.database import initialize_database
from barbarion.domain.privacy import InferenceExecution, PrivacyPolicy
from barbarion.infrastructure.anthropic import (
    ANTHROPIC_MESSAGES_URL,
    AnthropicLlmProvider,
)
from tests.integration.test_ask_anthropic_http import (
    FakeOpener,
    FakeResponse,
    _write_ask_config,
)
from tests.support.privacy import passing_privacy_preflight
from tests.unit.test_h32_privacy_preflight_ask import _ask, _service
from tests.unit.test_rag_index_service import seed_chunks


@dataclass
class CountingPreflight:
    """Decorador que prueba que generation y repair comparten un preflight."""

    delegate: PrivacyPreflightService
    calls: int = 0

    @property
    def policy(self) -> PrivacyPolicy:
        return self.delegate.policy

    def authorize_with_diagnostics(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls += 1
        return self.delegate.authorize_with_diagnostics(**kwargs)


def test_int012_pass_calls_only_configured_provider_with_one_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Ask no introduce registry, gateway ni un segundo gate durante repair."""
    config = _write_ask_config(tmp_path)
    (tmp_path / "logs").mkdir()
    database = tmp_path / "barbarion.db"
    initialize_database(database)
    seed_chunks(database)
    opener = FakeOpener(
        [
            FakeResponse("Respuesta original sin cita."),
            FakeResponse("order_total se selecciona desde dual [F1]."),
        ]
    )
    preflight = CountingPreflight(passing_privacy_preflight())
    monkeypatch.setattr(cli, "_build_privacy_preflight", lambda settings: preflight)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-t11-never-output")
    monkeypatch.setattr(
        AnthropicLlmProvider,
        "_open",
        lambda self, request, timeout_seconds: opener.open(
            request, timeout=timeout_seconds
        ),
    )

    exit_code = cli.main(
        ["--config", str(config), "ask", "order_total", "--mode", "keyword"]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert preflight.calls == 1
    assert len(opener.requests) == 2
    assert {
        request.full_url for request, _timeout in opener.requests
    } == {ANTHROPIC_MESSAGES_URL}
    observable = captured.out + captured.err + (tmp_path / "logs/barbarion.log").read_text(
        encoding="utf-8"
    )
    assert "sk-ant-t11-never-output" not in observable
    assert "registry" not in " ".join(
        request.full_url.lower() for request, _timeout in opener.requests
    )
    assert "gateway" not in " ".join(
        request.full_url.lower() for request, _timeout in opener.requests
    )


@pytest.mark.parametrize("cache_status", ["missing", "expired", "invalid"])
def test_int011_untrusted_cache_blocks_before_prompt_and_provider(
    tmp_path: Path,
    cache_status: str,
) -> None:
    preflight = PrivacyPreflightService(
        policy=PrivacyPolicy(),
        policy_source=None,
        account_verifier=UnavailableAccountPrivacyVerifier(),
        cache_status=cache_status,
    )
    service, llm, builder, _source = _service(
        tmp_path,
        execution=None,
        remote=True,
        preflight=preflight,
    )

    with pytest.raises(PrivacyPreflightBlockedError) as captured:
        _ask(service, "order_total")

    assert captured.value.diagnostics.cache_status == cache_status
    assert llm.prompts == []
    assert builder.build_calls == 0


def test_int011_ollama_cloud_behind_localhost_cannot_bypass_preflight(
    tmp_path: Path,
) -> None:
    """La declaracion remote prevalece aunque el transporte sea localhost."""
    service, llm, builder, source = _service(
        tmp_path,
        execution="remote",
        remote=False,
        evidence=(),
    )

    with pytest.raises(PrivacyPreflightBlockedError) as captured:
        _ask(service, "order_total")

    target = captured.value.result.target
    assert target.execution is InferenceExecution.REMOTE
    assert target.provider == "ollama"
    assert target.platform == "ollama_cloud"
    assert len(source.calls) == 1
    assert llm.prompts == []
    assert builder.build_calls == 0
