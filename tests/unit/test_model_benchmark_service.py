"""Pruebas del runner secuencial de benchmark."""

from dataclasses import replace

from barbarion.application.local_models import VALIDATION_MARKER, VALIDATION_PROMPT
from barbarion.application.model_benchmark import ModelBenchmarkService
from barbarion.application.model_benchmark_context import ModelBenchmarkRagAdapter
from barbarion.application.model_benchmark_dataset import load_model_benchmark_dataset
from barbarion.application.rag import CitationValidator, ContextBuilder, PromptBuilder
from barbarion.domain.local_models import (
    LocalModel,
    LocalModelErrorCode,
    LocalModelProviderError,
    ModelGenerationResult,
)
from barbarion.domain.model_benchmark import BenchmarkRunStatus, BenchmarkUnitStatus


class FakeBenchmarkProvider:
    def __init__(self, *, fail_at: int | None = None, interrupt_at: int | None = None) -> None:
        self.fail_at = fail_at
        self.interrupt_at = interrupt_at
        self.benchmark_calls = 0
        self.calls: list[tuple[str, object]] = []

    def list_models(self, *, timeout_seconds: float):  # noqa: ANN201
        self.calls.append(("list", timeout_seconds))
        return tuple(LocalModel(name) for name in ("m1", "m2", "m3"))

    def generate_detailed(self, request):  # noqa: ANN001, ANN201
        if request.prompt == VALIDATION_PROMPT:
            self.calls.append(("probe", request.model))
            return ModelGenerationResult(VALIDATION_MARKER)
        self.benchmark_calls += 1
        self.calls.append(("benchmark", request.model))
        assert request.temperature == 0.0
        if self.interrupt_at == self.benchmark_calls:
            raise KeyboardInterrupt
        if self.fail_at == self.benchmark_calls:
            raise LocalModelProviderError(
                LocalModelErrorCode.TIMEOUT,
                "timeout sintetico",
            )
        return ModelGenerationResult("Respuesta sintetica respaldada [F1].")


def _service(provider: FakeBenchmarkProvider) -> ModelBenchmarkService:
    ticks = iter(float(index) / 10 for index in range(100))
    return ModelBenchmarkService(
        provider=provider,
        rag_adapter=ModelBenchmarkRagAdapter(
            ContextBuilder(1000, 500, 8, 0),
            PromptBuilder(),
            CitationValidator(),
        ),
        clock=lambda: next(ticks),
    )


def _dataset(case_count: int):  # noqa: ANN202
    source = load_model_benchmark_dataset()
    return replace(source, cases=source.cases[:case_count])


def test_runner_rotates_models_and_executes_each_matrix_unit_once() -> None:
    provider = FakeBenchmarkProvider()

    result = _service(provider).run(
        run_id="run-1",
        dataset=_dataset(3),
        model_names=("m1", "m2", "m3"),
        timeout_seconds=20,
    )

    assert result.status is BenchmarkRunStatus.COMPLETED
    assert result.planned_units == 9
    assert len(result.units) == 9
    assert [(unit.case_id, unit.model, unit.execution_order) for unit in result.units] == [
        ("syn-001", "m1", 1),
        ("syn-001", "m2", 2),
        ("syn-001", "m3", 3),
        ("syn-002", "m2", 1),
        ("syn-002", "m3", 2),
        ("syn-002", "m1", 3),
        ("syn-003", "m3", 1),
        ("syn-003", "m1", 2),
        ("syn-003", "m2", 3),
    ]
    assert provider.benchmark_calls == 9
    for case_id in ("syn-001", "syn-002", "syn-003"):
        case_units = [unit for unit in result.units if unit.case_id == case_id]
        assert len({unit.question_hash for unit in case_units}) == 1
        assert len({unit.context_hash for unit in case_units}) == 1
        assert len({unit.prompt_hash for unit in case_units}) == 1


def test_unit_failure_is_confirmed_and_later_units_continue() -> None:
    provider = FakeBenchmarkProvider(fail_at=2)

    result = _service(provider).run(
        run_id="run-partial-error",
        dataset=_dataset(2),
        model_names=("m1", "m2"),
        timeout_seconds=20,
    )

    assert result.status is BenchmarkRunStatus.COMPLETED_WITH_ERRORS
    assert len(result.units) == result.planned_units == 4
    assert result.failed_units == 1
    assert result.units[1].status is BenchmarkUnitStatus.FAILED
    assert result.units[1].error_code == "OLLAMA_TIMEOUT"
    assert result.units[2].status is BenchmarkUnitStatus.COMPLETED


def test_keyboard_interrupt_returns_only_confirmed_units_without_resume() -> None:
    provider = FakeBenchmarkProvider(interrupt_at=3)

    result = _service(provider).run(
        run_id="run-interrupted",
        dataset=_dataset(3),
        model_names=("m1", "m2"),
        timeout_seconds=20,
    )

    assert result.status is BenchmarkRunStatus.INTERRUPTED
    assert result.planned_units == 6
    assert len(result.units) == 2
    assert provider.benchmark_calls == 3
    assert all(unit.status is BenchmarkUnitStatus.COMPLETED for unit in result.units)


def test_duplicate_models_are_deduplicated_preserving_first_appearance() -> None:
    provider = FakeBenchmarkProvider()

    result = _service(provider).run(
        run_id="run-dedupe",
        dataset=_dataset(1),
        model_names=("m2", "m1", "m2"),
        timeout_seconds=20,
    )

    assert result.models == ("m2", "m1")
    assert [unit.model for unit in result.units] == ["m2", "m1"]

