"""Cliente HTTP pequeno para administrar modelos de una instancia Ollama local."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from barbarion.domain.local_models import (
    LocalModel,
    LocalModelDetails,
    LocalModelErrorCode,
    LocalModelProviderError,
    ModelGenerationRequest,
    ModelGenerationResult,
    ModelGenerationTelemetry,
    PullProgress,
    PullResult,
)


@dataclass(frozen=True, slots=True)
class OllamaModelClient:
    """Implementa administracion de modelos sin SDK ni comandos shell."""

    base_url: str
    _opener: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        normalized = self.base_url.strip().rstrip("/")
        if not normalized:
            raise ValueError("base_url debe ser texto no vacio.")
        object.__setattr__(self, "base_url", normalized)

    def list_models(self, *, timeout_seconds: float) -> tuple[LocalModel, ...]:
        """Consulta `/api/tags` y tolera metadata opcional o desconocida."""
        payload = self._request_json("/api/tags", timeout_seconds=timeout_seconds)
        models = payload.get("models")
        if not isinstance(models, list):
            raise _invalid_response("Ollama no devolvio una lista de modelos.")
        parsed: list[LocalModel] = []
        for item in models:
            if not isinstance(item, dict):
                raise _invalid_response("Ollama devolvio un modelo invalido.")
            name = _optional_str(item.get("name")) or _optional_str(item.get("model"))
            if name is None:
                raise _invalid_response("Ollama devolvio un modelo sin nombre.")
            parsed.append(
                LocalModel(
                    name=name,
                    size_bytes=_optional_int(item.get("size")),
                    modified_at=_optional_str(item.get("modified_at")),
                    digest=_optional_str(item.get("digest")),
                )
            )
        return tuple(parsed)

    def server_version(self, *, timeout_seconds: float) -> str:
        """Consulta `/api/version` sin conservar campos adicionales."""
        payload = self._request_json("/api/version", timeout_seconds=timeout_seconds)
        version = _optional_str(payload.get("version"))
        if version is None:
            raise _invalid_response("Ollama no devolvio una version valida.")
        return version[:128]

    def show_model(
        self,
        name: str,
        *,
        timeout_seconds: float,
    ) -> LocalModelDetails:
        """Consulta `/api/show` y conserva solo metadata generica acotada."""
        model_name = _required_name(name)
        payload = self._request_json(
            "/api/show",
            timeout_seconds=timeout_seconds,
            body={"model": model_name},
        )
        details = payload.get("details")
        if details is None:
            details = {}
        if not isinstance(details, dict):
            raise _invalid_response("Ollama devolvio detalles invalidos.")
        capabilities_raw = payload.get("capabilities", ())
        capabilities = (
            tuple(value for value in capabilities_raw if isinstance(value, str))
            if isinstance(capabilities_raw, list)
            else ()
        )
        return LocalModelDetails(
            model=LocalModel(
                name=model_name,
                modified_at=_optional_str(payload.get("modified_at")),
            ),
            format=_optional_str(details.get("format")),
            family=_optional_str(details.get("family")),
            parameter_size=_optional_str(details.get("parameter_size")),
            quantization_level=_optional_str(details.get("quantization_level")),
            capabilities=capabilities,
        )

    def pull_model(
        self,
        name: str,
        *,
        timeout_seconds: float,
        on_progress: Callable[[PullProgress], None] | None = None,
    ) -> PullResult:
        """Consume el stream NDJSON de `/api/pull` sin asumir sus capas."""
        model_name = _required_name(name)
        request = self._build_request(
            "/api/pull",
            body={"model": model_name, "stream": True},
        )
        response = self._open(request, timeout_seconds)
        last_status: str | None = None
        try:
            with response:
                while True:
                    line = response.readline()
                    if not line:
                        break
                    event = _decode_object(line)
                    error = _optional_str(event.get("error"))
                    if error is not None:
                        raise LocalModelProviderError(
                            LocalModelErrorCode.OPERATION_FAILED,
                            error,
                        )
                    status = _optional_str(event.get("status"))
                    if status is None:
                        raise _invalid_response(
                            "Ollama devolvio progreso sin estado."
                        )
                    last_status = status
                    progress = PullProgress(
                        status=status,
                        completed=_optional_int(event.get("completed")),
                        total=_optional_int(event.get("total")),
                    )
                    if on_progress is not None:
                        on_progress(progress)
        except KeyboardInterrupt as error:
            raise LocalModelProviderError(
                LocalModelErrorCode.INTERRUPTED,
                "Barbarion dejo de esperar; Ollama podria continuar localmente.",
            ) from error
        except (TimeoutError, socket.timeout) as error:
            raise LocalModelProviderError(
                LocalModelErrorCode.TIMEOUT,
                "Ollama no envio progreso dentro del timeout.",
            ) from error
        except OSError as error:
            raise LocalModelProviderError(
                LocalModelErrorCode.OPERATION_FAILED,
                "Se interrumpio la lectura del progreso de Ollama.",
            ) from error
        if last_status is None:
            raise _invalid_response("Ollama devolvio un stream de pull vacio.")
        return PullResult(model=model_name, status=last_status)

    def generate_detailed(
        self,
        request: ModelGenerationRequest,
    ) -> ModelGenerationResult:
        """Genera texto y normaliza telemetria cuando Ollama la informa."""
        options: dict[str, object] = {"temperature": request.temperature}
        if request.max_output_tokens is not None:
            options["num_predict"] = request.max_output_tokens
        payload = self._request_json(
            "/api/generate",
            timeout_seconds=request.timeout_seconds,
            body={
                "model": request.model,
                "prompt": request.prompt,
                "stream": False,
                "options": options,
            },
        )
        response = _optional_str(payload.get("response"))
        if response is None:
            raise _invalid_response("Ollama devolvio una respuesta vacia.")
        return ModelGenerationResult(
            response=response,
            telemetry=ModelGenerationTelemetry(
                total_duration_ns=_optional_int(payload.get("total_duration")),
                load_duration_ns=_optional_int(payload.get("load_duration")),
                prompt_eval_duration_ns=_optional_int(
                    payload.get("prompt_eval_duration")
                ),
                eval_duration_ns=_optional_int(payload.get("eval_duration")),
                prompt_eval_count=_optional_int(payload.get("prompt_eval_count")),
                eval_count=_optional_int(payload.get("eval_count")),
            ),
        )

    def _request_json(
        self,
        path: str,
        *,
        timeout_seconds: float,
        body: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        request = self._build_request(path, body=body)
        response = self._open(request, timeout_seconds)
        with response:
            return _decode_object(response.read())

    def _build_request(
        self,
        path: str,
        *,
        body: dict[str, object] | None = None,
    ) -> urllib.request.Request:
        data = None
        method = "GET"
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(
                body,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            method = "POST"
            headers["Content-Type"] = "application/json"
        return urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )

    def _open(self, request: urllib.request.Request, timeout_seconds: float):
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds debe ser mayor que cero.")
        try:
            if self._opener is None:
                return urllib.request.urlopen(request, timeout=timeout_seconds)
            return self._opener.open(request, timeout=timeout_seconds)  # type: ignore[attr-defined]
        except KeyboardInterrupt as error:
            raise LocalModelProviderError(
                LocalModelErrorCode.INTERRUPTED,
                "Barbarion dejo de esperar; Ollama podria continuar localmente.",
            ) from error
        except (TimeoutError, socket.timeout) as error:
            raise LocalModelProviderError(
                LocalModelErrorCode.TIMEOUT,
                "Ollama no respondio dentro del timeout.",
            ) from error
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise LocalModelProviderError(
                    LocalModelErrorCode.MODEL_NOT_FOUND,
                    "El modelo no esta instalado o no existe en Ollama.",
                ) from error
            raise LocalModelProviderError(
                LocalModelErrorCode.OPERATION_FAILED,
                f"Ollama devolvio HTTP {error.code}.",
            ) from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError | socket.timeout):
                code = LocalModelErrorCode.TIMEOUT
                detail = "Ollama no respondio dentro del timeout."
            else:
                code = LocalModelErrorCode.UNAVAILABLE
                detail = "No se pudo contactar la instancia Ollama local."
            raise LocalModelProviderError(code, detail) from error


def _decode_object(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _invalid_response("Ollama devolvio JSON invalido.") from error
    if not isinstance(payload, dict):
        raise _invalid_response("Ollama devolvio un payload invalido.")
    return payload


def _required_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("name debe ser texto no vacio.")
    return value.strip()


def _optional_str(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _optional_int(value: object) -> int | None:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else None
    )


def _invalid_response(detail: str) -> LocalModelProviderError:
    return LocalModelProviderError(LocalModelErrorCode.INVALID_RESPONSE, detail)
