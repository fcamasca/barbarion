"""H3.2-TP-044..047: vinculacion y reutilizacion de PrivacyAuthorization."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from barbarion.application.privacy import (
    InvalidPrivacyAuthorizationError,
    resolve_inference_target,
)
from barbarion.domain.privacy import (
    ConstraintEvaluation,
    EvaluationState,
    InferenceExecution,
    InferenceTarget,
    PrivacyAuthorization,
    PrivacyConstraint,
    PrivacyEvidence,
    PrivacyPolicy,
    PrivacyPreflightResult,
)
from barbarion.domain.rag import RagQueryStatus, RetrievalMode
from tests.unit.test_h32_privacy_preflight_ask import (
    _passing_evidence,
    _service,
)


NOW = datetime(2026, 8, 7, 12, tzinfo=UTC)
OPERATION_ID = "ASK-001"


class MultiAnswerLlm:
    provider = "synthetic"
    model = "synthetic-v1"

    def __init__(self, *answers: str) -> None:
        self.answers = answers
        self.prompts: list[str] = []

    def generate(self, *, prompt: str, timeout_seconds: float) -> str:
        assert timeout_seconds > 0
        self.prompts.append(prompt)
        return self.answers[len(self.prompts) - 1]


class CountingPreflight:
    def __init__(self, delegate) -> None:  # noqa: ANN001
        self.delegate = delegate
        self.policy = delegate.policy
        self.calls = 0

    def authorize(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls += 1
        return self.delegate.authorize(**kwargs)


class ForgedAuthorization:
    def __init__(self, legitimate: PrivacyAuthorization) -> None:
        self.operation_id = legitimate.operation_id
        self.target_fingerprint = legitimate.target_fingerprint
        self.policy_fingerprint = legitimate.policy_fingerprint


def _authorized_service(tmp_path):  # noqa: ANN001, ANN202
    service, llm, _, _ = _service(
        tmp_path,
        execution=None,
        remote=True,
        evidence=_passing_evidence(),
    )
    target = resolve_inference_target(service.settings)
    policy = service.privacy_preflight.policy
    authorization = service.privacy_preflight.authorize(
        operation_id=OPERATION_ID,
        target=target,
    )
    return service, llm, target, policy, authorization


def test_tp044_valid_generation_uses_matching_authorization(tmp_path) -> None:
    service, llm, target, policy, authorization = _authorized_service(tmp_path)

    response = service._generate_with_observability(
        "synthetic authorized prompt",
        stage="generation",
        authorization=authorization,
        operation_id=OPERATION_ID,
        target=target,
        policy=policy,
    )

    assert response
    assert llm.prompts == ["synthetic authorized prompt"]


def test_tp045_generation_and_repair_reuse_one_preflight_authorization(tmp_path) -> None:
    service, _, _, _ = _service(
        tmp_path,
        execution=None,
        remote=True,
        evidence=_passing_evidence(),
    )
    provider = MultiAnswerLlm(
        "Conclusion inicial sin cita.",
        "order_total se selecciona desde dual [F1].",
    )
    preflight = CountingPreflight(service.privacy_preflight)
    service = replace(
        service,
        llm_provider=provider,
        privacy_preflight=preflight,
    )

    result = service.ask(
        "order_total",
        mode=RetrievalMode.KEYWORD,
        top_k=3,
        candidate_k=3,
        threshold=0,
    )

    assert result.status is RagQueryStatus.COMPLETED
    assert preflight.calls == 1
    assert len(provider.prompts) == 2


@pytest.mark.parametrize("mismatch", ["operation", "target", "policy"])
def test_tp046_047_mismatched_binding_blocks_before_provider(
    tmp_path,
    mismatch: str,
) -> None:
    service, llm, target, policy, authorization = _authorized_service(tmp_path)
    operation_id = OPERATION_ID
    effective_target = target
    effective_policy = policy
    if mismatch == "operation":
        operation_id = "ASK-002"
    elif mismatch == "target":
        effective_target = InferenceTarget(
            execution=InferenceExecution.REMOTE,
            provider="ollama",
            platform="ollama_cloud",
            model=target.model,
        )
    else:
        effective_policy = PrivacyPolicy(allowed_regions=("region-b",))

    with pytest.raises(InvalidPrivacyAuthorizationError):
        service._generate_with_observability(
            "must not leave process",
            stage="generation",
            authorization=authorization,
            operation_id=operation_id,
            target=effective_target,
            policy=effective_policy,
        )

    assert llm.prompts == []


@pytest.mark.parametrize("kind", ["none", "forged", "local"])
def test_invalid_or_not_applicable_authorization_cannot_guard_remote(
    tmp_path,
    kind: str,
) -> None:
    service, llm, target, policy, legitimate = _authorized_service(tmp_path)
    authorization: object
    if kind == "none":
        authorization = None
    elif kind == "forged":
        authorization = ForgedAuthorization(legitimate)
    else:
        local_target = InferenceTarget(
            execution=InferenceExecution.LOCAL,
            provider="ollama",
            platform="local_runtime",
        )
        local_result = PrivacyPreflightResult(
            target=local_target,
            policy=policy,
            evaluated_at=NOW,
            evaluations=tuple(
                ConstraintEvaluation(
                    constraint=constraint,
                    state=EvaluationState.NOT_APPLICABLE,
                    reason_code="local_inference",
                )
                for constraint in PrivacyConstraint
            ),
        )
        authorization = PrivacyAuthorization.issue(
            operation_id=OPERATION_ID,
            result=local_result,
        )

    with pytest.raises(InvalidPrivacyAuthorizationError):
        service._generate_with_observability(
            "must not leave process",
            stage="generation",
            authorization=authorization,  # type: ignore[arg-type]
            operation_id=OPERATION_ID,
            target=target,
            policy=policy,
        )

    assert llm.prompts == []


def test_block_result_cannot_issue_authorization(tmp_path) -> None:
    service, llm, target, policy, _ = _authorized_service(tmp_path)
    evidence = PrivacyEvidence(
        constraint=PrivacyConstraint.NO_TRAINING,
        value="training_confirmed",
        scope="offering:synthetic",
        source_kind="external_registry",
        source_id="synthetic:block",
        verified_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=1),
    )
    block = PrivacyPreflightResult(
        target=target,
        policy=policy,
        evaluated_at=NOW,
        evaluations=(
            ConstraintEvaluation(
                constraint=PrivacyConstraint.NO_TRAINING,
                state=EvaluationState.FAIL,
                reason_code="training_confirmed",
                evidence=(evidence,),
            ),
            ConstraintEvaluation(
                constraint=PrivacyConstraint.RETENTION,
                state=EvaluationState.UNKNOWN,
                reason_code="retention_unknown",
            ),
            ConstraintEvaluation(
                constraint=PrivacyConstraint.DATA_LOCATION,
                state=EvaluationState.UNKNOWN,
                reason_code="data_location_unknown",
            ),
        ),
    )

    with pytest.raises(ValueError, match="BLOCK"):
        PrivacyAuthorization.issue(operation_id=OPERATION_ID, result=block)

    assert llm.prompts == []
