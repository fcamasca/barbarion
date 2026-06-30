"""Pruebas de reportes de cierre RAG."""

import json
from pathlib import Path

from barbarion.application.reporting import generate_rag_report


def test_generate_rag_report_writes_required_artifacts(tmp_path: Path) -> None:
    summary = generate_rag_report(
        dataset_path=Path("tests/fixtures/rag_evaluation.json"),
        output_dir=tmp_path / "reports" / "rag",
        test_summary="341 passed, 12 skipped",
        smoke_summary="10 skipped: entry point no instalado",
        metadata={"commit": "test"},
    )

    assert summary.metrics_path.exists()
    assert summary.topk_report_path.exists()
    assert summary.smoke_report_path.exists()
    assert summary.benchmark_path.exists()
    assert summary.history_path.exists()
    assert summary.recall_at_5 == 1.0
    assert "## Baseline" in summary.benchmark_path.read_text(encoding="utf-8")
    metrics = json.loads(summary.metrics_path.read_text(encoding="utf-8"))
    assert metrics["benchmark"]["recall@5"] == 1.0
