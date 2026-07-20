"""Modelos puros para administrar LLM locales mediante Ollama."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class LocalModelErrorCode(StrEnum):
    """Codigos estables de errores del proveedor de modelos locales."""

    UNAVAILABLE = "OLLAMA_UNAVAILABLE"
    TIMEOUT = "OLLAMA_TIMEOUT"
    MODEL_NOT_FOUND = "MODEL_NOT_INSTALLED"
    INVALID_RESPONSE = "MODEL_RESPONSE_INVALID"
    OPERATION_FAILED = "MODEL_OPERATION_FAILED"
    INTERRUPTED = "MODEL_OPERATION_INTERRUPTED"
    NOT_GENERATION_READY = "MODEL_NOT_GENERATION_READY"


class LocalModelProviderError(RuntimeError):
    """Error tipado y presentable producido por el proveedor local."""

    def __init__(self, code: LocalModelErrorCode, detail: str) -> None:
        normalized_detail = _required_text(detail, "detail")
        self.code = code
        self.detail = normalized_detail
        super().__init__(f"{code.value}: {normalized_detail}")


@dataclass(frozen=True, slots=True)
class LocalModel:
    """Modelo instalado reportado por Ollama."""

    name: str
    size_bytes: int | None = None
    modified_at: str | None = None
    digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required_text(self.name, "name"))
        _optional_non_negative(self.size_bytes, "size_bytes")
        _optional_text(self.modified_at, "modified_at")
        _optional_text(self.digest, "digest")


@dataclass(frozen=True, slots=True)
class LocalModelDetails:
    """Metadata acotada y generica disponible para un modelo local."""

    model: LocalModel
    format: str | None = None
    family: str | None = None
    parameter_size: str | None = None
    quantization_level: str | None = None
    capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _optional_text(self.format, "format")
        _optional_text(self.family, "family")
        _optional_text(self.parameter_size, "parameter_size")
        _optional_text(self.quantization_level, "quantization_level")
        normalized = tuple(
            _required_text(value, "capability") for value in self.capabilities
        )
        object.__setattr__(self, "capabilities", normalized)


@dataclass(frozen=True, slots=True)
class PullProgress:
    """Evento de progreso normalizado de una instalacion."""

    status: str
    completed: int | None = None
    total: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _required_text(self.status, "status"))
        _optional_non_negative(self.completed, "completed")
        _optional_non_negative(self.total, "total")

    @property
    def percent(self) -> float | None:
        """Calcula porcentaje solo cuando Ollama informa un total util."""
        if self.completed is None or self.total is None or self.total <= 0:
            return None
        return min(100.0, (self.completed / self.total) * 100.0)


@dataclass(frozen=True, slots=True)
class PullResult:
    """Resultado final de solicitar un modelo a Ollama."""

    model: str
    status: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "model", _required_text(self.model, "model"))
        object.__setattr__(self, "status", _required_text(self.status, "status"))


@dataclass(frozen=True, slots=True)
class ModelGenerationRequest:
    """Solicitud local de generacion con opciones minimas y explicitas."""

    model: str
    prompt: str
    timeout_seconds: float
    temperature: float = 0.0
    max_output_tokens: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "model", _required_text(self.model, "model"))
        object.__setattr__(self, "prompt", _required_text(self.prompt, "prompt"))
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds debe ser mayor que cero.")
        if self.temperature < 0:
            raise ValueError("temperature no puede ser negativa.")
        if self.max_output_tokens is not None and self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens debe ser mayor que cero.")


@dataclass(frozen=True, slots=True)
class ModelGenerationTelemetry:
    """Telemetria opcional devuelta por Ollama, sin fabricar valores."""

    total_duration_ns: int | None = None
    load_duration_ns: int | None = None
    prompt_eval_duration_ns: int | None = None
    eval_duration_ns: int | None = None
    prompt_eval_count: int | None = None
    eval_count: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "total_duration_ns",
            "load_duration_ns",
            "prompt_eval_duration_ns",
            "eval_duration_ns",
            "prompt_eval_count",
            "eval_count",
        ):
            _optional_non_negative(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class ModelGenerationResult:
    """Texto generado y telemetria disponible para benchmark."""

    response: str
    telemetry: ModelGenerationTelemetry = field(
        default_factory=ModelGenerationTelemetry
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "response",
            _required_text(self.response, "response"),
        )


def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} debe ser texto no vacio.")
    return value.strip()


def _optional_text(value: str | None, name: str) -> None:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise ValueError(f"{name} debe ser null o texto no vacio.")


def _optional_non_negative(value: int | None, name: str) -> None:
    if value is not None and (not isinstance(value, int) or value < 0):
        raise ValueError(f"{name} debe ser null o un entero no negativo.")
