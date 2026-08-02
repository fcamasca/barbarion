"""Integracion offline de configuracion, factoria y request Anthropic."""

import json
from dataclasses import replace
from pathlib import Path

from barbarion import cli
from barbarion.config import load_settings
from barbarion.infrastructure.anthropic import (
    ANTHROPIC_API_VERSION,
    ANTHROPIC_MESSAGES_URL,
    AnthropicLlmProvider,
)


class FakeResponse:
    headers = {"request-id": "req_integration_safe"}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def read(self) -> bytes:
        return json.dumps(
            {
                "content": [{"type": "text", "text": "Respuesta [F1]"}],
                "stop_reason": "end_turn",
            }
        ).encode("utf-8")


class FakeOpener:
    def __init__(self) -> None:
        self.requests: list[tuple[object, float]] = []

    def open(self, request: object, *, timeout: float) -> FakeResponse:
        self.requests.append((request, timeout))
        return FakeResponse()


def test_configured_factory_emits_one_messages_api_request(tmp_path: Path) -> None:
    source = tmp_path / "anthropic.toml"
    source.write_text(
        "\n".join(
            (
                "[llm]",
                'provider = "anthropic"',
                'model = "claude-integration-test"',
                "timeout_seconds = 19.0",
                "temperature = 0.25",
                "max_output_tokens = 2048",
            )
        ),
        encoding="utf-8",
    )
    settings = load_settings(source, environ={}, cwd=tmp_path)
    built = cli._build_llm_provider(
        settings,
        environ={"ANTHROPIC_API_KEY": "sk-ant-integration-fake"},
    )
    assert isinstance(built, AnthropicLlmProvider)
    opener = FakeOpener()
    provider = replace(built, _opener=opener)

    answer = provider.generate(
        prompt="Pregunta y evidencia sinteticas [F1]",
        timeout_seconds=settings.llm.timeout_seconds,
    )

    assert answer == "Respuesta [F1]"
    assert len(opener.requests) == 1
    request, timeout = opener.requests[0]
    assert request.full_url == ANTHROPIC_MESSAGES_URL
    assert request.get_method() == "POST"
    assert timeout == 19.0
    headers = {key.lower(): value for key, value in request.header_items()}
    assert headers["anthropic-version"] == ANTHROPIC_API_VERSION
    payload = json.loads(request.data)
    assert payload["model"] == "claude-integration-test"
    assert payload["max_tokens"] == 2048
    assert payload["messages"] == [
        {
            "role": "user",
            "content": "Pregunta y evidencia sinteticas [F1]",
        }
    ]
