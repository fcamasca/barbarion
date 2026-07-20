"""Integracion HTTP del proveedor Ollama construido por ``ask``."""

from __future__ import annotations

import json
import threading
import urllib.request
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from barbarion import cli
from barbarion.config import load_settings
from barbarion.infrastructure import llm as llm_module


class OllamaGenerateHandler(BaseHTTPRequestHandler):
    """Captura una generacion y devuelve una respuesta Ollama completa."""

    payloads: list[dict[str, object]] = []

    def do_POST(self) -> None:
        """Atiende exclusivamente ``POST /api/generate``."""
        if self.path != "/api/generate":
            self.send_error(404)
            return
        content_length = int(self.headers["Content-Length"])
        body = self.rfile.read(content_length)
        self.payloads.append(json.loads(body.decode("utf-8")))
        response = json.dumps({"response": "Respuesta [F1]"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format: str, *args: object) -> None:
        """Silencia la salida del servidor local durante la prueba."""
        del format, args


@pytest.fixture
def ollama_generate_url() -> Iterator[str]:
    """Expone un endpoint Ollama capturador y restablece su estado."""
    OllamaGenerateHandler.payloads = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), OllamaGenerateHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_ask_provider_sends_effective_llm_settings_over_http(
    tmp_path: Path,
    ollama_generate_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifica el payload y timeout de la instancia que construye ``ask``."""
    config = tmp_path / "barbarion.toml"
    config.write_text(
        "\n".join(
            (
                f'ollama_url = "{ollama_generate_url}"',
                '[llm]',
                'model = "qwen3:8b"',
                'timeout_seconds = 3.5',
                'temperature = 0.1',
                'think = false',
            )
        ),
        encoding="utf-8",
    )
    settings = load_settings(config, environ={}, cwd=tmp_path)
    service = cli._build_ask_service(settings)
    real_urlopen = urllib.request.urlopen
    observed_timeouts: list[float] = []

    def recording_urlopen(request, *, timeout):  # noqa: ANN001, ANN201
        """Registra el timeout y conserva la llamada HTTP real."""
        observed_timeouts.append(timeout)
        return real_urlopen(request, timeout=timeout)

    monkeypatch.setattr(llm_module.urllib.request, "urlopen", recording_urlopen)

    answer = service.llm_provider.generate(
        prompt="Pregunta minima con acento: generacion.",
        timeout_seconds=settings.llm.timeout_seconds,
    )

    assert answer == "Respuesta [F1]"
    assert observed_timeouts == [3.5]
    assert OllamaGenerateHandler.payloads == [
        {
            "model": "qwen3:8b",
            "prompt": "Pregunta minima con acento: generacion.",
            "stream": False,
            "options": {"temperature": 0.1},
            "think": False,
        }
    ]
