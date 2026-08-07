"""Value objects puros para Privacy Preflight H3.2."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable


class InferenceExecution(StrEnum):
    """Frontera efectiva de ejecucion generativa."""

    LOCAL = "local"
    REMOTE = "remote"
    UNKNOWN = "unknown"


class PrivacyConstraint(StrEnum):
    """Restricciones independientes evaluadas por el preflight."""

    NO_TRAINING = "no_training"
    RETENTION = "retention"
    DATA_LOCATION = "data_location"


class EvaluationState(StrEnum):
    """Estado verificable de una restriccion."""

    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class PrivacyPreflightDecision(StrEnum):
    """Decision agregada de una evaluacion."""

    PASS = "pass"
    BLOCK = "block"
    NOT_APPLICABLE = "not_applicable"


class PrivacyProfile(StrEnum):
    """Perfiles de privacidad soportados inicialmente."""

    STRICT = "strict"


@dataclass(frozen=True, slots=True)
class InferenceTarget:
    """Identidad publica e inmutable del destino generativo."""

    execution: InferenceExecution
    provider: str
    platform: str | None
    offering: str | None = None
    model: str | None = None

    def __post_init__(self) -> None:
        _require_instance(self.execution, InferenceExecution, "execution")
        object.__setattr__(self, "provider", _normalize_required(self.provider, "provider"))
        object.__setattr__(self, "platform", _normalize_optional(self.platform))
        object.__setattr__(self, "offering", _normalize_optional(self.offering))
        object.__setattr__(self, "model", _normalize_optional(self.model))
        if self.execution is not InferenceExecution.UNKNOWN and self.platform is None:
            raise ValueError("platform es obligatorio para execution local o remote.")

    @property
    def fingerprint(self) -> str:
        """Firma solo la identidad tecnica, nunca contenido de una consulta."""
        return _fingerprint(
            {
                "execution": self.execution.value,
                "provider": self.provider,
                "platform": self.platform,
                "offering": self.offering,
                "model": self.model,
            }
        )


@dataclass(frozen=True, slots=True)
class PrivacyPolicy:
    """Requisitos de Barbarion, no afirmaciones sobre un proveedor."""

    profile: PrivacyProfile = PrivacyProfile.STRICT
    allowed_regions: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        _require_instance(self.profile, PrivacyProfile, "profile")
        if self.allowed_regions is None:
            return
        normalized = tuple(
            _normalize_required(region, "allowed_regions")
            for region in self.allowed_regions
        )
        if not normalized:
            raise ValueError("allowed_regions debe omitirse o contener regiones.")
        if len(set(normalized)) != len(normalized):
            raise ValueError("allowed_regions no admite duplicados.")
        object.__setattr__(self, "allowed_regions", tuple(sorted(normalized)))

    @property
    def fingerprint(self) -> str:
        """Firma solo el perfil y sus regiones permitidas."""
        return _fingerprint(
            {
                "profile": self.profile.value,
                "allowed_regions": self.allowed_regions,
            }
        )


@dataclass(frozen=True, slots=True)
class PrivacyEvidence:
    """Referencia estructurada y publica que respalda una evaluacion."""

    constraint: PrivacyConstraint
    value: str | int | bool
    scope: str
    source_kind: str
    source_id: str
    verified_at: datetime
    expires_at: datetime
    conditional_on_account: bool = False

    def __post_init__(self) -> None:
        _require_instance(self.constraint, PrivacyConstraint, "constraint")
        if isinstance(self.value, str):
            object.__setattr__(self, "value", _normalize_required(self.value, "value"))
        elif not isinstance(self.value, (bool, int)):
            raise ValueError("value debe ser str, int o bool.")
        for name in ("scope", "source_kind", "source_id"):
            object.__setattr__(self, name, _normalize_required(getattr(self, name), name))
        if not isinstance(self.conditional_on_account, bool):
            raise ValueError("conditional_on_account debe ser bool.")
        _require_aware(self.verified_at, "verified_at")
        _require_aware(self.expires_at, "expires_at")
        if self.expires_at <= self.verified_at:
            raise ValueError("expires_at debe ser posterior a verified_at.")

    def is_valid_at(self, evaluated_at: datetime) -> bool:
        """Indica vigencia inclusiva desde verificacion y exclusiva al expirar."""
        _require_aware(evaluated_at, "evaluated_at")
        return self.verified_at <= evaluated_at < self.expires_at


@dataclass(frozen=True, slots=True)
class PrivacyPolicySourceResult:
    """Evidencia normalizada y metadata segura de una fuente de politicas."""

    source_id: str
    source_version: str
    evidence: tuple[PrivacyEvidence, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_id",
            _normalize_required(self.source_id, "source_id"),
        )
        object.__setattr__(
            self,
            "source_version",
            _normalize_required(self.source_version, "source_version"),
        )
        object.__setattr__(self, "evidence", tuple(self.evidence))
        if any(not isinstance(item, PrivacyEvidence) for item in self.evidence):
            raise ValueError("evidence solo admite PrivacyEvidence.")


@runtime_checkable
class PrivacyPolicySource(Protocol):
    """Puerto que solo conoce la identidad publica del destino."""

    def lookup(self, target: InferenceTarget) -> PrivacyPolicySourceResult:
        """Obtiene evidencia ya normalizada, sin recibir contenido de usuario."""
        ...


@dataclass(frozen=True, slots=True)
class ConstraintEvaluation:
    """Resultado explicable de una unica restriccion."""

    constraint: PrivacyConstraint
    state: EvaluationState
    reason_code: str
    evidence: tuple[PrivacyEvidence, ...] = ()

    def __post_init__(self) -> None:
        _require_instance(self.constraint, PrivacyConstraint, "constraint")
        _require_instance(self.state, EvaluationState, "state")
        object.__setattr__(self, "reason_code", _normalize_required(self.reason_code, "reason_code"))
        object.__setattr__(self, "evidence", tuple(self.evidence))
        if any(not isinstance(item, PrivacyEvidence) for item in self.evidence):
            raise ValueError("evidence solo admite PrivacyEvidence.")
        if any(item.constraint is not self.constraint for item in self.evidence):
            raise ValueError("Toda evidencia debe corresponder a la restriccion evaluada.")
        if self.state is EvaluationState.PASS and not self.evidence:
            raise ValueError("PASS requiere al menos una evidencia estructurada.")
        if self.state is EvaluationState.NOT_APPLICABLE and self.evidence:
            raise ValueError("NOT_APPLICABLE no admite evidencia.")


@dataclass(frozen=True, slots=True)
class PrivacyPreflightResult:
    """Decision agregada derivada sin IO de tres evaluaciones."""

    target: InferenceTarget
    policy: PrivacyPolicy
    evaluated_at: datetime
    evaluations: tuple[ConstraintEvaluation, ...]
    decision: PrivacyPreflightDecision = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.target, InferenceTarget):
            raise ValueError("target debe ser InferenceTarget.")
        if not isinstance(self.policy, PrivacyPolicy):
            raise ValueError("policy debe ser PrivacyPolicy.")
        _require_aware(self.evaluated_at, "evaluated_at")
        evaluations = tuple(self.evaluations)
        object.__setattr__(self, "evaluations", evaluations)
        if any(not isinstance(item, ConstraintEvaluation) for item in evaluations):
            raise ValueError("evaluations solo admite ConstraintEvaluation.")
        expected = set(PrivacyConstraint)
        observed = {item.constraint for item in evaluations}
        if len(evaluations) != len(expected) or observed != expected:
            raise ValueError("Debe existir una evaluacion unica por restriccion.")

        states = tuple(item.state for item in evaluations)
        if self.target.execution is InferenceExecution.LOCAL:
            if any(state is not EvaluationState.NOT_APPLICABLE for state in states):
                raise ValueError("La ejecucion local requiere NOT_APPLICABLE en todo.")
            decision = PrivacyPreflightDecision.NOT_APPLICABLE
        else:
            if any(state is EvaluationState.NOT_APPLICABLE for state in states):
                raise ValueError("Un destino no local no admite NOT_APPLICABLE.")
            if self.target.execution is InferenceExecution.UNKNOWN:
                decision = PrivacyPreflightDecision.BLOCK
            elif all(state is EvaluationState.PASS for state in states):
                _require_current_pass_evidence(evaluations, self.evaluated_at)
                decision = PrivacyPreflightDecision.PASS
            else:
                decision = PrivacyPreflightDecision.BLOCK
        object.__setattr__(self, "decision", decision)

    def evaluation_for(self, constraint: PrivacyConstraint) -> ConstraintEvaluation:
        """Obtiene la evaluacion unica de una restriccion."""
        return next(item for item in self.evaluations if item.constraint is constraint)


@dataclass(frozen=True, slots=True, init=False)
class PrivacyAuthorization:
    """Permiso inmutable y acotado a una operacion, target y politica."""

    operation_id: str
    target_fingerprint: str
    policy_fingerprint: str

    @classmethod
    def issue(
        cls,
        *,
        operation_id: str,
        result: PrivacyPreflightResult,
    ) -> PrivacyAuthorization:
        """Emite solo desde PASS remoto o NOT_APPLICABLE local."""
        if not isinstance(result, PrivacyPreflightResult):
            raise ValueError("result debe ser PrivacyPreflightResult.")
        if result.decision not in {
            PrivacyPreflightDecision.PASS,
            PrivacyPreflightDecision.NOT_APPLICABLE,
        }:
            raise ValueError("Una decision BLOCK no puede producir autorizacion.")
        authorization = object.__new__(cls)
        object.__setattr__(
            authorization,
            "operation_id",
            _normalize_required(operation_id, "operation_id"),
        )
        object.__setattr__(
            authorization,
            "target_fingerprint",
            result.target.fingerprint,
        )
        object.__setattr__(
            authorization,
            "policy_fingerprint",
            result.policy.fingerprint,
        )
        return authorization


def _require_current_pass_evidence(
    evaluations: tuple[ConstraintEvaluation, ...],
    evaluated_at: datetime,
) -> None:
    for evaluation in evaluations:
        if not all(item.is_valid_at(evaluated_at) for item in evaluation.evidence):
            raise ValueError("PASS remoto no admite evidencia expirada o aun no vigente.")


def _fingerprint(value: dict[str, object]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalize_required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} no puede estar vacio.")
    return value.strip().lower()


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return _normalize_required(value, "valor opcional")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} debe incluir zona horaria.")


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field_name} debe ser SHA-256 hexadecimal lowercase.")


def _require_instance(value: object, expected_type: type, field_name: str) -> None:
    if not isinstance(value, expected_type):
        raise ValueError(f"{field_name} debe ser {expected_type.__name__}.")
