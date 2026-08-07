"""Composicion local del destino de inferencia para H3.2."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from urllib.parse import urlsplit

from barbarion.config import Settings
from barbarion.domain.privacy import (
    AccountPrivacyVerificationResult,
    AccountPrivacyVerifier,
    AccountVerificationStatus,
    ConstraintEvaluation,
    EvaluationState,
    InferenceExecution,
    InferenceTarget,
    PrivacyConstraint,
    PrivacyEvidence,
    PrivacyAuthorization,
    PrivacyPolicy,
    PrivacyPolicySource,
    PrivacyPreflightDecision,
    PrivacyPreflightResult,
)


OLLAMA_CLOUD_API_HOST = "ollama.com"
NO_TRAINING_GUARANTEED = "no_training_guaranteed"
TRAINING_CONFIRMED = "training_confirmed"
TRAINING_OPT_OUT_AVAILABLE = "opt_out_available"
ZERO_DATA_RETENTION = "zdr"
ZERO_DATA_RETENTION_AVAILABLE = "zdr_available"
_LOGGER = logging.getLogger("barbarion")


class InferenceTargetResolutionError(ValueError):
    """La declaracion del operador contradice el transporte demostrado."""


class UnavailableAccountPrivacyVerifier:
    """Implementacion productiva v1: contrato presente, observacion ausente."""

    def verify(self, target: InferenceTarget) -> AccountPrivacyVerificationResult:
        if not isinstance(target, InferenceTarget):
            raise ValueError("target debe ser InferenceTarget.")
        return AccountPrivacyVerificationResult(
            status=AccountVerificationStatus.UNAVAILABLE,
            reason_code="account_verifier_unavailable",
        )


class InMemoryAccountPrivacyVerifier:
    """Fake contractual sin IO para demostrar extensibilidad futura."""

    def __init__(self, result: AccountPrivacyVerificationResult) -> None:
        if not isinstance(result, AccountPrivacyVerificationResult):
            raise ValueError("result debe ser AccountPrivacyVerificationResult.")
        self._result = result
        self.observed_targets: list[InferenceTarget] = []

    def verify(self, target: InferenceTarget) -> AccountPrivacyVerificationResult:
        if not isinstance(target, InferenceTarget):
            raise ValueError("target debe ser InferenceTarget.")
        self.observed_targets.append(target)
        return self._result


class PrivacyPreflightBlockedError(RuntimeError):
    """Decision segura que impide construir o enviar el prompt generativo."""

    def __init__(self, diagnostics: PrivacyPreflightDiagnostics) -> None:
        self.diagnostics = diagnostics
        self.result = diagnostics.result
        super().__init__("Privacy preflight bloqueo la inferencia remota.")


class InvalidPrivacyAuthorizationError(RuntimeError):
    """La autorizacion no corresponde a la invocacion generativa efectiva."""


@dataclass(frozen=True, slots=True)
class PrivacyPreflightDiagnostics:
    """Vista operacional segura, sin contenido ni payloads externos."""

    result: PrivacyPreflightResult
    cache_status: str
    account_verifier_status: str
    source_id: str | None = None
    source_version: str | None = None

    def as_safe_dict(self) -> dict[str, object]:
        target = self.result.target
        return {
            "decision": self.result.decision.value,
            "execution": target.execution.value,
            "provider": target.provider,
            "platform": target.platform,
            "offering": target.offering,
            "model": target.model,
            "policy": {
                "profile": self.result.policy.profile.value,
                "allowed_regions": self.result.policy.allowed_regions,
            },
            "cache_status": self.cache_status,
            "account_verifier": self.account_verifier_status,
            "source_id": self.source_id,
            "source_version": self.source_version,
            "constraints": {
                evaluation.constraint.value: {
                    "state": evaluation.state.value,
                    "reason_code": evaluation.reason_code,
                    "evidence": tuple(
                        {
                            "source_kind": item.source_kind,
                            "source_id": item.source_id,
                            "scope": item.scope,
                            "verified_at": item.verified_at.isoformat(),
                            "expires_at": item.expires_at.isoformat(),
                        }
                        for item in evaluation.evidence
                    ),
                }
                for evaluation in self.result.evaluations
            },
        }


@dataclass(frozen=True, slots=True)
class PrivacyPreflightOutcome:
    """Autorizacion y diagnostico producidos por una sola evaluacion."""

    authorization: PrivacyAuthorization
    diagnostics: PrivacyPreflightDiagnostics


@dataclass(frozen=True, slots=True)
class PrivacyPreflightService:
    """Combina evidencia local y evaluadores puros para emitir autorizacion."""

    policy: PrivacyPolicy
    policy_source: PrivacyPolicySource | None
    account_verifier: AccountPrivacyVerifier
    cache_status: str = "unknown"
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def authorize(
        self,
        *,
        operation_id: str,
        target: InferenceTarget,
    ) -> PrivacyAuthorization:
        return self.authorize_with_diagnostics(
            operation_id=operation_id,
            target=target,
        ).authorization

    def authorize_with_diagnostics(
        self,
        *,
        operation_id: str,
        target: InferenceTarget,
    ) -> PrivacyPreflightOutcome:
        evaluated_at = self.clock()
        if target.execution is InferenceExecution.LOCAL:
            result = PrivacyPreflightResult(
                target=target,
                policy=self.policy,
                evaluated_at=evaluated_at,
                evaluations=tuple(
                    ConstraintEvaluation(
                        constraint=constraint,
                        state=EvaluationState.NOT_APPLICABLE,
                        reason_code="local_inference",
                    )
                    for constraint in PrivacyConstraint
                ),
            )
            return _authorized_outcome(
                operation_id=operation_id,
                result=result,
                cache_status="not_consulted",
                account_status="not_consulted",
            )

        evidence: tuple[PrivacyEvidence, ...] = ()
        source_id = None
        source_version = None
        account_status = "not_consulted"
        if target.execution is InferenceExecution.REMOTE:
            if self.policy_source is not None:
                try:
                    source_result = self.policy_source.lookup(target)
                    evidence = source_result.evidence
                    source_id = source_result.source_id
                    source_version = source_result.source_version
                except Exception:
                    evidence = ()
            try:
                account = self.account_verifier.verify(target)
            except Exception:
                account = AccountPrivacyVerificationResult(
                    status=AccountVerificationStatus.ERROR,
                    reason_code="account_verifier_error",
                )
            account_status = account.status.value
            evidence = (*evidence, *account.evidence)

        evaluations = (
            evaluate_no_training(evidence, evaluated_at=evaluated_at),
            evaluate_retention(evidence, evaluated_at=evaluated_at),
            evaluate_data_location(
                evidence,
                policy=self.policy,
                evaluated_at=evaluated_at,
            ),
        )
        result = PrivacyPreflightResult(
            target=target,
            policy=self.policy,
            evaluated_at=evaluated_at,
            evaluations=evaluations,
        )
        diagnostics = PrivacyPreflightDiagnostics(
            result=result,
            cache_status=(
                self.cache_status
                if target.execution is InferenceExecution.REMOTE
                else "not_consulted"
            ),
            account_verifier_status=account_status,
            source_id=source_id,
            source_version=source_version,
        )
        _log_privacy_preflight(diagnostics)
        if result.decision is PrivacyPreflightDecision.BLOCK:
            raise PrivacyPreflightBlockedError(diagnostics)
        return PrivacyPreflightOutcome(
            authorization=PrivacyAuthorization.issue(
                operation_id=operation_id,
                result=result,
            ),
            diagnostics=diagnostics,
        )


def _authorized_outcome(
    *,
    operation_id: str,
    result: PrivacyPreflightResult,
    cache_status: str,
    account_status: str,
) -> PrivacyPreflightOutcome:
    diagnostics = PrivacyPreflightDiagnostics(
        result=result,
        cache_status=cache_status,
        account_verifier_status=account_status,
    )
    _log_privacy_preflight(diagnostics)
    return PrivacyPreflightOutcome(
        authorization=PrivacyAuthorization.issue(
            operation_id=operation_id,
            result=result,
        ),
        diagnostics=diagnostics,
    )


def _log_privacy_preflight(diagnostics: PrivacyPreflightDiagnostics) -> None:
    safe = diagnostics.as_safe_dict()
    constraints = safe["constraints"]
    assert isinstance(constraints, dict)
    _LOGGER.info(
        "privacy_preflight decision=%s execution=%s provider=%s platform=%s "
        "no_training=%s retention=%s data_location=%s cache_status=%s "
        "account_verifier=%s source_id=%s source_version=%s",
        safe["decision"],
        safe["execution"],
        safe["provider"],
        safe["platform"],
        constraints["no_training"]["state"],
        constraints["retention"]["state"],
        constraints["data_location"]["state"],
        safe["cache_status"],
        safe["account_verifier"],
        safe["source_id"] or "none",
        safe["source_version"] or "none",
    )


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
    observed_values = {item.value for item in observed}
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
        if TRAINING_OPT_OUT_AVAILABLE in observed_values
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
    observed_values = {item.value for item in observed}

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
        if ZERO_DATA_RETENTION_AVAILABLE in observed_values
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
