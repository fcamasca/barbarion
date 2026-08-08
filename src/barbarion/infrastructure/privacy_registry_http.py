"""Fetcher HTTP acotado para el snapshot publico de privacidad."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.request import Request, urlopen


PRIVACY_REGISTRY_URL = "https://aiprovidertrust.com/data.json"
PRIVACY_REGISTRY_TIMEOUT_SECONDS = 20.0
MAX_REGISTRY_BYTES = 10 * 1024 * 1024


class PrivacyRegistryHttpError(RuntimeError):
    """La descarga del registry no produjo un JSON valido."""


class HttpPrivacyRegistryFetcher:
    """Descarga exclusivamente el documento publico completo mediante GET."""

    def __init__(
        self,
        *,
        url: str = PRIVACY_REGISTRY_URL,
        timeout_seconds: float = PRIVACY_REGISTRY_TIMEOUT_SECONDS,
    ) -> None:
        if url != PRIVACY_REGISTRY_URL:
            raise ValueError("La URL del registry debe ser la oficial fija.")
        if timeout_seconds <= 0:
            raise ValueError("El timeout del registry debe ser positivo.")
        self.url = url
        self.timeout_seconds = timeout_seconds

    def fetch(self) -> Mapping[str, Any]:
        request = Request(
            self.url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Barbarion-PrivacyRefresh/1.0",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                status = getattr(response, "status", None)
                if status != 200:
                    raise PrivacyRegistryHttpError(
                        f"El registry respondio HTTP {status!r}."
                    )
                payload = response.read(MAX_REGISTRY_BYTES + 1)
        except PrivacyRegistryHttpError:
            raise
        except Exception as exc:
            raise PrivacyRegistryHttpError(
                "No se pudo descargar el registry de privacidad."
            ) from exc
        if len(payload) > MAX_REGISTRY_BYTES:
            raise PrivacyRegistryHttpError("El registry excede el tamano permitido.")
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PrivacyRegistryHttpError("El registry no devolvio JSON valido.") from exc
        if not isinstance(decoded, Mapping):
            raise PrivacyRegistryHttpError("El registry no devolvio un objeto JSON.")
        return decoded
