"""Benchmark offline y publicable para seleccionar límites H3.3."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import mean
from typing import Any

from barbarion.application.rag import (
    ContextBuilder,
    GraphAwareEvidenceRetriever,
    GraphEvidenceResolver,
    GraphExpansionService,
    _prepare_graph_aware_families,
    _select_ask_candidates_relevance_first,
)
from barbarion.domain.models import Confidence
from barbarion.domain.rag import (
    GraphExpansionLimits,
    RetrievalCandidate,
    SymbolMetadata,
)
from barbarion.domain.reverse_engineering import (
    DependencyDirection,
    EvidenceClassification,
    RelationStatus,
    ResolutionStatus,
    SymbolStatus,
    TechnicalRelation,
    TechnicalSymbol,
)


DEFAULT_DATASET = Path("tests/fixtures/h33_graph_benchmark.json")
DEFAULT_OUTPUT = Path("reports/h33")
RELATION_TYPES = frozenset(
    {"calls", "uses", "opens", "references", "parent_of", "precedes"}
)
POLICIES: dict[str, GraphExpansionLimits | None] = {
    "baseline": None,
    "shallow": GraphExpansionLimits(1, 2, 3, 4),
    "balanced": GraphExpansionLimits(2, 4, 6, 8),
    "wide": GraphExpansionLimits(2, 8, 12, 16),
    "deep_wide": GraphExpansionLimits(3, 8, 20, 30),
}


def load_dataset(path: Path = DEFAULT_DATASET) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("license") != "synthetic-for-barbarion":
        raise ValueError("El benchmark H3.3 debe ser sintético y publicable.")
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) < 6:
        raise ValueError("El benchmark H3.3 requiere al menos seis casos.")
    return payload


def run_benchmark(dataset: dict[str, Any], *, repetitions: int = 20) -> dict[str, Any]:
    policies = {
        name: _run_policy(dataset, limits, repetitions=repetitions)
        for name, limits in POLICIES.items()
    }
    return {
        "benchmark_id": "h33-graph-aware-v1",
        "dataset_id": dataset["dataset_id"],
        "license": dataset["license"],
        "repetitions": repetitions,
        "policies": policies,
        "recommendation": _recommend(policies),
    }


def _run_policy(
    dataset: dict[str, Any],
    limits: GraphExpansionLimits | None,
    *,
    repetitions: int,
) -> dict[str, Any]:
    case_results = []
    elapsed_samples = []
    for case in dataset["cases"]:
        result = None
        for _ in range(repetitions):
            started = time.perf_counter_ns()
            current = _run_case(case, limits, top_k=int(dataset["top_k"]))
            elapsed_samples.append((time.perf_counter_ns() - started) / 1_000_000)
            result = current
        case_results.append(result)
    multi = tuple(case for case in case_results if case["expected_count"] > 1)
    simple = next(case for case in case_results if case["id"] == "simple-point-query")
    return {
        "limits": None if limits is None else {
            "max_depth": limits.max_depth,
            "max_seeds": limits.max_seeds,
            "max_neighbors_per_seed": limits.max_neighbors_per_seed,
            "max_candidates": limits.max_candidates,
        },
        "metrics": {
            "multi_component_recall": round(mean(case["recall"] for case in multi), 6),
            "simple_recall": simple["recall"],
            "noise_ratio": round(
                sum(case["noise_count"] for case in case_results)
                / max(1, sum(case["selected_count"] for case in case_results)),
                6,
            ),
            "selected_chunks_avg": round(mean(case["selected_count"] for case in case_results), 3),
            "context_tokens_est_avg": round(mean(case["context_tokens_est"] for case in case_results), 3),
            "relations_seen_avg": round(mean(case["relations_seen"] for case in case_results), 3),
            "latency_ms_median_like": round(sorted(elapsed_samples)[len(elapsed_samples) // 2], 6),
            "latency_ms_avg": round(mean(elapsed_samples), 6),
        },
        "cases": case_results,
        "provider_evidence_equal": all(case["provider_evidence_equal"] for case in case_results),
    }


def _run_case(
    case: dict[str, Any],
    limits: GraphExpansionLimits | None,
    *,
    top_k: int,
) -> dict[str, Any]:
    symbols = tuple(_symbol(name) for name in case["symbols"])
    by_name = {symbol.normalized_name: symbol for symbol in symbols}
    relations = tuple(
        _relation(by_name[source], by_name[target], relation_type)
        for source, target, relation_type in case["relations"]
    )
    repository = _Repository(symbols, relations)
    rag_repository = _RagRepository(symbols)
    direct = tuple(_direct_candidate(by_name[name], rank=index) for index, name in enumerate(case["direct"]))
    graph_candidates: tuple[RetrievalCandidate, ...] = ()
    graph_metrics: dict[str, object] = {}
    if limits is not None:
        retriever = GraphAwareEvidenceRetriever(
            expansion_service=GraphExpansionService(repository, "benchmark"),
            resolver=GraphEvidenceResolver(repository, rag_repository, "benchmark"),
            limits=limits,
            relation_types=RELATION_TYPES,
            direction=DependencyDirection.OUTGOING,
            min_confidence=Confidence.LOW,
        )
        graph_result = retriever.retrieve(direct)
        graph_candidates = graph_result.candidates
        graph_metrics = dict(graph_result.metrics)
    structural, chunks = _prepare_graph_aware_families((), graph_candidates, direct)
    selected, _decisions = _select_ask_candidates_relevance_first(
        structural,
        chunks,
        limit=top_k,
        dedupe_min_hash_prefix=16,
        question=case["question"],
    )
    context = ContextBuilder(
        token_budget=6000,
        max_chunk_tokens=1200,
        dedupe_min_hash_prefix=16,
        threshold=0,
        selection_policy="optimized_v1",
    ).build(selected)
    selected_ids = tuple(source.candidate.chunk_id for source in context.sources)
    expected_ids = tuple(f"chunk-{name}" for name in case["expected"])
    recall = len(set(selected_ids) & set(expected_ids)) / len(expected_ids)
    noise = len(set(selected_ids) - set(expected_ids))
    # Retrieval es anterior al proveedor: ambos adaptadores reciben el mismo contexto.
    provider_sets = {provider: selected_ids for provider in ("ollama", "anthropic")}
    return {
        "id": case["id"],
        "expected_count": len(expected_ids),
        "selected_count": len(selected_ids),
        "selected": selected_ids,
        "recall": round(recall, 6),
        "noise_count": noise,
        "context_tokens_est": context.token_estimate,
        "relations_seen": int(graph_metrics.get("graph_relations_seen", 0)),
        "provider_evidence_equal": provider_sets["ollama"] == provider_sets["anthropic"],
    }


def _recommend(policies: dict[str, Any]) -> dict[str, Any]:
    eligible = [
        (name, result)
        for name, result in policies.items()
        if name != "baseline"
        and result["metrics"]["multi_component_recall"] >= 0.95
        and result["metrics"]["simple_recall"] == 1.0
        and result["metrics"]["noise_ratio"] <= 0.15
    ]
    if not eligible:
        return {"policy": None, "reason": "ninguna política satisface el gate"}
    name, result = min(
        eligible,
        key=lambda item: (
            item[1]["metrics"]["context_tokens_est_avg"],
            sum(item[1]["limits"].values()),
            item[1]["metrics"]["latency_ms_avg"],
        ),
    )
    return {
        "policy": name,
        "limits": result["limits"],
        "reason": "menor contexto y menor amplitud entre políticas con recall>=0.95, simple sin regresión y ruido<=0.15",
    }


def write_report(result: dict[str, Any], output: Path = DEFAULT_OUTPUT) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "benchmark.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    lines = [
        "# H3.3 — Benchmark Graph-Aware Retrieval",
        "",
        "| Política | Recall multi | Ruido | Chunks | Tokens contexto | Latencia ms |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, policy in result["policies"].items():
        metric = policy["metrics"]
        lines.append(
            f"| {name} | {metric['multi_component_recall']:.3f} | "
            f"{metric['noise_ratio']:.3f} | {metric['selected_chunks_avg']:.3f} | "
            f"{metric['context_tokens_est_avg']:.3f} | {metric['latency_ms_avg']:.3f} |"
        )
    recommendation = result["recommendation"]
    lines.extend(("", f"Recomendación: `{recommendation['policy']}` — {recommendation['reason']}"))
    (output / "benchmark.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _symbol(name: str) -> TechnicalSymbol:
    technology = "configuration" if name == "cfg" else "oracle"
    symbol_type = "configuration_record" if name == "cfg" else "procedure"
    return TechnicalSymbol(
        symbol_id=_sha(f"symbol:{name}"),
        original_name=name.upper(),
        normalized_name=name,
        symbol_type=symbol_type,
        technology=technology,
        extraction_method="benchmark",
        confidence=Confidence.HIGH,
        file_id=1,
        chunk_id=f"chunk-{name}",
        status=SymbolStatus.ACTIVE,
    )


def _relation(source: TechnicalSymbol, target: TechnicalSymbol, relation_type: str) -> TechnicalRelation:
    relation_id = _sha(f"relation:{source.normalized_name}:{target.normalized_name}:{relation_type}")
    return TechnicalRelation(
        relation_id=relation_id,
        reference_id=_sha(f"reference:{relation_id}"),
        relation_type=relation_type,
        classification=EvidenceClassification.DETECTED,
        resolution_status=ResolutionStatus.RESOLVED,
        confidence=Confidence.HIGH,
        evidence_file_id=1,
        source_symbol_id=source.symbol_id,
        target_symbol_id=target.symbol_id,
        target_key=target.normalized_name,
        status=RelationStatus.ACTIVE,
    )


def _direct_candidate(symbol: TechnicalSymbol, *, rank: int) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=symbol.chunk_id or "",
        content_sha256=_sha(f"content:{symbol.normalized_name}"),
        combined_score=max(0.1, 1.0 - (rank * 0.05)),
        keyword_score=max(0.1, 1.0 - (rank * 0.05)),
        metadata=SymbolMetadata(symbol_name=symbol.normalized_name, symbol_kind=symbol.symbol_type),
        source={"content": _content(symbol), "domain": "benchmark"},
    )


def _content(symbol: TechnicalSymbol) -> str:
    return f"Componente {symbol.normalized_name}. Evidencia sintética publicable de su responsabilidad."


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class _Repository:
    def __init__(self, symbols, relations) -> None:
        self.symbols = {symbol.symbol_id: symbol for symbol in symbols}
        self.by_chunk = {symbol.chunk_id: (symbol,) for symbol in symbols}
        self.relations = tuple(relations)

    def get_symbol(self, symbol_id):
        return self.symbols.get(symbol_id)

    def active_symbols_for_chunk(self, chunk_id):
        return self.by_chunk.get(chunk_id, ())

    def symbol_domain(self, symbol_id):
        return "benchmark" if symbol_id in self.symbols else None

    def active_relations_for_symbol(self, symbol_id, *, direction):
        values = tuple(
            relation
            for relation in self.relations
            if relation.status == RelationStatus.ACTIVE
            and (
                (direction == DependencyDirection.OUTGOING and relation.source_symbol_id == symbol_id)
                or (direction == DependencyDirection.INCOMING and relation.target_symbol_id == symbol_id)
                or (direction == DependencyDirection.BOTH and symbol_id in (relation.source_symbol_id, relation.target_symbol_id))
            )
        )
        return tuple(sorted(values, key=lambda relation: (relation.relation_type, relation.target_key or "", relation.relation_id)))

    def relation_candidates(self, relation_id):
        return ()

    def get_relation(self, relation_id):
        return next((relation for relation in self.relations if relation.relation_id == relation_id), None)

    def get_reference(self, reference_id):
        return None


class _RagRepository:
    def __init__(self, symbols) -> None:
        self.content = {symbol.chunk_id: _content(symbol) for symbol in symbols}

    def active_chunk_exists(self, chunk_id, *, domain):
        return domain == "benchmark" and chunk_id in self.content

    def enrich_candidates(self, candidates, *, include_snippets):
        return tuple(
            replace(
                candidate,
                content_sha256=_sha(f"content:{candidate.chunk_id}"),
                source={"content": self.content[candidate.chunk_id], **dict(candidate.source)},
            )
            for candidate in candidates
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--repetitions", type=int, default=20)
    args = parser.parse_args()
    result = run_benchmark(load_dataset(args.dataset), repetitions=args.repetitions)
    write_report(result, args.output)
    print(json.dumps(result["recommendation"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
