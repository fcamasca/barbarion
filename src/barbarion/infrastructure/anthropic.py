"""Adaptador HTTP directo para Anthropic Messages API."""

from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from barbarion.domain.rag import LlmProviderError

ANTHROPIC_API_KEY_ENV_VAR = "ANTHROPIC_API_KEY"
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"

_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
_SAFE_HEADER_VALUE_PATTERN = re.compile(r"[\x21-\x7e]+\Z")


class _RejectRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Impide reenviar credenciales o prompts a destinos redirigidos."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        del req, fp, code, msg, headers, newurl
        return None


@dataclass(frozen=True, slots=True)
class AnthropicLlmProvider:
    """Genera texto con la operacion no streaming de Messages API."""

    model: str
    temperature: float
    max_output_tokens: int
    _api_key_resolver: Callable[[], str | None] = field(
        repr=False,
        compare=False,
    )
    provider: str = "anthropic"
    _opener: object | None = field(default=None, repr=False, compare=False)

    def generate(self, *, prompt: str, timeout_seconds: float) -> str:
        """Realiza exactamente una solicitud y devuelve su contenido textual."""
        api_key = self._resolve_api_key()
        payload = json.dumps(
            {
                "model": self.model,
                "max_tokens": self.max_output_tokens,
                "temperature": self.temperature,
                "messages": [{"role": "user", "content": prompt}],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            ANTHROPIC_MESSAGES_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Api-Key": api_key,
                "Anthropic-Version": ANTHROPIC_API_VERSION,
            },
            method="POST",
        )

        try:
            response = self._open(request, timeout_seconds)
            with response:
                raw_body = response.read()
                request_id = _safe_request_id(
                    getattr(response, "headers", None)
                )
        except (TimeoutError, socket.timeout):
            raise _provider_error(
                "ANTHROPIC_TIMEOUT",
                "Anthropic no respondio dentro del timeout.",
            ) from None
        except urllib.error.HTTPError as error:
            request_id = _safe_request_id(error.headers)
            error.close()
            raise _http_error(error.code, request_id) from None
        except urllib.error.URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                raise _provider_error(
                    "ANTHROPIC_TIMEOUT",
                    "Anthropic no respondio dentro del timeout.",
                ) from None
            raise _provider_error(
                "ANTHROPIC_UNAVAILABLE",
                "No se pudo contactar el servicio Anthropic.",
            ) from None

        return _parse_response(raw_body, request_id)

    def _resolve_api_key(self) -> str:
        """Obtiene y valida defensivamente la credencial al generar."""
        api_key = self._api_key_resolver()
        if api_key is None or not api_key.strip():
            raise _provider_error(
                "ANTHROPIC_API_KEY_MISSING",
                "Define ANTHROPIC_API_KEY en el entorno antes de solicitar "
                "generacion Anthropic.",
            )
        normalized = api_key.strip()
        if _SAFE_HEADER_VALUE_PATTERN.fullmatch(normalized) is None:
            raise _provider_error(
                "ANTHROPIC_AUTHENTICATION_ERROR",
                "ANTHROPIC_API_KEY contiene un valor no valido.",
            )
        return normalized

    def _open(
        self,
        request: urllib.request.Request,
        timeout_seconds: float,
    ):
        """Abre una sola solicitud con redirects deshabilitados."""
        if self._opener is not None:
            return self._opener.open(  # type: ignore[attr-defined]
                request,
                timeout=timeout_seconds,
            )
        opener = urllib.request.build_opener(_RejectRedirectHandler())
        return opener.open(request, timeout=timeout_seconds)


def _parse_response(raw_body: bytes, request_id: str | None) -> str:
    """Extrae en orden los bloques text de una respuesta Messages API."""
    try:
        body = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _provider_error(
            "ANTHROPIC_RESPONSE_INVALID",
            "Anthropic devolvio una respuesta invalida.",
            request_id,
        ) from None

    if not isinstance(body, dict):
        raise _provider_error(
            "ANTHROPIC_RESPONSE_INVALID",
            "Anthropic devolvio una respuesta invalida.",
            request_id,
        )
    if body.get("stop_reason") == "max_tokens":
        raise _provider_error(
            "ANTHROPIC_LLM_TRUNCATED",
            "Anthropic alcanzo el limite max_output_tokens.",
            request_id,
        )

    content = body.get("content")
    if not isinstance(content, list):
        raise _provider_error(
            "ANTHROPIC_RESPONSE_INVALID",
            "Anthropic devolvio contenido invalido.",
            request_id,
        )

    text_blocks: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            raise _provider_error(
                "ANTHROPIC_RESPONSE_INVALID",
                "Anthropic devolvio un bloque de contenido invalido.",
                request_id,
            )
        if block.get("type") != "text":
            continue
        text = block.get("text")
        if not isinstance(text, str):
            raise _provider_error(
                "ANTHROPIC_RESPONSE_INVALID",
                "Anthropic devolvio un bloque de texto invalido.",
                request_id,
            )
        text_blocks.append(text)

    answer = "".join(text_blocks)
    if not answer.strip():
        raise _provider_error(
            "ANTHROPIC_RESPONSE_INVALID",
            "Anthropic devolvio una respuesta textual vacia.",
            request_id,
        )
    return answer


def _http_error(status: int, request_id: str | None) -> LlmProviderError:
    """Normaliza estados HTTP sin incorporar headers ni cuerpos remotos."""
    mappings = {
        400: (
            "ANTHROPIC_REQUEST_INVALID",
            "Anthropic rechazo la solicitud.",
        ),
        401: (
            "ANTHROPIC_AUTHENTICATION_ERROR",
            "Anthropic rechazo la autenticacion.",
        ),
        402: (
            "ANTHROPIC_BILLING_ERROR",
            "La cuenta Anthropic no permite procesar la solicitud.",
        ),
        403: (
            "ANTHROPIC_PERMISSION_ERROR",
            "La credencial no tiene permiso para esta solicitud o modelo.",
        ),
        404: (
            "ANTHROPIC_MODEL_NOT_FOUND",
            "El modelo Anthropic configurado no esta disponible.",
        ),
        409: (
            "ANTHROPIC_REQUEST_INVALID",
            "Anthropic informo un conflicto para la solicitud.",
        ),
        413: (
            "ANTHROPIC_REQUEST_TOO_LARGE",
            "La solicitud excede el tamano admitido por Anthropic.",
        ),
        429: (
            "ANTHROPIC_RATE_LIMITED",
            "Anthropic aplico un limite de solicitudes; reintenta manualmente.",
        ),
        500: (
            "ANTHROPIC_HTTP_ERROR",
            "Anthropic devolvio un error interno.",
        ),
        504: (
            "ANTHROPIC_TIMEOUT",
            "Anthropic no completo la solicitud dentro del timeout remoto.",
        ),
        529: (
            "ANTHROPIC_OVERLOADED",
            "Anthropic esta temporalmente sobrecargado.",
        ),
    }
    code, detail = mappings.get(
        status,
        (
            "ANTHROPIC_HTTP_ERROR",
            f"Anthropic devolvio un error HTTP ({status}).",
        ),
    )
    return _provider_error(code, detail, request_id)


def _safe_request_id(headers: object) -> str | None:
    """Conserva solo identificadores remotos cortos y ASCII."""
    if not isinstance(headers, Mapping) and not hasattr(headers, "get"):
        return None
    try:
        value = headers.get("request-id")  # type: ignore[union-attr]
    except (AttributeError, TypeError):
        return None
    if not isinstance(value, str):
        return None
    if _REQUEST_ID_PATTERN.fullmatch(value) is None:
        return None
    return value


def _provider_error(
    code: str,
    detail: str,
    request_id: str | None = None,
) -> LlmProviderError:
    """Crea un error estable que nunca incorpora material remoto libre."""
    suffix = f" request-id={request_id}." if request_id is not None else ""
    return LlmProviderError(f"{code}: {detail}{suffix}")
