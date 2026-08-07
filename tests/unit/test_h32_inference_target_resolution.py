"""Resolucion determinista de la frontera de inferencia H3.2-T03."""

from __future__ import annotations

from pathlib import Path

import pytest

from barbarion.application.privacy import (
    InferenceTargetResolutionError,
    resolve_inference_target,
)
from barbarion.config import load_settings
from barbarion.domain.privacy import InferenceExecution


def _settings(
    tmp_path: Path,
    *,
    provider: str,
    model: str,
    ollama_url: str = "http://127.0.0.1:11434",
    execution: str | None = None,
):
    lines = [
        f'ollama_url = "{ollama_url}"',
        "[llm]",
        f'provider = "{provider}"',
        f'model = "{model}"',
    ]
    if execution is not None:
        lines.append(f'execution = "{execution}"')
    source = tmp_path / f"{provider}-{model.replace(':', '-')}.toml"
    source.write_text("\n".join(lines), encoding="utf-8")
    return load_settings(source, environ={}, cwd=tmp_path)


@pytest.mark.parametrize("model", ("claude-synthetic", "nombre-local:latest"))
def test_h32_tp009_anthropic_direct_is_always_remote(
    tmp_path: Path,
    model: str,
) -> None:
    target = resolve_inference_target(
        _settings(tmp_path, provider="anthropic", model=model)
    )

    assert target.execution is InferenceExecution.REMOTE
    assert target.provider == "anthropic"
    assert target.platform == "direct_api"
    assert target.model == model


@pytest.mark.parametrize("model", ("local-model", "cloud-looking:cloud"))
def test_h32_tp007_explicit_ollama_local_is_local_without_model_heuristic(
    tmp_path: Path,
    model: str,
) -> None:
    target = resolve_inference_target(
        _settings(
            tmp_path,
            provider="ollama",
            model=model,
            execution="local",
        )
    )

    assert target.execution is InferenceExecution.LOCAL
    assert target.provider == "ollama"
    assert target.platform == "local_runtime"


@pytest.mark.parametrize("model", ("cloud-model", "plain-name"))
def test_h32_tp008_direct_ollama_cloud_endpoint_is_remote_for_any_model(
    tmp_path: Path,
    model: str,
) -> None:
    target = resolve_inference_target(
        _settings(
            tmp_path,
            provider="ollama",
            model=model,
            ollama_url="https://ollama.com",
        )
    )

    assert target.execution is InferenceExecution.REMOTE
    assert target.provider == "ollama"
    assert target.platform == "ollama_cloud"


def test_h32_tp008_remote_override_marks_daemon_backed_cloud(tmp_path: Path) -> None:
    target = resolve_inference_target(
        _settings(
            tmp_path,
            provider="ollama",
            model="opaque-model-name",
            execution="remote",
        )
    )

    assert target.execution is InferenceExecution.REMOTE
    assert target.platform == "ollama_cloud"


@pytest.mark.parametrize("model", ("ordinary-local-name", "obvious:cloud"))
def test_h32_tp008_loopback_without_transport_proof_is_unknown_not_local(
    tmp_path: Path,
    model: str,
) -> None:
    target = resolve_inference_target(
        _settings(tmp_path, provider="ollama", model=model)
    )

    assert target.execution is InferenceExecution.UNKNOWN
    assert target.platform is None


@pytest.mark.parametrize(
    "url",
    (
        "https://ollama.com.example.test",
        "https://api.ollama.com.example.test",
        "http://ollama.com",
    ),
)
def test_h32_ollama_cloud_detection_requires_exact_secure_host(
    tmp_path: Path,
    url: str,
) -> None:
    target = resolve_inference_target(
        _settings(
            tmp_path,
            provider="ollama",
            model="irrelevant-model",
            ollama_url=url,
        )
    )

    assert target.execution is InferenceExecution.UNKNOWN
    assert target.platform is None


def test_h32_direct_cloud_rejects_contradictory_local_override(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        provider="ollama",
        model="irrelevant-model",
        ollama_url="https://ollama.com",
        execution="local",
    )

    with pytest.raises(InferenceTargetResolutionError, match="contradice"):
        resolve_inference_target(settings)
