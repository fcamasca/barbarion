"""Adaptador HTTP directo para Anthropic Messages API."""

from __future__ import annotations

import json
import logging
import re
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

from barbarion.domain.rag import LlmProviderError

ANTHROPIC_API_KEY_ENV_VAR = "ANTHROPIC_API_KEY"
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"

_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
_SAFE_HEADER_VALUE_PATTERN = re.compile(r"[\x21-\x7e]+\Z")
_ERROR_CODE_PATTERN = re.compile(r"ANTHROPIC_[A-Z_]+\Z")
_LOGGER = logging.getLogger("barbarion")


@dataclass(frozen=True, slots=True)
class AnthropicUsage:
    """Uso agregado de una o mas solicitudes Anthropic de la misma consulta."""

    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    elapsed_seconds: float
    request_count: int


@dataclass(frozen=True, slots=True)
class _ParsedMessage:
    """Texto y uso opcional extraidos de una respuesta remota."""

    text: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None


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
    _clock: Callable[[], float] = field(
        default=time.monotonic,
        repr=False,
        compare=False,
    )
    _usage_records: list[AnthropicUsage] = field(
        default_factory=list,
        repr=False,
        compare=False,
    )

    def generate(self, *, prompt: str, timeout_seconds: float) -> str:
        """Genera texto y conserva telemetria segura fuera del puerto publico."""
        started = self._clock()
        try:
            parsed = self._generate_once(
                prompt=prompt,
                timeout_seconds=timeout_seconds,
            )
        except KeyboardInterrupt:
            _LOGGER.warning(
                "anthropic_llm_finished provider=anthropic model=%s "
                "duration_ms=%d result=interrupted",
                self.model,
                _elapsed_ms(started, self._clock),
            )
            raise
        except LlmProviderError as error:
            _LOGGER.error(
                "anthropic_llm_finished provider=anthropic model=%s "
                "duration_ms=%d result=error error_code=%s",
                self.model,
                _elapsed_ms(started, self._clock),
                _safe_error_code(error),
            )
            raise

        elapsed_seconds = max(0.0, self._clock() - started)
        usage = AnthropicUsage(
            input_tokens=parsed.input_tokens,
            output_tokens=parsed.output_tokens,
            total_tokens=parsed.total_tokens,
            elapsed_seconds=elapsed_seconds,
            request_count=1,
        )
        self._usage_records.append(usage)
        _LOGGER.info(
            "anthropic_llm_finished provider=anthropic model=%s "
            "duration_ms=%d result=completed input_tokens=%s "
            "output_tokens=%s total_tokens=%s",
            self.model,
            round(elapsed_seconds * 1000),
            _metric_value(usage.input_tokens),
            _metric_value(usage.output_tokens),
            _metric_value(usage.total_tokens),
        )
        return parsed.text

    def usage_snapshot(self) -> AnthropicUsage | None:
        """Devuelve uso agregado sin exponer prompts, respuestas ni headers."""
        if not self._usage_records:
            return None
        return AnthropicUsage(
            input_tokens=_sum_known(
                record.input_tokens for record in self._usage_records
            ),
            output_tokens=_sum_known(
                record.output_tokens for record in self._usage_records
            ),
            total_tokens=_sum_known(
                record.total_tokens for record in self._usage_records
            ),
            elapsed_seconds=sum(
                record.elapsed_seconds for record in self._usage_records
            ),
            request_count=len(self._usage_records),
        )

    def _generate_once(
        self,
        *,
        prompt: str,
        timeout_seconds: float,
    ) -> _ParsedMessage:
        """Realiza exactamente una solicitud Messages API."""
        api_key = self._resolve_api_key()
        if api_key in prompt:
            raise _provider_error(
                "ANTHROPIC_REQUEST_INVALID",
                "La solicitud contiene la credencial Anthropic y fue bloqueada.",
            )
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

        parsed = _parse_response(raw_body, request_id)
        if api_key in parsed.text:
            raise _provider_error(
                "ANTHROPIC_RESPONSE_INVALID",
                "Anthropic devolvio contenido que coincide con la credencial; "
                "la respuesta fue descartada.",
                request_id,
            )
        return parsed

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


def _parse_response(raw_body: bytes, request_id: str | None) -> _ParsedMessage:
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
    input_tokens, output_tokens, total_tokens = _parse_usage(body.get("usage"))
    return _ParsedMessage(
        text=answer,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def _parse_usage(value: object) -> tuple[int | None, int | None, int | None]:
    """Lee contadores opcionales sin invalidar una respuesta textual util."""
    if not isinstance(value, dict):
        return None, None, None
    input_tokens = _optional_token_count(value.get("input_tokens"))
    output_tokens = _optional_token_count(value.get("output_tokens"))
    total_tokens = _optional_token_count(value.get("total_tokens"))
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return input_tokens, output_tokens, total_tokens


def _optional_token_count(value: object) -> int | None:
    """Acepta solo enteros no negativos como telemetria de uso."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _sum_known(values: Iterable[int | None]) -> int | None:
    """Suma contadores presentes y conserva ausencia total como `None`."""
    known = [value for value in values if value is not None]
    return sum(known) if known else None


def _elapsed_ms(started: float, clock: Callable[[], float]) -> int:
    """Calcula duracion monotona no negativa para observabilidad."""
    return round(max(0.0, clock() - started) * 1000)


def _metric_value(value: int | None) -> str:
    """Formatea ausencia de telemetria sin inventar ceros."""
    return "unavailable" if value is None else str(value)


def _safe_error_code(error: LlmProviderError) -> str:
    """Extrae solo el prefijo tecnico estable del error normalizado."""
    candidate = str(error).partition(":")[0]
    if _ERROR_CODE_PATTERN.fullmatch(candidate) is None:
        return "ANTHROPIC_UNKNOWN_ERROR"
    return candidate


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
    suffix = f" [request-id={request_id}]" if request_id is not None else ""
    return LlmProviderError(f"{code}: {detail}{suffix}")
