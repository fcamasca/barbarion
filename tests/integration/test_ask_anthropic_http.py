"""Integracion offline de configuracion, factoria y request Anthropic."""

import json
import socket
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from barbarion import cli
from barbarion.application.rag import PromptBuilder
from barbarion.config import load_settings
from barbarion.database import initialize_database
from barbarion.infrastructure.anthropic import (
    ANTHROPIC_API_VERSION,
    ANTHROPIC_MESSAGES_URL,
    AnthropicLlmProvider,
)
from tests.unit.test_rag_index_service import seed_chunks
from tests.support.privacy import passing_privacy_preflight


@pytest.fixture(autouse=True)
def _authorized_privacy_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli,
        "_build_privacy_preflight",
        lambda settings: passing_privacy_preflight(),
    )


class FakeResponse:
    headers = {"request-id": "req_integration_safe"}

    def __init__(
        self,
        text: str = "Respuesta [F1]",
        *,
        input_tokens: int = 10,
        output_tokens: int = 2,
    ) -> None:
        self.text = text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def read(self) -> bytes:
        return json.dumps(
            {
                "content": [{"type": "text", "text": self.text}],
                "stop_reason": "end_turn",
                "usage": {
                    "input_tokens": self.input_tokens,
                    "output_tokens": self.output_tokens,
                },
            },
            ensure_ascii=False,
        ).encode("utf-8")


class FakeOpener:
    def __init__(self, responses: list[FakeResponse] | None = None) -> None:
        self.responses = responses or [FakeResponse()]
        self.requests: list[tuple[object, float]] = []

    def open(self, request: object, *, timeout: float) -> FakeResponse:
        self.requests.append((request, timeout))
        return self.responses.pop(0)


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


def _write_ask_config(tmp_path: Path) -> Path:
    source = tmp_path / "barbarion.toml"
    source.write_text(
        "\n".join(
            (
                'database_path = "barbarion.db"',
                'logs_dir = "logs"',
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
    return source


def test_real_ask_composition_uses_anthropic_for_generation_and_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _write_ask_config(tmp_path)
    (tmp_path / "logs").mkdir()
    database = tmp_path / "barbarion.db"
    initialize_database(database)
    seed_chunks(database)
    opener = FakeOpener(
        [
            FakeResponse(
                "Respuesta original sin cita.",
                input_tokens=100,
                output_tokens=10,
            ),
            FakeResponse(
                "order_total se selecciona desde dual [F1].",
                input_tokens=120,
                output_tokens=12,
            ),
        ]
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-integration-fake")
    monkeypatch.setattr(
        AnthropicLlmProvider,
        "_open",
        lambda self, request, timeout_seconds: opener.open(
            request,
            timeout=timeout_seconds,
        ),
    )
    generated_prompts: list[str] = []
    repaired_prompts: list[str] = []
    original_build = PromptBuilder.build
    original_repair = PromptBuilder.repair

    def observe_build(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        prompt = original_build(self, *args, **kwargs)
        generated_prompts.append(prompt)
        return prompt

    def observe_repair(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        prompt = original_repair(self, *args, **kwargs)
        repaired_prompts.append(prompt)
        return prompt

    monkeypatch.setattr(PromptBuilder, "build", observe_build)
    monkeypatch.setattr(PromptBuilder, "repair", observe_repair)

    exit_code = cli.main(
        [
            "--config",
            str(source),
            "ask",
            "order_total",
            "--mode",
            "keyword",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "order_total se selecciona desde dual [F1]." in captured.out
    assert "Input tokens : 220" in captured.err
    assert "Output tokens: 22" in captured.err
    assert "Total tokens : 242" in captured.err
    assert "Elapsed time :" in captured.err
    assert len(opener.requests) == 2
    payloads = [json.loads(request.data) for request, _timeout in opener.requests]
    assert payloads[0]["messages"][0]["content"] == generated_prompts[0]
    assert payloads[1]["messages"][0]["content"] == repaired_prompts[0]
    assert {payload["model"] for payload in payloads} == {
        "claude-integration-test"
    }
    with sqlite3.connect(database) as connection:
        status = connection.execute(
            "SELECT status FROM rag_queries ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
    assert status == "completed"


@pytest.mark.parametrize("output_format", ["text", "json", "markdown"])
def test_unicode_survives_ask_end_to_end_in_all_formats_and_debug(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    output_format: str,
) -> None:
    question = "¿Dónde se calcula la provisión diaria?"
    context_text = (
        "La configuración de adquisición calcula la provisión diaria: "
        "días, cupón, último y cálculo."
    )
    answer = f"{context_text} [F1]"
    canary_key = "sk-ant-unicode-canary-never-output"
    source = _write_ask_config(tmp_path)
    (tmp_path / "logs").mkdir()
    database = tmp_path / "barbarion.db"
    initialize_database(database)
    seed_chunks(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE chunks SET content = ? WHERE id = 'chunk-2'",
            (context_text,),
        )
        connection.commit()

    opener = FakeOpener(
        [FakeResponse(answer, input_tokens=10198, output_tokens=612)]
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", canary_key)
    monkeypatch.setattr(
        AnthropicLlmProvider,
        "_open",
        lambda self, request, timeout_seconds: opener.open(
            request,
            timeout=timeout_seconds,
        ),
    )
    prompts: list[str] = []
    original_build = PromptBuilder.build

    def observe_build(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        prompt = original_build(self, *args, **kwargs)
        prompts.append(prompt)
        return prompt

    monkeypatch.setattr(PromptBuilder, "build", observe_build)

    exit_code = cli.main(
        [
            "--config",
            str(source),
            "ask",
            question,
            "--mode",
            "keyword",
            "--format",
            output_format,
            "--debug",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert len(prompts) == 1
    assert question in prompts[0]
    assert context_text in prompts[0]
    assert question not in captured.err
    assert context_text not in captured.err
    assert answer not in captured.err
    assert "validation: PASS" in captured.err
    assert "=== PRIVACY PREFLIGHT ===" in captured.err
    assert "decision=pass" in captured.err
    assert "account_verifier=unavailable" in captured.err
    assert "Input tokens : 10,198" in captured.err
    assert "Output tokens: 612" in captured.err
    assert "Total tokens : 10,810" in captured.err
    if output_format == "json":
        rendered = json.loads(captured.out)
        assert rendered["answer"] == answer
        assert any(
            source_item["content"] == context_text
            for source_item in rendered["sources"]
        )
    else:
        assert answer in captured.out

    request, _timeout = opener.requests[0]
    request_text = request.data.decode("utf-8")
    payload = json.loads(request_text)
    assert payload["messages"][0]["content"] == prompts[0]
    assert question in request_text
    assert context_text in request_text
    assert "provisión".encode("utf-8") in request.data
    assert b"\\u00f3" not in request.data

    log_text = (tmp_path / "logs" / "barbarion.log").read_text(encoding="utf-8")
    observed = "\n".join((captured.out, captured.err, log_text, request_text))
    assert "�" not in observed
    assert "ï¿½" not in observed
    assert canary_key not in captured.out
    assert canary_key not in captured.err
    assert canary_key not in log_text
    assert canary_key not in request_text


@pytest.mark.parametrize(
    ("question", "extra_args"),
    [
        ("order_total", ("--no-llm",)),
        ("identificador_sintetico_totalmente_ausente", ()),
    ],
)
def test_anthropic_ask_without_generation_needs_no_key_or_http(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    question: str,
    extra_args: tuple[str, ...],
) -> None:
    source = _write_ask_config(tmp_path)
    (tmp_path / "logs").mkdir()
    database = tmp_path / "barbarion.db"
    initialize_database(database)
    seed_chunks(database)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def unexpected_open(*args, **kwargs):  # noqa: ANN002, ANN003
        del args, kwargs
        raise AssertionError("No debe abrir HTTP en este flujo")

    monkeypatch.setattr(AnthropicLlmProvider, "_open", unexpected_open)

    exit_code = cli.main(
        [
            "--config",
            str(source),
            "ask",
            question,
            "--mode",
            "keyword",
            *extra_args,
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "ANTHROPIC_API_KEY" not in captured.err
    assert "anthropic_llm_finished" not in captured.err


@pytest.mark.parametrize(
    ("failure", "expected_exit", "expected_message"),
    [
        (socket.timeout("synthetic timeout"), 1, "timeout configurado"),
        (KeyboardInterrupt(), 130, "interrumpida por el usuario"),
    ],
)
def test_failed_anthropic_generation_never_leaves_query_completed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: BaseException,
    expected_exit: int,
    expected_message: str,
) -> None:
    source = _write_ask_config(tmp_path)
    (tmp_path / "logs").mkdir()
    database = tmp_path / "barbarion.db"
    initialize_database(database)
    seed_chunks(database)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-integration-fake")

    def fail_open(*args, **kwargs):  # noqa: ANN002, ANN003
        del args, kwargs
        raise failure

    monkeypatch.setattr(AnthropicLlmProvider, "_open", fail_open)

    exit_code = cli.main(
        [
            "--config",
            str(source),
            "ask",
            "order_total",
            "--mode",
            "keyword",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == expected_exit
    assert expected_message in captured.err
    assert "Fuentes:" not in captured.out
    with sqlite3.connect(database) as connection:
        status = connection.execute(
            "SELECT status FROM rag_queries ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
    assert status == "error"
