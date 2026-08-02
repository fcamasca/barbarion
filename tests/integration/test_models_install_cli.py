"""Integracion CLI de `models install` con Ollama fake."""

from collections.abc import Callable
from pathlib import Path

import pytest

from barbarion import cli
from barbarion.domain.local_models import (
    LocalModel,
    LocalModelErrorCode,
    LocalModelProviderError,
    PullProgress,
    PullResult,
)


class FakeInstallClient:
    def __init__(
        self,
        listings: list[tuple[LocalModel, ...]],
        *,
        interrupt: bool = False,
    ) -> None:
        self.listings = list(listings)
        self.interrupt = interrupt
        self.calls: list[tuple[object, ...]] = []

    def list_models(self, *, timeout_seconds: float):  # noqa: ANN201
        self.calls.append(("list", timeout_seconds))
        return self.listings.pop(0)

    def pull_model(
        self,
        name: str,
        *,
        timeout_seconds: float,
        on_progress: Callable[[PullProgress], None] | None = None,
    ) -> PullResult:
        self.calls.append(("pull", name, timeout_seconds))
        if on_progress is not None:
            for completed in (1, 5, 11, 55):
                on_progress(
                    PullProgress(
                        "downloading",
                        completed=completed,
                        total=100,
                    )
                )
        if self.interrupt:
            raise LocalModelProviderError(
                LocalModelErrorCode.INTERRUPTED,
                "interrumpido",
            )
        if on_progress is not None:
            on_progress(PullProgress("success"))
        return PullResult(name, "success")


def _config(tmp_path: Path) -> Path:
    source = tmp_path / "barbarion.toml"
    source.write_text(
        """ollama_timeout_seconds = 2.0
[llm]
provider = "ollama"
model = "modelo-activo:tag"
timeout_seconds = 90.0
temperature = 0.1
""",
        encoding="utf-8",
    )
    return source


def _anthropic_config(tmp_path: Path) -> Path:
    source = tmp_path / "barbarion-anthropic.toml"
    source.write_text(
        """ollama_timeout_seconds = 2.0
[llm]
provider = "anthropic"
model = "claude-synthetic"
timeout_seconds = 90.0
temperature = 0.1
max_output_tokens = 1024
""",
        encoding="utf-8",
    )
    return source


def _use_fake(
    monkeypatch: pytest.MonkeyPatch,
    fake: FakeInstallClient,
) -> None:
    monkeypatch.setattr(cli, "OllamaModelClient", lambda _url: fake)


def test_install_confirms_presence_without_modifying_active_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _config(tmp_path)
    before = source.read_bytes()
    fake = FakeInstallClient([(), (LocalModel("modelo-nuevo:tag"),)])
    _use_fake(monkeypatch, fake)

    exit_code = cli.main(
        ["--config", str(source), "models", "install", "modelo-nuevo:tag"]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "estado = instalado y confirmado" in captured.out
    assert "presencia_final = confirmada" in captured.out
    assert "Ollama: downloading 1%" in captured.err
    assert "Ollama: downloading 11%" in captured.err
    assert "Ollama: downloading 5%" not in captured.err
    assert source.read_bytes() == before
    assert b'model = "modelo-activo:tag"' in before
    assert fake.calls == [
        ("list", 90.0),
        ("pull", "modelo-nuevo:tag", 90.0),
        ("list", 90.0),
    ]


def test_install_dry_run_never_pulls_or_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _config(tmp_path)
    before = source.read_bytes()
    fake = FakeInstallClient([()])
    _use_fake(monkeypatch, fake)

    assert cli.main(
        [
            "--config",
            str(source),
            "models",
            "install",
            "modelo-nuevo:tag",
            "--dry-run",
        ]
    ) == 0
    captured = capsys.readouterr()

    assert "estado = se solicitaría la descarga" in captured.out
    assert "pull_solicitado = no" in captured.out
    assert captured.err == ""
    assert fake.calls == [("list", 90.0)]
    assert source.read_bytes() == before


def test_install_already_present_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _config(tmp_path)
    fake = FakeInstallClient([(LocalModel("modelo-nuevo:tag"),)])
    _use_fake(monkeypatch, fake)

    assert cli.main(
        ["--config", str(source), "models", "install", "modelo-nuevo:tag"]
    ) == 0

    assert "estado = ya instalado" in capsys.readouterr().out
    assert fake.calls == [("list", 90.0)]


def test_install_interruption_warns_ollama_may_continue_and_returns_130(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _config(tmp_path)
    before = source.read_bytes()
    fake = FakeInstallClient([()], interrupt=True)
    _use_fake(monkeypatch, fake)

    exit_code = cli.main(
        ["--config", str(source), "models", "install", "modelo-nuevo:tag"]
    )
    captured = capsys.readouterr()

    assert exit_code == 130
    assert "Solicitud interrumpida." in captured.err
    assert "Barbarion dejo de esperar la descarga." in captured.err
    assert "Ollama podria continuarla localmente." in captured.err
    assert "Ollama: downloading" in captured.err
    assert source.read_bytes() == before
    assert fake.calls == [
        ("list", 90.0),
        ("pull", "modelo-nuevo:tag", 90.0),
    ]


def test_install_missing_after_pull_returns_operational_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _config(tmp_path)
    fake = FakeInstallClient([(), ()])
    _use_fake(monkeypatch, fake)

    assert cli.main(
        ["--config", str(source), "models", "install", "modelo-nuevo:tag"]
    ) == 1

    captured = capsys.readouterr()
    assert "MODEL_OPERATION_FAILED" in captured.err
    assert "no reporta el modelo instalado" in captured.err
    assert "Traceback" not in captured.err


def test_install_rejects_url_without_contacting_ollama(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _config(tmp_path)
    fake = FakeInstallClient([])
    _use_fake(monkeypatch, fake)

    assert cli.main(
        [
            "--config",
            str(source),
            "models",
            "install",
            "https://example.invalid/model",
        ]
    ) == 2

    assert "Error de argumentos" in capsys.readouterr().err
    assert fake.calls == []


def test_install_remains_ollama_only_and_preserves_anthropic_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _anthropic_config(tmp_path)
    before = source.read_bytes()
    fake = FakeInstallClient([(), (LocalModel("modelo-local:tag"),)])
    _use_fake(monkeypatch, fake)

    assert cli.main(
        ["--config", str(source), "models", "install", "modelo-local:tag"]
    ) == 0
    captured = capsys.readouterr()

    assert "estado = instalado y confirmado" in captured.out
    assert fake.calls == [
        ("list", 90.0),
        ("pull", "modelo-local:tag", 90.0),
        ("list", 90.0),
    ]
    assert source.read_bytes() == before
