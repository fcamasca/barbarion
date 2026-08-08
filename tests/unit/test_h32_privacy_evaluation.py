"""Evaluadores puros strict para H3.2-T04."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import product

import pytest

from barbarion.application.privacy import (
    NO_TRAINING_GUARANTEED,
    TRAINING_CONFIRMED,
    TRAINING_OPT_OUT_AVAILABLE,
    ZERO_DATA_RETENTION,
    ZERO_DATA_RETENTION_AVAILABLE,
    aggregate_remote_result,
    evaluate_data_location,
    evaluate_no_training,
    evaluate_retention,
)
from barbarion.domain.privacy import (
    ConstraintEvaluation,
    EvaluationState,
    InferenceExecution,
    InferenceTarget,
    PrivacyConstraint,
    PrivacyEvidence,
    PrivacyPolicy,
    PrivacyPreflightDecision,
)


NOW = datetime(2026, 8, 7, 15, tzinfo=UTC)


def _evidence(
    constraint: PrivacyConstraint,
    value: str | int | bool,
    *,
    conditional: bool = False,
    expired: bool = False,
    source_id: str = "synthetic-source",
) -> PrivacyEvidence:
    return PrivacyEvidence(
        constraint=constraint,
        value=value,
        scope="offering",
        source_kind="synthetic",
        source_id=source_id,
        verified_at=NOW - timedelta(days=2),
        expires_at=(
            NOW - timedelta(seconds=1)
            if expired
            else NOW + timedelta(days=2)
        ),
        conditional_on_account=conditional,
    )


def _state_evaluation(
    constraint: PrivacyConstraint,
    state: EvaluationState,
) -> ConstraintEvaluation:
    evidence = (
        (_evidence(constraint, "synthetic-pass"),)
        if state is EvaluationState.PASS
        else ()
    )
    return ConstraintEvaluation(
        constraint=constraint,
        state=state,
        reason_code=f"synthetic_{state.value}",
        evidence=evidence,
    )


def _remote_target() -> InferenceTarget:
    return InferenceTarget(
        execution=InferenceExecution.REMOTE,
        provider="synthetic-ai",
        platform="direct_api",
        offering="standard",
    )


def test_h32_tp010_strict_means_no_training_zdr_and_known_location() -> None:
    policy = PrivacyPolicy()
    assert evaluate_no_training(
        (_evidence(PrivacyConstraint.NO_TRAINING, NO_TRAINING_GUARANTEED),),
        evaluated_at=NOW,
    ).state is EvaluationState.PASS
    assert evaluate_retention(
        (_evidence(PrivacyConstraint.RETENTION, ZERO_DATA_RETENTION),),
        evaluated_at=NOW,
    ).state is EvaluationState.PASS
    assert evaluate_data_location(
        (_evidence(PrivacyConstraint.DATA_LOCATION, "region-a"),),
        policy=policy,
        evaluated_at=NOW,
    ).state is EvaluationState.PASS


def test_h32_tp011_no_training_pass_requires_unconditional_evidence() -> None:
    result = evaluate_no_training(
        (_evidence(PrivacyConstraint.NO_TRAINING, NO_TRAINING_GUARANTEED),),
        evaluated_at=NOW,
    )
    assert result.state is EvaluationState.PASS
    assert result.reason_code == "no_training_guaranteed"


def test_h32_tp012_training_confirmed_fails() -> None:
    result = evaluate_no_training(
        (_evidence(PrivacyConstraint.NO_TRAINING, TRAINING_CONFIRMED),),
        evaluated_at=NOW,
    )
    assert result.state is EvaluationState.FAIL
    assert result.reason_code == "training_confirmed"


@pytest.mark.parametrize(
    "evidence",
    (
        (),
        (_evidence(PrivacyConstraint.NO_TRAINING, TRAINING_OPT_OUT_AVAILABLE),),
        (
            _evidence(
                PrivacyConstraint.NO_TRAINING,
                NO_TRAINING_GUARANTEED,
                conditional=True,
            ),
        ),
        (
            _evidence(PrivacyConstraint.NO_TRAINING, NO_TRAINING_GUARANTEED),
            _evidence(
                PrivacyConstraint.NO_TRAINING,
                TRAINING_CONFIRMED,
                source_id="conflict",
            ),
        ),
        (
            _evidence(
                PrivacyConstraint.NO_TRAINING,
                NO_TRAINING_GUARANTEED,
                expired=True,
            ),
        ),
    ),
)
def test_h32_tp013_no_training_unknown_is_fail_closed(evidence) -> None:
    result = evaluate_no_training(tuple(evidence), evaluated_at=NOW)
    assert result.state is EvaluationState.UNKNOWN


@pytest.mark.parametrize("value", (ZERO_DATA_RETENTION, 0))
def test_h32_tp014_effective_zero_retention_passes(value: str | int) -> None:
    result = evaluate_retention(
        (_evidence(PrivacyConstraint.RETENTION, value),),
        evaluated_at=NOW,
    )
    assert result.state is EvaluationState.PASS
    assert result.reason_code == "zero_data_retention_effective"


@pytest.mark.parametrize("days", (1, 7, 30))
def test_h32_tp015_positive_retention_fails(days: int) -> None:
    result = evaluate_retention(
        (_evidence(PrivacyConstraint.RETENTION, days),),
        evaluated_at=NOW,
    )
    assert result.state is EvaluationState.FAIL
    assert result.reason_code == "positive_retention_confirmed"


@pytest.mark.parametrize(
    "evidence",
    (
        (),
        (_evidence(PrivacyConstraint.RETENTION, ZERO_DATA_RETENTION_AVAILABLE),),
        (
            _evidence(
                PrivacyConstraint.RETENTION,
                ZERO_DATA_RETENTION,
                conditional=True,
            ),
        ),
        (
            _evidence(PrivacyConstraint.RETENTION, 0),
            _evidence(PrivacyConstraint.RETENTION, 7, source_id="conflict"),
        ),
        (_evidence(PrivacyConstraint.RETENTION, 0, expired=True),),
    ),
)
def test_h32_tp016_unverified_zdr_or_ambiguity_is_unknown(evidence) -> None:
    result = evaluate_retention(tuple(evidence), evaluated_at=NOW)
    assert result.state is EvaluationState.UNKNOWN


@pytest.mark.parametrize(
    ("allowed", "location"),
    (
        (None, "region-a"),
        (("region-a",), "region-a"),
    ),
)
def test_h32_tp017_known_location_passes_when_allowed(allowed, location) -> None:
    result = evaluate_data_location(
        (_evidence(PrivacyConstraint.DATA_LOCATION, location),),
        policy=PrivacyPolicy(allowed_regions=allowed),
        evaluated_at=NOW,
    )
    assert result.state is EvaluationState.PASS


def test_h32_tp018_known_location_outside_allowlist_fails() -> None:
    result = evaluate_data_location(
        (_evidence(PrivacyConstraint.DATA_LOCATION, "region-b"),),
        policy=PrivacyPolicy(allowed_regions=("region-a",)),
        evaluated_at=NOW,
    )
    assert result.state is EvaluationState.FAIL
    assert result.reason_code == "data_location_not_allowed"


@pytest.mark.parametrize(
    "evidence",
    (
        (),
        (
            _evidence(
                PrivacyConstraint.DATA_LOCATION,
                "region-a",
                conditional=True,
            ),
        ),
        (
            _evidence(PrivacyConstraint.DATA_LOCATION, "region-a"),
            _evidence(
                PrivacyConstraint.DATA_LOCATION,
                "region-b",
                source_id="conflict",
            ),
        ),
        (_evidence(PrivacyConstraint.DATA_LOCATION, "region-a", expired=True),),
    ),
)
def test_h32_tp019_undetermined_location_is_unknown(evidence) -> None:
    result = evaluate_data_location(
        tuple(evidence),
        policy=PrivacyPolicy(),
        evaluated_at=NOW,
    )
    assert result.state is EvaluationState.UNKNOWN


@pytest.mark.parametrize(
    "states",
    tuple(product((EvaluationState.PASS, EvaluationState.FAIL, EvaluationState.UNKNOWN), repeat=3)),
)
def test_h32_remote_aggregation_allows_only_three_passes(states) -> None:
    evaluations = tuple(
        _state_evaluation(constraint, state)
        for constraint, state in zip(PrivacyConstraint, states, strict=True)
    )
    result = aggregate_remote_result(
        target=_remote_target(),
        policy=PrivacyPolicy(),
        evaluated_at=NOW,
        evaluations=evaluations,
    )
    expected = (
        PrivacyPreflightDecision.BLOCK
        if states[0] is not EvaluationState.PASS
        else (
            PrivacyPreflightDecision.PASS
            if states[1] is EvaluationState.PASS
            else PrivacyPreflightDecision.WARNING
        )
    )
    assert result.decision is expected


def test_h32_remote_aggregation_rejects_non_remote_target() -> None:
    local = InferenceTarget(
        execution=InferenceExecution.LOCAL,
        provider="ollama",
        platform="local_runtime",
    )
    with pytest.raises(ValueError, match="requiere execution=remote"):
        aggregate_remote_result(
            target=local,
            policy=PrivacyPolicy(),
            evaluated_at=NOW,
            evaluations=tuple(
                _state_evaluation(constraint, EvaluationState.PASS)
                for constraint in PrivacyConstraint
            ),
        )
