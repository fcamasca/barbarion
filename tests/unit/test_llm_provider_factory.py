"""Pruebas de la factoria LLM cerrada de H1.2."""

from dataclasses import replace
from pathlib import Path

import pytest

from barbarion import cli
from barbarion.config import ConfigError, Settings, load_settings
from barbarion.domain.rag import LlmProviderError
from barbarion.infrastructure.anthropic import AnthropicLlmProvider
from barbarion.infrastructure.llm import OllamaLlmProvider


class TrackingEnvironment(dict[str, str]):
    """Entorno mutable que registra lecturas explicitas."""

    def __init__(self) -> None:
        super().__init__()
        self.read_count = 0

    def get(self, key: str, default: str | None = None) -> str | None:
        self.read_count += 1
        return super().get(key, default)


def _load_anthropic_settings(tmp_path: Path) -> Settings:
    source = tmp_path / "anthropic.toml"
    source.write_text(
        "\n".join(
            (
                "[llm]",
                'provider = "anthropic"',
                'model = "claude-test"',
                "timeout_seconds = 45.0",
                "temperature = 0.3",
                "max_output_tokens = 6144",
            )
        ),
        encoding="utf-8",
    )
    return load_settings(source, environ={}, cwd=tmp_path)


def test_factory_keeps_existing_ollama_branch(tmp_path: Path) -> None:
    settings = load_settings(environ={}, cwd=tmp_path)

    provider = cli._build_llm_provider(settings, environ={})

    assert isinstance(provider, OllamaLlmProvider)
    assert provider.provider == "ollama"
    assert provider.model == settings.llm.model


def test_factory_builds_anthropic_without_http_transport(tmp_path: Path) -> None:
    settings = _load_anthropic_settings(tmp_path)

    provider = cli._build_llm_provider(settings, environ={})

    assert isinstance(provider, AnthropicLlmProvider)
    assert provider.provider == "anthropic"
    assert provider.model == "claude-test"
    assert provider.temperature == 0.3
    assert provider.max_output_tokens == 6144


def test_factory_reads_anthropic_key_only_when_generation_starts(
    tmp_path: Path,
) -> None:
    settings = _load_anthropic_settings(tmp_path)
    environment = TrackingEnvironment()

    provider = cli._build_llm_provider(settings, environ=environment)

    assert environment.read_count == 0
    with pytest.raises(LlmProviderError, match="ANTHROPIC_API_KEY_MISSING"):
        provider.generate(prompt="prompt sintetico", timeout_seconds=1.0)
    assert environment.read_count == 1

    canary = "sk-ant-test-NEVER-LOG-H12-0123456789"
    environment["ANTHROPIC_API_KEY"] = canary
    with pytest.raises(LlmProviderError, match="ANTHROPIC_LLM_NOT_IMPLEMENTED"):
        provider.generate(prompt="prompt sintetico", timeout_seconds=1.0)

    assert environment.read_count == 2
    assert canary not in repr(provider)


def test_factory_rejects_any_branch_outside_closed_pair(tmp_path: Path) -> None:
    settings = load_settings(environ={}, cwd=tmp_path)
    invalid = replace(
        settings,
        llm=replace(settings.llm, provider="unknown"),
    )

    with pytest.raises(ConfigError, match="Proveedor LLM no soportado"):
        cli._build_llm_provider(invalid, environ={})
