"""Seguridad y privacidad offline de H1.2."""

from __future__ import annotations

import io
import json
import socket
import sqlite3
import urllib.error
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from barbarion import cli
from barbarion.application.rag import PromptBuilder
from barbarion.database import initialize_database
from barbarion.domain.rag import EmbeddingManifest, LlmProviderError
from barbarion.infrastructure import anthropic
from barbarion.infrastructure.anthropic import AnthropicLlmProvider
from barbarion.infrastructure.sqlite import SQLiteRagRepository
from tests.unit.test_rag_index_service import seed_chunks

CANARY_KEY = "sk-ant-test-NEVER-LOG-H12-0123456789"
PROMPT_CANARY = "H12_PROMPT_EPHEMERAL_8C02E9"
RESPONSE_CANARY = "order_total se selecciona desde dual [F1]."
REQUEST_ID_CANARY = "req_h12_ephemeral_7f15"


class _Response:
    def __init__(
        self,
        text: str,
        *,
        stop_reason: str = "end_turn",
        request_id: str = REQUEST_ID_CANARY,
    ) -> None:
        self.text = text
        self.stop_reason = stop_reason
        self.headers = {"request-id": request_id}
        self.closed = False

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        del args
        self.closed = True

    def read(self) -> bytes:
        return json.dumps(
            {
                "content": [{"type": "text", "text": self.text}],
                "stop_reason": self.stop_reason,
                "usage": {"input_tokens": 20, "output_tokens": 5},
            }
        ).encode("utf-8")


class _Opener:
    def __init__(self, result: object) -> None:
        self.result = result
        self.requests: list[tuple[object, float]] = []

    def open(self, request: object, *, timeout: float):  # noqa: ANN201
        self.requests.append((request, timeout))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class _RedirectHandler(BaseHTTPRequestHandler):
    records: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.records.append(
            {
                "path": self.path,
                "headers": {key.lower(): value for key, value in self.headers.items()},
                "body": body,
            }
        )
        self.send_response(307)
        self.send_header(
            "Location",
            f"http://127.0.0.1:{self.server.server_port}/redirected",
        )
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        del format, args


def test_offline_guard_blocks_external_connections_before_dns() -> None:
    with pytest.raises(AssertionError, match="suite offline"):
        socket.create_connection(("example.invalid", 443), timeout=0.01)


def test_default_transport_does_not_forward_key_or_context_on_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _RedirectHandler.records = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RedirectHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    initial_url = f"http://127.0.0.1:{server.server_port}/v1/messages"
    monkeypatch.setattr(anthropic, "ANTHROPIC_MESSAGES_URL", initial_url)
    provider = AnthropicLlmProvider(
        model="claude-security-test",
        temperature=0.0,
        max_output_tokens=128,
        _api_key_resolver=lambda: CANARY_KEY,
    )
    try:
        with pytest.raises(LlmProviderError, match="ANTHROPIC_HTTP_ERROR") as caught:
            provider.generate(prompt=PROMPT_CANARY, timeout_seconds=2.0)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)

    assert str(caught.value).find(CANARY_KEY) == -1
    assert [record["path"] for record in _RedirectHandler.records] == [
        "/v1/messages"
    ]
    first = _RedirectHandler.records[0]
    assert first["headers"]["x-api-key"] == CANARY_KEY
    assert PROMPT_CANARY.encode() in first["body"]
    assert not any(
        record["path"] == "/redirected" for record in _RedirectHandler.records
    )


def test_canary_request_is_minimal_and_sensitive_material_is_not_persisted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config, database = _security_workspace(tmp_path)
    repository = SQLiteRagRepository(database)
    repository.get_or_create_manifest(
        EmbeddingManifest("fake", "snapshot-model", 3)
    )
    before = _database_snapshot(database, exclude={"rag_queries"})
    manifests_before = _table_rows(database, "embedding_manifests")
    response = _Response(RESPONSE_CANARY)
    opener = _Opener(response)
    monkeypatch.setenv("ANTHROPIC_API_KEY", CANARY_KEY)
    monkeypatch.setattr(
        AnthropicLlmProvider,
        "_open",
        lambda self, request, timeout_seconds: opener.open(
            request,
            timeout=timeout_seconds,
        ),
    )
    original_build = PromptBuilder.build

    def marked_prompt(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        return f"{original_build(self, *args, **kwargs)}\n{PROMPT_CANARY}"

    monkeypatch.setattr(PromptBuilder, "build", marked_prompt)

    assert cli.main(
        [
            "--config",
            str(config),
            "ask",
            "order_total",
            "--mode",
            "keyword",
            "--debug",
        ]
    ) == 0
    captured = capsys.readouterr()

    assert RESPONSE_CANARY in captured.out
    assert PROMPT_CANARY in captured.err
    assert CANARY_KEY not in captured.out + captured.err
    assert len(opener.requests) == 1
    request, timeout = opener.requests[0]
    payload = json.loads(request.data)
    headers = {key.lower(): value for key, value in request.header_items()}
    assert timeout == 19.0
    assert set(payload) == {"model", "max_tokens", "temperature", "messages"}
    assert payload["messages"] == [
        {
            "role": "user",
            "content": payload["messages"][0]["content"],
        }
    ]
    assert PROMPT_CANARY in payload["messages"][0]["content"]
    assert headers["x-api-key"] == CANARY_KEY
    assert "stream" not in payload
    serialized_payload = json.dumps(payload, ensure_ascii=False)
    assert str(database.resolve()) not in serialized_payload
    assert str(config.resolve()) not in serialized_payload
    assert REQUEST_ID_CANARY not in serialized_payload
    assert CANARY_KEY not in repr(request)

    after = _database_snapshot(database, exclude={"rag_queries"})
    assert after == before
    assert _table_rows(database, "embedding_manifests") == manifests_before
    with sqlite3.connect(database) as connection:
        query_rows = connection.execute("SELECT * FROM rag_queries").fetchall()
        dump = "\n".join(connection.iterdump())
    assert len(query_rows) == 1
    assert query_rows[0][-2] == "completed"
    for marker in (CANARY_KEY, PROMPT_CANARY, RESPONSE_CANARY, REQUEST_ID_CANARY):
        assert marker not in dump

    provider = cli._build_llm_provider(
        cli.load_settings(config),
        environ={"ANTHROPIC_API_KEY": CANARY_KEY},
    )
    assert CANARY_KEY not in repr(provider)
    _assert_files_do_not_contain(
        tmp_path,
        (CANARY_KEY, PROMPT_CANARY, RESPONSE_CANARY, REQUEST_ID_CANARY),
    )


@pytest.mark.parametrize(
    ("result", "expected_exit", "expected_fragment"),
    [
        (socket.timeout("timeout with secret " + CANARY_KEY), 1, "timeout"),
        (
            _Response(
                "respuesta parcial " + CANARY_KEY,
                stop_reason="max_tokens",
            ),
            1,
            "max_output_tokens",
        ),
        (_Response("eco remoto " + CANARY_KEY), 1, "respuesta invalida"),
        (KeyboardInterrupt(), 130, "interrumpida por el usuario"),
    ],
)
def test_failure_paths_do_not_leak_or_persist_sensitive_material(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    result: object,
    expected_exit: int,
    expected_fragment: str,
) -> None:
    config, database = _security_workspace(tmp_path)
    opener = _Opener(result)
    monkeypatch.setenv("ANTHROPIC_API_KEY", CANARY_KEY)
    monkeypatch.setattr(
        AnthropicLlmProvider,
        "_open",
        lambda self, request, timeout_seconds: opener.open(
            request,
            timeout=timeout_seconds,
        ),
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

    assert exit_code == expected_exit
    assert expected_fragment in captured.err
    assert CANARY_KEY not in captured.out + captured.err
    assert len(opener.requests) == 1
    with sqlite3.connect(database) as connection:
        status = connection.execute(
            "SELECT status FROM rag_queries ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        dump = "\n".join(connection.iterdump())
    assert status == "error"
    assert CANARY_KEY not in dump
    assert REQUEST_ID_CANARY not in dump
    _assert_files_do_not_contain(tmp_path, (CANARY_KEY, REQUEST_ID_CANARY))


def test_http_error_body_headers_and_reason_never_cross_safe_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config, database = _security_workspace(tmp_path)
    headers = Message()
    headers["request-id"] = REQUEST_ID_CANARY
    headers["x-secret"] = CANARY_KEY
    error = urllib.error.HTTPError(
        anthropic.ANTHROPIC_MESSAGES_URL,
        529,
        "remote reason " + CANARY_KEY,
        headers,
        io.BytesIO(("remote body " + CANARY_KEY).encode()),
    )
    opener = _Opener(error)
    monkeypatch.setenv("ANTHROPIC_API_KEY", CANARY_KEY)
    monkeypatch.setattr(
        AnthropicLlmProvider,
        "_open",
        lambda self, request, timeout_seconds: opener.open(
            request,
            timeout=timeout_seconds,
        ),
    )

    assert cli.main(
        [
            "--config",
            str(config),
            "ask",
            "order_total",
            "--mode",
            "keyword",
        ]
    ) == 1
    captured = capsys.readouterr()
    combined = captured.out + captured.err

    assert "sobrecargado" in captured.err
    assert REQUEST_ID_CANARY in captured.err
    assert CANARY_KEY not in combined
    assert "remote reason" not in combined
    assert "remote body" not in combined
    assert "x-secret" not in combined
    with sqlite3.connect(database) as connection:
        dump = "\n".join(connection.iterdump())
    assert CANARY_KEY not in dump
    assert REQUEST_ID_CANARY not in dump
    _assert_files_do_not_contain(tmp_path, (CANARY_KEY, REQUEST_ID_CANARY))


def _security_workspace(tmp_path: Path) -> tuple[Path, Path]:
    (tmp_path / "logs").mkdir()
    database = tmp_path / "barbarion.db"
    initialize_database(database)
    seed_chunks(database)
    config = tmp_path / "barbarion.toml"
    config.write_text(
        """database_path = "barbarion.db"
logs_dir = "logs"
log_level = "DEBUG"

[llm]
provider = "anthropic"
model = "claude-security-test"
timeout_seconds = 19.0
temperature = 0.0
max_output_tokens = 2048
""",
        encoding="utf-8",
    )
    return config, database


def _database_snapshot(
    path: Path,
    *,
    exclude: set[str],
) -> dict[str, tuple[tuple[object, ...], ...]]:
    with sqlite3.connect(path) as connection:
        tables = [
            row[0]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            )
            if row[0] not in exclude
        ]
        return {
            table: tuple(
                tuple(row)
                for row in connection.execute(
                    f'SELECT * FROM "{table}" ORDER BY rowid'
                ).fetchall()
            )
            for table in tables
        }


def _table_rows(path: Path, table: str) -> tuple[tuple[object, ...], ...]:
    with sqlite3.connect(path) as connection:
        return tuple(
            tuple(row)
            for row in connection.execute(
                f'SELECT * FROM "{table}" ORDER BY rowid'
            ).fetchall()
        )


def _assert_files_do_not_contain(root: Path, markers: tuple[str, ...]) -> None:
    encoded = tuple(marker.encode("utf-8") for marker in markers)
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        content = path.read_bytes()
        for marker in encoded:
            assert marker not in content, f"material sensible persistido en {path}"
