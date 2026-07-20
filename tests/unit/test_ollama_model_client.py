"""Pruebas del cliente HTTP local de modelos Ollama."""

from __future__ import annotations

import io
import json
import socket
import urllib.error

import pytest

from barbarion.domain.local_models import (
    LocalModelErrorCode,
    LocalModelProviderError,
    ModelGenerationRequest,
)
from barbarion.infrastructure.ollama_models import OllamaModelClient


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self._stream = io.BytesIO(body)

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def read(self) -> bytes:
        return self._body

    def readline(self) -> bytes:
        return self._stream.readline()


class FakeOpener:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[object, float]] = []

    def open(self, request, *, timeout: float):  # noqa: ANN001
        self.requests.append((request, timeout))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class PartialTimeoutResponse(FakeResponse):
    """Entrega progreso parcial y luego simula inactividad de red."""

    def __init__(self) -> None:
        super().__init__(b'{"status":"downloading","completed":1,"total":10}\n')
        self._reads = 0

    def readline(self) -> bytes:
        self._reads += 1
        if self._reads == 1:
            return super().readline()
        raise socket.timeout("sin progreso")


def _payload(request) -> dict[str, object]:  # noqa: ANN001
    return json.loads(request.data.decode("utf-8"))


def test_list_models_tolerates_optional_and_unknown_fields() -> None:
    opener = FakeOpener(
        [
            FakeResponse(
                json.dumps(
                    {
                        "models": [
                            {
                                "name": "b:latest",
                                "size": 25,
                                "digest": "abc",
                                "modified_at": "2026-07-20T10:00:00Z",
                                "unknown": {"future": True},
                            },
                            {"model": "a:tag"},
                        ]
                    }
                ).encode()
            )
        ]
    )
    client = OllamaModelClient("http://127.0.0.1:11434/", _opener=opener)

    models = client.list_models(timeout_seconds=2)

    assert [model.name for model in models] == ["b:latest", "a:tag"]
    assert models[0].size_bytes == 25
    assert models[1].size_bytes is None
    request, timeout = opener.requests[0]
    assert request.full_url == "http://127.0.0.1:11434/api/tags"
    assert request.method == "GET"
    assert timeout == 2


def test_server_version_keeps_only_bounded_version() -> None:
    opener = FakeOpener(
        [FakeResponse(json.dumps({"version": "1.2.3", "extra": "ignored"}).encode())]
    )
    client = OllamaModelClient("http://127.0.0.1:11434", _opener=opener)

    assert client.server_version(timeout_seconds=2) == "1.2.3"
    request, timeout = opener.requests[0]
    assert request.full_url.endswith("/api/version")
    assert request.method == "GET"
    assert timeout == 2


def test_show_model_normalizes_safe_details() -> None:
    opener = FakeOpener(
        [
            FakeResponse(
                json.dumps(
                    {
                        "details": {
                            "format": "gguf",
                            "family": "generic",
                            "parameter_size": "small",
                            "quantization_level": "Q4",
                            "parent_model": "ignored",
                        },
                        "capabilities": ["completion", "tools", 123],
                        "template": "contenido extenso que no se conserva",
                    }
                ).encode()
            )
        ]
    )
    client = OllamaModelClient("http://localhost:11434", _opener=opener)

    details = client.show_model("modelo:tag", timeout_seconds=3)

    assert details.model.name == "modelo:tag"
    assert details.format == "gguf"
    assert details.capabilities == ("completion", "tools")
    request, _timeout = opener.requests[0]
    assert request.full_url.endswith("/api/show")
    assert _payload(request) == {"model": "modelo:tag"}


def test_pull_model_emits_normalized_progress() -> None:
    body = (
        b'{"status":"pulling manifest"}\n'
        b'{"status":"downloading","completed":5,"total":10}\n'
        b'{"status":"success"}\n'
    )
    opener = FakeOpener([FakeResponse(body)])
    client = OllamaModelClient("http://localhost:11434", _opener=opener)
    events = []

    result = client.pull_model(
        "modelo:tag",
        timeout_seconds=30,
        on_progress=events.append,
    )

    assert result.model == "modelo:tag"
    assert result.status == "success"
    assert [event.status for event in events] == [
        "pulling manifest",
        "downloading",
        "success",
    ]
    assert events[1].percent == 50.0
    request, _timeout = opener.requests[0]
    assert _payload(request) == {"model": "modelo:tag", "stream": True}


def test_pull_model_maps_stream_error_without_logging_payload() -> None:
    client = OllamaModelClient(
        "http://localhost:11434",
        _opener=FakeOpener([FakeResponse(b'{"error":"sin espacio"}\n')]),
    )

    with pytest.raises(LocalModelProviderError) as captured:
        client.pull_model("modelo", timeout_seconds=10)

    assert captured.value.code is LocalModelErrorCode.OPERATION_FAILED
    assert captured.value.detail == "sin espacio"


def test_pull_model_preserves_partial_progress_and_maps_read_timeout() -> None:
    client = OllamaModelClient(
        "http://localhost:11434",
        _opener=FakeOpener([PartialTimeoutResponse()]),
    )
    events = []

    with pytest.raises(LocalModelProviderError) as captured:
        client.pull_model(
            "modelo",
            timeout_seconds=10,
            on_progress=events.append,
        )

    assert [event.percent for event in events] == [10.0]
    assert captured.value.code is LocalModelErrorCode.TIMEOUT


def test_generate_detailed_preserves_optional_telemetry() -> None:
    opener = FakeOpener(
        [
            FakeResponse(
                json.dumps(
                    {
                        "response": "BARBARION_OK",
                        "total_duration": 100,
                        "load_duration": 10,
                        "prompt_eval_count": 7,
                        "eval_count": 2,
                        "future_metric": 99,
                    }
                ).encode()
            )
        ]
    )
    client = OllamaModelClient("http://localhost:11434", _opener=opener)

    result = client.generate_detailed(
        ModelGenerationRequest(
            model="modelo:tag",
            prompt="Devuelve BARBARION_OK",
            timeout_seconds=4,
            max_output_tokens=8,
        )
    )

    assert result.response == "BARBARION_OK"
    assert result.telemetry.total_duration_ns == 100
    assert result.telemetry.prompt_eval_count == 7
    assert result.telemetry.eval_duration_ns is None
    request, timeout = opener.requests[0]
    assert timeout == 4
    assert _payload(request)["options"] == {"temperature": 0.0, "num_predict": 8}


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (urllib.error.URLError("connection refused"), LocalModelErrorCode.UNAVAILABLE),
        (TimeoutError(), LocalModelErrorCode.TIMEOUT),
        (FakeResponse(b"not-json"), LocalModelErrorCode.INVALID_RESPONSE),
    ],
)
def test_client_maps_transport_and_payload_errors(
    response: object,
    expected_code: LocalModelErrorCode,
) -> None:
    client = OllamaModelClient(
        "http://localhost:11434",
        _opener=FakeOpener([response]),
    )

    with pytest.raises(LocalModelProviderError) as captured:
        client.list_models(timeout_seconds=1)

    assert captured.value.code is expected_code


def test_client_maps_model_not_found() -> None:
    error = urllib.error.HTTPError(
        "http://localhost:11434/api/show",
        404,
        "missing",
        hdrs={},
        fp=io.BytesIO(),
    )
    client = OllamaModelClient(
        "http://localhost:11434",
        _opener=FakeOpener([error]),
    )

    with pytest.raises(LocalModelProviderError) as captured:
        client.show_model("missing", timeout_seconds=1)

    assert captured.value.code is LocalModelErrorCode.MODEL_NOT_FOUND


def test_client_tolerates_malformed_optional_numeric_metadata() -> None:
    client = OllamaModelClient(
        "http://localhost:11434",
        _opener=FakeOpener(
            [FakeResponse(b'{"models":[{"name":"modelo","size":-1}]}')]
        ),
    )

    assert client.list_models(timeout_seconds=1)[0].size_bytes is None


def test_client_maps_interruption_while_opening_request() -> None:
    client = OllamaModelClient(
        "http://localhost:11434",
        _opener=FakeOpener([KeyboardInterrupt()]),
    )

    with pytest.raises(LocalModelProviderError) as captured:
        client.list_models(timeout_seconds=1)

    assert captured.value.code is LocalModelErrorCode.INTERRUPTED


def test_existing_llm_provider_contract_is_not_required_by_new_client() -> None:
    """El cliente detallado no cambia ni hereda el adaptador RAG existente."""
    client = OllamaModelClient("http://localhost:11434", _opener=FakeOpener([]))

    assert not hasattr(client, "generate")
