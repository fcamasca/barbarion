"""Proveedor Anthropic pendiente de transporte HTTP en H1.2-T03."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from barbarion.domain.rag import LlmProviderError

ANTHROPIC_API_KEY_ENV_VAR = "ANTHROPIC_API_KEY"


@dataclass(frozen=True, slots=True)
class AnthropicLlmProvider:
    """Configuracion Anthropic con resolucion tardia de la credencial."""

    model: str
    temperature: float
    max_output_tokens: int
    _api_key_resolver: Callable[[], str | None] = field(
        repr=False,
        compare=False,
    )
    provider: str = "anthropic"

    def generate(self, *, prompt: str, timeout_seconds: float) -> str:
        """Resuelve la key al generar; el transporte se incorpora en T03."""
        del prompt, timeout_seconds
        self._resolve_api_key()
        raise LlmProviderError(
            "ANTHROPIC_LLM_NOT_IMPLEMENTED: el transporte Anthropic se "
            "incorporara en H1.2-T03."
        )

    def _resolve_api_key(self) -> str:
        """Obtiene la credencial solo durante una generacion efectiva."""
        api_key = self._api_key_resolver()
        if api_key is None or not api_key.strip():
            raise LlmProviderError(
                "ANTHROPIC_API_KEY_MISSING: define ANTHROPIC_API_KEY en el "
                "entorno antes de solicitar generacion Anthropic."
            )
        return api_key
