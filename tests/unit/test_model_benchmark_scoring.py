"""Pruebas de metricas lexicales y renormalizacion v1."""

from dataclasses import replace

from barbarion.application.model_benchmark_dataset import load_model_benchmark_dataset
from barbarion.application.model_benchmark_scoring import (
    METRIC_WEIGHTS,
    DeterministicModelScorer,
)
from barbarion.domain.rag import CitationValidation


def test_full_supported_answer_scores_all_metrics_at_one() -> None:
    case = load_model_benchmark_dataset().cases[0]
    answer = "El Componente A es ámbar y el estado es estable [F1]."

    score = DeterministicModelScorer().score(
        case,
        answer,
        CitationValidation(valid=True, cited_source_ids=("F1",)),
    )

    assert score.metrics.answer_quality == 1.0
    assert score.metrics.instruction_following == 1.0
    assert score.metrics.groundedness == 1.0
    assert score.metrics.context_use == 1.0
    assert score.metrics.citation_score == 1.0
    assert score.metrics.validator_acceptance == 1.0
    assert score.quality_score == 1.0
    assert score.recommendation_score == 1.0


def test_forbidden_claim_penalizes_quality_and_groundedness_transparently() -> None:
    case = load_model_benchmark_dataset().cases[0]
    answer = "El Componente A es ámbar, azul y su estado es estable [F1]."

    score = DeterministicModelScorer().score(
        case,
        answer,
        CitationValidation(valid=False, cited_source_ids=("F1",)),
    )

    assert score.metrics.answer_quality == 0.0
    assert score.metrics.groundedness == 0.666667
    assert score.detected_forbidden_claims == ("forbidden-color",)
    assert score.quality_score is not None
    assert score.recommendation_score is None


def test_rejected_answer_keeps_partial_scores_but_cannot_contribute_recommendation() -> None:
    case = load_model_benchmark_dataset().cases[0]

    score = DeterministicModelScorer().score(
        case,
        "El Componente A es ámbar y el estado es estable [F1].",
        CitationValidation(valid=False, cited_source_ids=("F1",)),
    )

    assert score.metrics.answer_quality == 1.0
    assert score.metrics.context_use == 1.0
    assert score.metrics.validator_acceptance == 0.0
    assert score.quality_score == 0.75
    assert score.recommendation_score is None


def test_non_applicable_metric_is_null_and_remaining_weights_are_renormalized() -> None:
    case = replace(load_model_benchmark_dataset().cases[0], instructions=())

    score = DeterministicModelScorer().score(
        case,
        "El Componente A es ámbar y el estado es estable [F1].",
        CitationValidation(valid=True, cited_source_ids=("F1",)),
    )

    assert score.metrics.instruction_following is None
    assert score.applied_weight == 0.9
    assert score.quality_score == 1.0


def test_validator_has_the_single_largest_metric_weight() -> None:
    validator_weight = METRIC_WEIGHTS["validator_acceptance"]

    assert validator_weight == 0.25
    assert validator_weight > max(
        weight
        for name, weight in METRIC_WEIGHTS.items()
        if name != "validator_acceptance"
    )
    assert sum(METRIC_WEIGHTS.values()) == 1.0


def test_structural_and_length_instructions_are_checked_deterministically() -> None:
    case = load_model_benchmark_dataset().cases[2]

    compliant = DeterministicModelScorer().score(
        case,
        "## Conclusion\nLas etiquetas son alfa y beta [F1].",
        CitationValidation(valid=True, cited_source_ids=("F1",)),
    )
    missing_section = DeterministicModelScorer().score(
        case,
        "Las etiquetas son alfa y beta [F1].",
        CitationValidation(valid=True, cited_source_ids=("F1",)),
    )

    assert compliant.metrics.instruction_following == 1.0
    assert missing_section.metrics.instruction_following == 0.666667
    assert missing_section.failed_instructions == ("ins-section",)


def test_multiple_sources_report_partial_context_and_citation_coverage() -> None:
    case = load_model_benchmark_dataset().cases[6]

    score = DeterministicModelScorer().score(
        case,
        "La Pieza G aparece antes que la Pieza H [F1].",
        CitationValidation(valid=True, cited_source_ids=("F1",)),
    )

    assert score.metrics.answer_quality == 0.5
    assert score.metrics.context_use == 0.5
    assert score.metrics.citation_score == 0.833333


def test_empty_evaluable_rubrics_remain_null_instead_of_zero() -> None:
    case = replace(
        load_model_benchmark_dataset().cases[0],
        expected_facts=(),
        forbidden_claims=(),
    )

    score = DeterministicModelScorer().score(
        case,
        "La respuesta sintetica usa evidencia [F1].",
        CitationValidation(valid=True, cited_source_ids=("F1",)),
    )

    assert score.metrics.answer_quality is None
    assert score.metrics.groundedness is None
    assert score.metrics.context_use is None
    assert score.quality_score is not None
