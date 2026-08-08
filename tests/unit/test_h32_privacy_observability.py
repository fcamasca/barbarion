"""H3.2-TP-048..053: CLI y observabilidad segura del preflight."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest

from barbarion import cli
from barbarion.application.privacy import (
    PrivacyPreflightBlockedError,
    PrivacyPreflightService,
    UnavailableAccountPrivacyVerifier,
)
from barbarion.domain.privacy import (
    InferenceExecution,
    InferenceTarget,
    PrivacyConstraint,
    PrivacyEvidence,
    PrivacyPolicy,
    PrivacyPolicySourceResult,
)


NOW = datetime(2026, 8, 7, 12, tzinfo=UTC)
TARGET = InferenceTarget(
    execution=InferenceExecution.REMOTE,
    provider="anthropic",
    platform="direct_api",
    offering="anthropic-api",
    model="public-model",
)


class ObservableSource:
    def lookup(self, target: InferenceTarget) -> PrivacyPolicySourceResult:
        assert target == TARGET
        return PrivacyPolicySourceResult(
            source_id="synthetic-registry",
            source_version="2026-08-07",
            evidence=(
                _evidence(
                    PrivacyConstraint.NO_TRAINING,
                    "training_confirmed",
                ),
                _evidence(
                    PrivacyConstraint.RETENTION,
                    "zdr_available",
                    conditional=True,
                ),
                _evidence(PrivacyConstraint.DATA_LOCATION, "us"),
            ),
        )


@pytest.fixture(autouse=True)
def _isolated_privacy_logger():  # noqa: ANN202
    logger = logging.getLogger("barbarion")
    previous_handlers = tuple(logger.handlers)
    previous_propagate = logger.propagate
    for handler in previous_handlers:
        logger.removeHandler(handler)
    logger.propagate = True
    try:
        yield
    finally:
        logger.propagate = previous_propagate
        for handler in previous_handlers:
            logger.addHandler(handler)


def _evidence(
    constraint: PrivacyConstraint,
    value: str,
    *,
    conditional: bool = False,
) -> PrivacyEvidence:
    return PrivacyEvidence(
        constraint=constraint,
        value=value,
        scope="offering:anthropic-api",
        source_kind="external_registry",
        source_id=f"synthetic-registry:{constraint.value}",
        verified_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=1),
        conditional_on_account=conditional,
    )


def _blocked() -> PrivacyPreflightBlockedError:
    service = PrivacyPreflightService(
        policy=PrivacyPolicy(allowed_regions=("us",)),
        policy_source=ObservableSource(),
        account_verifier=UnavailableAccountPrivacyVerifier(),
        cache_status="valid",
        clock=lambda: NOW,
    )
    with pytest.raises(PrivacyPreflightBlockedError) as captured:
        service.authorize(operation_id="ASK-OBSERVABLE", target=TARGET)
    return captured.value


def test_tp048_normal_block_output_is_compact_and_actionable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli._render_privacy_preflight_block(_blocked(), debug=False)
    captured = capsys.readouterr()

    assert captured.out == ""
    assert captured.err == (
        "Privacy preflight: BLOCKED\n\n"
        "no_training : FAIL\n"
        "retention   : UNKNOWN\n"
        "location    : PASS\n\n"
        "No se envio contexto al proveedor remoto.\n"
    )


def test_tp049_debug_contains_only_public_structured_diagnostics(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli._render_privacy_preflight_block(_blocked(), debug=True)
    text = capsys.readouterr().err

    for expected in (
        "decision=block",
        "execution=remote",
        "provider=anthropic",
        "platform=direct_api",
        "policy_profile=strict",
        "policy_allowed_regions=('us',)",
        "cache_status=valid",
        "account_verifier=unavailable",
        "source_id=synthetic-registry",
        "source_version=2026-08-07",
        "retention_reason=zdr_available_not_effective",
        "scope=offering:anthropic-api",
        "verified_at=",
        "expires_at=",
    ):
        assert expected in text


def test_tp050_privacy_event_and_debug_exclude_sensitive_canaries(
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="barbarion")
    cli._render_privacy_preflight_block(_blocked(), debug=True)
    combined = capsys.readouterr().err + "\n" + caplog.text
    canaries = (
        "QUERY_CANARY_81A",
        "PROMPT_CANARY_82B",
        "CHUNK_CANARY_83C",
        "C:/secret/path.sql",
        "SYMBOL_CANARY_84D",
        "FORMULA_CANARY_85E",
        "REJECTED_RESPONSE_CANARY_86F",
        "sk-ant-api-key-canary",
        "REGISTRY_PAYLOAD_CANARY_87G",
    )

    assert "privacy_decision=block" in combined
    for canary in canaries:
        assert canary not in combined
