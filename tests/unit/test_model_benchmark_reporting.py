"""Pruebas del reporte comparativo y recomendacion humana."""

import json
from pathlib import Path

import pytest

from barbarion.application.model_benchmark_reporting import (
    BenchmarkModelMetadata,
    BenchmarkReportConditions,
    build_model_benchmark_payload,
    recommend_model,
    render_model_benchmark_markdown,
    write_model_benchmark_report,
)
from barbarion.domain.model_benchmark import (
    BenchmarkCategory,
    BenchmarkRunStatus,
    BenchmarkUnitStatus,
    ModelBenchmarkCaseMetrics,
    ModelBenchmarkCaseScore,
    ModelBenchmarkRunResult,
    ModelBenchmarkUnitResult,
)
from barbarion.domain.rag import CitationValidation


def _conditions() -> BenchmarkReportConditions:
    return BenchmarkReportConditions(
        generated_at_utc="2026-07-20T12:00:00Z",
        barbarion_version="0.6.0",
        python_version="3.12.10",
        platform_system="TestOS",
        platform_release="1",
        platform_machine="test-machine",
        ollama_version="1.2.3",
        timeout_seconds=30,
        model_metadata=(
            BenchmarkModelMetadata(
                model="m1",
                format="gguf",
                family="synthetic",
                parameter_size="small",
                quantization_level="Q4",
                capabilities=("completion",),
            ),
            BenchmarkModelMetadata(model="m2", diagnostic_code="METADATA_UNAVAILABLE"),
        ),
    )


def _score(value: float, *, accepted: bool = True) -> ModelBenchmarkCaseScore:
    metrics = ModelBenchmarkCaseMetrics(
        answer_quality=value,
        instruction_following=value,
        groundedness=value,
        context_use=value,
        citation_score=value,
        validator_acceptance=1.0 if accepted else 0.0,
    )
    return ModelBenchmarkCaseScore(
        metrics=metrics,
        quality_score=value,
        recommendation_score=value if accepted else None,
        applied_weight=1.0,
    )


def _unit(model: str, quality: float, duration: int, *, accepted: bool = True):  # noqa: ANN202
    return ModelBenchmarkUnitResult(
        case_id="syn-001",
        category=BenchmarkCategory.FACTUAL,
        model=model,
        execution_order=1,
        status=BenchmarkUnitStatus.COMPLETED,
        question_hash="a" * 64,
        context_hash="b" * 64,
        prompt_hash="c" * 64,
        duration_ms=duration,
        response="RESPUESTA-PRIVADA",
        validation=CitationValidation(valid=accepted, cited_source_ids=("F1",)),
        score=_score(quality, accepted=accepted),
    )


def _run(*, status: BenchmarkRunStatus = BenchmarkRunStatus.COMPLETED):
    return ModelBenchmarkRunResult(
        run_id="20260720T120000Z-fixed",
        dataset_id="barbarion-local-llm-synthetic-v1",
        dataset_hash="d" * 64,
        models=("m1", "m2"),
        status=status,
        planned_units=2,
        units=(_unit("m1", 0.8, 100), _unit("m2", 0.9, 200)),
    )


def test_recommendation_uses_quality_then_latency_without_selecting() -> None:
    decision = recommend_model(_run())

    assert decision.candidate == "m2"
    assert decision.eligible_models == ("m2", "m1")
    assert "informativo" in decision.reason


def test_incomplete_run_has_no_candidate_even_with_high_scores() -> None:
    decision = recommend_model(_run(status=BenchmarkRunStatus.INTERRUPTED))

    assert decision.candidate is None
    assert "no esta completa" in decision.reason


def test_lexical_tie_break_is_explicit() -> None:
    run = _run()
    tied = ModelBenchmarkRunResult(
        run_id=run.run_id,
        dataset_id=run.dataset_id,
        dataset_hash=run.dataset_hash,
        models=run.models,
        status=run.status,
        planned_units=2,
        units=(_unit("m2", 0.8, 100), _unit("m1", 0.8, 100)),
    )

    decision = recommend_model(tied)

    assert decision.candidate == "m1"
    assert decision.lexical_tiebreak_used is True
    assert "nombre exacto" in decision.reason


def test_payload_and_markdown_explain_limits_without_private_content() -> None:
    run = _run()
    payload = build_model_benchmark_payload(run, _conditions())
    markdown = render_model_benchmark_markdown(run, _conditions())
    serialized = json.dumps(payload, ensure_ascii=False)

    assert payload["recommendation"]["candidate"] == "m2"
    assert payload["recommendation"]["automatic_selection"] is False
    assert "RESPUESTA-PRIVADA" not in serialized + markdown
    assert "Responde en espanol usando solo" not in serialized + markdown
    assert "## Limitaciones" in markdown
    assert "no selecciona ni configura" in markdown
    assert "revision humana" in markdown
    assert "una ejecucion por caso/modelo" in markdown
    assert "no calcula p95" in markdown
    assert "Fallas operativas: 0" in markdown


def test_writer_creates_two_files_and_rejects_collision(tmp_path: Path) -> None:
    run = _run()

    json_path, markdown_path = write_model_benchmark_report(
        run,
        _conditions(),
        tmp_path,
    )

    assert json_path.name == "model-benchmark.json"
    assert markdown_path.name == "model-benchmark.md"
    assert json_path.parent == markdown_path.parent
    with pytest.raises(FileExistsError):
        write_model_benchmark_report(run, _conditions(), tmp_path)

