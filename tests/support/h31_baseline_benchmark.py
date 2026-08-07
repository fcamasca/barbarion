"""Runner offline y determinista del benchmark baseline H3.1-T03."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from statistics import mean
from typing import Any

from barbarion.application.rag import (
    TOKEN_ESTIMATOR_ID,
    CitationValidator,
    ContextBuilder,
    PromptBuilder,
)
from barbarion.domain.rag import RetrievalCandidate


DEFAULT_DATASET = Path("tests/fixtures/h31_baseline_benchmark.json")
DEFAULT_OUTPUT = Path("reports/h31")


def load_dataset(path: Path = DEFAULT_DATASET) -> dict[str, Any]:
    """Carga y valida las invariantes publicables minimas del dataset."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("license") != "synthetic-for-barbarion":
        raise ValueError("El benchmark H3.1 debe declarar origen sintetico.")
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) < 10:
        raise ValueError("El benchmark H3.1 requiere al menos diez casos.")
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Los IDs del benchmark H3.1 deben ser unicos.")
    return payload


def run_baseline(dataset: dict[str, Any]) -> dict[str, Any]:
    """Ejecuta mediciones baseline sin modificar el pipeline productivo."""
    top_k = int(dataset["top_k"])
    cases = tuple(_run_case(case, top_k=top_k) for case in dataset["cases"])
    answerable = tuple(case for case in cases if case["expected_source_count"] > 0)
    generated = tuple(case for case in cases if case["generation"] is not None)
    answerable_generated = tuple(
        case for case in generated if case["expected_source_count"] > 0
    )
    repaired = tuple(case for case in cases if case["repair"] is not None)
    component_totals = _aggregate_components(generated, stage="generation")
    repair_component_totals = _aggregate_components(repaired, stage="repair")
    generation_tokens = sum(
        case["generation"]["tokens_est_local"] for case in generated
    )
    redundancy_tokens = sum(
        case["diagnostics"]["overlap_tokens_est_local"] for case in cases
    )
    return {
        "benchmark_id": "h31-t03-baseline-v1",
        "dataset_id": dataset["dataset_id"],
        "dataset_license": dataset["license"],
        "policy": "baseline_v1",
        "estimator_id": TOKEN_ESTIMATOR_ID,
        "optimization_enabled": False,
        "top_k": top_k,
        "case_count": len(cases),
        "answerable_case_count": len(answerable),
        "metrics": {
            "recall_at_5": _avg(answerable, "recall_at_5"),
            "recall_at_10": _avg(answerable, "recall_at_10"),
            "mrr": _avg(answerable, "mrr"),
            "selected_source_recall": _avg(
                answerable,
                "selected_source_recall",
            ),
            "fact_coverage": _avg(answerable, "fact_coverage"),
            "citation_precision": _avg(answerable_generated, "citation_precision"),
            "citation_recall": _avg(answerable_generated, "citation_recall"),
            "citation_valid_rate": mean(
                1.0 if case["citations_valid"] else 0.0 for case in generated
            ),
            "insufficient_case_count": sum(
                1 for case in cases if case["result_status"] == "insufficient"
            ),
            "exact_duplicate_pairs": sum(
                case["diagnostics"]["exact_duplicate_count"] for case in cases
            ),
            "exact_duplicate_prompt_tokens_est_local": sum(
                case["diagnostics"]["exact_duplicate_prompt_tokens_est_local"]
                for case in cases
            ),
            "exact_duplicate_avoided_content_tokens_est_local": sum(
                case["diagnostics"][
                    "exact_duplicate_avoided_content_tokens_est_local"
                ]
                for case in cases
            ),
            "overlap_pairs": sum(
                len(case["diagnostics"]["overlap_pairs"]) for case in cases
            ),
            "overlap_chars": sum(
                case["diagnostics"]["overlap_chars"] for case in cases
            ),
            "overlap_tokens_est_local": redundancy_tokens,
            "redundancy_prompt_tokens_est_local": redundancy_tokens,
            "redundancy_share_of_generation_prompt": round(
                redundancy_tokens / generation_tokens if generation_tokens else 0.0,
                6,
            ),
            "generation_prompt_chars_total": sum(
                case["generation"]["chars"] for case in generated
            ),
            "generation_prompt_utf8_bytes_total": sum(
                case["generation"]["utf8_bytes"] for case in generated
            ),
            "generation_prompt_tokens_est_local_total": generation_tokens,
            "repair_prompt_count": len(repaired),
            "repair_prompt_chars_total": sum(
                case["repair"]["chars"] for case in repaired
            ),
            "repair_prompt_utf8_bytes_total": sum(
                case["repair"]["utf8_bytes"] for case in repaired
            ),
            "repair_prompt_tokens_est_local_total": sum(
                case["repair"]["tokens_est_local"] for case in repaired
            ),
        },
        "generation_components": component_totals,
        "repair_components": repair_component_totals,
        "cases": cases,
        "decisions": {
            "t04_t08_gate": "pending-human-review",
            "token_reduction_target": None,
            "rule": (
                "No optimization is authorized by T03; hypotheses may be "
                "confirmed, rejected or deferred from these measurements."
            ),
        },
    }


def _run_case(case: dict[str, Any], *, top_k: int) -> dict[str, Any]:
    candidates = tuple(
        _candidate(source, rank=index)
        for index, source in enumerate(case["sources"], start=1)
    )
    expected_facts = tuple(case["expected_facts"])
    expected_ids = tuple(dict.fromkeys(fact["chunk_id"] for fact in expected_facts))
    retrieved_ids = tuple(candidate.chunk_id for candidate in candidates)
    selected_candidates = candidates[:top_k]
    context = ContextBuilder(
        token_budget=6000,
        max_chunk_tokens=1200,
        dedupe_min_hash_prefix=16,
        threshold=0.0,
    ).build(selected_candidates, debug=True)
    selected_ids = tuple(source.candidate.chunk_id for source in context.sources)
    generation = None
    repair = None
    citations_valid = True
    citation_precision = 1.0
    citation_recall = 1.0 if not expected_ids else 0.0
    result_status = "insufficient" if not context.sources else "completed"
    answer = ""

    if context.sources:
        builder = PromptBuilder()
        generation_composition = builder.compose(
            question=case["question"],
            context=context,
        )
        generation = _composition_metrics(generation_composition)
        answer = _answer_for(
            expected_facts,
            context=context,
            force_invalid=bool(case.get("force_repair")),
        )
        validation = CitationValidator().validate(
            answer,
            context,
            question=case["question"],
        )
        if not validation.valid and case.get("force_repair"):
            repair_composition = builder.compose_repair(
                question=case["question"],
                context=context,
                answer=answer,
            )
            repair = _composition_metrics(repair_composition)
            answer = _answer_for(expected_facts, context=context)
            validation = CitationValidator().validate(
                answer,
                context,
                question=case["question"],
            )
        citations_valid = validation.valid
        citation_precision, citation_recall = _citation_metrics(
            answer,
            context=context,
            expected_ids=expected_ids,
        )
        if answer.lower().startswith("evidencia insuficiente"):
            result_status = "insufficient"
        elif not validation.valid:
            result_status = "error"

    cited_source_ids = set(re.findall(r"\[(F\d+)\]", answer))
    source_id_by_chunk = {
        source.candidate.chunk_id: source.source_id for source in context.sources
    }
    evidence_decisions = []
    for decision in context.debug["evidence_decisions"]:
        row = dict(decision)
        source_id = source_id_by_chunk.get(str(row["chunk_id"]))
        row["citation_status"] = (
            "not_selected"
            if source_id is None
            else "cited"
            if source_id in cited_source_ids
            else "not_cited"
        )
        evidence_decisions.append(row)
    return {
        "id": case["id"],
        "category": case["category"],
        "mode": case["mode"],
        "retrieved": retrieved_ids,
        "selected": selected_ids,
        "expected_sources": expected_ids,
        "expected_source_count": len(expected_ids),
        "recall_at_5": _recall(retrieved_ids[:5], expected_ids),
        "recall_at_10": _recall(retrieved_ids[:10], expected_ids),
        "mrr": _mrr(retrieved_ids, expected_ids),
        "selected_source_recall": _recall(selected_ids, expected_ids),
        "fact_coverage": _fact_coverage(expected_facts, context.rendered_context),
        "citation_precision": citation_precision,
        "citation_recall": citation_recall,
        "citations_valid": citations_valid,
        "result_status": result_status,
        "context": {
            "sources": len(context.sources),
            "chars": len(context.rendered_context),
            "tokens_est_local": context.token_estimate,
            "omitted": list(context.omitted),
        },
        "generation": generation,
        "repair": repair,
        "evidence_decisions": evidence_decisions,
        "diagnostics": _plain_value(context.debug["redundancy_report"]),
    }


def _candidate(source: dict[str, Any], *, rank: int) -> RetrievalCandidate:
    content = str(source["content"])
    metadata = {
        "document_id": int(source["document_id"]),
        "ordinal": int(source["ordinal"]),
        "relative_path": f"synthetic/{source['chunk_id']}.txt",
        "start_line": 1 + (int(source["ordinal"]) * 5),
        "end_line": 5 + (int(source["ordinal"]) * 5),
        "content": content,
    }
    if source.get("evidence_kind"):
        metadata["evidence_kind"] = source["evidence_kind"]
    return RetrievalCandidate(
        chunk_id=source["chunk_id"],
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        combined_score=max(0.01, 1.0 - ((rank - 1) * 0.08)),
        source=metadata,
    )


def _composition_metrics(composition: Any) -> dict[str, Any]:
    metrics = composition.metrics()
    return {
        "chars": metrics["chars"],
        "utf8_bytes": metrics["utf8_bytes"],
        "tokens_est_local": metrics["tokens_est_local"],
        "chars_reconciled": metrics["chars_reconciled"],
        "utf8_bytes_reconciled": metrics["utf8_bytes_reconciled"],
        "components": [dict(component) for component in metrics["components"]],
    }


def _answer_for(
    facts: tuple[dict[str, Any], ...],
    *,
    context: Any,
    force_invalid: bool = False,
) -> str:
    if force_invalid:
        return "Respuesta sintetica sin cita."
    source_by_chunk = {
        source.candidate.chunk_id: source.source_id for source in context.sources
    }
    supported = [fact for fact in facts if fact["chunk_id"] in source_by_chunk]
    if len(supported) != len(facts):
        first_id = context.sources[0].source_id
        return f"Evidencia insuficiente para confirmar el hecho solicitado [{first_id}]."
    return "\n".join(
        f"{fact['text']} [{source_by_chunk[fact['chunk_id']]}]."
        for fact in supported
    )


def _citation_metrics(
    answer: str,
    *,
    context: Any,
    expected_ids: tuple[str, ...],
) -> tuple[float, float]:
    cited_source_ids = set(re.findall(r"\[(F\d+)\]", answer))
    allowed = {source.source_id for source in context.sources}
    valid = cited_source_ids & allowed
    precision = len(valid) / len(cited_source_ids) if cited_source_ids else 0.0
    expected_citation_ids = {
        source.source_id
        for source in context.sources
        if source.candidate.chunk_id in expected_ids
    }
    if not expected_ids:
        recall = 1.0
    elif not expected_citation_ids:
        recall = 0.0
    else:
        recall = len(valid & expected_citation_ids) / len(expected_citation_ids)
    return round(precision, 6), round(recall, 6)


def _plain_value(value: Any) -> Any:
    if isinstance(value, dict) or hasattr(value, "items"):
        return {key: _plain_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain_value(item) for item in value]
    return value


def _fact_coverage(facts: tuple[dict[str, Any], ...], context: str) -> float:
    if not facts:
        return 1.0
    found = sum(1 for fact in facts if fact["text"] in context)
    return round(found / len(facts), 6)


def _recall(returned: tuple[str, ...], expected: tuple[str, ...]) -> float:
    if not expected:
        return 1.0
    return round(len(set(returned) & set(expected)) / len(set(expected)), 6)


def _mrr(returned: tuple[str, ...], expected: tuple[str, ...]) -> float:
    expected_set = set(expected)
    for rank, chunk_id in enumerate(returned, start=1):
        if chunk_id in expected_set:
            return round(1.0 / rank, 6)
    return 0.0


def _avg(cases: tuple[dict[str, Any], ...], key: str) -> float:
    return round(mean(float(case[key]) for case in cases), 6)


def _aggregate_components(
    cases: tuple[dict[str, Any], ...],
    *,
    stage: str,
) -> dict[str, dict[str, int]]:
    totals: dict[str, dict[str, int]] = {}
    for case in cases:
        composition = case[stage]
        if composition is None:
            continue
        for component in composition["components"]:
            row = totals.setdefault(
                component["kind"],
                {"chars": 0, "utf8_bytes": 0, "tokens_est_local": 0},
            )
            for metric in row:
                row[metric] += int(component[metric])
    return dict(sorted(totals.items()))


def write_reports(result: dict[str, Any], output_dir: Path = DEFAULT_OUTPUT) -> None:
    """Escribe JSON canonico y resumen Markdown determinista."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "t03-baseline.json"
    md_path = output_dir / "t03-baseline.md"
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(_render_markdown(result), encoding="utf-8")
    t04_result = _t04_report(result)
    (output_dir / "t04-redundancy-report.json").write_text(
        json.dumps(t04_result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "t04-redundancy-report.md").write_text(
        _render_t04_markdown(t04_result), encoding="utf-8"
    )


def _t04_report(result: dict[str, Any]) -> dict[str, Any]:
    metrics = result["metrics"]
    return {
        "report_id": "h31-t04-redundancy-report-v1",
        "dataset_id": result["dataset_id"],
        "policy": result["policy"],
        "mode": "report_only",
        "behavior_changed": False,
        "generation_prompt_tokens_est_local_total": metrics[
            "generation_prompt_tokens_est_local_total"
        ],
        "exact_duplicate_count": metrics["exact_duplicate_pairs"],
        "exact_duplicate_prompt_tokens_est_local": metrics[
            "exact_duplicate_prompt_tokens_est_local"
        ],
        "exact_duplicate_avoided_content_tokens_est_local": metrics[
            "exact_duplicate_avoided_content_tokens_est_local"
        ],
        "overlap_pair_count": metrics["overlap_pairs"],
        "overlap_chars": metrics["overlap_chars"],
        "overlap_tokens_est_local": metrics["overlap_tokens_est_local"],
        "redundancy_prompt_tokens_est_local": metrics[
            "redundancy_prompt_tokens_est_local"
        ],
        "redundancy_share_of_generation_prompt": metrics[
            "redundancy_share_of_generation_prompt"
        ],
        "coverage_gap_case_count": sum(
            1 for case in result["cases"] if case["fact_coverage"] < 1.0
        ),
        "decisions_by_action": _decision_counts(result["cases"]),
        "selected_not_cited_count": sum(
            1
            for case in result["cases"]
            for decision in case["evidence_decisions"]
            if decision["citation_status"] == "not_cited"
        ),
        "cases": [
            {
                "id": case["id"],
                "decisions": case["evidence_decisions"],
                "redundancy": case["diagnostics"],
                "fact_coverage": case["fact_coverage"],
                "result_status": case["result_status"],
            }
            for case in result["cases"]
        ],
        "assessment": "marginal",
        "decision": {
            "t07_focus": "supported-by-coverage-gap",
            "t08_trim_overlap": "candidate-for-deferral",
            "reason": (
                "Measured overlap explains less than one percent of generation "
                "prompt tokens; exact duplicates are already omitted by baseline_v1."
            ),
        },
    }


def _decision_counts(cases: tuple[dict[str, Any], ...]) -> dict[str, int]:
    counts = {"selected": 0, "truncated": 0, "omitted": 0}
    for case in cases:
        for decision in case["evidence_decisions"]:
            counts[decision["action"]] += 1
    return counts


def _render_t04_markdown(report: dict[str, Any]) -> str:
    share_percent = report["redundancy_share_of_generation_prompt"] * 100
    return "\n".join(
        [
            "# H3.1-T04 - Diagnostico report-only de redundancia",
            "",
            "## Resultado",
            "",
            "La duplicacion y el overlap son marginales en esta baseline. La politica",
            "efectiva permanece `baseline_v1`; no se elimina ni recorta evidencia.",
            "",
            "| Medicion | Valor |",
            "|---|---:|",
            f"| Prompt generation | `{report['generation_prompt_tokens_est_local_total']}` tokens est. |",
            f"| Duplicados exactos detectados | `{report['exact_duplicate_count']}` |",
            f"| Duplicados exactos enviados | `{report['exact_duplicate_prompt_tokens_est_local']}` tokens est. |",
            f"| Contenido duplicado ya evitado | `{report['exact_duplicate_avoided_content_tokens_est_local']}` tokens est. |",
            f"| Pares con overlap | `{report['overlap_pair_count']}` |",
            f"| Overlap enviado | `{report['overlap_chars']}` chars / `{report['overlap_tokens_est_local']}` tokens est. |",
            f"| Fraccion explicada del prompt | `{share_percent:.3f}%` |",
            f"| Casos con perdida de cobertura | `{report['coverage_gap_case_count']}` |",
            f"| Fuentes seleccionadas no citadas | `{report['selected_not_cited_count']}` |",
            "",
            "## Interpretacion",
            "",
            "El duplicado exacto no desperdicia prompt: la deduplicacion vigente ya lo",
            "omite. El unico overlap demostrado explica menos de 1% del total medido.",
            "En cambio, existe un caso con perdida total de cobertura porque la fuente",
            "necesaria queda en posicion seis. Los datos respaldan concentrar T07 en",
            "seleccion y considerar T08 diferible, sujeto a la decision formal posterior.",
            "",
            "## Garantia report-only",
            "",
            "Cada candidato registra `selected`, `truncated` u `omitted`, razones y",
            "contribucion estimada. El diagnostico no cambia fuentes, orden, contexto,",
            "presupuesto, prompt ni respuesta.",
            "",
        ]
    )


def _render_markdown(result: dict[str, Any]) -> str:
    metrics = result["metrics"]
    generation = result["generation_components"]
    total_generation_tokens = metrics["generation_prompt_tokens_est_local_total"]
    metadata_tokens = generation["source_metadata"]["tokens_est_local"]
    evidence_tokens = generation["source_content"]["tokens_est_local"]
    lines = [
        "# H3.1-T03 - Benchmark baseline",
        "",
        "## Estado",
        "",
        "Baseline reproducible sobre corpus sintetico. No habilita optimizaciones",
        "ni fija un objetivo de reduccion.",
        "El dataset y todas sus fuentes son sinteticos y publicables.",
        "",
        "## Metricas agregadas",
        "",
        "| Metrica | Valor |",
        "|---|---:|",
    ]
    for key, value in metrics.items():
        lines.append(f"| `{key}` | `{value}` |")
    lines.extend(
        [
            "",
            "## Composicion de generation",
            "",
            "| Componente | Chars | UTF-8 bytes | Tokens est. local |",
            "|---|---:|---:|---:|",
        ]
    )
    for kind, values in result["generation_components"].items():
        lines.append(
            f"| `{kind}` | {values['chars']} | {values['utf8_bytes']} | "
            f"{values['tokens_est_local']} |"
        )
    lines.extend(
        [
            "",
            "Metadata de fuentes: "
            f"`{metadata_tokens}` tokens (`{metadata_tokens / total_generation_tokens:.1%}` "
            "del prompt de generacion). Evidencia: "
            f"`{evidence_tokens}` tokens (`{evidence_tokens / total_generation_tokens:.1%}`).",
            "",
            "## Composicion de repair",
            "",
            "| Componente | Chars | UTF-8 bytes | Tokens est. local |",
            "|---|---:|---:|---:|",
        ]
    )
    for kind, values in result["repair_components"].items():
        lines.append(
            f"| `{kind}` | {values['chars']} | {values['utf8_bytes']} | "
            f"{values['tokens_est_local']} |"
        )
    lines.extend(
        [
            "",
            "## Casos",
            "",
            "| Caso | R@5 | R@10 | MRR | Evidencia | Hechos | Citas | Estado |",
            "|---|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for case in result["cases"]:
        lines.append(
            f"| `{case['id']}` | {case['recall_at_5']:.3f} | "
            f"{case['recall_at_10']:.3f} | {case['mrr']:.3f} | "
            f"{case['selected_source_recall']:.3f} | "
            f"{case['fact_coverage']:.3f} | "
            f"{'PASS' if case['citations_valid'] else 'FAIL'} | "
            f"{case['result_status']} |"
        )
    lines.extend(
        [
            "",
            "## Decision T03",
            "",
            "T03 no autoriza ninguna optimizacion. T04-T08 requieren revision",
            "humana de estos numeros y pueden confirmar, rechazar o diferir cada",
            "hipotesis inicial.",
            "",
            "Hallazgos observados: metadata supera a evidencia en la composicion",
            "medida; existe duplicacion exacta y overlap contiguo demostrable; y",
            "el caso con evidencia relevante en posicion seis conserva R@10 pero",
            "pierde cobertura bajo el top-k vigente. Son datos, no autorizaciones",
            "para modificar seleccion, ranking, presupuesto u overlap.",
            "",
            "## Reproduccion",
            "",
            "```powershell",
            "python -m tests.support.h31_baseline_benchmark --output reports/h31",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark baseline H3.1-T03")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run_baseline(load_dataset(args.dataset))
    write_reports(result, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
