"""Golden del reporte Markdown de benchmark local."""

from pathlib import Path

from barbarion.application.model_benchmark_reporting import (
    BenchmarkReportConditions,
    render_model_benchmark_markdown,
)
from barbarion.domain.model_benchmark import (
    BenchmarkRunStatus,
    ModelBenchmarkRunResult,
)


def test_model_benchmark_markdown_matches_golden() -> None:
    run = ModelBenchmarkRunResult(
        run_id="20260720T120000Z-golden",
        dataset_id="barbarion-local-llm-synthetic-v1",
        dataset_hash="d" * 64,
        models=("m1", "m2"),
        status=BenchmarkRunStatus.INTERRUPTED,
        planned_units=16,
        units=(),
    )
    conditions = BenchmarkReportConditions(
        generated_at_utc="2026-07-20T12:00:00Z",
        barbarion_version="0.6.0",
        python_version="3.12.10",
        platform_system="TestOS",
        platform_release="1",
        platform_machine="test-machine",
        ollama_version=None,
        timeout_seconds=30,
        model_metadata=(),
    )

    expected = (Path(__file__).parent / "model_benchmark.md").read_text(
        encoding="utf-8"
    )

    assert render_model_benchmark_markdown(run, conditions) == expected

