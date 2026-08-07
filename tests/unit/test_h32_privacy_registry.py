"""H3.2-TP-020..024: contrato y normalizacion conservadora del registry."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from barbarion.application.privacy import (
    evaluate_data_location,
    evaluate_no_training,
    evaluate_retention,
)
from barbarion.domain.privacy import (
    EvaluationState,
    InferenceExecution,
    InferenceTarget,
    PrivacyConstraint,
    PrivacyPolicy,
    PrivacyPolicySource,
)
from barbarion.infrastructure.privacy_registry import (
    AiProviderTrustRegistrySource,
    PrivacyRegistrySchemaError,
    UnsupportedPrivacyRegistrySchemaError,
)


FIXTURE = Path(__file__).parents[1] / "fixtures" / "h32_ai_provider_trust_registry.json"
EVALUATED_AT = datetime(2026, 8, 7, 12, tzinfo=UTC)
EXPIRES_AT = datetime(2026, 8, 8, tzinfo=UTC)


def _payload() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _target(
    *,
    platform: str = "direct_api",
    offering: str | None = "anthropic-api",
    model: str = "claude-current",
) -> InferenceTarget:
    return InferenceTarget(
        execution=InferenceExecution.REMOTE,
        provider="anthropic",
        platform=platform,
        offering=offering,
        model=model,
    )


def _source(payload: dict[str, object] | None = None) -> AiProviderTrustRegistrySource:
    source = AiProviderTrustRegistrySource(payload or _payload(), expires_at=EXPIRES_AT)
    assert isinstance(source, PrivacyPolicySource)
    return source


def test_tp020_normalizes_only_structured_cells_and_drops_free_text() -> None:
    result = _source().lookup(_target())

    assert result.source_id == "ai-provider-trust-registry"
    assert result.source_version == "2026-08-07"
    assert {item.constraint for item in result.evidence} == set(PrivacyConstraint)
    serialized = repr(result)
    for canary in (
        "SYNTHETIC-CONTENT-CANARY",
        "SYNTHETIC-NOTES-CANARY",
        "SYNTHETIC-EVIDENCE-CANARY",
        "SYNTHETIC-ZDR-NOTES",
        "SYNTHETIC-RESIDENCY-NOTES",
    ):
        assert canary not in serialized


def test_registry_capabilities_do_not_claim_effective_zdr_or_location() -> None:
    evidence = _source().lookup(_target()).evidence

    assert evaluate_no_training(evidence, evaluated_at=EVALUATED_AT).state is EvaluationState.PASS
    assert evaluate_retention(evidence, evaluated_at=EVALUATED_AT).state is EvaluationState.UNKNOWN
    assert (
        evaluate_data_location(
            evidence,
            policy=PrivacyPolicy(),
            evaluated_at=EVALUATED_AT,
        ).state
        is EvaluationState.UNKNOWN
    )


def test_tp021_resolves_specific_scope_and_ambiguity_as_no_evidence() -> None:
    source = _source()

    exact = source.lookup(_target(offering="anthropic-api"))
    other_platform = source.lookup(
        _target(platform="Synthetic Cloud", offering=None)
    )
    ambiguous = source.lookup(_target(platform="unknown-platform", offering=None))

    assert exact.evidence
    assert all(item.scope == "offering:anthropic-api" for item in exact.evidence)
    assert len(other_platform.evidence) == 1
    assert other_platform.evidence[0].scope == "offering:anthropic-distribution"
    assert ambiguous.evidence == ()


def test_tp022_new_model_inherits_offering_without_model_catalog() -> None:
    current = _source().lookup(_target(model="claude-current")).evidence
    future = _source().lookup(_target(model="new-model-v99")).evidence

    assert future == current


def test_tp023_only_published_model_exception_overrides_offering() -> None:
    source = _source()
    ordinary = source.lookup(_target(model="unpublished-model")).evidence
    exceptional = source.lookup(_target(model="published-exception-v1")).evidence

    ordinary_training = next(
        item for item in ordinary if item.constraint is PrivacyConstraint.NO_TRAINING
    )
    exceptional_training = next(
        item for item in exceptional if item.constraint is PrivacyConstraint.NO_TRAINING
    )
    assert ordinary_training.value == "no_training_guaranteed"
    assert exceptional_training.value == "opt_out_available"
    assert exceptional_training.conditional_on_account is True
    assert all(item.scope == "model_exception:published-exception-v1" for item in exceptional)


def test_tp024_source_receives_only_public_target_identity() -> None:
    class SpySource:
        seen: InferenceTarget | None = None

        def lookup(self, target: InferenceTarget):  # noqa: ANN202
            self.seen = target
            return _source().lookup(target)

    spy = SpySource()
    spy.lookup(_target(model="new-model-v99"))

    assert spy.seen is not None
    assert set(spy.seen.__dataclass_fields__) == {
        "execution",
        "provider",
        "platform",
        "offering",
        "model",
    }
    assert "prompt" not in repr(spy.seen).lower()
    assert "query" not in repr(spy.seen).lower()
    assert "corpus" not in repr(spy.seen).lower()


def test_registry_rejects_unknown_schema_and_malformed_payload() -> None:
    unsupported = _payload()
    unsupported["schema_version"] = 99
    with pytest.raises(UnsupportedPrivacyRegistrySchemaError):
        _source(unsupported)

    malformed = _payload()
    malformed["offerings"] = "not-a-list"
    with pytest.raises(PrivacyRegistrySchemaError):
        _source(malformed)
