"""Pruebas de orquestacion segura para seleccionar el modelo activo."""

from pathlib import Path
from dataclasses import replace

import pytest

from barbarion.application.local_models import (
    SelectModelService,
    ValidateModelService,
    VALIDATION_MARKER,
)
from barbarion.config import load_settings
from barbarion.domain.local_models import (
    LocalModel,
    LocalModelErrorCode,
    LocalModelProviderError,
    ModelGenerationResult,
)
from barbarion.infrastructure.model_config import (
    ModelConfigEditError,
    TomlLlmModelEditor,
)


class FakeProvider:
    def __init__(self, models: tuple[LocalModel, ...], response: str) -> None:
        self.models = models
        self.response = response
        self.calls: list[str] = []

    def list_models(self, *, timeout_seconds: float):  # noqa: ANN201
        del timeout_seconds
        self.calls.append("list")
        return self.models

    def generate_detailed(self, request):  # noqa: ANN001, ANN201
        self.calls.append("generate")
        return ModelGenerationResult(self.response)


class TimeoutProvider(FakeProvider):
    """Simula dos timeouts consecutivos durante la validacion."""

    def generate_detailed(self, request):  # noqa: ANN001, ANN201
        """Registra el intento y devuelve el timeout controlado."""
        del request
        self.calls.append("generate")
        raise LocalModelProviderError(LocalModelErrorCode.TIMEOUT, "timeout")


def _settings(tmp_path: Path):  # noqa: ANN202
    source = tmp_path / "barbarion.toml"
    source.write_text(
        """[llm]
provider = "ollama"
model = "modelo-anterior:tag" # conservar
timeout_seconds = 30.0
temperature = 0.1

[embeddings]
provider = "ollama"
model = "embed-estable:tag"
""",
        encoding="utf-8",
    )
    return source, load_settings(source, environ={}, cwd=tmp_path)


def _service(provider: FakeProvider) -> SelectModelService:
    return SelectModelService(
        ValidateModelService(provider, "modelo-anterior:tag"),
        TomlLlmModelEditor(),
    )


def test_select_validates_then_changes_only_llm_model(tmp_path: Path) -> None:
    source, settings = _settings(tmp_path)
    before = source.read_bytes()
    provider = FakeProvider(
        (LocalModel("modelo-nuevo:tag"),),
        VALIDATION_MARKER,
    )

    result = _service(provider).run(
        settings,
        "modelo-nuevo:tag",
        timeout_seconds=8,
    )

    assert provider.calls == ["list", "generate"]
    assert result.previous_model == "modelo-anterior:tag"
    assert result.new_model == "modelo-nuevo:tag"
    assert result.generation_validated is True
    assert source.read_bytes() == before.replace(
        b'model = "modelo-anterior:tag"',
        b'model = "modelo-nuevo:tag"',
        1,
    )
    reloaded = load_settings(source, environ={}, cwd=tmp_path)
    assert reloaded.llm.model == "modelo-nuevo:tag"
    assert reloaded.embeddings.model == "embed-estable:tag"


def test_select_dry_run_checks_editability_without_ollama_or_write(
    tmp_path: Path,
) -> None:
    source, settings = _settings(tmp_path)
    before = source.read_bytes()
    provider = FakeProvider((), "no debe usarse")

    result = _service(provider).run(
        settings,
        "modelo-nuevo:tag",
        timeout_seconds=8,
        dry_run=True,
    )

    assert result.dry_run is True
    assert result.generation_validated is False
    assert provider.calls == []
    assert source.read_bytes() == before


def test_select_rejects_non_editable_config_before_generation(
    tmp_path: Path,
) -> None:
    _source, settings = _settings(tmp_path)
    provider = FakeProvider((LocalModel("modelo-nuevo:tag"),), VALIDATION_MARKER)

    with pytest.raises(ModelConfigEditError):
        _service(provider).run(
            replace(settings, config_source=None),
            "modelo-nuevo:tag",
            timeout_seconds=8,
        )

    assert provider.calls == []


@pytest.mark.parametrize(
    ("models", "response"),
    [
        ((), VALIDATION_MARKER),
        ((LocalModel("modelo-nuevo:tag"),), "marcador incorrecto"),
    ],
)
def test_select_rejects_missing_or_not_ready_and_preserves_file(
    tmp_path: Path,
    models: tuple[LocalModel, ...],
    response: str,
) -> None:
    source, settings = _settings(tmp_path)
    before = source.read_bytes()

    with pytest.raises(LocalModelProviderError):
        _service(FakeProvider(models, response)).run(
            settings,
            "modelo-nuevo:tag",
            timeout_seconds=8,
        )

    assert source.read_bytes() == before


def test_select_preserves_file_after_cold_start_retry_times_out(
    tmp_path: Path,
) -> None:
    source, settings = _settings(tmp_path)
    before = source.read_bytes()
    provider = TimeoutProvider(
        (LocalModel("modelo-nuevo:tag"),),
        VALIDATION_MARKER,
    )

    with pytest.raises(LocalModelProviderError) as captured:
        _service(provider).run(
            settings,
            "modelo-nuevo:tag",
            timeout_seconds=8,
        )

    assert captured.value.code is LocalModelErrorCode.TIMEOUT
    assert provider.calls == ["list", "generate", "generate"]
    assert source.read_bytes() == before
