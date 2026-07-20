"""Pruebas de agregacion, null, tokens y elegibilidad."""

from dataclasses import replace

from barbarion.application.model_benchmark_dataset import load_model_benchmark_dataset
from barbarion.application.model_benchmark_scoring import (
    DeterministicModelScorer,
    aggregate_model_benchmark,
)
from barbarion.domain.local_models import ModelGenerationTelemetry
from barbarion.domain.model_benchmark import (
    BenchmarkRunStatus,
    BenchmarkUnitStatus,
    ModelBenchmarkRunResult,
    ModelBenchmarkUnitResult,
)
from barbarion.domain.rag import CitationValidation


def _unit(
    model: str,
    case_index: int,
    *,
    accepted: bool,
    telemetry: ModelGenerationTelemetry | None = None,
) -> ModelBenchmarkUnitResult:
    case = load_model_benchmark_dataset().cases[case_index]
    validation = CitationValidation(valid=accepted, cited_source_ids=("F1",))
    score = DeterministicModelScorer().score(
        case,
        "Respuesta con evidencia alfa beta estable ámbar [F1].",
        validation,
    )
    return ModelBenchmarkUnitResult(
        case_id=case.id,
        category=case.category,
        model=model,
        execution_order=1,
        status=BenchmarkUnitStatus.COMPLETED,
        question_hash="a" * 64,
        context_hash="b" * 64,
        prompt_hash="c" * 64,
        duration_ms=100 + case_index,
        response="respuesta solo en memoria",
        validation=validation,
        telemetry=telemetry,
        score=score,
    )


def test_aggregation_keeps_missing_tokens_null_and_reports_coverage() -> None:
    run = ModelBenchmarkRunResult(
        run_id="run",
        dataset_id="dataset",
        dataset_hash="d" * 64,
        models=("m1", "m2"),
        status=BenchmarkRunStatus.COMPLETED,
        planned_units=4,
        units=(
            _unit(
                "m1",
                0,
                accepted=True,
                telemetry=ModelGenerationTelemetry(
                    prompt_eval_count=20,
                    eval_count=5,
                ),
            ),
            _unit("m1", 1, accepted=False),
            _unit("m2", 0, accepted=True),
            _unit("m2", 1, accepted=True),
        ),
    )

    first, second = aggregate_model_benchmark(run)

    assert first.prompt_tokens_total == 20
    assert first.prompt_tokens_median == 20.0
    assert first.prompt_tokens_coverage == 0.5
    assert first.output_tokens_total == 5
    assert first.acceptance_rate == 0.5
    assert first.recommendation_eligible is False
    assert first.mean_quality_score is not None
    accepted_score = run.units[0].score
    assert accepted_score is not None
    assert first.recommendation_quality_score == accepted_score.recommendation_score
    assert second.prompt_tokens_total is None
    assert second.prompt_tokens_median is None
    assert second.prompt_tokens_coverage == 0.0
    assert second.output_tokens_total is None
    assert second.recommendation_eligible is True


def test_interrupted_or_failed_run_is_never_recommendation_eligible() -> None:
    completed = _unit("m1", 0, accepted=True)
    failed = replace(
        completed,
        case_id="syn-failed",
        status=BenchmarkUnitStatus.FAILED,
        response=None,
        validation=None,
        telemetry=None,
        score=None,
        error_code="OLLAMA_TIMEOUT",
    )
    run = ModelBenchmarkRunResult(
        run_id="partial",
        dataset_id="dataset",
        dataset_hash="d" * 64,
        models=("m1",),
        status=BenchmarkRunStatus.INTERRUPTED,
        planned_units=2,
        units=(completed, failed),
    )

    aggregate = aggregate_model_benchmark(run)[0]

    assert aggregate.completion_rate == 0.5
    assert aggregate.recommendation_eligible is False
    assert aggregate.failures_by_code == (("OLLAMA_TIMEOUT", 1),)
