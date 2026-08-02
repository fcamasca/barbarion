"""Pruebas del adaptador LLM local."""

import io
import inspect
import json
import urllib.error
from pathlib import Path

import pytest

from barbarion import cli
from barbarion.config import load_settings
from barbarion.domain.ports import LlmProviderPort
from barbarion.domain.rag import LlmProviderError
from barbarion.infrastructure.llm import OllamaLlmProvider


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def read(self) -> bytes:
        return self.body


class FakeOpener:
    def __init__(self, response: object) -> None:
        self.response = response
        self.requests = []

    def open(self, request, *, timeout: float):  # noqa: ANN001
        self.requests.append((request, timeout))
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


def test_llm_provider_port_preserves_minimal_generation_contract() -> None:
    """Congela el seam que H1.2 debe reutilizar sin ampliarlo."""
    contract = inspect.signature(LlmProviderPort.generate)

    assert tuple(contract.parameters) == ("self", "prompt", "timeout_seconds")
    assert contract.parameters["prompt"].kind is inspect.Parameter.KEYWORD_ONLY
    assert (
        contract.parameters["timeout_seconds"].kind
        is inspect.Parameter.KEYWORD_ONLY
    )
    assert LlmProviderPort.__annotations__ == {
        "provider": "str",
        "model": "str",
    }


def test_llm_provider_factory_preserves_effective_ollama_settings(
    tmp_path: Path,
) -> None:
    """Caracteriza la composicion concreta previa al adaptador Anthropic."""
    config = tmp_path / "barbarion.toml"
    config.write_text(
        "\n".join(
            (
                'ollama_url = "http://127.0.0.1:22000"',
                "[llm]",
                'provider = "ollama"',
                'model = "modelo-caracterizado:tag"',
                "timeout_seconds = 321.0",
                "temperature = 0.25",
                "think = false",
                "num_ctx = 24576",
            )
        ),
        encoding="utf-8",
    )
    settings = load_settings(config, environ={}, cwd=tmp_path)

    provider = cli._build_llm_provider(settings)

    assert isinstance(provider, OllamaLlmProvider)
    assert provider.provider == "ollama"
    assert provider.base_url == "http://127.0.0.1:22000"
    assert provider.model == "modelo-caracterizado:tag"
    assert provider.temperature == 0.25
    assert provider.think is False
    assert provider.num_ctx == 24576


def test_ollama_llm_provider_generates_text() -> None:
    opener = FakeOpener(FakeResponse(b'{"response":"Respuesta [F1]"}'))
    provider = OllamaLlmProvider(
        base_url="http://localhost:11434",
        model="llama",
        temperature=0.1,
        _opener=opener,
    )

    answer = provider.generate(prompt="hola", timeout_seconds=2)

    assert answer == "Respuesta [F1]"
    assert opener.requests[0][1] == 2
    payload = json.loads(opener.requests[0][0].data)
    assert "think" not in payload
    assert payload["options"] == {"temperature": 0.1}


def test_ollama_llm_provider_sends_disabled_thinking_on_every_generation() -> None:
    opener = FakeOpener(FakeResponse(b'{"response":"Respuesta [F1]"}'))
    provider = OllamaLlmProvider(
        base_url="http://localhost:11434",
        model="modelo-local",
        temperature=0.2,
        think=False,
        num_ctx=16384,
        _opener=opener,
    )

    first = provider.generate(prompt="generacion", timeout_seconds=600)
    second = provider.generate(prompt="reparacion", timeout_seconds=600)

    assert first == second == "Respuesta [F1]"
    assert [timeout for _request, timeout in opener.requests] == [600, 600]
    payloads = [json.loads(request.data) for request, _timeout in opener.requests]
    assert [payload["think"] for payload in payloads] == [False, False]
    assert all(
        payload["options"] == {"temperature": 0.2, "num_ctx": 16384}
        for payload in payloads
    )


def test_ollama_llm_provider_maps_model_not_found() -> None:
    error = urllib.error.HTTPError(
        "http://localhost",
        404,
        "missing",
        hdrs={},
        fp=io.BytesIO(),
    )
    provider = OllamaLlmProvider("http://localhost:11434", "missing", 0.0, _opener=FakeOpener(error))

    with pytest.raises(LlmProviderError, match="MODEL_NOT_FOUND"):
        provider.generate(prompt="hola", timeout_seconds=2)


def test_ollama_llm_provider_rejects_invalid_response() -> None:
    provider = OllamaLlmProvider(
        "http://localhost:11434",
        "llama",
        0.0,
        _opener=FakeOpener(FakeResponse(b'{"bad":true}')),
    )

    with pytest.raises(LlmProviderError, match="RESPONSE_INVALID"):
        provider.generate(prompt="hola", timeout_seconds=2)
