"""Scoring lexical versionado y agregacion honesta del benchmark."""

from __future__ import annotations

import re
import statistics
import unicodedata
from collections import Counter
from dataclasses import dataclass

from barbarion.domain.model_benchmark import (
    BenchmarkRunStatus,
    BenchmarkUnitStatus,
    InstructionKind,
    ModelBenchmarkAggregate,
    ModelBenchmarkCase,
    ModelBenchmarkCaseMetrics,
    ModelBenchmarkCaseScore,
    ModelBenchmarkRunResult,
)
from barbarion.domain.rag import CitationValidation


SCORING_VERSION = 1
METRIC_WEIGHTS = {
    "answer_quality": 0.20,
    "instruction_following": 0.10,
    "groundedness": 0.20,
    "context_use": 0.10,
    "citation_score": 0.15,
    "validator_acceptance": 0.25,
}
_CITATION = re.compile(r"\[(F\d+)\]")
_SPANISH_CUES = frozenset(
    ("el", "la", "los", "las", "de", "del", "y", "es", "en", "con", "no")
)


@dataclass(frozen=True, slots=True)
class DeterministicModelScorer:
    """Aplica reglas declaradas sin LLM juez ni conocimiento externo."""

    def score(
        self,
        case: ModelBenchmarkCase,
        answer: str,
        validation: CitationValidation,
    ) -> ModelBenchmarkCaseScore:
        normalized = _normalize(answer)
        cited = frozenset(_CITATION.findall(answer))
        satisfied_facts = tuple(
            fact.id
            for fact in case.expected_facts
            if all(_normalize(term) in normalized for term in fact.all_terms)
        )
        missed_facts = tuple(
            fact.id for fact in case.expected_facts if fact.id not in satisfied_facts
        )
        detected_forbidden = tuple(
            claim.id
            for claim in case.forbidden_claims
            if any(_normalize(term) in normalized for term in claim.any_terms)
        )
        satisfied_instructions = tuple(
            instruction.id
            for instruction in case.instructions
            if _instruction_satisfied(instruction.kind, instruction.value, answer)
        )
        failed_instructions = tuple(
            instruction.id
            for instruction in case.instructions
            if instruction.id not in satisfied_instructions
        )

        fact_ratio = _ratio(len(satisfied_facts), len(case.expected_facts))
        forbidden_ratio = _ratio(
            len(detected_forbidden),
            len(case.forbidden_claims),
        )
        answer_quality = (
            None
            if fact_ratio is None
            else max(0.0, fact_ratio - (forbidden_ratio or 0.0))
        )
        instruction_following = _ratio(
            len(satisfied_instructions),
            len(case.instructions),
        )
        evaluable = len(case.expected_facts) + len(case.forbidden_claims)
        groundedness = _ratio(
            len(satisfied_facts)
            + len(case.forbidden_claims)
            - len(detected_forbidden),
            evaluable,
        )
        contextual_facts = tuple(
            fact for fact in case.expected_facts if fact.citations
        )
        context_hits = sum(
            fact.id in satisfied_facts and bool(cited.intersection(fact.citations))
            for fact in contextual_facts
        )
        context_use = _ratio(context_hits, len(contextual_facts))
        allowed = frozenset(
            fragment.citation_id for fragment in case.context
        )
        citation_presence = 1.0 if cited else 0.0
        citation_validity = (
            1.0
            if cited and not validation.missing_source_ids and cited <= allowed
            else 0.0
        )
        citation_coverage = _ratio(context_hits, len(contextual_facts))
        citation_score = _mean_present(
            (citation_presence, citation_validity, citation_coverage)
        )
        metrics = ModelBenchmarkCaseMetrics(
            answer_quality=_rounded(answer_quality),
            instruction_following=_rounded(instruction_following),
            groundedness=_rounded(groundedness),
            context_use=_rounded(context_use),
            citation_score=_rounded(citation_score),
            validator_acceptance=1.0 if validation.valid else 0.0,
        )
        quality, applied_weight = _weighted_quality(metrics)
        return ModelBenchmarkCaseScore(
            metrics=metrics,
            quality_score=quality,
            recommendation_score=quality if validation.valid else None,
            applied_weight=applied_weight,
            satisfied_facts=satisfied_facts,
            missed_facts=missed_facts,
            detected_forbidden_claims=detected_forbidden,
            satisfied_instructions=satisfied_instructions,
            failed_instructions=failed_instructions,
        )


def aggregate_model_benchmark(
    run: ModelBenchmarkRunResult,
) -> tuple[ModelBenchmarkAggregate, ...]:
    """Agrega por modelo sin transformar observaciones ausentes en cero."""
    planned_per_model = run.planned_units // len(run.models) if run.models else 0
    aggregates = []
    for model in run.models:
        units = tuple(unit for unit in run.units if unit.model == model)
        completed = tuple(
            unit for unit in units if unit.status is BenchmarkUnitStatus.COMPLETED
        )
        scored = tuple(unit.score for unit in completed if unit.score is not None)
        validations = tuple(
            unit.validation for unit in completed if unit.validation is not None
        )
        acceptance_rate = _ratio(
            sum(validation.valid for validation in validations),
            len(validations),
        )
        prompt_tokens = tuple(
            unit.telemetry.prompt_eval_count
            for unit in completed
            if unit.telemetry is not None
            and unit.telemetry.prompt_eval_count is not None
        )
        output_tokens = tuple(
            unit.telemetry.eval_count
            for unit in completed
            if unit.telemetry is not None and unit.telemetry.eval_count is not None
        )
        durations = tuple(unit.duration_ms for unit in completed)
        recommendation_scores = tuple(
            score.recommendation_score
            for score in scored
            if score.recommendation_score is not None
        )
        failures = Counter(
            unit.error_code or "MODEL_BENCHMARK_INCOMPLETE"
            for unit in units
            if unit.status is BenchmarkUnitStatus.FAILED
        )
        all_completed = len(completed) == planned_per_model
        aggregates.append(
            ModelBenchmarkAggregate(
                model=model,
                planned_units=planned_per_model,
                confirmed_units=len(units),
                completed_units=len(completed),
                failed_units=len(units) - len(completed),
                completion_rate=_rounded(_ratio(len(completed), planned_per_model)) or 0.0,
                acceptance_rate=_rounded(acceptance_rate),
                mean_metrics=_mean_metrics(scored),
                mean_quality_score=_rounded(
                    _mean_present(tuple(score.quality_score for score in scored))
                ),
                recommendation_quality_score=_rounded(
                    _mean_present(recommendation_scores)
                ),
                recommendation_eligible=(
                    run.status is BenchmarkRunStatus.COMPLETED
                    and all_completed
                    and acceptance_rate is not None
                    and acceptance_rate >= 0.90
                ),
                average_duration_ms=_rounded(_mean_present(durations)),
                median_duration_ms=_rounded(_median(durations)),
                prompt_tokens_total=sum(prompt_tokens) if prompt_tokens else None,
                prompt_tokens_median=_rounded(_median(prompt_tokens)),
                prompt_tokens_coverage=_rounded(
                    _ratio(len(prompt_tokens), len(completed))
                ) or 0.0,
                output_tokens_total=sum(output_tokens) if output_tokens else None,
                output_tokens_median=_rounded(_median(output_tokens)),
                output_tokens_coverage=_rounded(
                    _ratio(len(output_tokens), len(completed))
                ) or 0.0,
                failures_by_code=tuple(sorted(failures.items())),
            )
        )
    return tuple(aggregates)


def _mean_metrics(
    scores: tuple[ModelBenchmarkCaseScore, ...],
) -> ModelBenchmarkCaseMetrics:
    names = tuple(METRIC_WEIGHTS)
    values = {
        name: _rounded(
            _mean_present(tuple(getattr(score.metrics, name) for score in scores))
        )
        for name in names
    }
    return ModelBenchmarkCaseMetrics(**values)


def _weighted_quality(metrics: ModelBenchmarkCaseMetrics) -> tuple[float | None, float]:
    available = tuple(
        (METRIC_WEIGHTS[name], getattr(metrics, name))
        for name in METRIC_WEIGHTS
        if getattr(metrics, name) is not None
    )
    weight = sum(item[0] for item in available)
    if not available or weight == 0:
        return None, 0.0
    value = sum(metric_weight * metric for metric_weight, metric in available) / weight
    return _rounded(value), _rounded(weight) or 0.0


def _instruction_satisfied(kind: InstructionKind, value: str, answer: str) -> bool:
    normalized = _normalize(answer)
    expected = _normalize(value)
    if kind is InstructionKind.LANGUAGE:
        tokens = set(re.findall(r"\w+", normalized))
        return bool(tokens.intersection(_SPANISH_CUES))
    if kind is InstructionKind.REQUIRED_SECTION:
        return re.search(rf"(?im)^\s*#{{1,6}}\s+{re.escape(value)}\s*$", answer) is not None
    if kind is InstructionKind.REQUIRED_PHRASE:
        return expected in normalized
    if kind is InstructionKind.FORBIDDEN_PHRASE:
        return expected not in normalized
    if kind is InstructionKind.MAX_SENTENCES:
        return _sentence_count(answer) <= int(value)
    return False


def _sentence_count(value: str) -> int:
    count = len(re.findall(r"[.!?]+(?:\s|$)", value.strip()))
    return count or (1 if value.strip() else 0)


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _mean_present(values) -> float | None:  # noqa: ANN001
    present = tuple(value for value in values if value is not None)
    return None if not present else statistics.fmean(present)


def _median(values) -> float | None:  # noqa: ANN001
    return None if not values else float(statistics.median(values))


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 6)
