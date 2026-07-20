"""Pruebas de estados separados en validacion de modelos."""

from collections.abc import Iterator

import pytest

from barbarion.application.local_models import (
    VALIDATION_MARKER,
    VALIDATION_PROMPT,
    ValidateModelService,
)
from barbarion.domain.local_models import (
    LocalModel,
    LocalModelErrorCode,
    LocalModelProviderError,
    ModelGenerationResult,
)


class FakeValidationProvider:
    def __init__(
        self,
        *,
        models: tuple[LocalModel, ...] = (),
        response: str = VALIDATION_MARKER,
        list_error: LocalModelProviderError | None = None,
        generation_error: LocalModelProviderError | None = None,
    ) -> None:
        self.models = models
        self.response = response
        self.list_error = list_error
        self.generation_error = generation_error
        self.calls: list[tuple[object, ...]] = []
        self.generation_request = None

    def list_models(self, *, timeout_seconds: float):  # noqa: ANN201
        self.calls.append(("list", timeout_seconds))
        if self.list_error is not None:
            raise self.list_error
        return self.models

    def generate_detailed(self, request):  # noqa: ANN001, ANN201
        self.calls.append(("generate", request.model, request.timeout_seconds))
        self.generation_request = request
        if self.generation_error is not None:
            raise self.generation_error
        return ModelGenerationResult(self.response)


class TimeoutOnceValidationProvider(FakeValidationProvider):
    """Simula la carga en frio que termina despues del primer timeout."""

    def generate_detailed(self, request):  # noqa: ANN001, ANN201
        """Falla una vez y responde normalmente en el reintento."""
        self.calls.append(("generate", request.model, request.timeout_seconds))
        self.generation_request = request
        if sum(call[0] == "generate" for call in self.calls) == 1:
            raise LocalModelProviderError(LocalModelErrorCode.TIMEOUT, "timeout")
        return ModelGenerationResult(self.response)


def _clock(values: tuple[float, ...]):  # noqa: ANN202
    iterator: Iterator[float] = iter(values)
    return lambda: next(iterator)


def test_validation_ready_keeps_four_states_explicit() -> None:
    provider = FakeValidationProvider(models=(LocalModel("modelo:tag"),))
    service = ValidateModelService(
        provider,
        "modelo:tag",
        clock=_clock((10.0, 10.125)),
    )

    result = service.run(None, timeout_seconds=12)

    assert result.active is True
    assert result.available is True
    assert result.installed is True
    assert result.generation_ready is True
    assert result.benchmark_eligible is True
    assert result.duration_ms == 125
    assert result.diagnostic_code is None
    request = provider.generation_request
    assert request.prompt == VALIDATION_PROMPT
    assert request.prompt == (
        "Devuelve exactamente este texto y nada mas: "
        "BARBARION_MODEL_READY"
    )
    assert request.temperature == 0.0
    assert request.timeout_seconds == 12
    assert request.max_output_tokens == 16


def test_validation_prompt_contains_only_instruction_and_marker() -> None:
    assert VALIDATION_MARKER in VALIDATION_PROMPT
    instruction = VALIDATION_PROMPT.replace(VALIDATION_MARKER, "")
    assert "barbarion" not in instruction.lower()


def test_unavailable_is_not_installed_ready_or_eligible() -> None:
    provider = FakeValidationProvider(
        list_error=LocalModelProviderError(
            LocalModelErrorCode.UNAVAILABLE,
            "Ollama ausente",
        )
    )
    result = ValidateModelService(
        provider,
        "activo",
        clock=_clock((1.0, 1.1)),
    ).run(None, timeout_seconds=2)

    assert result.available is False
    assert result.installed is False
    assert result.generation_ready is False
    assert result.benchmark_eligible is False
    assert result.diagnostic_code == "OLLAMA_UNAVAILABLE"
    assert provider.calls == [("list", 2)]


def test_available_missing_model_does_not_generate() -> None:
    provider = FakeValidationProvider(models=(LocalModel("otro"),))

    result = ValidateModelService(
        provider,
        "activo",
        clock=_clock((1.0, 1.01)),
    ).run("missing", timeout_seconds=3)

    assert result.available is True
    assert result.installed is False
    assert result.generation_ready is False
    assert result.benchmark_eligible is False
    assert result.diagnostic_code == "MODEL_NOT_INSTALLED"
    assert provider.calls == [("list", 3)]


def test_installed_wrong_marker_is_not_generation_ready() -> None:
    provider = FakeValidationProvider(
        models=(LocalModel("modelo"),),
        response=f"{VALIDATION_MARKER} texto adicional",
    )

    result = ValidateModelService(
        provider,
        "activo",
        clock=_clock((1.0, 1.02)),
    ).run("modelo", timeout_seconds=4)

    assert result.available is True
    assert result.installed is True
    assert result.generation_ready is False
    assert result.benchmark_eligible is False
    assert result.diagnostic_code == "MODEL_NOT_GENERATION_READY"


def test_generation_error_preserves_available_and_installed() -> None:
    provider = FakeValidationProvider(
        models=(LocalModel("modelo"),),
        generation_error=LocalModelProviderError(
            LocalModelErrorCode.TIMEOUT,
            "timeout",
        ),
    )

    result = ValidateModelService(
        provider,
        "activo",
        clock=_clock((1.0, 2.0)),
    ).run("modelo", timeout_seconds=5)

    assert result.available is True
    assert result.installed is True
    assert result.generation_ready is False
    assert result.benchmark_eligible is False
    assert result.diagnostic_code == "OLLAMA_TIMEOUT"
    assert provider.calls == [
        ("list", 5),
        ("generate", "modelo", 5),
        ("generate", "modelo", 5),
    ]


def test_validation_retries_once_after_cold_start_timeout() -> None:
    provider = TimeoutOnceValidationProvider(models=(LocalModel("modelo"),))

    result = ValidateModelService(
        provider,
        "activo",
        clock=_clock((1.0, 2.0)),
    ).run("modelo", timeout_seconds=5)

    assert result.generation_ready is True
    assert provider.calls == [
        ("list", 5),
        ("generate", "modelo", 5),
        ("generate", "modelo", 5),
    ]


@pytest.mark.parametrize("name", ["https://invalid/model", "bad\nmodel"])
def test_validation_rejects_invalid_name_before_ollama(name: str) -> None:
    provider = FakeValidationProvider()

    with pytest.raises(ValueError):
        ValidateModelService(provider, "activo").run(name, timeout_seconds=2)

    assert provider.calls == []
