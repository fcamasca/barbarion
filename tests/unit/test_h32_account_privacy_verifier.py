"""H3.2-TP-033..037: contrato futuro minimo, unavailable y fake sin IO."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from barbarion.application.privacy import (
    InMemoryAccountPrivacyVerifier,
    UnavailableAccountPrivacyVerifier,
    aggregate_remote_result,
    evaluate_data_location,
    evaluate_no_training,
    evaluate_retention,
)
from barbarion.domain.privacy import (
    AccountPrivacyVerificationResult,
    AccountPrivacyVerifier,
    AccountVerificationStatus,
    EvaluationState,
    InferenceExecution,
    InferenceTarget,
    PrivacyConstraint,
    PrivacyEvidence,
    PrivacyPolicy,
    PrivacyPreflightDecision,
)


NOW = datetime(2026, 8, 7, 12, tzinfo=UTC)
TARGET = InferenceTarget(
    execution=InferenceExecution.REMOTE,
    provider="synthetic-provider",
    platform="direct_api",
    offering="synthetic-offering",
    model="public-model",
)
POLICY = PrivacyPolicy(allowed_regions=("us",))


def _evidence(
    constraint: PrivacyConstraint,
    value: str | int,
    *,
    scope: str,
    source_kind: str,
    conditional: bool = False,
) -> PrivacyEvidence:
    return PrivacyEvidence(
        constraint=constraint,
        value=value,
        scope=scope,
        source_kind=source_kind,
        source_id=f"synthetic:{scope}:{constraint.value}",
        verified_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=1),
        conditional_on_account=conditional,
    )


def _capability(constraint: PrivacyConstraint, value: str) -> PrivacyEvidence:
    return _evidence(
        constraint,
        value,
        scope="offering:synthetic-offering",
        source_kind="external_registry",
        conditional=True,
    )


def _account(constraint: PrivacyConstraint, value: str | int) -> PrivacyEvidence:
    return _evidence(
        constraint,
        value,
        scope="account",
        source_kind="account_verifier",
    )


def test_tp033_fake_account_evidence_can_confirm_zdr_and_region() -> None:
    result = AccountPrivacyVerificationResult(
        status=AccountVerificationStatus.PARTIAL,
        evidence=(
            _account(PrivacyConstraint.RETENTION, "zdr"),
            _account(PrivacyConstraint.DATA_LOCATION, "us"),
        ),
    )
    verifier = InMemoryAccountPrivacyVerifier(result)
    assert isinstance(verifier, AccountPrivacyVerifier)

    observed = verifier.verify(TARGET)
    evidence = (
        _capability(PrivacyConstraint.RETENTION, "zdr_available"),
        *observed.evidence,
    )

    assert evaluate_retention(evidence, evaluated_at=NOW).state is EvaluationState.PASS
    assert (
        evaluate_data_location(evidence, policy=POLICY, evaluated_at=NOW).state
        is EvaluationState.PASS
    )
    assert verifier.observed_targets == [TARGET]


def test_tp034_v1_production_verifier_is_always_unavailable() -> None:
    verifier = UnavailableAccountPrivacyVerifier()
    assert isinstance(verifier, AccountPrivacyVerifier)

    result = verifier.verify(TARGET)

    assert result.status is AccountVerificationStatus.UNAVAILABLE
    assert result.evidence == ()
    assert result.reason_code == "account_verifier_unavailable"


def test_tp035_zdr_capability_with_unavailable_account_stays_unknown() -> None:
    account = UnavailableAccountPrivacyVerifier().verify(TARGET)
    evidence = (
        _capability(PrivacyConstraint.RETENTION, "zdr_available"),
        *account.evidence,
    )

    evaluation = evaluate_retention(evidence, evaluated_at=NOW)

    assert evaluation.state is EvaluationState.UNKNOWN
    assert evaluation.reason_code == "zdr_available_not_effective"


def test_tp036_account_contradiction_never_selects_capability_optimistically() -> None:
    capability = _evidence(
        PrivacyConstraint.NO_TRAINING,
        "no_training_guaranteed",
        scope="offering:synthetic-offering",
        source_kind="external_registry",
    )
    account = AccountPrivacyVerificationResult(
        status=AccountVerificationStatus.PARTIAL,
        evidence=(
            _account(PrivacyConstraint.NO_TRAINING, "training_confirmed"),
        ),
    )

    evaluation = evaluate_no_training(
        (capability, *account.evidence),
        evaluated_at=NOW,
    )

    assert evaluation.state is EvaluationState.UNKNOWN
    assert evaluation.reason_code == "conflicting_training_evidence"


def test_tp037_fake_error_has_no_evidence_and_aggregates_to_block() -> None:
    error = AccountPrivacyVerificationResult(
        status=AccountVerificationStatus.ERROR,
        reason_code="synthetic_verifier_error",
    )
    observed = InMemoryAccountPrivacyVerifier(error).verify(TARGET)

    assert observed.evidence == ()
    evaluations = (
        evaluate_no_training(observed.evidence, evaluated_at=NOW),
        evaluate_retention(observed.evidence, evaluated_at=NOW),
        evaluate_data_location(
            observed.evidence,
            policy=POLICY,
            evaluated_at=NOW,
        ),
    )
    result = aggregate_remote_result(
        target=TARGET,
        policy=POLICY,
        evaluated_at=NOW,
        evaluations=evaluations,
    )

    assert all(item.state is EvaluationState.UNKNOWN for item in evaluations)
    assert result.decision is PrivacyPreflightDecision.BLOCK
