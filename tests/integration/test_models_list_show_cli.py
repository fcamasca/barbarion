"""Integracion CLI de `models list` y `models show` con Ollama fake."""

import json
from pathlib import Path

import pytest

from barbarion import cli
from barbarion.domain.local_models import (
    LocalModel,
    LocalModelDetails,
    LocalModelErrorCode,
    LocalModelProviderError,
)


class FakeOllamaClient:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.raw_template = "BLOB-SECRETO-QUE-NO-DEBE-SALIR"

    def list_models(self, *, timeout_seconds: float):  # noqa: ANN201
        self.calls.append(("list", timeout_seconds))
        return (
            LocalModel("modelo-b:tag", size_bytes=20, digest="b" * 64),
            LocalModel(
                "modelo-a:tag",
                size_bytes=10,
                modified_at="2026-07-20T10:00:00Z",
                digest="a" * 64,
            ),
        )

    def show_model(self, name: str, *, timeout_seconds: float):  # noqa: ANN201
        self.calls.append(("show", name, timeout_seconds))
        return LocalModelDetails(
            LocalModel(name),
            format="gguf",
            family="generic",
            parameter_size="small",
            quantization_level="Q4",
            capabilities=("completion", "tools"),
        )


def _config(tmp_path: Path) -> Path:
    source = tmp_path / "barbarion.toml"
    source.write_text(
        """ollama_timeout_seconds = 3.0
[llm]
provider = "ollama"
model = "modelo-a:tag"
timeout_seconds = 120.0
temperature = 0.1
""",
        encoding="utf-8",
    )
    return source


def _anthropic_config(tmp_path: Path) -> Path:
    source = tmp_path / "barbarion-anthropic.toml"
    source.write_text(
        """ollama_timeout_seconds = 3.0
[llm]
provider = "anthropic"
model = "claude-synthetic"
timeout_seconds = 120.0
temperature = 0.1
max_output_tokens = 1024
""",
        encoding="utf-8",
    )
    return source


def _use_fake(
    monkeypatch: pytest.MonkeyPatch,
    fake: FakeOllamaClient,
) -> None:
    monkeypatch.setattr(cli, "OllamaModelClient", lambda _url: fake)


def test_models_list_text_marks_active_and_does_not_expose_raw_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _config(tmp_path)
    fake = FakeOllamaClient()
    _use_fake(monkeypatch, fake)

    exit_code = cli.main(["--config", str(source), "models", "list"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out.index("modelo-a:tag") < captured.out.index("modelo-b:tag")
    assert "modelo-a:tag [activo]" in captured.out
    assert "modelo_activo_instalado = si" in captured.out
    assert "BLOB-SECRETO" not in captured.out + captured.err
    assert fake.calls == [("list", 3.0)]


def test_models_list_json_uses_only_normalized_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _config(tmp_path)
    fake = FakeOllamaClient()
    _use_fake(monkeypatch, fake)

    assert cli.main(
        ["--config", str(source), "models", "list", "--format", "json"]
    ) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["active_model"] == "modelo-a:tag"
    assert payload["active_model_installed"] is True
    assert [item["name"] for item in payload["models"]] == [
        "modelo-a:tag",
        "modelo-b:tag",
    ]
    assert set(payload["models"][0]) == {
        "name",
        "size_bytes",
        "modified_at",
        "digest",
        "active",
        "metadata_truncated",
    }


def test_models_show_json_never_exposes_template_modelfile_or_blob(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _config(tmp_path)
    fake = FakeOllamaClient()
    _use_fake(monkeypatch, fake)

    assert cli.main(
        [
            "--config",
            str(source),
            "models",
            "show",
            "modelo-a:tag",
            "--format",
            "json",
        ]
    ) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert payload["name"] == "modelo-a:tag"
    assert payload["active"] is True
    assert payload["capabilities"] == ["completion", "tools"]
    serialized = captured.out + captured.err
    assert "template" not in serialized
    assert "modelfile" not in serialized
    assert "BLOB-SECRETO" not in serialized
    assert fake.calls == [("show", "modelo-a:tag", 3.0)]


def test_models_error_is_actionable_bounded_and_has_no_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _config(tmp_path)

    class FailedClient(FakeOllamaClient):
        def list_models(self, *, timeout_seconds: float):  # noqa: ANN201
            del timeout_seconds
            raise LocalModelProviderError(
                LocalModelErrorCode.UNAVAILABLE,
                "detalle\n" + ("x" * 500),
            )

    _use_fake(monkeypatch, FailedClient())

    assert cli.main(["--config", str(source), "models", "list"]) == 1
    captured = capsys.readouterr()

    assert captured.out == ""
    assert "OLLAMA_UNAVAILABLE" in captured.err
    assert "Traceback" not in captured.err
    assert "\n" not in captured.err.rstrip("\n")
    assert len(captured.err) < 380


def test_models_list_and_show_remain_ollama_only_with_anthropic_active(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _anthropic_config(tmp_path)
    fake = FakeOllamaClient()
    _use_fake(monkeypatch, fake)

    assert cli.main(
        ["--config", str(source), "models", "list", "--format", "json"]
    ) == 0
    listed = json.loads(capsys.readouterr().out)
    assert cli.main(
        [
            "--config",
            str(source),
            "models",
            "show",
            "modelo-a:tag",
            "--format",
            "json",
        ]
    ) == 0
    shown = json.loads(capsys.readouterr().out)

    assert listed["active_model"] == "claude-synthetic"
    assert listed["active_model_installed"] is False
    assert shown["name"] == "modelo-a:tag"
    assert shown["active"] is False
    assert fake.calls == [
        ("list", 3.0),
        ("show", "modelo-a:tag", 3.0),
    ]
