"""Adaptador conservador para snapshots del AI Provider Trust Registry."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from barbarion.domain.privacy import (
    InferenceTarget,
    PrivacyConstraint,
    PrivacyEvidence,
    PrivacyPolicySourceResult,
)


REGISTRY_SOURCE_ID = "ai-provider-trust-registry"
REGISTRY_NAME = "AI Provider Trust Registry"
SUPPORTED_SCHEMA_VERSION = 1
DATA_RESIDENCY_AVAILABLE = "data_residency_available"
NO_TRAINING_GUARANTEED = "no_training_guaranteed"
TRAINING_OPT_OUT_AVAILABLE = "opt_out_available"
ZERO_DATA_RETENTION_AVAILABLE = "zdr_available"


class PrivacyRegistryError(ValueError):
    """Error base al validar o normalizar un snapshot externo."""


class PrivacyRegistrySchemaError(PrivacyRegistryError):
    """El payload no satisface el contrato estructurado minimo."""


class UnsupportedPrivacyRegistrySchemaError(PrivacyRegistryError):
    """La fuente declara una version que este adaptador no entiende."""


class AiProviderTrustRegistrySource:
    """Normaliza un snapshot ya obtenido; no realiza red ni cache."""

    def __init__(
        self,
        payload: Mapping[str, Any],
        *,
        expires_at: datetime,
    ) -> None:
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise PrivacyRegistrySchemaError("expires_at debe incluir zona horaria.")
        self._payload = _validate_payload(payload)
        self._expires_at = expires_at

    def lookup(self, target: InferenceTarget) -> PrivacyPolicySourceResult:
        """Busca solo por identidad publica y devuelve evidencia de dominio."""
        offering = _select_offering(self._payload["offerings"], target)
        version = str(self._payload["generated"])
        if offering is None:
            return PrivacyPolicySourceResult(
                source_id=REGISTRY_SOURCE_ID,
                source_version=version,
            )

        dimensions = offering["dimensions"]
        scope = f"offering:{offering['id']}"
        exception = _select_model_exception(offering, target.model)
        if exception is _CONFLICT:
            return PrivacyPolicySourceResult(
                source_id=REGISTRY_SOURCE_ID,
                source_version=version,
            )
        if exception is not None:
            dimensions = {**dimensions, **exception["dimensions"]}
            scope = f"model_exception:{target.model}"

        evidence = tuple(
            item
            for dimension_name in (
                "training_on_customer_data",
                "retention_zdr",
                "data_residency",
            )
            if (
                item := self._normalize_dimension(
                    dimension_name,
                    dimensions.get(dimension_name),
                    offering_id=str(offering["id"]),
                    scope=scope,
                )
            )
            is not None
        )
        return PrivacyPolicySourceResult(
            source_id=REGISTRY_SOURCE_ID,
            source_version=version,
            evidence=evidence,
        )

    def _normalize_dimension(
        self,
        name: str,
        cell: object,
        *,
        offering_id: str,
        scope: str,
    ) -> PrivacyEvidence | None:
        if not isinstance(cell, Mapping):
            return None
        value = cell.get("value")
        confidence = cell.get("confidence")
        source = cell.get("source")
        verified = cell.get("verified")
        required = (value, confidence, source, verified)
        if not all(isinstance(item, str) and item.strip() for item in required):
            return None
        if confidence != "high":
            return None
        verified_at = _parse_verified(verified)
        if self._expires_at <= verified_at:
            raise PrivacyRegistrySchemaError(
                f"expires_at no es posterior a verified para {offering_id}/{name}."
            )
        source_id = f"{REGISTRY_SOURCE_ID}:{offering_id}:{name}:{source}"

        if name == "training_on_customer_data" and value == "yes_public":
            return PrivacyEvidence(
                constraint=PrivacyConstraint.NO_TRAINING,
                value=NO_TRAINING_GUARANTEED,
                scope=scope,
                source_kind="external_registry",
                source_id=source_id,
                verified_at=verified_at,
                expires_at=self._expires_at,
            )
        if name == "training_on_customer_data" and value in {
            "yes_sales_gated",
            "yes_platform_only",
        }:
            return PrivacyEvidence(
                constraint=PrivacyConstraint.NO_TRAINING,
                value=TRAINING_OPT_OUT_AVAILABLE,
                scope=scope,
                source_kind="external_registry",
                source_id=source_id,
                verified_at=verified_at,
                expires_at=self._expires_at,
                conditional_on_account=True,
            )
        if name == "retention_zdr" and value in {
            "yes_public",
            "yes_sales_gated",
            "yes_platform_only",
        }:
            return PrivacyEvidence(
                constraint=PrivacyConstraint.RETENTION,
                value=ZERO_DATA_RETENTION_AVAILABLE,
                scope=scope,
                source_kind="external_registry",
                source_id=source_id,
                verified_at=verified_at,
                expires_at=self._expires_at,
                conditional_on_account=True,
            )
        if name == "data_residency" and value in {
            "yes_public",
            "yes_sales_gated",
            "yes_platform_only",
        }:
            return PrivacyEvidence(
                constraint=PrivacyConstraint.DATA_LOCATION,
                value=DATA_RESIDENCY_AVAILABLE,
                scope=scope,
                source_kind="external_registry",
                source_id=source_id,
                verified_at=verified_at,
                expires_at=self._expires_at,
                conditional_on_account=True,
            )
        return None


_CONFLICT = object()


def _validate_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise PrivacyRegistrySchemaError("El snapshot debe ser un objeto JSON.")
    version = payload.get("schema_version", SUPPORTED_SCHEMA_VERSION)
    if version != SUPPORTED_SCHEMA_VERSION:
        raise UnsupportedPrivacyRegistrySchemaError(
            f"schema_version no soportada: {version!r}."
        )
    if payload.get("name") != REGISTRY_NAME:
        raise PrivacyRegistrySchemaError("Fuente de registry inesperada.")
    generated = payload.get("generated")
    offerings = payload.get("offerings")
    if not isinstance(generated, str) or not generated.strip():
        raise PrivacyRegistrySchemaError("generated es obligatorio.")
    _parse_verified(generated)
    if not isinstance(offerings, list):
        raise PrivacyRegistrySchemaError("offerings debe ser una lista.")
    for offering in offerings:
        if not isinstance(offering, Mapping):
            raise PrivacyRegistrySchemaError("Cada offering debe ser un objeto.")
        for field in ("id", "developer", "platform"):
            if not isinstance(offering.get(field), str) or not offering[field].strip():
                raise PrivacyRegistrySchemaError(f"offering.{field} es obligatorio.")
        if not isinstance(offering.get("dimensions"), Mapping):
            raise PrivacyRegistrySchemaError("offering.dimensions debe ser un objeto.")
    return payload


def _select_offering(
    offerings: list[object],
    target: InferenceTarget,
) -> Mapping[str, Any] | None:
    candidates = [
        item
        for item in offerings
        if isinstance(item, Mapping)
        and _key(str(item["developer"])) == _key(target.provider)
    ]
    if target.offering is not None:
        exact = [item for item in candidates if _key(str(item["id"])) == _key(target.offering)]
        return exact[0] if len(exact) == 1 else None
    if target.platform is not None:
        platform = [
            item
            for item in candidates
            if _key(str(item["platform"])) == _key(target.platform)
        ]
        if len(platform) == 1:
            return platform[0]
        if len(platform) > 1:
            return None
    return candidates[0] if len(candidates) == 1 else None


def _select_model_exception(
    offering: Mapping[str, Any],
    model: str | None,
) -> Mapping[str, Any] | object | None:
    if model is None:
        return None
    exceptions = offering.get("model_exceptions", [])
    if not isinstance(exceptions, list):
        return _CONFLICT
    matches = [
        item
        for item in exceptions
        if isinstance(item, Mapping)
        and isinstance(item.get("model"), str)
        and _key(item["model"]) == _key(model)
        and isinstance(item.get("dimensions"), Mapping)
    ]
    if len(matches) > 1:
        return _CONFLICT
    return matches[0] if matches else None


def _parse_verified(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise PrivacyRegistrySchemaError(f"Fecha invalida: {value!r}.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _key(value: str) -> str:
    return "-".join(value.strip().lower().replace("_", "-").split())
