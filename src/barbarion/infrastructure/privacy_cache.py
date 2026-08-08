"""Cache atomica y refresh explicito para evidencia publica de privacidad."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from barbarion.domain.privacy import PrivacyPolicySource
from barbarion.infrastructure.privacy_registry import (
    REGISTRY_NAME,
    REGISTRY_SOURCE_ID,
    AiProviderTrustRegistrySource,
    PrivacyRegistryError,
)


CACHE_SCHEMA_VERSION = 1
CACHE_FILENAME = "registry-snapshot.json"
_DIMENSIONS = frozenset(
    {"training_on_customer_data", "retention_zdr", "data_residency"}
)
_CELL_FIELDS = ("value", "confidence", "source", "verified")


class PrivacyCacheStatus(StrEnum):
    """Estado exhaustivo de una lectura local."""

    VALID = "valid"
    MISSING = "missing"
    EXPIRED = "expired"
    INVALID = "invalid"


class PrivacyCacheError(RuntimeError):
    """Error base del almacenamiento local de evidencia."""


class PrivacyRefreshError(PrivacyCacheError):
    """El refresh no pudo producir un snapshot valido."""


class PrivacyRegistryFetcher(Protocol):
    """Puerto del comando explicito; no recibe identidad ni contenido."""

    def fetch(self) -> Mapping[str, Any]:
        """Descarga el snapshot publico completo."""
        ...


@dataclass(frozen=True, slots=True)
class PrivacyCacheReadResult:
    """Resultado local; nunca expresa una decision de privacidad."""

    status: PrivacyCacheStatus
    reason_code: str
    source: PrivacyPolicySource | None = None
    source_version: str | None = None
    fetched_at: datetime | None = None
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.status is PrivacyCacheStatus.VALID and self.source is None:
            raise ValueError("Una cache valid requiere source.")
        if self.status is not PrivacyCacheStatus.VALID and self.source is not None:
            raise ValueError("Solo una cache valid puede exponer source.")


@dataclass(frozen=True, slots=True)
class PrivacyRefreshResult:
    """Metadata del snapshot persistido por una operacion explicita."""

    source_version: str
    fetched_at: datetime
    expires_at: datetime
    path: Path


class PrivacySnapshotCache:
    """Lee evidencia local y reemplaza snapshots de forma atomica."""

    def __init__(self, data_dir: Path) -> None:
        self._directory = Path(data_dir) / "privacy"
        self._path = self._directory / CACHE_FILENAME

    @property
    def path(self) -> Path:
        return self._path

    def read(self, *, now: datetime) -> PrivacyCacheReadResult:
        _require_aware(now, "now")
        if not self._path.exists():
            return PrivacyCacheReadResult(
                status=PrivacyCacheStatus.MISSING,
                reason_code="privacy_cache_missing",
            )
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            envelope = _validate_envelope(raw, now=now)
        except (OSError, UnicodeError, json.JSONDecodeError, PrivacyCacheError):
            return PrivacyCacheReadResult(
                status=PrivacyCacheStatus.INVALID,
                reason_code="privacy_cache_invalid",
            )

        if now >= envelope["expires_at"]:
            return PrivacyCacheReadResult(
                status=PrivacyCacheStatus.EXPIRED,
                reason_code="privacy_cache_expired",
                source_version=envelope["source_version"],
                fetched_at=envelope["fetched_at"],
                expires_at=envelope["expires_at"],
            )
        try:
            source = AiProviderTrustRegistrySource(
                envelope["payload"],
                expires_at=envelope["expires_at"],
            )
        except PrivacyRegistryError:
            return PrivacyCacheReadResult(
                status=PrivacyCacheStatus.INVALID,
                reason_code="privacy_cache_invalid",
            )
        return PrivacyCacheReadResult(
            status=PrivacyCacheStatus.VALID,
            reason_code="privacy_cache_valid",
            source=source,
            source_version=envelope["source_version"],
            fetched_at=envelope["fetched_at"],
            expires_at=envelope["expires_at"],
        )

    def refresh(
        self,
        fetcher: PrivacyRegistryFetcher,
        *,
        now: datetime,
        ttl: timedelta,
    ) -> PrivacyRefreshResult:
        """Obtiene, valida y reemplaza la cache solo al completar todo."""
        _require_aware(now, "now")
        if not isinstance(ttl, timedelta) or ttl <= timedelta(0):
            raise PrivacyRefreshError("ttl debe ser positivo.")
        try:
            payload = _sanitize_payload(fetcher.fetch())
            source_expires_at = _optional_source_expiry(payload)
            expires_at = now + ttl
            if source_expires_at is not None:
                expires_at = min(expires_at, source_expires_at)
            if expires_at <= now:
                raise PrivacyRefreshError("El snapshot ya esta expirado.")
            _validate_verified_clock(payload, fetched_at=now)
            # Valida el contrato de cache antes de tocar la cache vigente.
            AiProviderTrustRegistrySource(payload, expires_at=expires_at)
            envelope = _build_envelope(
                payload,
                fetched_at=now,
                expires_at=expires_at,
            )
            self._write_atomic(envelope)
        except PrivacyRefreshError:
            raise
        except Exception as exc:
            raise PrivacyRefreshError("No se pudo refrescar la evidencia.") from exc
        return PrivacyRefreshResult(
            source_version=str(payload["generated"]),
            fetched_at=now,
            expires_at=expires_at,
            path=self._path,
        )

    def _write_atomic(self, envelope: Mapping[str, Any]) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        serialized = _canonical_json(envelope)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=self._directory,
                prefix=f".{CACHE_FILENAME}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self._path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()


def _build_envelope(
    payload: Mapping[str, Any],
    *,
    fetched_at: datetime,
    expires_at: datetime,
) -> dict[str, Any]:
    body = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "source_id": REGISTRY_SOURCE_ID,
        "source_version": str(payload["generated"]),
        "fetched_at": _format_datetime(fetched_at),
        "expires_at": _format_datetime(expires_at),
        "payload": payload,
    }
    return {**body, "integrity_sha256": _digest(body)}


def _validate_envelope(raw: object, *, now: datetime) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise PrivacyCacheError("Envelope invalido.")
    if raw.get("schema_version") != CACHE_SCHEMA_VERSION:
        raise PrivacyCacheError("Schema de cache no soportado.")
    if raw.get("source_id") != REGISTRY_SOURCE_ID:
        raise PrivacyCacheError("Identidad de fuente invalida.")
    integrity = raw.get("integrity_sha256")
    body = {key: value for key, value in raw.items() if key != "integrity_sha256"}
    if not isinstance(integrity, str) or integrity != _digest(body):
        raise PrivacyCacheError("Integridad invalida.")
    fetched_at = _parse_datetime(raw.get("fetched_at"))
    expires_at = _parse_datetime(raw.get("expires_at"))
    if fetched_at > now:
        raise PrivacyCacheError("Reloj futuro.")
    if expires_at <= fetched_at:
        raise PrivacyCacheError("Vigencia invalida.")
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        raise PrivacyCacheError("Payload invalido.")
    if raw.get("source_version") != payload.get("generated"):
        raise PrivacyCacheError("Version de fuente inconsistente.")
    _validate_verified_clock(payload, fetched_at=fetched_at)
    return {
        **raw,
        "payload": payload,
        "fetched_at": fetched_at,
        "expires_at": expires_at,
    }


def _sanitize_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise PrivacyRefreshError("El registry no devolvio un objeto.")
    sanitized: dict[str, Any] = {
        "schema_version": payload.get("schema_version", 1),
        "name": payload.get("name"),
        "generated": payload.get("generated"),
        "offerings": [],
    }
    if "expires" in payload:
        sanitized["expires"] = payload["expires"]
    offerings = payload.get("offerings")
    if not isinstance(offerings, list):
        raise PrivacyRefreshError("offerings debe ser una lista.")
    for raw_offering in offerings:
        if not isinstance(raw_offering, Mapping):
            raise PrivacyRefreshError("Offering invalido.")
        offering: dict[str, Any] = {
            field: raw_offering.get(field)
            for field in ("id", "developer", "platform")
        }
        offering["dimensions"] = _sanitize_dimensions(raw_offering.get("dimensions"))
        if "model_exceptions" in raw_offering:
            exceptions = raw_offering["model_exceptions"]
            if not isinstance(exceptions, list):
                raise PrivacyRefreshError("model_exceptions debe ser una lista.")
            offering["model_exceptions"] = [
                {
                    "model": item.get("model"),
                    "dimensions": _sanitize_dimensions(item.get("dimensions")),
                }
                for item in exceptions
                if isinstance(item, Mapping)
            ]
        sanitized["offerings"].append(offering)
    if sanitized["name"] != REGISTRY_NAME:
        raise PrivacyRefreshError("Fuente de registry inesperada.")
    return sanitized


def _sanitize_dimensions(raw: object) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise PrivacyRefreshError("dimensions debe ser un objeto.")
    return {
        name: {field: cell.get(field) for field in _CELL_FIELDS}
        for name, cell in raw.items()
        if name in _DIMENSIONS and isinstance(cell, Mapping)
    }


def _validate_verified_clock(payload: Mapping[str, Any], *, fetched_at: datetime) -> None:
    for offering in payload.get("offerings", []):
        dimension_groups = [offering.get("dimensions", {})]
        dimension_groups.extend(
            item.get("dimensions", {})
            for item in offering.get("model_exceptions", [])
            if isinstance(item, Mapping)
        )
        for dimensions in dimension_groups:
            for cell in dimensions.values():
                if isinstance(cell, Mapping) and isinstance(cell.get("verified"), str):
                    if _parse_source_datetime(cell["verified"]) > fetched_at:
                        raise PrivacyCacheError("Evidencia verificada en el futuro.")


def _optional_source_expiry(payload: Mapping[str, Any]) -> datetime | None:
    value = payload.get("expires")
    return None if value is None else _parse_source_datetime(value)


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _format_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise PrivacyCacheError("Timestamp invalido.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PrivacyCacheError("Timestamp invalido.") from exc
    _require_aware(parsed, "timestamp")
    return parsed


def _parse_source_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise PrivacyCacheError("Timestamp de fuente invalido.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PrivacyCacheError("Timestamp de fuente invalido.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _require_aware(value: datetime, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PrivacyCacheError(f"{name} debe incluir zona horaria.")
