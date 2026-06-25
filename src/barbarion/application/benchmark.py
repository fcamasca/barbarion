"""Benchmark local de recuperacion H3."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from barbarion.domain.rag import RetrievalMode, SearchRequest


ALLOWED_CATEGORIES = {
    "navegacion",
    "dependencias",
    "ubicacion de objetos",
    "explicaciones",
    "impacto",
    "documentacion",
}


@dataclass(frozen=True, slots=True)
class EvaluationQuestion:
    """Pregunta versionada para evaluar retrieval."""

    id: str
    category: str
    question: str
    expected_chunks: tuple[str, ...]
    expected_documents: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BenchmarkQuestionResult:
    """Resultado por pregunta."""

    id: str
    category: str
    recall_at_5: float
    recall_at_10: float
    mrr: float
    latency_ms: int
    returned_chunks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    """Metricas agregadas del benchmark."""

    question_count: int
    recall_at_5: float
    recall_at_10: float
    mrr: float
    latency_ms_avg: float
    results: tuple[BenchmarkQuestionResult, ...]


def load_evaluation_dataset(path: Path) -> tuple[EvaluationQuestion, ...]:
    """Carga y valida el dataset RAG versionado."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    questions = raw.get("questions")
    if not isinstance(questions, list) or len(questions) < 10:
        raise ValueError("El dataset debe contener al menos 10 preguntas.")
    parsed = []
    for item in questions:
        category = str(item["category"])
        if category not in ALLOWED_CATEGORIES:
            raise ValueError(f"Categoria invalida: {category}")
        expected_chunks = tuple(str(value) for value in item["expected_chunks"])
        expected_documents = tuple(str(value) for value in item["expected_documents"])
        if not expected_chunks and not expected_documents:
            raise ValueError(f"Pregunta sin fuentes esperadas: {item['id']}")
        parsed.append(
            EvaluationQuestion(
                id=str(item["id"]),
                category=category,
                question=str(item["question"]),
                expected_chunks=expected_chunks,
                expected_documents=expected_documents,
            )
        )
    return tuple(parsed)


def run_retrieval_benchmark(
    search_service: Any,
    questions: tuple[EvaluationQuestion, ...],
    *,
    top_k: int = 10,
    mode: RetrievalMode = RetrievalMode.HYBRID,
) -> BenchmarkResult:
    """Ejecuta preguntas contra SearchService y calcula metricas top-k."""
    results = []
    for question in questions:
        started = time.monotonic()
        response = search_service.search(
            SearchRequest(
                query=question.question,
                mode=mode,
                top_k=top_k,
                candidate_k=max(50, top_k),
                similarity_threshold=0,
            )
        )
        latency_ms = int((time.monotonic() - started) * 1000)
        returned = tuple(candidate.chunk_id for candidate in response.candidates)
        results.append(
            BenchmarkQuestionResult(
                id=question.id,
                category=question.category,
                recall_at_5=_recall(returned[:5], question.expected_chunks),
                recall_at_10=_recall(returned[:10], question.expected_chunks),
                mrr=_mrr(returned, question.expected_chunks),
                latency_ms=latency_ms,
                returned_chunks=returned,
            )
        )
    return BenchmarkResult(
        question_count=len(results),
        recall_at_5=_avg(result.recall_at_5 for result in results),
        recall_at_10=_avg(result.recall_at_10 for result in results),
        mrr=_avg(result.mrr for result in results),
        latency_ms_avg=_avg(result.latency_ms for result in results),
        results=tuple(results),
    )


def write_benchmark_artifacts(
    result: BenchmarkResult,
    *,
    output_dir: Path,
    metadata: dict[str, object] | None = None,
) -> None:
    """Escribe reporte y conserva historico JSONL local."""
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = {} if metadata is None else dict(metadata)
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata,
        "metrics": _benchmark_json(result),
    }
    history_path = output_dir / "benchmark-history.jsonl"
    with history_path.open("a", encoding="utf-8") as history:
        history.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    (output_dir / "benchmark.md").write_text(
        _benchmark_markdown(result, metadata),
        encoding="utf-8",
    )


def _recall(returned: tuple[str, ...], expected: tuple[str, ...]) -> float:
    if not expected:
        return 0.0
    returned_set = set(returned)
    return len(returned_set.intersection(expected)) / len(set(expected))


def _mrr(returned: tuple[str, ...], expected: tuple[str, ...]) -> float:
    expected_set = set(expected)
    for index, chunk_id in enumerate(returned, start=1):
        if chunk_id in expected_set:
            return 1 / index
    return 0.0


def _avg(values) -> float:
    values = tuple(float(value) for value in values)
    return sum(values) / len(values) if values else 0.0


def _benchmark_json(result: BenchmarkResult) -> dict[str, object]:
    return {
        "question_count": result.question_count,
        "recall@5": result.recall_at_5,
        "recall@10": result.recall_at_10,
        "mrr": result.mrr,
        "latency_ms_avg": result.latency_ms_avg,
        "questions": [
            {
                "id": item.id,
                "category": item.category,
                "recall@5": item.recall_at_5,
                "recall@10": item.recall_at_10,
                "mrr": item.mrr,
                "latency_ms": item.latency_ms,
                "returned_chunks": list(item.returned_chunks),
            }
            for item in result.results
        ],
    }


def _benchmark_markdown(
    result: BenchmarkResult,
    metadata: dict[str, object],
) -> str:
    lines = [
        "# H3 Retrieval Benchmark",
        "",
        "## Baseline",
        "",
        f"- recall@5: {result.recall_at_5:.3f}",
        f"- recall@10: {result.recall_at_10:.3f}",
        f"- mrr: {result.mrr:.3f}",
        f"- latency_ms_avg: {result.latency_ms_avg:.1f}",
        "",
        "## Metadata",
        "",
    ]
    if metadata:
        lines.extend(f"- {key}: {value}" for key, value in sorted(metadata.items()))
    else:
        lines.append("- none")
    lines.extend(["", "## Questions", ""])
    for item in result.results:
        lines.append(
            f"- {item.id} ({item.category}): recall@5={item.recall_at_5:.3f}, "
            f"recall@10={item.recall_at_10:.3f}, mrr={item.mrr:.3f}, "
            f"latency_ms={item.latency_ms}"
        )
    return "\n".join(lines) + "\n"
