"""Integracion CLI de `models validate`."""

import json
from pathlib import Path

import pytest

from barbarion import cli
from barbarion.application.local_models import VALIDATION_MARKER
from barbarion.domain.local_models import (
    LocalModel,
    LocalModelErrorCode,
    LocalModelProviderError,
    ModelGenerationResult,
)


class FakeValidationClient:
    def __init__(
        self,
        models: tuple[LocalModel, ...],
        *,
        response: str = VALIDATION_MARKER,
        list_error: LocalModelProviderError | None = None,
    ) -> None:
        self.models = models
        self.response = response
        self.list_error = list_error
        self.calls: list[tuple[object, ...]] = []
        self.prompt: str | None = None

    def list_models(self, *, timeout_seconds: float):  # noqa: ANN201
        self.calls.append(("list", timeout_seconds))
        if self.list_error is not None:
            raise self.list_error
        return self.models

    def generate_detailed(self, request):  # noqa: ANN001, ANN201
        self.calls.append(("generate", request.model, request.timeout_seconds))
        self.prompt = request.prompt
        return ModelGenerationResult(self.response)


def _config(tmp_path: Path) -> Path:
    source = tmp_path / "barbarion.toml"
    source.write_text(
        """[llm]
provider = "ollama"
model = "modelo-activo:tag"
timeout_seconds = 80.0
temperature = 0.1
""",
        encoding="utf-8",
    )
    return source


def _use_fake(
    monkeypatch: pytest.MonkeyPatch,
    fake: FakeValidationClient,
) -> None:
    monkeypatch.setattr(cli, "OllamaModelClient", lambda _url: fake)


def test_validate_defaults_to_active_and_reports_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _config(tmp_path)
    fake = FakeValidationClient((LocalModel("modelo-activo:tag"),))
    _use_fake(monkeypatch, fake)

    assert cli.main(["--config", str(source), "models", "validate"]) == 0
    captured = capsys.readouterr()

    assert "available = si" in captured.out
    assert "installed = si" in captured.out
    assert "generation_ready = si" in captured.out
    assert "benchmark_eligible = si" in captured.out
    assert "no acredita calidad RAG" in captured.out
    assert VALIDATION_MARKER not in captured.out + captured.err
    assert fake.prompt is not None
    assert "modelo-activo:tag" not in fake.prompt


def test_validate_explicit_model_json_keeps_states_separate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _config(tmp_path)
    fake = FakeValidationClient((LocalModel("modelo-alterno:tag"),))
    _use_fake(monkeypatch, fake)

    assert cli.main(
        [
            "--config",
            str(source),
            "models",
            "validate",
            "modelo-alterno:tag",
            "--format",
            "json",
            "--timeout",
            "9",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["model"] == "modelo-alterno:tag"
    assert payload["active"] is False
    assert payload["available"] is True
    assert payload["installed"] is True
    assert payload["generation_ready"] is True
    assert payload["benchmark_eligible"] is True
    assert fake.calls == [
        ("list", 9.0),
        ("generate", "modelo-alterno:tag", 9.0),
    ]


def test_validate_missing_model_returns_one_without_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _config(tmp_path)
    fake = FakeValidationClient(())
    _use_fake(monkeypatch, fake)

    assert cli.main(["--config", str(source), "models", "validate"]) == 1
    payload_text = capsys.readouterr().out

    assert "available = si" in payload_text
    assert "installed = no" in payload_text
    assert "generation_ready = no" in payload_text
    assert "benchmark_eligible = no" in payload_text
    assert "MODEL_NOT_INSTALLED" in payload_text
    assert fake.calls == [("list", 80.0)]


def test_validate_unavailable_still_renders_four_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _config(tmp_path)
    fake = FakeValidationClient(
        (),
        list_error=LocalModelProviderError(
            LocalModelErrorCode.UNAVAILABLE,
            "sin conexion\n" + "x" * 500,
        ),
    )
    _use_fake(monkeypatch, fake)

    assert cli.main(
        ["--config", str(source), "models", "validate", "--format", "json"]
    ) == 1
    payload = json.loads(capsys.readouterr().out)

    assert payload["available"] is False
    assert payload["installed"] is False
    assert payload["generation_ready"] is False
    assert payload["benchmark_eligible"] is False
    assert payload["diagnostic_code"] == "OLLAMA_UNAVAILABLE"
    assert "\n" not in payload["diagnostic"]
    assert len(payload["diagnostic"]) == 300


def test_validate_wrong_marker_does_not_expose_model_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _config(tmp_path)
    secret_response = "RESPUESTA-SINTETICA-NO-MOSTRAR"
    fake = FakeValidationClient(
        (LocalModel("modelo-activo:tag"),),
        response=secret_response,
    )
    _use_fake(monkeypatch, fake)

    assert cli.main(["--config", str(source), "models", "validate"]) == 1
    captured = capsys.readouterr()

    assert "MODEL_NOT_GENERATION_READY" in captured.out
    assert secret_response not in captured.out + captured.err
