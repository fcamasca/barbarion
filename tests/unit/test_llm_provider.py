"""Pruebas del adaptador LLM local."""

import io
import json
import urllib.error

import pytest

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
        _opener=opener,
    )

    first = provider.generate(prompt="generacion", timeout_seconds=600)
    second = provider.generate(prompt="reparacion", timeout_seconds=600)

    assert first == second == "Respuesta [F1]"
    assert [timeout for _request, timeout in opener.requests] == [600, 600]
    payloads = [json.loads(request.data) for request, _timeout in opener.requests]
    assert [payload["think"] for payload in payloads] == [False, False]
    assert all(
        payload["options"] == {"temperature": 0.2} for payload in payloads
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
