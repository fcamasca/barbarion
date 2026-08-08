"""Pruebas de dominio puro para H3.2-T02."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from barbarion.domain.privacy import (
    ConstraintEvaluation,
    EvaluationState,
    InferenceExecution,
    InferenceTarget,
    PrivacyAuthorization,
    PrivacyConstraint,
    PrivacyEvidence,
    PrivacyPolicy,
    PrivacyPreflightDecision,
    PrivacyPreflightResult,
)


NOW = datetime(2026, 8, 7, 12, tzinfo=UTC)


def _target(execution: InferenceExecution) -> InferenceTarget:
    return InferenceTarget(
        execution=execution,
        provider="Synthetic-AI",
        platform=None if execution is InferenceExecution.UNKNOWN else "Direct_API",
        offering="Standard",
        model="New-Model-v99",
    )


def _evidence(constraint: PrivacyConstraint, *, expired: bool = False) -> PrivacyEvidence:
    verified_at = NOW - timedelta(days=2)
    expires_at = NOW - timedelta(seconds=1) if expired else NOW + timedelta(days=1)
    return PrivacyEvidence(
        constraint=constraint,
        value="guaranteed",
        scope="offering",
        source_kind="external_registry",
        source_id="synthetic-registry-v1",
        verified_at=verified_at,
        expires_at=expires_at,
    )


def _evaluation(
    constraint: PrivacyConstraint,
    state: EvaluationState,
    *,
    expired: bool = False,
) -> ConstraintEvaluation:
    evidence = (_evidence(constraint, expired=expired),) if state is EvaluationState.PASS else ()
    return ConstraintEvaluation(
        constraint=constraint,
        state=state,
        reason_code=f"synthetic_{state.value}",
        evidence=evidence,
    )


def _evaluations(state: EvaluationState) -> tuple[ConstraintEvaluation, ...]:
    return tuple(_evaluation(constraint, state) for constraint in PrivacyConstraint)


def _result(
    execution: InferenceExecution,
    evaluations: tuple[ConstraintEvaluation, ...],
) -> PrivacyPreflightResult:
    return PrivacyPreflightResult(
        target=_target(execution),
        policy=PrivacyPolicy(allowed_regions=("Region-B", "region-a")),
        evaluated_at=NOW,
        evaluations=evaluations,
    )


def test_h32_tp003_exposes_only_four_evaluation_states() -> None:
    assert {state.value for state in EvaluationState} == {
        "pass",
        "fail",
        "unknown",
        "not_applicable",
    }
    with pytest.raises(ValueError):
        EvaluationState("conditional")


def test_h32_tp004_local_requires_not_applicable() -> None:
    result = _result(
        InferenceExecution.LOCAL,
        _evaluations(EvaluationState.NOT_APPLICABLE),
    )
    assert result.decision is PrivacyPreflightDecision.NOT_APPLICABLE
    assert all(
        item.state is EvaluationState.NOT_APPLICABLE
        for item in result.evaluations
    )

    with pytest.raises(ValueError, match="local requiere NOT_APPLICABLE"):
        _result(InferenceExecution.LOCAL, _evaluations(EvaluationState.UNKNOWN))


def test_h32_tp004_remote_passes_only_when_every_constraint_passes() -> None:
    passing = _result(InferenceExecution.REMOTE, _evaluations(EvaluationState.PASS))
    assert passing.decision is PrivacyPreflightDecision.PASS

    for blocked_state in (EvaluationState.FAIL, EvaluationState.UNKNOWN):
        evaluations = list(_evaluations(EvaluationState.PASS))
        evaluations[1] = _evaluation(PrivacyConstraint.RETENTION, blocked_state)
        warning = _result(InferenceExecution.REMOTE, tuple(evaluations))
        assert warning.decision is PrivacyPreflightDecision.WARNING

    evaluations = list(_evaluations(EvaluationState.PASS))
    evaluations[2] = _evaluation(PrivacyConstraint.DATA_LOCATION, EvaluationState.UNKNOWN)
    assert _result(InferenceExecution.REMOTE, tuple(evaluations)).decision is PrivacyPreflightDecision.PASS


def test_h32_tp005_authorization_is_frozen_and_content_independent() -> None:
    result = _result(InferenceExecution.REMOTE, _evaluations(EvaluationState.PASS))
    authorization = PrivacyAuthorization.issue(operation_id="ASK-0001", result=result)

    assert authorization.operation_id == "ask-0001"
    assert authorization.target_fingerprint == result.target.fingerprint
    assert authorization.policy_fingerprint == result.policy.fingerprint
    assert len(authorization.target_fingerprint) == 64
    assert len(authorization.policy_fingerprint) == 64
    assert "query" not in authorization.__dataclass_fields__
    assert "prompt" not in authorization.__dataclass_fields__
    assert "content" not in authorization.__dataclass_fields__
    assert "evidence" not in authorization.__dataclass_fields__
    with pytest.raises(FrozenInstanceError):
        authorization.operation_id = "otro"  # type: ignore[misc]


def test_h32_tp005_fingerprints_are_canonical_and_scope_limited() -> None:
    target_a = _target(InferenceExecution.REMOTE)
    target_b = InferenceTarget(
        execution=InferenceExecution.REMOTE,
        provider=" synthetic-ai ",
        platform="direct_api",
        offering="standard",
        model="new-model-v99",
    )
    policy_a = PrivacyPolicy(allowed_regions=("region-b", "region-a"))
    policy_b = PrivacyPolicy(allowed_regions=("REGION-A", "REGION-B"))

    assert target_a.fingerprint == target_b.fingerprint
    assert policy_a.fingerprint == policy_b.fingerprint
    assert target_a.fingerprint != policy_a.fingerprint


def test_h32_tp006_unknown_execution_always_blocks_authorization() -> None:
    unknown = _result(
        InferenceExecution.UNKNOWN,
        _evaluations(EvaluationState.PASS),
    )
    assert unknown.decision is PrivacyPreflightDecision.BLOCK
    with pytest.raises(ValueError, match="BLOCK no puede producir"):
        PrivacyAuthorization.issue(operation_id="ask-unknown", result=unknown)
    with pytest.raises(TypeError):
        PrivacyAuthorization(  # type: ignore[call-arg]
            operation_id="forged",
            target_fingerprint=unknown.target.fingerprint,
            policy_fingerprint=unknown.policy.fingerprint,
        )


def test_h32_tp006_non_local_rejects_not_applicable() -> None:
    for execution in (InferenceExecution.REMOTE, InferenceExecution.UNKNOWN):
        with pytest.raises(ValueError, match="no local no admite NOT_APPLICABLE"):
            _result(execution, _evaluations(EvaluationState.NOT_APPLICABLE))


def test_h32_tp006_remote_pass_rejects_expired_evidence() -> None:
    evaluations = list(_evaluations(EvaluationState.PASS))
    evaluations[1] = _evaluation(
        PrivacyConstraint.RETENTION,
        EvaluationState.PASS,
        expired=True,
    )
    with pytest.raises(ValueError, match="evidencia expirada"):
        _result(InferenceExecution.REMOTE, tuple(evaluations))


def test_h32_domain_rejects_incomplete_or_incoherent_models() -> None:
    with pytest.raises(ValueError, match="platform es obligatorio"):
        InferenceTarget(
            execution=InferenceExecution.REMOTE,
            provider="synthetic-ai",
            platform=None,
        )
    with pytest.raises(ValueError, match="evaluacion unica"):
        _result(
            InferenceExecution.REMOTE,
            (_evaluation(PrivacyConstraint.RETENTION, EvaluationState.UNKNOWN),),
        )
    with pytest.raises(ValueError, match="PASS requiere"):
        ConstraintEvaluation(
            constraint=PrivacyConstraint.RETENTION,
            state=EvaluationState.PASS,
            reason_code="sin_evidencia",
        )
    with pytest.raises(ValueError, match="execution debe ser InferenceExecution"):
        InferenceTarget(  # type: ignore[arg-type]
            execution="remote",
            provider="synthetic-ai",
            platform="direct_api",
        )


@pytest.mark.parametrize("value", (True, 0, "region-a"))
def test_h32_privacy_evidence_accepts_only_immutable_scalars(value) -> None:
    evidence = PrivacyEvidence(
        constraint=PrivacyConstraint.RETENTION,
        value=value,
        scope="offering",
        source_kind="external_registry",
        source_id="synthetic-registry-v1",
        verified_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=1),
    )
    assert evidence.value == value

    with pytest.raises(ValueError, match="value debe ser"):
        PrivacyEvidence(
            constraint=PrivacyConstraint.RETENTION,
            value={"days": 0},  # type: ignore[arg-type]
            scope="offering",
            source_kind="external_registry",
            source_id="synthetic-registry-v1",
            verified_at=NOW - timedelta(days=1),
            expires_at=NOW + timedelta(days=1),
        )
