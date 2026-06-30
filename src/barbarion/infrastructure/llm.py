"""Proveedor local de LLM para RAG."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from barbarion.domain.rag import LlmProviderError


@dataclass(frozen=True, slots=True)
class OllamaLlmProvider:
    """Adaptador local para generacion con Ollama."""

    base_url: str
    model: str
    temperature: float
    provider: str = "ollama"
    _opener: object | None = field(default=None, repr=False, compare=False)

    def generate(self, *, prompt: str, timeout_seconds: float) -> str:
        """Genera texto llamando al endpoint local de Ollama."""
        payload = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": self.temperature},
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            if self._opener is None:
                with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                    raw_body = response.read()
            else:
                response = self._opener.open(request, timeout=timeout_seconds)  # type: ignore[attr-defined]
                with response:
                    raw_body = response.read()
        except (TimeoutError, socket.timeout) as error:
            raise LlmProviderError(
                "OLLAMA_LLM_TIMEOUT: Ollama no respondio dentro del timeout."
            ) from error
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise LlmProviderError(
                    "OLLAMA_LLM_MODEL_NOT_FOUND: modelo LLM no disponible en Ollama."
                ) from error
            raise LlmProviderError(
                "OLLAMA_LLM_HTTP_ERROR: Ollama devolvio un error HTTP."
            ) from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError | socket.timeout):
                raise LlmProviderError(
                    "OLLAMA_LLM_TIMEOUT: Ollama no respondio dentro del timeout."
                ) from error
            raise LlmProviderError(
                "OLLAMA_LLM_UNAVAILABLE: no se pudo contactar Ollama local."
            ) from error

        try:
            body = json.loads(raw_body.decode("utf-8"))
            answer = body["response"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
            raise LlmProviderError(
                "OLLAMA_LLM_RESPONSE_INVALID: Ollama devolvio una respuesta invalida."
            ) from error
        if not isinstance(answer, str) or not answer.strip():
            raise LlmProviderError(
                "OLLAMA_LLM_RESPONSE_INVALID: respuesta vacia o invalida."
            )
        return answer
