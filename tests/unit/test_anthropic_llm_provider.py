"""Pruebas del adaptador HTTP Anthropic."""

import io
import json
import logging
import socket
import urllib.error
from email.message import Message

import pytest

from barbarion.domain.rag import LlmProviderError
from barbarion.infrastructure import anthropic
from barbarion.infrastructure.anthropic import (
    ANTHROPIC_API_VERSION,
    ANTHROPIC_MESSAGES_URL,
    AnthropicLlmProvider,
)

CANARY_KEY = "sk-ant-test-NEVER-LOG-H12-0123456789"


class FakeResponse:
    def __init__(
        self,
        body: bytes | BaseException,
        *,
        headers: object | None = None,
    ) -> None:
        self.body = body
        self.headers = {} if headers is None else headers
        self.closed = False

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        del args
        self.closed = True

    def read(self) -> bytes:
        if isinstance(self.body, BaseException):
            raise self.body
        return self.body


class FakeOpener:
    def __init__(self, result: object) -> None:
        self.result = result
        self.requests: list[tuple[object, float]] = []

    def open(self, request: object, *, timeout: float):
        self.requests.append((request, timeout))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class SequenceOpener:
    def __init__(self, results: list[object]) -> None:
        self.results = results
        self.requests: list[tuple[object, float]] = []

    def open(self, request: object, *, timeout: float):
        self.requests.append((request, timeout))
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def _body(
    content: object,
    *,
    stop_reason: object = "end_turn",
    **extra: object,
) -> bytes:
    return json.dumps(
        {
            "id": "msg_synthetic",
            "type": "message",
            "content": content,
            "stop_reason": stop_reason,
            **extra,
        }
    ).encode("utf-8")


def _provider(
    result: object,
    *,
    key: str | None = CANARY_KEY,
) -> tuple[AnthropicLlmProvider, FakeOpener]:
    opener = FakeOpener(result)
    provider = AnthropicLlmProvider(
        model="claude-test",
        temperature=0.2,
        max_output_tokens=4096,
        _api_key_resolver=lambda: key,
        _opener=opener,
    )
    return provider, opener


def _http_error(
    status: int,
    *,
    request_id: str | None = None,
    body: bytes = b'{"error":"REMOTE BODY MUST NOT LEAK"}',
) -> urllib.error.HTTPError:
    headers = Message()
    if request_id is not None:
        headers["request-id"] = request_id
    headers["x-secret-remote-header"] = "NEVER-EXPOSE"
    return urllib.error.HTTPError(
        ANTHROPIC_MESSAGES_URL,
        status,
        "REMOTE REASON MUST NOT LEAK",
        headers,
        io.BytesIO(body),
    )


def test_messages_request_is_fixed_minimal_and_non_streaming() -> None:
    response = FakeResponse(_body([{"type": "text", "text": "Respuesta [F1]"}]))
    provider, opener = _provider(response)

    answer = provider.generate(prompt="prompt sintetico", timeout_seconds=37.5)

    assert answer == "Respuesta [F1]"
    assert len(opener.requests) == 1
    request, timeout = opener.requests[0]
    assert request.full_url == ANTHROPIC_MESSAGES_URL
    assert request.get_method() == "POST"
    assert timeout == 37.5
    headers = {key.lower(): value for key, value in request.header_items()}
    assert headers == {
        "content-type": "application/json",
        "x-api-key": CANARY_KEY,
        "anthropic-version": ANTHROPIC_API_VERSION,
    }
    payload = json.loads(request.data)
    assert payload == {
        "model": "claude-test",
        "max_tokens": 4096,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": "prompt sintetico"}],
    }
    assert not {
        "stream",
        "system",
        "tools",
        "thinking",
        "files",
        "metadata",
    }.intersection(payload)
    assert response.closed is True


def test_usage_and_elapsed_time_are_captured_without_changing_generate_result() -> None:
    clock_values = iter((10.0, 14.18))
    response = FakeResponse(
        _body(
            [{"type": "text", "text": "Respuesta [F1]"}],
            usage={"input_tokens": 7842, "output_tokens": 612},
        )
    )
    provider = AnthropicLlmProvider(
        model="claude-test",
        temperature=0.2,
        max_output_tokens=4096,
        _api_key_resolver=lambda: CANARY_KEY,
        _opener=FakeOpener(response),
        _clock=lambda: next(clock_values),
    )

    answer = provider.generate(prompt="prompt sintetico", timeout_seconds=30.0)
    usage = provider.usage_snapshot()

    assert answer == "Respuesta [F1]"
    assert usage is not None
    assert usage.input_tokens == 7842
    assert usage.output_tokens == 612
    assert usage.total_tokens == 8454
    assert usage.elapsed_seconds == pytest.approx(4.18)
    assert usage.request_count == 1


def test_usage_is_aggregated_across_generation_and_repair() -> None:
    opener = SequenceOpener(
        [
            FakeResponse(
                _body(
                    [{"type": "text", "text": "Sin cita"}],
                    usage={
                        "input_tokens": 100,
                        "output_tokens": 10,
                        "total_tokens": 111,
                    },
                )
            ),
            FakeResponse(
                _body(
                    [{"type": "text", "text": "Reparada [F1]"}],
                    usage={"input_tokens": 120, "output_tokens": 12},
                )
            ),
        ]
    )
    clock_values = iter((1.0, 2.5, 3.0, 5.0))
    provider = AnthropicLlmProvider(
        model="claude-test",
        temperature=0.2,
        max_output_tokens=4096,
        _api_key_resolver=lambda: CANARY_KEY,
        _opener=opener,
        _clock=lambda: next(clock_values),
    )

    assert provider.generate(prompt="generation", timeout_seconds=30.0) == "Sin cita"
    assert provider.generate(prompt="repair", timeout_seconds=30.0) == "Reparada [F1]"
    usage = provider.usage_snapshot()

    assert usage is not None
    assert usage.input_tokens == 220
    assert usage.output_tokens == 22
    assert usage.total_tokens == 243
    assert usage.elapsed_seconds == 3.5
    assert usage.request_count == 2
    assert len(opener.requests) == 2


def test_invalid_usage_is_ignored_without_rejecting_valid_text() -> None:
    provider, _opener = _provider(
        FakeResponse(
            _body(
                [{"type": "text", "text": "Respuesta [F1]"}],
                usage={
                    "input_tokens": True,
                    "output_tokens": -1,
                    "total_tokens": "unknown",
                },
            )
        )
    )

    assert provider.generate(prompt="x", timeout_seconds=2.0) == "Respuesta [F1]"
    usage = provider.usage_snapshot()
    assert usage is not None
    assert usage.input_tokens is None
    assert usage.output_tokens is None
    assert usage.total_tokens is None


def test_usage_observability_never_logs_content_headers_or_key() -> None:
    logger = logging.getLogger("barbarion")
    original_handlers = list(logger.handlers)
    original_level = logger.level
    original_propagate = logger.propagate
    records: list[logging.LogRecord] = []

    class Handler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger.handlers[:] = [Handler()]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    prompt_secret = "prompt-secret-never-log"
    response_secret = "response-secret-never-log [F1]"
    try:
        provider, _opener = _provider(
            FakeResponse(
                _body(
                    [{"type": "text", "text": response_secret}],
                    usage={"input_tokens": 20, "output_tokens": 5},
                ),
                headers={"request-id": "req_safe", "x-secret": CANARY_KEY},
            )
        )
        provider.generate(prompt=prompt_secret, timeout_seconds=2.0)
    finally:
        logger.handlers[:] = original_handlers
        logger.setLevel(original_level)
        logger.propagate = original_propagate

    log_text = "\n".join(record.getMessage() for record in records)
    assert "anthropic_llm_finished" in log_text
    assert "input_tokens=20" in log_text
    assert "output_tokens=5" in log_text
    assert "total_tokens=25" in log_text
    assert "duration_ms=" in log_text
    assert prompt_secret not in log_text
    assert response_secret not in log_text
    assert CANARY_KEY not in log_text
    assert "x-secret" not in log_text


def test_default_transport_installs_redirect_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = FakeResponse(_body([{"type": "text", "text": "ok"}]))
    opener = FakeOpener(response)
    handlers: list[object] = []

    def fake_build_opener(*values: object) -> FakeOpener:
        handlers.extend(values)
        return opener

    monkeypatch.setattr(anthropic.urllib.request, "build_opener", fake_build_opener)
    provider = AnthropicLlmProvider(
        model="claude-test",
        temperature=0.0,
        max_output_tokens=1,
        _api_key_resolver=lambda: CANARY_KEY,
    )

    assert provider.generate(prompt="x", timeout_seconds=2.0) == "ok"
    assert len(handlers) == 1
    assert isinstance(handlers[0], anthropic._RejectRedirectHandler)
    assert handlers[0].redirect_request(None, None, 302, "", {}, "https://bad") is None


@pytest.mark.parametrize("stop_reason", [None, "future_reason"])
def test_text_blocks_are_concatenated_in_order_and_unknown_blocks_ignored(
    stop_reason: object,
) -> None:
    response = FakeResponse(
        _body(
            [
                {"type": "text", "text": "  primera ", "extra": True},
                {"type": "future", "value": CANARY_KEY},
                {"type": "text", "text": "segunda  "},
            ],
            stop_reason=stop_reason,
            future_field={"secret": CANARY_KEY},
        )
    )
    provider, _opener = _provider(response)

    answer = provider.generate(prompt="x", timeout_seconds=2.0)

    assert answer == "  primera segunda  "


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        b"\xff",
        b"[]",
        json.dumps({"stop_reason": "end_turn"}).encode(),
        _body(None),
        _body("invalid"),
        _body(["invalid"]),
        _body([{"type": "text"}]),
        _body([{"type": "text", "text": 1}]),
        _body([]),
        _body([{"type": "future"}]),
        _body([{"type": "text", "text": "  "}]),
    ],
)
def test_invalid_or_empty_responses_are_rejected(body: bytes) -> None:
    provider, _opener = _provider(FakeResponse(body))

    with pytest.raises(
        LlmProviderError,
        match="ANTHROPIC_RESPONSE_INVALID",
    ) as caught:
        provider.generate(prompt="x", timeout_seconds=2.0)

    assert caught.value.__cause__ is None


def test_max_tokens_never_returns_partial_text() -> None:
    response = FakeResponse(
        _body(
            [{"type": "text", "text": "respuesta parcial sensible"}],
            stop_reason="max_tokens",
        ),
        headers={"request-id": "req_safe-123"},
    )
    provider, _opener = _provider(response)

    with pytest.raises(LlmProviderError, match="ANTHROPIC_LLM_TRUNCATED") as caught:
        provider.generate(prompt="x", timeout_seconds=2.0)

    message = str(caught.value)
    assert "respuesta parcial sensible" not in message
    assert "request-id=req_safe-123" in message


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (400, "ANTHROPIC_REQUEST_INVALID"),
        (401, "ANTHROPIC_AUTHENTICATION_ERROR"),
        (402, "ANTHROPIC_BILLING_ERROR"),
        (403, "ANTHROPIC_PERMISSION_ERROR"),
        (404, "ANTHROPIC_MODEL_NOT_FOUND"),
        (409, "ANTHROPIC_REQUEST_INVALID"),
        (413, "ANTHROPIC_REQUEST_TOO_LARGE"),
        (429, "ANTHROPIC_RATE_LIMITED"),
        (500, "ANTHROPIC_HTTP_ERROR"),
        (504, "ANTHROPIC_TIMEOUT"),
        (529, "ANTHROPIC_OVERLOADED"),
        (418, "ANTHROPIC_HTTP_ERROR"),
    ],
)
def test_http_statuses_are_mapped_without_remote_content(
    status: int,
    code: str,
) -> None:
    provider, opener = _provider(_http_error(status, body=CANARY_KEY.encode()))

    with pytest.raises(LlmProviderError, match=code) as caught:
        provider.generate(prompt="x", timeout_seconds=2.0)

    message = str(caught.value)
    assert len(opener.requests) == 1
    assert caught.value.__cause__ is None
    assert CANARY_KEY not in message
    assert "REMOTE" not in message
    assert "NEVER-EXPOSE" not in message


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (TimeoutError("late"), "ANTHROPIC_TIMEOUT"),
        (socket.timeout("late"), "ANTHROPIC_TIMEOUT"),
        (urllib.error.URLError(TimeoutError("late")), "ANTHROPIC_TIMEOUT"),
        (urllib.error.URLError(socket.timeout("late")), "ANTHROPIC_TIMEOUT"),
        (urllib.error.URLError("dns synthetic"), "ANTHROPIC_UNAVAILABLE"),
    ],
)
def test_transport_failures_are_mapped_once(
    error: BaseException,
    code: str,
) -> None:
    provider, opener = _provider(error)

    with pytest.raises(LlmProviderError, match=code) as caught:
        provider.generate(prompt="x", timeout_seconds=2.0)

    assert len(opener.requests) == 1
    assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    ("request_id", "visible"),
    [
        ("req_safe.A-1:2", True),
        ("x" * 128, True),
        ("x" * 129, False),
        ("req con espacios", False),
        ("req_\ninyectado", False),
        ("req_á", False),
    ],
)
def test_request_id_is_strictly_bounded(request_id: str, visible: bool) -> None:
    provider, _opener = _provider(_http_error(500, request_id=request_id))

    with pytest.raises(LlmProviderError) as caught:
        provider.generate(prompt="x", timeout_seconds=2.0)

    assert (request_id in str(caught.value)) is visible


@pytest.mark.parametrize("key", [None, "", "   "])
def test_missing_key_fails_before_opening(key: str | None) -> None:
    provider, opener = _provider(
        FakeResponse(_body([{"type": "text", "text": "unexpected"}])),
        key=key,
    )

    with pytest.raises(LlmProviderError, match="ANTHROPIC_API_KEY_MISSING"):
        provider.generate(prompt="x", timeout_seconds=2.0)

    assert opener.requests == []


def test_key_is_not_represented_and_header_injection_is_rejected() -> None:
    injected = f"{CANARY_KEY}\r\nX-Evil: exposed"
    provider, opener = _provider(FakeResponse(b"{}"), key=injected)

    with pytest.raises(LlmProviderError, match="ANTHROPIC_AUTHENTICATION_ERROR") as caught:
        provider.generate(prompt="x", timeout_seconds=2.0)

    assert opener.requests == []
    assert CANARY_KEY not in repr(provider)
    assert CANARY_KEY not in str(caught.value)


def test_key_in_prompt_is_blocked_before_http_and_never_represented() -> None:
    provider, opener = _provider(
        FakeResponse(_body([{"type": "text", "text": "unexpected"}]))
    )

    with pytest.raises(LlmProviderError, match="ANTHROPIC_REQUEST_INVALID") as caught:
        provider.generate(
            prompt=f"contenido sintetico {CANARY_KEY}",
            timeout_seconds=2.0,
        )

    assert opener.requests == []
    assert CANARY_KEY not in str(caught.value)
    assert CANARY_KEY not in repr(provider)


def test_key_echoed_by_success_response_is_discarded_without_leak() -> None:
    response = FakeResponse(
        _body([{"type": "text", "text": f"eco remoto {CANARY_KEY}"}]),
        headers={"request-id": "req_echo_safe"},
    )
    provider, opener = _provider(response)

    with pytest.raises(LlmProviderError, match="ANTHROPIC_RESPONSE_INVALID") as caught:
        provider.generate(prompt="prompt sintetico", timeout_seconds=2.0)

    assert len(opener.requests) == 1
    assert response.closed is True
    assert CANARY_KEY not in str(caught.value)
    assert "request-id=req_echo_safe" in str(caught.value)
    assert provider.usage_snapshot() is None


@pytest.mark.parametrize(
    "result",
    [
        KeyboardInterrupt(),
        FakeResponse(KeyboardInterrupt()),
    ],
)
def test_keyboard_interrupt_propagates_without_retry(result: object) -> None:
    provider, opener = _provider(result)

    with pytest.raises(KeyboardInterrupt):
        provider.generate(prompt="x", timeout_seconds=2.0)

    assert len(opener.requests) == 1
    if isinstance(result, FakeResponse):
        assert result.closed is True
