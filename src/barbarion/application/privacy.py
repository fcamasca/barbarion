"""Composicion local del destino de inferencia para H3.2."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit

from barbarion.config import Settings
from barbarion.domain.privacy import (
    ConstraintEvaluation,
    EvaluationState,
    InferenceExecution,
    InferenceTarget,
    PrivacyConstraint,
    PrivacyEvidence,
    PrivacyPolicy,
    PrivacyPreflightResult,
)


OLLAMA_CLOUD_API_HOST = "ollama.com"
NO_TRAINING_GUARANTEED = "no_training_guaranteed"
TRAINING_CONFIRMED = "training_confirmed"
TRAINING_OPT_OUT_AVAILABLE = "opt_out_available"
ZERO_DATA_RETENTION = "zdr"
ZERO_DATA_RETENTION_AVAILABLE = "zdr_available"


class InferenceTargetResolutionError(ValueError):
    """La declaracion del operador contradice el transporte demostrado."""


def resolve_inference_target(settings: Settings) -> InferenceTarget:
    """Resuelve la frontera sin IO, politicas, registry, cache ni nombres modelo."""
    provider = settings.llm.provider
    if provider == "anthropic":
        return InferenceTarget(
            execution=InferenceExecution.REMOTE,
            provider="anthropic",
            platform="direct_api",
            model=settings.llm.model,
        )
    if provider != "ollama":
        return InferenceTarget(
            execution=InferenceExecution.UNKNOWN,
            provider=provider,
            platform=None,
            model=settings.llm.model,
        )
    return _resolve_ollama_target(settings)


def _resolve_ollama_target(settings: Settings) -> InferenceTarget:
    parsed = urlsplit(settings.ollama_url)
    host = (parsed.hostname or "").lower().rstrip(".")
    direct_cloud = parsed.scheme.lower() == "https" and host == OLLAMA_CLOUD_API_HOST
    declared = settings.llm.execution

    if direct_cloud:
        if declared == "local":
            raise InferenceTargetResolutionError(
                "llm.execution=local contradice el endpoint remoto ollama.com."
            )
        return InferenceTarget(
            execution=InferenceExecution.REMOTE,
            provider="ollama",
            platform="ollama_cloud",
            model=settings.llm.model,
        )

    if declared == "local":
        return InferenceTarget(
            execution=InferenceExecution.LOCAL,
            provider="ollama",
            platform="local_runtime",
            model=settings.llm.model,
        )
    if declared == "remote":
        return InferenceTarget(
            execution=InferenceExecution.REMOTE,
            provider="ollama",
            platform="ollama_cloud",
            model=settings.llm.model,
        )

    # Un daemon Ollama, incluso loopback, puede offloadear al cloud. Sin una
    # declaracion o endpoint directo demostrable, fail-closed comienza en UNKNOWN.
    return InferenceTarget(
        execution=InferenceExecution.UNKNOWN,
        provider="ollama",
        platform=None,
        model=settings.llm.model,
    )


def evaluate_no_training(
    evidence: tuple[PrivacyEvidence, ...],
    *,
    evaluated_at: datetime,
) -> ConstraintEvaluation:
    """Evalua no-training sin consultar ninguna fuente externa."""
    observed, applicable = _evidence_for(
        evidence,
        constraint=PrivacyConstraint.NO_TRAINING,
        evaluated_at=evaluated_at,
    )
    values = {item.value for item in applicable}
    guaranteed = tuple(
        item for item in applicable if item.value == NO_TRAINING_GUARANTEED
    )
    confirmed = tuple(
        item for item in applicable if item.value == TRAINING_CONFIRMED
    )

    if guaranteed and confirmed:
        return _evaluation(
            PrivacyConstraint.NO_TRAINING,
            EvaluationState.UNKNOWN,
            "conflicting_training_evidence",
            observed,
        )
    if confirmed:
        return _evaluation(
            PrivacyConstraint.NO_TRAINING,
            EvaluationState.FAIL,
            "training_confirmed",
            confirmed,
        )
    if guaranteed and values == {NO_TRAINING_GUARANTEED}:
        return _evaluation(
            PrivacyConstraint.NO_TRAINING,
            EvaluationState.PASS,
            "no_training_guaranteed",
            guaranteed,
        )
    reason = (
        "training_opt_out_only"
        if TRAINING_OPT_OUT_AVAILABLE in values
        else "no_training_unknown"
    )
    return _evaluation(
        PrivacyConstraint.NO_TRAINING,
        EvaluationState.UNKNOWN,
        reason,
        observed,
    )


def evaluate_retention(
    evidence: tuple[PrivacyEvidence, ...],
    *,
    evaluated_at: datetime,
) -> ConstraintEvaluation:
    """Evalua ZDR/retencion efectiva sin inferir habilitacion de una capability."""
    observed, applicable = _evidence_for(
        evidence,
        constraint=PrivacyConstraint.RETENTION,
        evaluated_at=evaluated_at,
    )
    zero = tuple(
        item
        for item in applicable
        if item.value == ZERO_DATA_RETENTION
        or (type(item.value) is int and item.value == 0)
    )
    positive = tuple(
        item
        for item in applicable
        if type(item.value) is int and item.value > 0
    )
    values = {item.value for item in applicable}

    if zero and positive:
        return _evaluation(
            PrivacyConstraint.RETENTION,
            EvaluationState.UNKNOWN,
            "conflicting_retention_evidence",
            observed,
        )
    if positive:
        return _evaluation(
            PrivacyConstraint.RETENTION,
            EvaluationState.FAIL,
            "positive_retention_confirmed",
            positive,
        )
    recognized = {
        ZERO_DATA_RETENTION,
        ZERO_DATA_RETENTION_AVAILABLE,
        0,
    }
    if zero and values.issubset(recognized):
        return _evaluation(
            PrivacyConstraint.RETENTION,
            EvaluationState.PASS,
            "zero_data_retention_effective",
            zero,
        )
    reason = (
        "zdr_available_not_effective"
        if ZERO_DATA_RETENTION_AVAILABLE in values
        else "retention_unknown"
    )
    return _evaluation(
        PrivacyConstraint.RETENTION,
        EvaluationState.UNKNOWN,
        reason,
        observed,
    )


def evaluate_data_location(
    evidence: tuple[PrivacyEvidence, ...],
    *,
    policy: PrivacyPolicy,
    evaluated_at: datetime,
) -> ConstraintEvaluation:
    """Exige ubicacion conocida y aplica allowlist solo cuando existe."""
    observed, applicable = _evidence_for(
        evidence,
        constraint=PrivacyConstraint.DATA_LOCATION,
        evaluated_at=evaluated_at,
    )
    locations = {
        item.value
        for item in applicable
        if isinstance(item.value, str)
    }
    if len(locations) != 1:
        reason = (
            "conflicting_data_locations"
            if len(locations) > 1
            else "data_location_unknown"
        )
        return _evaluation(
            PrivacyConstraint.DATA_LOCATION,
            EvaluationState.UNKNOWN,
            reason,
            observed,
        )

    location = next(iter(locations))
    location_evidence = tuple(
        item for item in applicable if item.value == location
    )
    if policy.allowed_regions is not None and location not in policy.allowed_regions:
        return _evaluation(
            PrivacyConstraint.DATA_LOCATION,
            EvaluationState.FAIL,
            "data_location_not_allowed",
            location_evidence,
        )
    return _evaluation(
        PrivacyConstraint.DATA_LOCATION,
        EvaluationState.PASS,
        "data_location_known",
        location_evidence,
    )


def aggregate_remote_result(
    *,
    target: InferenceTarget,
    policy: PrivacyPolicy,
    evaluated_at: datetime,
    evaluations: tuple[ConstraintEvaluation, ...],
) -> PrivacyPreflightResult:
    """Agrega exclusivamente un target remoto con la regla all-PASS."""
    if target.execution is not InferenceExecution.REMOTE:
        raise ValueError("aggregate_remote_result requiere execution=remote.")
    return PrivacyPreflightResult(
        target=target,
        policy=policy,
        evaluated_at=evaluated_at,
        evaluations=evaluations,
    )


def _evidence_for(
    evidence: tuple[PrivacyEvidence, ...],
    *,
    constraint: PrivacyConstraint,
    evaluated_at: datetime,
) -> tuple[tuple[PrivacyEvidence, ...], tuple[PrivacyEvidence, ...]]:
    observed = tuple(item for item in evidence if item.constraint is constraint)
    applicable = tuple(
        item
        for item in observed
        if item.is_valid_at(evaluated_at) and not item.conditional_on_account
    )
    return observed, applicable


def _evaluation(
    constraint: PrivacyConstraint,
    state: EvaluationState,
    reason_code: str,
    evidence: tuple[PrivacyEvidence, ...],
) -> ConstraintEvaluation:
    return ConstraintEvaluation(
        constraint=constraint,
        state=state,
        reason_code=reason_code,
        evidence=evidence,
    )
