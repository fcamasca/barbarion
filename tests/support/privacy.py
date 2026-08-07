"""Fakes sinteticos para probar componentes situados despues del gate H3.2."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from barbarion.application.privacy import (
    PrivacyPreflightService,
    UnavailableAccountPrivacyVerifier,
)
from barbarion.domain.privacy import (
    InferenceTarget,
    PrivacyConstraint,
    PrivacyEvidence,
    PrivacyPolicy,
    PrivacyPolicySourceResult,
)


class PassingPrivacyPolicySource:
    """Fuente in-memory que garantiza las tres propiedades de un test."""

    def __init__(self, now: datetime) -> None:
        self._evidence = tuple(
            PrivacyEvidence(
                constraint=constraint,
                value=value,
                scope="offering:synthetic-test",
                source_kind="external_registry",
                source_id=f"synthetic-test:{constraint.value}",
                verified_at=now - timedelta(hours=1),
                expires_at=now + timedelta(hours=1),
            )
            for constraint, value in (
                (PrivacyConstraint.NO_TRAINING, "no_training_guaranteed"),
                (PrivacyConstraint.RETENTION, "zdr"),
                (PrivacyConstraint.DATA_LOCATION, "synthetic-region"),
            )
        )

    def lookup(self, target: InferenceTarget) -> PrivacyPolicySourceResult:
        del target
        return PrivacyPolicySourceResult(
            source_id="synthetic-test",
            source_version="v1",
            evidence=self._evidence,
        )


def passing_privacy_preflight() -> PrivacyPreflightService:
    """Autoriza targets remotos solo mediante evidencia sintetica explicita."""
    now = datetime.now(UTC)
    return PrivacyPreflightService(
        policy=PrivacyPolicy(),
        policy_source=PassingPrivacyPolicySource(now),
        account_verifier=UnavailableAccountPrivacyVerifier(),
        clock=lambda: now,
    )
