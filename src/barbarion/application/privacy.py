"""Composicion local del destino de inferencia para H3.2."""

from __future__ import annotations

from urllib.parse import urlsplit

from barbarion.config import Settings
from barbarion.domain.privacy import InferenceExecution, InferenceTarget


OLLAMA_CLOUD_API_HOST = "ollama.com"


class InferenceTargetResolutionError(ValueError):
    """La declaracion del operador contradice el transporte demostrado."""


def resolve_inference_target(settings: Settings) -> InferenceTarget:
    """Resuelve la frontera sin IO, politicas, registry, cache ni nombres modelo."""
    provider = settings.llm.provider
    if provider == "anthropic":
        return InferenceTarget(
            execution=InferenceExecution.REMOTE,
            provider="anthropic",
            platform="direct_api",
            model=settings.llm.model,
        )
    if provider != "ollama":
        return InferenceTarget(
            execution=InferenceExecution.UNKNOWN,
            provider=provider,
            platform=None,
            model=settings.llm.model,
        )
    return _resolve_ollama_target(settings)


def _resolve_ollama_target(settings: Settings) -> InferenceTarget:
    parsed = urlsplit(settings.ollama_url)
    host = (parsed.hostname or "").lower().rstrip(".")
    direct_cloud = parsed.scheme.lower() == "https" and host == OLLAMA_CLOUD_API_HOST
    declared = settings.llm.execution

    if direct_cloud:
        if declared == "local":
            raise InferenceTargetResolutionError(
                "llm.execution=local contradice el endpoint remoto ollama.com."
            )
        return InferenceTarget(
            execution=InferenceExecution.REMOTE,
            provider="ollama",
            platform="ollama_cloud",
            model=settings.llm.model,
        )

    if declared == "local":
        return InferenceTarget(
            execution=InferenceExecution.LOCAL,
            provider="ollama",
            platform="local_runtime",
            model=settings.llm.model,
        )
    if declared == "remote":
        return InferenceTarget(
            execution=InferenceExecution.REMOTE,
            provider="ollama",
            platform="ollama_cloud",
            model=settings.llm.model,
        )

    # Un daemon Ollama, incluso loopback, puede offloadear al cloud. Sin una
    # declaracion o endpoint directo demostrable, fail-closed comienza en UNKNOWN.
    return InferenceTarget(
        execution=InferenceExecution.UNKNOWN,
        provider="ollama",
        platform=None,
        model=settings.llm.model,
    )
