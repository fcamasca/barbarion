"""Runner secuencial y reproducible del benchmark de modelos locales."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from barbarion.application.local_models import ValidateModelService
from barbarion.application.model_benchmark_context import (
    ModelBenchmarkRagAdapter,
    PreparedBenchmarkCase,
)
from barbarion.application.model_benchmark_scoring import DeterministicModelScorer
from barbarion.domain.local_models import (
    LocalModelProviderError,
    ModelGenerationRequest,
)
from barbarion.domain.model_benchmark import (
    BenchmarkRunStatus,
    BenchmarkUnitStatus,
    ModelBenchmarkDataset,
    ModelBenchmarkRunResult,
    ModelBenchmarkUnitResult,
)
from barbarion.domain.ports import LocalModelProvider


MAX_BENCHMARK_MODELS = 10
MAX_RUN_CASES = 50
MAX_BENCHMARK_TIMEOUT_SECONDS = 3600.0


class ModelBenchmarkSetupError(ValueError):
    """La corrida no puede comenzar con las entradas indicadas."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True, slots=True)
class ModelBenchmarkService:
    """Valida modelos y ejecuta una matriz secuencial con orden rotado."""

    provider: LocalModelProvider
    rag_adapter: ModelBenchmarkRagAdapter
    scorer: DeterministicModelScorer = field(
        default_factory=DeterministicModelScorer
    )
    clock: Callable[[], float] = time.monotonic

    def run(
        self,
        *,
        run_id: str,
        dataset: ModelBenchmarkDataset,
        model_names: Sequence[str],
        timeout_seconds: float,
    ) -> ModelBenchmarkRunResult:
        models = _benchmark_models(model_names)
        if not 1 <= timeout_seconds <= MAX_BENCHMARK_TIMEOUT_SECONDS:
            raise ModelBenchmarkSetupError(
                "MODEL_BENCHMARK_INCOMPLETE",
                "El timeout debe estar entre 1 y 3600 segundos.",
            )
        if len(dataset.cases) > MAX_RUN_CASES:
            raise ModelBenchmarkSetupError(
                "MODEL_DATASET_INVALID",
                f"La corrida admite como maximo {MAX_RUN_CASES} casos.",
            )
        planned = len(models) * len(dataset.cases)
        units: list[ModelBenchmarkUnitResult] = []
        try:
            validator = ValidateModelService(self.provider, models[0])
            for model in models:
                validation = validator.run(model, timeout_seconds=timeout_seconds)
                if not validation.generation_ready:
                    raise ModelBenchmarkSetupError(
                        validation.diagnostic_code or "MODEL_NOT_GENERATION_READY",
                        f"El modelo '{model}' no esta listo para el benchmark: "
                        f"{validation.diagnostic or 'validacion no superada'}",
                    )
            prepared_cases = tuple(
                self.rag_adapter.prepare(case) for case in dataset.cases
            )
            for case_index, prepared in enumerate(prepared_cases):
                rotated = _rotated_models(models, case_index)
                for execution_order, model in enumerate(rotated, start=1):
                    units.append(
                        self._execute_unit(
                            prepared,
                            model,
                            execution_order=execution_order,
                            timeout_seconds=timeout_seconds,
                        )
                    )
        except KeyboardInterrupt:
            return _run_result(
                run_id,
                dataset,
                models,
                BenchmarkRunStatus.INTERRUPTED,
                planned,
                units,
            )
        status = (
            BenchmarkRunStatus.COMPLETED_WITH_ERRORS
            if any(unit.status is BenchmarkUnitStatus.FAILED for unit in units)
            else BenchmarkRunStatus.COMPLETED
        )
        return _run_result(run_id, dataset, models, status, planned, units)

    def _execute_unit(
        self,
        prepared: PreparedBenchmarkCase,
        model: str,
        *,
        execution_order: int,
        timeout_seconds: float,
    ) -> ModelBenchmarkUnitResult:
        started = self.clock()
        try:
            generation = self.provider.generate_detailed(
                ModelGenerationRequest(
                    model=model,
                    prompt=prepared.prompt,
                    timeout_seconds=timeout_seconds,
                    temperature=0.0,
                )
            )
            validation = self.rag_adapter.validate(
                prepared,
                generation.response,
            )
            score = self.scorer.score(
                prepared.case,
                generation.response,
                validation,
            )
        except LocalModelProviderError as error:
            return ModelBenchmarkUnitResult(
                case_id=prepared.case.id,
                category=prepared.case.category,
                model=model,
                execution_order=execution_order,
                status=BenchmarkUnitStatus.FAILED,
                question_hash=prepared.question_hash,
                context_hash=prepared.context_hash,
                prompt_hash=prepared.prompt_hash,
                duration_ms=_duration_ms(self.clock() - started),
                error_code=error.code.value,
                error_detail=_bounded_detail(error.detail),
            )
        return ModelBenchmarkUnitResult(
            case_id=prepared.case.id,
            category=prepared.case.category,
            model=model,
            execution_order=execution_order,
            status=BenchmarkUnitStatus.COMPLETED,
            question_hash=prepared.question_hash,
            context_hash=prepared.context_hash,
            prompt_hash=prepared.prompt_hash,
            duration_ms=_duration_ms(self.clock() - started),
            response=generation.response,
            validation=validation,
            telemetry=generation.telemetry,
            score=score,
        )


def _benchmark_models(values: Sequence[str]) -> tuple[str, ...]:
    models: list[str] = []
    for raw in values:
        if not isinstance(raw, str) or not raw.strip():
            raise ModelBenchmarkSetupError(
                "MODEL_BENCHMARK_INCOMPLETE",
                "Los nombres de modelo no pueden estar vacios.",
            )
        model = raw.strip()
        if any(ord(character) < 32 or ord(character) == 127 for character in model):
            raise ModelBenchmarkSetupError(
                "MODEL_BENCHMARK_INCOMPLETE",
                "Un nombre de modelo contiene caracteres de control.",
            )
        if "://" in model:
            raise ModelBenchmarkSetupError(
                "MODEL_BENCHMARK_INCOMPLETE",
                "Los modelos son identificadores Ollama, no URLs.",
            )
        if model not in models:
            models.append(model)
    if len(models) < 2:
        raise ModelBenchmarkSetupError(
            "MODEL_BENCHMARK_INCOMPLETE",
            "Se requieren al menos dos modelos distintos.",
        )
    if len(models) > MAX_BENCHMARK_MODELS:
        raise ModelBenchmarkSetupError(
            "MODEL_BENCHMARK_INCOMPLETE",
            f"El limite superior actual es {MAX_BENCHMARK_MODELS} modelos.",
        )
    return tuple(models)


def _rotated_models(models: tuple[str, ...], case_index: int) -> tuple[str, ...]:
    offset = case_index % len(models)
    return models[offset:] + models[:offset]


def _duration_ms(seconds: float) -> int:
    return max(0, int(seconds * 1000))


def _bounded_detail(value: str) -> str:
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= 300 else normalized[:297] + "..."


def _run_result(
    run_id: str,
    dataset: ModelBenchmarkDataset,
    models: tuple[str, ...],
    status: BenchmarkRunStatus,
    planned: int,
    units: list[ModelBenchmarkUnitResult],
) -> ModelBenchmarkRunResult:
    return ModelBenchmarkRunResult(
        run_id=run_id,
        dataset_id=dataset.dataset_id,
        dataset_hash=dataset.dataset_hash,
        models=models,
        status=status,
        planned_units=planned,
        units=tuple(units),
    )
