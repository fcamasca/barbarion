"""Pruebas del dominio y puerto de modelos locales."""

from collections.abc import Callable

import pytest

from barbarion.domain.local_models import (
    LocalModel,
    LocalModelDetails,
    LocalModelErrorCode,
    LocalModelProviderError,
    ModelGenerationRequest,
    ModelGenerationResult,
    PullProgress,
    PullResult,
)
from barbarion.domain.ports import LocalModelProvider


class FakeLocalModelProvider:
    """Implementacion estructural sin dependencia de infraestructura."""

    def list_models(self, *, timeout_seconds: float) -> tuple[LocalModel, ...]:
        assert timeout_seconds > 0
        return (LocalModel("modelo:tag"),)

    def show_model(
        self,
        name: str,
        *,
        timeout_seconds: float,
    ) -> LocalModelDetails:
        assert timeout_seconds > 0
        return LocalModelDetails(LocalModel(name), family="generic")

    def pull_model(
        self,
        name: str,
        *,
        timeout_seconds: float,
        on_progress: Callable[[PullProgress], None] | None = None,
    ) -> PullResult:
        assert timeout_seconds > 0
        progress = PullProgress("success", completed=10, total=10)
        if on_progress is not None:
            on_progress(progress)
        return PullResult(name, "success")

    def generate_detailed(
        self,
        request: ModelGenerationRequest,
    ) -> ModelGenerationResult:
        return ModelGenerationResult(f"respuesta de {request.model}")


def test_local_model_provider_accepts_structural_implementation() -> None:
    provider: LocalModelProvider = FakeLocalModelProvider()
    events: list[PullProgress] = []

    assert provider.list_models(timeout_seconds=1)[0].name == "modelo:tag"
    assert provider.show_model("modelo:tag", timeout_seconds=1).family == "generic"
    assert provider.pull_model(
        "modelo:tag",
        timeout_seconds=1,
        on_progress=events.append,
    ).status == "success"
    assert provider.generate_detailed(
        ModelGenerationRequest("modelo:tag", "entrada sintetica", 2)
    ).response == "respuesta de modelo:tag"
    assert events[0].percent == 100.0


def test_domain_models_validate_required_and_numeric_fields() -> None:
    with pytest.raises(ValueError, match="name"):
        LocalModel(" ")
    with pytest.raises(ValueError, match="size_bytes"):
        LocalModel("modelo", size_bytes=-1)
    with pytest.raises(ValueError, match="timeout_seconds"):
        ModelGenerationRequest("modelo", "prompt", 0)
    with pytest.raises(ValueError, match="max_output_tokens"):
        ModelGenerationRequest("modelo", "prompt", 1, max_output_tokens=0)


def test_pull_progress_does_not_invent_percentage() -> None:
    assert PullProgress("downloading").percent is None
    assert PullProgress("downloading", completed=3, total=0).percent is None
    assert PullProgress("downloading", completed=12, total=10).percent == 100.0


def test_local_model_error_exposes_stable_code() -> None:
    error = LocalModelProviderError(
        LocalModelErrorCode.UNAVAILABLE,
        "No se pudo contactar Ollama.",
    )

    assert error.code is LocalModelErrorCode.UNAVAILABLE
    assert str(error) == "OLLAMA_UNAVAILABLE: No se pudo contactar Ollama."
