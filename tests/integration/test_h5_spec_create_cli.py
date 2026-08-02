"""Pruebas de `barbarion spec create` como orquestador CLI."""

from pathlib import Path

from barbarion import cli
from barbarion.application.spec_mode import (
    SpecCreateResult,
    SpecReviewResult,
    SpecValidationResult,
)
from barbarion.database import initialize_database
from barbarion.domain.spec_mode import ReviewIssue, ValidationSeverity
from barbarion.infrastructure.markdown import SafeSpecWriter, render_spec_markdown
from tests.golden.test_h5_markdown import GENERATED_AT, _draft


def test_spec_create_cli_writes_spec_safely_and_passes_arguments(
    tmp_path: Path,
    capsys: object,
    monkeypatch: object,
) -> None:
    config = _prepare_workspace(tmp_path)
    service = _FakeSpecCreateService()
    monkeypatch.setattr(cli, "_build_spec_create_service", lambda settings: service)
    output_dir = tmp_path / "output" / "specs" / "credito"

    first = cli.main(
        [
            "--config",
            str(config),
            "spec",
            "create",
            "Validar limite de credito",
            "--name",
            "credito",
            "--output",
            str(output_dir),
            "--mode",
            "keyword",
            "--depth",
            "2",
            "--top-k",
            "3",
            "--no-llm",
        ]
    )
    first_capture = capsys.readouterr()
    second = cli.main(
        [
            "--config",
            str(config),
            "spec",
            "create",
            "Validar limite de credito",
            "--output",
            str(output_dir),
        ]
    )
    second_capture = capsys.readouterr()
    third = cli.main(
        [
            "--config",
            str(config),
            "spec",
            "create",
            "Validar limite de credito",
            "--output",
            str(output_dir),
            "--overwrite",
        ]
    )
    third_capture = capsys.readouterr()

    assert first == 0, first_capture.err
    assert "Spec escrita:" in first_capture.out
    assert (output_dir / "requirements.md").exists()
    assert (output_dir / "design.md").exists()
    assert service.requests[0].spec_request.retrieval_mode == "keyword"
    assert service.requests[0].spec_request.depth == 2
    assert service.requests[0].spec_request.top_k == 3
    assert service.requests[0].spec_request.no_llm is True
    assert second == 1
    assert "Usa --overwrite" in second_capture.err
    assert third == 0, third_capture.err


def test_spec_create_cli_stops_when_review_fails(
    tmp_path: Path,
    capsys: object,
    monkeypatch: object,
) -> None:
    config = _prepare_workspace(tmp_path)
    service = _FailingReviewSpecCreateService()
    monkeypatch.setattr(cli, "_build_spec_create_service", lambda settings: service)

    exit_code = cli.main(
        [
            "--config",
            str(config),
            "spec",
            "create",
            "Validar limite de credito",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Review de SpecDraft fallo" in captured.err
    assert not (tmp_path / "output" / "specs").exists()


def test_spec_create_no_llm_with_anthropic_builds_no_provider_or_network(
    tmp_path: Path,
    capsys: object,
    monkeypatch: object,
) -> None:
    config = _prepare_workspace(tmp_path)
    with config.open("a", encoding="utf-8") as stream:
        stream.write(
            """

[llm]
provider = "anthropic"
model = "claude-synthetic"
timeout_seconds = 12.0
temperature = 0.1
max_output_tokens = 1024
"""
        )
    fake_service = _FakeSpecCreateService()
    original_builder = cli._build_spec_create_service

    def unexpected_provider(_settings):  # noqa: ANN001, ANN202
        raise AssertionError("spec --no-llm no debe componer un proveedor")

    def build_without_llm(settings):  # noqa: ANN001, ANN202
        original_builder(settings)
        return fake_service

    monkeypatch.setattr(cli, "_build_llm_provider", unexpected_provider)
    monkeypatch.setattr(cli, "_build_spec_create_service", build_without_llm)
    output_dir = tmp_path / "output" / "specs" / "anthropic-no-llm"

    assert cli.main(
        [
            "--config",
            str(config),
            "spec",
            "create",
            "Requisito sintetico",
            "--output",
            str(output_dir),
            "--no-llm",
        ]
    ) == 0
    captured = capsys.readouterr()

    assert "Spec escrita:" in captured.out
    assert fake_service.requests[0].spec_request.no_llm is True


class _FakeSpecCreateService:
    def __init__(self) -> None:
        self.requests = []
        self.writer = SafeSpecWriter()

    def create(self, request):
        self.requests.append(request)
        draft = _draft()
        documents = render_spec_markdown(draft, generated_at=GENERATED_AT)
        written = self.writer.write(
            request.output_dir,
            documents,
            overwrite=request.spec_request.overwrite,
        )
        validation = cli.SpecValidator().validate(documents)
        return SpecCreateResult(
            output_dir=request.output_dir,
            draft=draft,
            review=SpecReviewResult(draft=draft),
            validation=validation,
            documents=documents,
            written_paths=written,
        )


class _FailingReviewSpecCreateService:
    def create(self, request):
        del request
        draft = _draft()
        issue = ReviewIssue(
            severity=ValidationSeverity.ERROR,
            code="H5_REVIEW_TEST",
            message="Review fixture.",
            draft_section="requirements",
        )
        return SpecCreateResult(
            output_dir=Path("unused"),
            draft=draft,
            review=SpecReviewResult(draft=draft, issues=(issue,)),
            validation=SpecValidationResult(),
            documents={},
        )


def _prepare_workspace(tmp_path: Path) -> Path:
    for name in ("data", "output", "logs"):
        (tmp_path / name).mkdir()
    db_path = tmp_path / "data" / "barbarion.db"
    initialize_database(db_path)
    config = tmp_path / "barbarion.toml"
    config.write_text(
        "\n".join(
            [
                'domain = "integration"',
                'data_dir = "data"',
                'output_dir = "output"',
                'logs_dir = "logs"',
                'database_path = "data/barbarion.db"',
                "[ingestion]",
                'paths = ["sources"]',
            ]
        ),
        encoding="utf-8",
    )
    return config
