"""Casos de uso de solo lectura para modelos locales."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import time

from barbarion.domain.ports import LocalModelProvider
from barbarion.domain.local_models import (
    LocalModelErrorCode,
    LocalModelProviderError,
    PullProgress,
    ModelGenerationRequest,
)
from barbarion.config import Settings, load_settings
from barbarion.infrastructure.model_config import (
    LlmModelConfigChange,
    TomlLlmModelEditor,
)


_MAX_METADATA_CHARS = 128
_MAX_CAPABILITIES = 20


@dataclass(frozen=True, slots=True)
class LocalModelView:
    """Vista acotada de un modelo instalado para presentacion."""

    name: str
    size_bytes: int | None
    modified_at: str | None
    digest: str | None
    active: bool
    metadata_truncated: bool = False


@dataclass(frozen=True, slots=True)
class ModelListResult:
    """Catalogo ordenado con estado del modelo activo."""

    active_model: str
    active_model_installed: bool
    models: tuple[LocalModelView, ...]


@dataclass(frozen=True, slots=True)
class ModelDetailsView:
    """Detalle allowlist; nunca contiene payloads crudos de Ollama."""

    name: str
    active: bool
    format: str | None
    family: str | None
    parameter_size: str | None
    quantization_level: str | None
    capabilities: tuple[str, ...]
    metadata_truncated: bool = False


@dataclass(frozen=True, slots=True)
class InstallModelResult:
    """Resultado explicito de instalar o previsualizar un modelo."""

    model: str
    already_installed: bool
    dry_run: bool
    pull_requested: bool
    final_present: bool
    final_status: str | None = None


@dataclass(frozen=True, slots=True)
class ModelValidationResult:
    """Cuatro estados separados de disponibilidad y preparacion."""

    model: str
    active: bool
    available: bool
    installed: bool
    generation_ready: bool
    benchmark_eligible: bool
    duration_ms: int
    diagnostic_code: str | None = None
    diagnostic: str | None = None


@dataclass(frozen=True, slots=True)
class SelectModelResult:
    """Resumen de una seleccion previsualizada o aplicada."""

    config_path: str
    previous_model: str
    new_model: str
    changed: bool
    dry_run: bool
    generation_validated: bool


@dataclass(frozen=True, slots=True)
class ListModelsService:
    """Lista y ordena modelos sin persistir un catalogo paralelo."""

    provider: LocalModelProvider
    active_model: str

    def run(self, *, timeout_seconds: float) -> ModelListResult:
        models = self.provider.list_models(timeout_seconds=timeout_seconds)
        views = tuple(
            sorted(
                (_model_view(model, self.active_model) for model in models),
                key=lambda item: (item.name.casefold(), item.name),
            )
        )
        return ModelListResult(
            active_model=self.active_model,
            active_model_installed=any(item.active for item in views),
            models=views,
        )


@dataclass(frozen=True, slots=True)
class ShowModelService:
    """Obtiene exclusivamente metadata allowlist de un modelo."""

    provider: LocalModelProvider
    active_model: str

    def run(self, name: str, *, timeout_seconds: float) -> ModelDetailsView:
        details = self.provider.show_model(name, timeout_seconds=timeout_seconds)
        metadata_truncated = False
        safe_values: list[str | None] = []
        for value in (
            details.format,
            details.family,
            details.parameter_size,
            details.quantization_level,
        ):
            safe, truncated = _bounded(value)
            safe_values.append(safe)
            metadata_truncated = metadata_truncated or truncated
        safe_capabilities = []
        for capability in details.capabilities[:_MAX_CAPABILITIES]:
            safe, truncated = _bounded(capability)
            if safe is not None:
                safe_capabilities.append(safe)
            metadata_truncated = metadata_truncated or truncated
        if len(details.capabilities) > _MAX_CAPABILITIES:
            metadata_truncated = True
        return ModelDetailsView(
            name=details.model.name,
            active=details.model.name == self.active_model,
            format=safe_values[0],
            family=safe_values[1],
            parameter_size=safe_values[2],
            quantization_level=safe_values[3],
            capabilities=tuple(safe_capabilities),
            metadata_truncated=metadata_truncated,
        )


@dataclass(frozen=True, slots=True)
class InstallModelService:
    """Instala explicitamente y confirma presencia final mediante Ollama."""

    provider: LocalModelProvider

    def run(
        self,
        name: str,
        *,
        timeout_seconds: float,
        dry_run: bool = False,
        on_progress: Callable[[PullProgress], None] | None = None,
    ) -> InstallModelResult:
        name = _validated_model_name(name)
        installed_before = self.provider.list_models(
            timeout_seconds=timeout_seconds
        )
        if _contains_exact(installed_before, name):
            return InstallModelResult(
                model=name,
                already_installed=True,
                dry_run=dry_run,
                pull_requested=False,
                final_present=True,
            )
        if dry_run:
            return InstallModelResult(
                model=name,
                already_installed=False,
                dry_run=True,
                pull_requested=False,
                final_present=False,
            )
        pull = self.provider.pull_model(
            name,
            timeout_seconds=timeout_seconds,
            on_progress=on_progress,
        )
        installed_after = self.provider.list_models(timeout_seconds=timeout_seconds)
        if not _contains_exact(installed_after, name):
            raise LocalModelProviderError(
                LocalModelErrorCode.OPERATION_FAILED,
                "Ollama finalizo el pull pero no reporta el modelo instalado.",
            )
        return InstallModelResult(
            model=name,
            already_installed=False,
            dry_run=False,
            pull_requested=True,
            final_present=True,
            final_status=pull.status,
        )


VALIDATION_MARKER = "BARBARION_MODEL_READY"
VALIDATION_PROMPT = (
    "Devuelve exactamente este texto y nada mas: "
    "BARBARION_MODEL_READY"
)
_VALIDATION_MAX_OUTPUT_TOKENS = 16


@dataclass(frozen=True, slots=True)
class ValidateModelService:
    """Valida conectividad, instalacion y generacion sin medir calidad RAG."""

    provider: LocalModelProvider
    active_model: str
    think: bool | None = None
    clock: Callable[[], float] = time.monotonic

    def run(
        self,
        name: str | None,
        *,
        timeout_seconds: float,
    ) -> ModelValidationResult:
        model = _validated_model_name(name or self.active_model)
        started = self.clock()
        try:
            installed_models = self.provider.list_models(
                timeout_seconds=timeout_seconds
            )
        except LocalModelProviderError as error:
            return self._result(
                model,
                started,
                available=False,
                installed=False,
                generation_ready=False,
                diagnostic_code=error.code.value,
                diagnostic=error.detail,
            )
        if not _contains_exact(installed_models, model):
            return self._result(
                model,
                started,
                available=True,
                installed=False,
                generation_ready=False,
                diagnostic_code=LocalModelErrorCode.MODEL_NOT_FOUND.value,
                diagnostic="El modelo no esta instalado en Ollama.",
            )
        try:
            generation = self.provider.generate_detailed(
                ModelGenerationRequest(
                    model=model,
                    prompt=VALIDATION_PROMPT,
                    timeout_seconds=timeout_seconds,
                    temperature=0.0,
                    max_output_tokens=_VALIDATION_MAX_OUTPUT_TOKENS,
                    think=self.think,
                )
            )
        except LocalModelProviderError as error:
            return self._result(
                model,
                started,
                available=True,
                installed=True,
                generation_ready=False,
                diagnostic_code=error.code.value,
                diagnostic=error.detail,
            )
        ready = generation.response.strip() == VALIDATION_MARKER
        return self._result(
            model,
            started,
            available=True,
            installed=True,
            generation_ready=ready,
            diagnostic_code=(
                None
                if ready
                else LocalModelErrorCode.NOT_GENERATION_READY.value
            ),
            diagnostic=(
                None
                if ready
                else "La generacion termino pero no devolvio el marcador exacto."
            ),
        )

    def _result(
        self,
        model: str,
        started: float,
        *,
        available: bool,
        installed: bool,
        generation_ready: bool,
        diagnostic_code: str | None,
        diagnostic: str | None,
    ) -> ModelValidationResult:
        return ModelValidationResult(
            model=model,
            active=model == self.active_model,
            available=available,
            installed=installed,
            generation_ready=generation_ready,
            benchmark_eligible=generation_ready,
            duration_ms=max(0, int((self.clock() - started) * 1000)),
            diagnostic_code=diagnostic_code,
            diagnostic=diagnostic,
        )


@dataclass(frozen=True, slots=True)
class SelectModelService:
    """Selecciona el modelo activo solo despues de una sonda satisfactoria."""

    validator: ValidateModelService
    editor: TomlLlmModelEditor

    def run(
        self,
        settings: Settings,
        name: str,
        *,
        timeout_seconds: float,
        dry_run: bool = False,
    ) -> SelectModelResult:
        model = _validated_model_name(name)
        preview = self.editor.edit(settings, model, dry_run=True)
        if dry_run:
            return _select_result(preview, generation_validated=False)

        validation = self.validator.run(model, timeout_seconds=timeout_seconds)
        if not validation.generation_ready:
            code = validation.diagnostic_code or (
                LocalModelErrorCode.NOT_GENERATION_READY.value
            )
            detail = validation.diagnostic or (
                "El modelo no supero la validacion minima de generacion."
            )
            raise LocalModelProviderError(_error_code(code), detail)

        change = self.editor.edit(settings, model)
        reloaded = load_settings(
            change.config_path,
            environ={},
            cwd=change.config_path.parent,
        )
        if reloaded.llm.model != model:
            raise RuntimeError(
                "La configuracion recargada no conserva el modelo seleccionado."
            )
        return _select_result(change, generation_validated=True)


def _select_result(
    change: LlmModelConfigChange,
    *,
    generation_validated: bool,
) -> SelectModelResult:
    return SelectModelResult(
        config_path=str(change.config_path),
        previous_model=change.previous_model,
        new_model=change.new_model,
        changed=change.changed,
        dry_run=change.dry_run,
        generation_validated=generation_validated,
    )


def _error_code(value: str) -> LocalModelErrorCode:
    try:
        return LocalModelErrorCode(value)
    except ValueError:
        return LocalModelErrorCode.OPERATION_FAILED


def _model_view(model, active_model: str) -> LocalModelView:  # noqa: ANN001
    modified_at, modified_truncated = _bounded(model.modified_at)
    digest, digest_truncated = _bounded(model.digest)
    return LocalModelView(
        name=model.name,
        size_bytes=model.size_bytes,
        modified_at=modified_at,
        digest=digest,
        active=model.name == active_model,
        metadata_truncated=modified_truncated or digest_truncated,
    )


def _contains_exact(models, name: str) -> bool:  # noqa: ANN001
    return any(model.name == name for model in models)


def _validated_model_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("El identificador del modelo no puede estar vacio.")
    normalized = value.strip()
    if "://" in normalized or any(
        ord(character) < 32 or ord(character) == 127 for character in normalized
    ):
        raise ValueError("El identificador del modelo no es valido.")
    return normalized


def _bounded(value: str | None) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    normalized = " ".join(value.split())
    normalized_changed = normalized != value
    if len(normalized) <= _MAX_METADATA_CHARS:
        return normalized, normalized_changed
    return normalized[: _MAX_METADATA_CHARS - 3] + "...", True
