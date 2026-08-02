"""Integracion CLI de `models select`."""

from pathlib import Path

import pytest

from barbarion import cli
from barbarion.application.local_models import VALIDATION_MARKER
from barbarion.config import load_settings
from barbarion.domain.local_models import LocalModel, ModelGenerationResult


class FakeSelectClient:
    def __init__(self, *, ready: bool = True, installed: bool = True) -> None:
        self.ready = ready
        self.installed = installed
        self.calls: list[str] = []

    def list_models(self, *, timeout_seconds: float):  # noqa: ANN201
        del timeout_seconds
        self.calls.append("list")
        if self.installed:
            return (LocalModel("modelo-nuevo:tag"),)
        return ()

    def generate_detailed(self, request):  # noqa: ANN001, ANN201
        self.calls.append("generate")
        response = VALIDATION_MARKER if self.ready else "respuesta incorrecta"
        return ModelGenerationResult(response)


def _config(tmp_path: Path) -> Path:
    source = tmp_path / "barbarion.toml"
    source.write_text(
        """[llm]
provider = "ollama"
model = "modelo-anterior:tag" # conservar comentario
timeout_seconds = 20.0
temperature = 0.1

[embeddings]
provider = "ollama"
model = "embed-estable:tag"
""",
        encoding="utf-8",
    )
    return source


def _anthropic_config(tmp_path: Path) -> Path:
    source = tmp_path / "barbarion-anthropic.toml"
    source.write_text(
        """[llm]
provider = "anthropic"
model = "claude-synthetic"
timeout_seconds = 20.0
temperature = 0.1
max_output_tokens = 1024
""",
        encoding="utf-8",
    )
    return source


def test_models_select_validates_and_applies_atomic_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _config(tmp_path)
    fake = FakeSelectClient()
    monkeypatch.setattr(cli, "OllamaModelClient", lambda _url: fake)

    exit_code = cli.main(
        ["--config", str(source), "models", "select", "modelo-nuevo:tag"]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert fake.calls == ["list", "generate"]
    assert "modelo_anterior = modelo-anterior:tag" in captured.out
    assert "modelo_nuevo = modelo-nuevo:tag" in captured.out
    assert "generation_ready_validado = si" in captured.out
    settings = load_settings(source, environ={}, cwd=tmp_path)
    assert settings.llm.model == "modelo-nuevo:tag"
    assert settings.embeddings.model == "embed-estable:tag"


def test_models_select_dry_run_does_not_call_ollama_or_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _config(tmp_path)
    before = source.read_bytes()
    fake = FakeSelectClient()
    monkeypatch.setattr(cli, "OllamaModelClient", lambda _url: fake)

    assert cli.main(
        [
            "--config",
            str(source),
            "models",
            "select",
            "modelo-nuevo:tag",
            "--dry-run",
        ]
    ) == 0
    output = capsys.readouterr().out

    assert "dry_run = si" in output
    assert "no se escribio" in output
    assert fake.calls == []
    assert source.read_bytes() == before


@pytest.mark.parametrize(("installed", "ready"), [(False, True), (True, False)])
def test_models_select_validation_failure_preserves_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    installed: bool,
    ready: bool,
) -> None:
    source = _config(tmp_path)
    before = source.read_bytes()
    fake = FakeSelectClient(installed=installed, ready=ready)
    monkeypatch.setattr(cli, "OllamaModelClient", lambda _url: fake)

    assert cli.main(
        ["--config", str(source), "models", "select", "modelo-nuevo:tag"]
    ) == 1

    captured = capsys.readouterr()
    assert source.read_bytes() == before
    assert "MODEL_NOT_" in captured.err


def test_models_select_defaults_config_is_actionable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "OllamaModelClient", lambda _url: FakeSelectClient())

    assert cli.main(["models", "select", "modelo-nuevo:tag", "--dry-run"]) == 1

    assert "MODEL_CONFIG_NOT_EDITABLE" in capsys.readouterr().err


@pytest.mark.parametrize("dry_run", [False, True])
def test_models_select_rejects_anthropic_without_calling_ollama_or_editing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    dry_run: bool,
) -> None:
    source = _anthropic_config(tmp_path)
    before = source.read_bytes()
    fake = FakeSelectClient()
    monkeypatch.setattr(cli, "OllamaModelClient", lambda _url: fake)
    arguments = [
        "--config",
        str(source),
        "models",
        "select",
        "modelo-local:tag",
    ]
    if dry_run:
        arguments.append("--dry-run")

    assert cli.main(arguments) == 1
    captured = capsys.readouterr()

    assert "MODEL_CONFIG_NOT_EDITABLE" in captured.err
    assert "limitacion temporal" in captured.err
    assert "provider = \"ollama\"" in captured.err
    assert fake.calls == []
    assert source.read_bytes() == before
