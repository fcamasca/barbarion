"""Reporte JSON/Markdown y recomendacion determinista del benchmark."""

from __future__ import annotations

import json
import os
import statistics
from dataclasses import dataclass
from pathlib import Path

from barbarion.application.model_benchmark_scoring import (
    METRIC_WEIGHTS,
    SCORING_VERSION,
    aggregate_model_benchmark,
)
from barbarion.domain.model_benchmark import (
    BenchmarkRunStatus,
    BenchmarkUnitStatus,
    ModelBenchmarkAggregate,
    ModelBenchmarkRunResult,
)


@dataclass(frozen=True, slots=True)
class BenchmarkModelMetadata:
    model: str
    format: str | None = None
    family: str | None = None
    parameter_size: str | None = None
    quantization_level: str | None = None
    capabilities: tuple[str, ...] = ()
    diagnostic_code: str | None = None


@dataclass(frozen=True, slots=True)
class BenchmarkReportConditions:
    generated_at_utc: str
    barbarion_version: str
    python_version: str
    platform_system: str
    platform_release: str
    platform_machine: str
    ollama_version: str | None
    timeout_seconds: float
    model_metadata: tuple[BenchmarkModelMetadata, ...]


@dataclass(frozen=True, slots=True)
class BenchmarkRecommendation:
    candidate: str | None
    eligible_models: tuple[str, ...]
    reason: str
    lexical_tiebreak_used: bool = False


def recommend_model(
    run: ModelBenchmarkRunResult,
    aggregates: tuple[ModelBenchmarkAggregate, ...] | None = None,
) -> BenchmarkRecommendation:
    """Aplica elegibilidad y desempates sin cambiar configuracion."""
    values = aggregates or aggregate_model_benchmark(run)
    eligible = tuple(item for item in values if item.recommendation_eligible)
    if not eligible:
        reason = (
            "La corrida no esta completa."
            if run.status is not BenchmarkRunStatus.COMPLETED
            else "Ningun modelo completo alcanza aceptacion >= 0.90."
        )
        return BenchmarkRecommendation(None, (), reason)
    ordered = tuple(sorted(eligible, key=_recommendation_key))
    first = ordered[0]
    lexical_tie = len(ordered) > 1 and _quality_key(first) == _quality_key(ordered[1])
    reason = (
        "Candidato informativo segun aceptacion, score de respuestas aceptadas, "
        "mediana de latencia y nombre exacto."
    )
    if lexical_tie:
        reason += " El empate previo se resolvio por nombre exacto."
    return BenchmarkRecommendation(
        candidate=first.model,
        eligible_models=tuple(item.model for item in ordered),
        reason=reason,
        lexical_tiebreak_used=lexical_tie,
    )


def build_model_benchmark_payload(
    run: ModelBenchmarkRunResult,
    conditions: BenchmarkReportConditions,
) -> dict[str, object]:
    """Construye JSON detallado sin respuestas, prompts ni contexto."""
    aggregates = aggregate_model_benchmark(run)
    recommendation = recommend_model(run, aggregates)
    return {
        "schema_version": 1,
        "scoring_version": SCORING_VERSION,
        "run_id": run.run_id,
        "generated_at_utc": conditions.generated_at_utc,
        "status": run.status.value,
        "resumable": False,
        "dataset_id": run.dataset_id,
        "dataset_hash": run.dataset_hash,
        "models": list(run.models),
        "options": {
            "timeout_seconds": conditions.timeout_seconds,
            "temperature": 0.0,
            "executions_per_case_model": 1,
            "rotation": "offset = case_index % model_count",
        },
        "environment": _environment_payload(conditions),
        "model_metadata": [_metadata_payload(item) for item in conditions.model_metadata],
        "planned_units": run.planned_units,
        "confirmed_units": len(run.units),
        "completed_units": run.completed_units,
        "failed_units": run.failed_units,
        "recommendation": {
            "candidate": recommendation.candidate,
            "eligible_models": list(recommendation.eligible_models),
            "reason": recommendation.reason,
            "lexical_tiebreak_used": recommendation.lexical_tiebreak_used,
            "automatic_selection": False,
        },
        "weights": dict(METRIC_WEIGHTS),
        "aggregates": [_aggregate_payload(item) for item in aggregates],
        "units": [_unit_payload(unit) for unit in run.units],
    }


def render_model_benchmark_markdown(
    run: ModelBenchmarkRunResult,
    conditions: BenchmarkReportConditions,
) -> str:
    """Renderiza un informe estable centrado en evidencia y limites."""
    aggregates = aggregate_model_benchmark(run)
    recommendation = recommend_model(run, aggregates)
    lines = [
        "# Benchmark de modelos locales",
        "",
        "## Resumen y alcance",
        "",
        f"- Run: `{_md(run.run_id)}`",
        f"- Estado: `{run.status.value}`",
        f"- Dataset: `{_md(run.dataset_id)}`",
        f"- Hash del dataset: `{run.dataset_hash}`",
        f"- Unidades confirmadas: {len(run.units)} de {run.planned_units}",
        "- Alcance: compara modelos generativos locales; no evalua retrieval ni modifica RAG.",
        "",
        "## Condiciones de ejecucion",
        "",
        f"- Fecha UTC: `{_md(conditions.generated_at_utc)}`",
        f"- Barbarion: `{_md(conditions.barbarion_version)}`",
        f"- Python: `{_md(conditions.python_version)}`",
        f"- Plataforma: `{_md(conditions.platform_system)} {_md(conditions.platform_release)} ({_md(conditions.platform_machine)})`",
        f"- Ollama: `{_md(conditions.ollama_version or 'no informado')}`",
        f"- Timeout por generacion: {conditions.timeout_seconds:g} s",
        "- Temperatura: 0",
        "- Repeticiones: una por caso/modelo",
        "- Rotacion: `offset = case_index % model_count`",
        "",
        "### Metadata Ollama acotada",
        "",
        "| Modelo | Formato | Familia | Parametros | Cuantizacion | Capacidades | Diagnostico |",
        "|---|---|---|---|---|---|---|",
    ]
    for item in conditions.model_metadata:
        lines.append(
            "| "
            + " | ".join(
                (
                    _cell(item.model),
                    _cell(item.format),
                    _cell(item.family),
                    _cell(item.parameter_size),
                    _cell(item.quantization_level),
                    _cell(", ".join(item.capabilities) if item.capabilities else None),
                    _cell(item.diagnostic_code),
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Comparacion",
            "",
            "| Modelo | Completitud | Aceptacion | Quality | Quality recomendacion | Latencia mediana ms | Tokens salida | Cobertura tokens | Elegible |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for item in aggregates:
        lines.append(
            f"| {_cell(item.model)} | {_pct(item.completion_rate)} | {_pct(item.acceptance_rate)} | "
            f"{_number(item.mean_quality_score)} | {_number(item.recommendation_quality_score)} | "
            f"{_number(item.median_duration_ms)} | {_number(item.output_tokens_total)} | "
            f"{_pct(item.output_tokens_coverage)} | {'si' if item.recommendation_eligible else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Candidato recomendado",
            "",
            f"- Candidato: `{_md(recommendation.candidate)}`" if recommendation.candidate else "- Candidato: ninguno.",
            f"- Motivo: {recommendation.reason}",
            "- Regla: corrida completa, todos los casos completados y aceptacion >= 0.90; luego aceptacion descendente, quality de respuestas aceptadas descendente, mediana de latencia ascendente y nombre exacto.",
            "- Esta recomendacion no selecciona ni configura el modelo. La decision y `models select` son acciones humanas separadas.",
            "",
            "## Resultados por categoria",
            "",
            "| Categoria | Unidades | Quality promedio | Aceptadas | Fallidas |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for category in sorted({unit.category.value for unit in run.units}):
        category_units = tuple(unit for unit in run.units if unit.category.value == category)
        qualities = tuple(
            unit.score.quality_score
            for unit in category_units
            if unit.score is not None and unit.score.quality_score is not None
        )
        lines.append(
            f"| {_cell(category)} | {len(category_units)} | {_number(_mean(qualities))} | "
            f"{sum(unit.validation is not None and unit.validation.valid for unit in category_units)} | "
            f"{sum(unit.status is BenchmarkUnitStatus.FAILED for unit in category_units)} |"
        )
    lines.extend(
        [
            "",
            "## Resultados por caso",
            "",
            "| Caso | Modelo | Orden | Estado | Validador | Quality | Duracion ms | Hash contexto | Codigo |",
            "|---|---|---:|---|---|---:|---:|---|---|",
        ]
    )
    for unit in run.units:
        lines.append(
            f"| {_cell(unit.case_id)} | {_cell(unit.model)} | {unit.execution_order} | {unit.status.value} | "
            f"{_validator_text(unit.validation)} | {_number(unit.score.quality_score if unit.score else None)} | "
            f"{unit.duration_ms} | `{unit.context_hash[:12]}` | {_cell(unit.error_code)} |"
        )
    lines.extend(
        [
            "",
            "## Rendimiento y tokens",
            "",
            "Los tokens son aproximados y solo se agregan cuando Ollama los informa. `null` no se convierte en cero.",
            "",
            "| Modelo | Latencia promedio ms | Latencia mediana ms | Prompt tokens | Cobertura prompt | Salida tokens | Cobertura salida |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in aggregates:
        lines.append(
            f"| {_cell(item.model)} | {_number(item.average_duration_ms)} | {_number(item.median_duration_ms)} | "
            f"{_number(item.prompt_tokens_total)} | {_pct(item.prompt_tokens_coverage)} | "
            f"{_number(item.output_tokens_total)} | {_pct(item.output_tokens_coverage)} |"
        )
    lines.extend(["", "## Fallas y diagnosticos", ""])
    failures = tuple(unit for unit in run.units if unit.status is BenchmarkUnitStatus.FAILED)
    rejected = tuple(unit for unit in run.units if unit.validation is not None and not unit.validation.valid)
    lines.append(f"- Fallas operativas: {len(failures)}.")
    lines.append(f"- Respuestas rechazadas por el validador: {len(rejected)}.")
    if failures:
        for item in aggregates:
            for code, count in item.failures_by_code:
                lines.append(f"- `{_md(item.model)}` / `{_md(code)}`: {count}.")
    else:
        lines.append("- No se registraron codigos de falla operativa.")
    lines.extend(
        [
            "",
            "## Metodologia y formulas",
            "",
            "Las metricas son lexicales y deterministas; no se usa un LLM juez.",
            "",
            "```text",
            "quality_score =",
            "  0.20 * answer_quality +",
            "  0.10 * instruction_following +",
            "  0.20 * groundedness +",
            "  0.10 * context_use +",
            "  0.15 * citation_score +",
            "  0.25 * validator_acceptance",
            "```",
            "",
            "Las metricas no aplicables quedan `null` y los pesos restantes se renormalizan. Una respuesta rechazada conserva scores descriptivos, pero su score de recomendacion queda `null`.",
            "",
            "## Limitaciones",
            "",
            "- El score lexical aproxima calidad; no es una verdad semantica ni sustituye revision humana.",
            "- El resultado solo aplica al dataset, versiones, opciones y hardware registrados.",
            "- H1.1 usa una ejecucion por caso/modelo; no calcula p95 ni estima variabilidad.",
            "- No se ejecuta retrieval y el contexto sintetico permanece congelado.",
            "- El reporte omite respuestas completas, prompts y contexto para reducir exposicion.",
            "- Una corrida interrumpida o con fallas no produce candidato elegible.",
            "- El candidato, cuando existe, requiere revision humana y seleccion explicita posterior.",
            "",
        ]
    )
    return "\n".join(lines)


def write_model_benchmark_report(
    run: ModelBenchmarkRunResult,
    conditions: BenchmarkReportConditions,
    output_parent: Path,
) -> tuple[Path, Path]:
    """Crea un directorio unico y los dos artefactos sin overwrite."""
    run_directory = output_parent.expanduser().resolve() / "model-benchmarks" / run.run_id
    run_directory.mkdir(parents=True, exist_ok=False)
    json_path = run_directory / "model-benchmark.json"
    markdown_path = run_directory / "model-benchmark.md"
    _write_new(
        json_path,
        json.dumps(
            build_model_benchmark_payload(run, conditions),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    _write_new(markdown_path, render_model_benchmark_markdown(run, conditions))
    return json_path.resolve(), markdown_path.resolve()


def _write_new(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _recommendation_key(item: ModelBenchmarkAggregate) -> tuple[float, float, float, str]:
    return (
        -(item.acceptance_rate if item.acceptance_rate is not None else -1.0),
        -(item.recommendation_quality_score if item.recommendation_quality_score is not None else -1.0),
        item.median_duration_ms if item.median_duration_ms is not None else float("inf"),
        item.model,
    )


def _quality_key(item: ModelBenchmarkAggregate) -> tuple[float | None, float | None, float | None]:
    return (item.acceptance_rate, item.recommendation_quality_score, item.median_duration_ms)


def _environment_payload(value: BenchmarkReportConditions) -> dict[str, object]:
    return {
        "barbarion_version": value.barbarion_version,
        "python_version": value.python_version,
        "platform_system": value.platform_system,
        "platform_release": value.platform_release,
        "platform_machine": value.platform_machine,
        "ollama_version": value.ollama_version,
    }


def _metadata_payload(item: BenchmarkModelMetadata) -> dict[str, object]:
    return {
        "model": item.model,
        "format": item.format,
        "family": item.family,
        "parameter_size": item.parameter_size,
        "quantization_level": item.quantization_level,
        "capabilities": list(item.capabilities),
        "diagnostic_code": item.diagnostic_code,
    }


def _unit_payload(unit) -> dict[str, object]:  # noqa: ANN001
    validation = unit.validation
    telemetry = unit.telemetry
    return {
        "case_id": unit.case_id,
        "category": unit.category.value,
        "model": unit.model,
        "execution_order": unit.execution_order,
        "status": unit.status.value,
        "question_hash": unit.question_hash,
        "context_hash": unit.context_hash,
        "prompt_hash": unit.prompt_hash,
        "duration_ms": unit.duration_ms,
        "validator": None if validation is None else {
            "accepted": validation.valid,
            "missing_source_ids": list(validation.missing_source_ids),
            "cited_source_ids": list(validation.cited_source_ids),
            "unsupported_claims_count": len(validation.unsupported_claims),
            "contradiction_claims_count": len(validation.contradiction_claims),
            "reason": validation.reason,
        },
        "telemetry": None if telemetry is None else {
            "total_duration_ns": telemetry.total_duration_ns,
            "load_duration_ns": telemetry.load_duration_ns,
            "prompt_eval_duration_ns": telemetry.prompt_eval_duration_ns,
            "eval_duration_ns": telemetry.eval_duration_ns,
            "prompt_eval_count": telemetry.prompt_eval_count,
            "eval_count": telemetry.eval_count,
        },
        "score": _score_payload(unit.score),
        "error_code": unit.error_code,
        "error_detail": unit.error_detail,
    }


def _score_payload(score) -> dict[str, object] | None:  # noqa: ANN001
    if score is None:
        return None
    return {
        "metrics": {name: getattr(score.metrics, name) for name in METRIC_WEIGHTS},
        "quality_score": score.quality_score,
        "recommendation_score": score.recommendation_score,
        "applied_weight": score.applied_weight,
        "satisfied_facts": list(score.satisfied_facts),
        "missed_facts": list(score.missed_facts),
        "detected_forbidden_claims": list(score.detected_forbidden_claims),
        "satisfied_instructions": list(score.satisfied_instructions),
        "failed_instructions": list(score.failed_instructions),
    }


def _aggregate_payload(item: ModelBenchmarkAggregate) -> dict[str, object]:
    return {
        "model": item.model,
        "planned_units": item.planned_units,
        "confirmed_units": item.confirmed_units,
        "completed_units": item.completed_units,
        "failed_units": item.failed_units,
        "completion_rate": item.completion_rate,
        "acceptance_rate": item.acceptance_rate,
        "mean_metrics": {name: getattr(item.mean_metrics, name) for name in METRIC_WEIGHTS},
        "mean_quality_score": item.mean_quality_score,
        "recommendation_quality_score": item.recommendation_quality_score,
        "recommendation_eligible": item.recommendation_eligible,
        "average_duration_ms": item.average_duration_ms,
        "median_duration_ms": item.median_duration_ms,
        "prompt_tokens_total": item.prompt_tokens_total,
        "prompt_tokens_median": item.prompt_tokens_median,
        "prompt_tokens_coverage": item.prompt_tokens_coverage,
        "output_tokens_total": item.output_tokens_total,
        "output_tokens_median": item.output_tokens_median,
        "output_tokens_coverage": item.output_tokens_coverage,
        "failures_by_code": dict(item.failures_by_code),
    }


def _md(value: str | None) -> str:
    return (value or "no informado").replace("`", "'").replace("\r", " ").replace("\n", " ")


def _cell(value: object | None) -> str:
    if value is None or value == "":
        return "null"
    return _md(str(value)).replace("|", "\\|")


def _number(value: int | float | None) -> str:
    if value is None:
        return "null"
    return f"{value:.6f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)


def _pct(value: float | None) -> str:
    return "null" if value is None else f"{value * 100:.2f}%"


def _validator_text(value) -> str:  # noqa: ANN001
    if value is None:
        return "null"
    return "accepted" if value.valid else "rejected"


def _mean(values: tuple[float, ...]) -> float | None:
    return None if not values else round(statistics.fmean(values), 6)
