"""Pruebas del dataset y benchmark RAG H3."""

import json
from pathlib import Path

from barbarion.application.benchmark import (
    ALLOWED_CATEGORIES,
    EvaluationQuestion,
    load_evaluation_dataset,
    run_retrieval_benchmark,
    write_benchmark_artifacts,
)
from barbarion.domain.rag import RetrievalCandidate, RetrievalMode, SearchResponse


class FakeSearchService:
    def __init__(self) -> None:
        self.queries = []

    def search(self, request):
        self.queries.append(request)
        expected = request.query.split()[0]
        return SearchResponse(
            query_id=None,
            mode=RetrievalMode.HYBRID,
            candidates=(
                RetrievalCandidate(
                    chunk_id=expected,
                    content_sha256="a" * 64,
                    combined_score=1.0,
                ),
                RetrievalCandidate(
                    chunk_id="other",
                    content_sha256="b" * 64,
                    combined_score=0.5,
                ),
            ),
        )


def test_evaluation_dataset_has_required_categories_and_examples() -> None:
    dataset = load_evaluation_dataset(Path("tests/fixtures/h3_rag_evaluation.json"))

    assert len(dataset) >= 10
    assert {question.category for question in dataset}.issubset(ALLOWED_CATEGORIES)
    questions = {question.question for question in dataset}
    assert "Donde se calcula COSTO_AMORT_DIA?" in questions
    assert "Que objetos llaman p_insertarCompraVenta?" in questions
    assert "Donde se usa NOM_OPERACION_DIA?" in questions
    assert "Que documentos hablan de CDVAL?" in questions


def test_retrieval_benchmark_computes_metrics_and_history(tmp_path: Path) -> None:
    questions = (
        EvaluationQuestion("q1", "navegacion", "chunk-a pregunta", ("chunk-a",), ()),
        EvaluationQuestion("q2", "impacto", "missing pregunta", ("chunk-x",), ()),
    )
    result = run_retrieval_benchmark(FakeSearchService(), questions)

    assert result.question_count == 2
    assert result.recall_at_5 == 0.5
    assert result.recall_at_10 == 0.5
    assert result.mrr == 0.5

    write_benchmark_artifacts(
        result,
        output_dir=tmp_path,
        metadata={"model": "fake"},
    )

    benchmark = (tmp_path / "benchmark.md").read_text(encoding="utf-8")
    history = (tmp_path / "benchmark-history.jsonl").read_text(encoding="utf-8")
    assert "## Baseline" in benchmark
    assert "recall@5" in benchmark
    assert json.loads(history.splitlines()[0])["metadata"]["model"] == "fake"
