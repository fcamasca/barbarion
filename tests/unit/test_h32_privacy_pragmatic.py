"""Ajuste pragmático H3.2: no-training bloquea; retention advierte."""

from datetime import UTC, datetime

from barbarion.application.privacy import OllamaOfficialPolicySource
from barbarion.application.privacy import evaluate_no_training, evaluate_retention
from barbarion.domain.privacy import (
    InferenceExecution,
    InferenceTarget,
    PrivacyConstraint,
    EvaluationState,
)


def test_ollama_official_policy_applies_to_cloud_without_model_rules() -> None:
    source = OllamaOfficialPolicySource()
    target = InferenceTarget(
        execution=InferenceExecution.REMOTE,
        provider="ollama",
        platform="ollama_cloud",
        model="future-model-cloud",
    )
    result = source.lookup(target)

    assert {item.constraint for item in result.evidence} == {
        PrivacyConstraint.NO_TRAINING,
        PrivacyConstraint.RETENTION,
    }
    assert all(item.source_kind == "provider_official_policy" for item in result.evidence)
    assert evaluate_no_training(
        result.evidence,
        evaluated_at=datetime(2026, 8, 7, tzinfo=UTC),
    ).state is EvaluationState.PASS
    assert evaluate_retention(
        result.evidence,
        evaluated_at=datetime(2026, 8, 7, tzinfo=UTC),
    ).state is EvaluationState.PASS


def test_ollama_policy_does_not_apply_to_other_transport() -> None:
    source = OllamaOfficialPolicySource()
    target = InferenceTarget(
        execution=InferenceExecution.REMOTE,
        provider="ollama",
        platform="local_runtime",
        model="model",
    )
    assert source.lookup(target).evidence == ()
