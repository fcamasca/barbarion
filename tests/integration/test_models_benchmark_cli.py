"""Integracion CLI de `models benchmark`."""

import json
from pathlib import Path

import pytest

from barbarion import cli
from barbarion.application.local_models import VALIDATION_MARKER, VALIDATION_PROMPT
from barbarion.domain.local_models import (
    LocalModel,
    LocalModelDetails,
    ModelGenerationResult,
)


class FakeBenchmarkClient:
    def __init__(self, *, interrupt_at: int | None = None) -> None:
        self.interrupt_at = interrupt_at
        self.benchmark_calls = 0
        self.models = (LocalModel("m1"), LocalModel("m2"))

    def list_models(self, *, timeout_seconds: float):  # noqa: ANN201
        del timeout_seconds
        return self.models

    def server_version(self, *, timeout_seconds: float) -> str:
        del timeout_seconds
        return "test-version"

    def show_model(self, name: str, *, timeout_seconds: float) -> LocalModelDetails:
        del timeout_seconds
        return LocalModelDetails(
            model=LocalModel(name),
            format="gguf",
            family="synthetic",
            parameter_size="small",
            quantization_level="Q4",
            capabilities=("completion",),
        )

    def generate_detailed(self, request):  # noqa: ANN001, ANN201
        if request.prompt == VALIDATION_PROMPT:
            return ModelGenerationResult(VALIDATION_MARKER)
        self.benchmark_calls += 1
        if self.interrupt_at == self.benchmark_calls:
            raise KeyboardInterrupt
        return ModelGenerationResult("Respuesta sintetica [F1].")


def _config(tmp_path: Path) -> Path:
    source = tmp_path / "barbarion.toml"
    source.write_text(
        f"""output_dir = "{(tmp_path / 'configured-output').as_posix()}"

[llm]
provider = "ollama"
model = "modelo-activo:tag"
timeout_seconds = 30.0
temperature = 0.1
""",
        encoding="utf-8",
    )
    return source


def test_models_benchmark_writes_safe_json_and_stdout_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _config(tmp_path)
    before = source.read_bytes()
    fake = FakeBenchmarkClient()
    monkeypatch.setattr(cli, "OllamaModelClient", lambda _url: fake)
    monkeypatch.setattr(cli, "_benchmark_run_id", lambda: "fixed-complete")
    output = tmp_path / "custom-output"

    assert cli.main(
        [
            "--config",
            str(source),
            "models",
            "benchmark",
            "--models",
            "m1",
            "m2",
            "--output",
            str(output),
        ]
    ) == 0
    captured = capsys.readouterr()
    artifact = output / "model-benchmarks" / "fixed-complete" / "model-benchmark.json"
    markdown = output / "model-benchmarks" / "fixed-complete" / "model-benchmark.md"
    payload = json.loads(artifact.read_text(encoding="utf-8"))

    assert "estado = completed" in captured.out
    assert str(artifact.resolve()) in captured.out
    assert str(markdown.resolve()) in captured.out
    assert markdown.exists()
    assert payload["status"] == "completed"
    assert payload["resumable"] is False
    assert payload["planned_units"] == 16
    assert payload["confirmed_units"] == 16
    assert payload["scoring_version"] == 1
    assert payload["environment"]["ollama_version"] == "test-version"
    assert payload["recommendation"]["automatic_selection"] is False
    assert all(unit["score"] is not None for unit in payload["units"])
    assert all(
        aggregate["prompt_tokens_total"] is None
        for aggregate in payload["aggregates"]
    )
    assert fake.benchmark_calls == 16
    assert [unit["model"] for unit in payload["units"][:4]] == [
        "m1",
        "m2",
        "m2",
        "m1",
    ]
    serialized = artifact.read_text(encoding="utf-8")
    assert "Respuesta sintetica" not in serialized
    assert "Responde en espanol" not in serialized
    assert source.read_bytes() == before


def test_models_benchmark_interrupt_writes_non_resumable_partial_and_returns_130(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _config(tmp_path)
    fake = FakeBenchmarkClient(interrupt_at=3)
    monkeypatch.setattr(cli, "OllamaModelClient", lambda _url: fake)
    monkeypatch.setattr(cli, "_benchmark_run_id", lambda: "fixed-interrupted")
    output = tmp_path / "partial-output"

    assert cli.main(
        [
            "--config",
            str(source),
            "models",
            "benchmark",
            "--models",
            "m1",
            "m2",
            "--output",
            str(output),
        ]
    ) == 130
    captured = capsys.readouterr()
    artifact = output / "model-benchmarks" / "fixed-interrupted" / "model-benchmark.json"
    markdown = output / "model-benchmarks" / "fixed-interrupted" / "model-benchmark.md"
    payload = json.loads(artifact.read_text(encoding="utf-8"))

    assert payload["status"] == "interrupted"
    assert payload["resumable"] is False
    assert payload["planned_units"] == 16
    assert payload["confirmed_units"] == 2
    assert markdown.exists()
    assert "parcial no reanudable" in captured.err


def test_models_benchmark_rejects_less_than_two_distinct_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _config(tmp_path)
    fake = FakeBenchmarkClient()
    monkeypatch.setattr(cli, "OllamaModelClient", lambda _url: fake)

    assert cli.main(
        [
            "--config",
            str(source),
            "models",
            "benchmark",
            "--models",
            "m1",
            "m1",
        ]
    ) == 2

    assert "al menos dos modelos distintos" in capsys.readouterr().err
    assert fake.benchmark_calls == 0
