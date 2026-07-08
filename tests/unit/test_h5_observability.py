"""Pruebas H5-T10 para observabilidad, errores y documentacion operativa."""

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


def test_spec_create_debug_reports_pipeline_metrics(
    tmp_path: Path,
    capsys: object,
    monkeypatch: object,
) -> None:
    config = _prepare_workspace(tmp_path)
    service = _FakeSpecCreateService()
    monkeypatch.setattr(cli, "_build_spec_create_service", lambda settings: service)
    output_dir = tmp_path / "output" / "specs" / "limite-credito"

    exit_code = cli.main(
        [
            "--config",
            str(config),
            "spec",
            "create",
            "Validar limite de credito",
            "--output",
            str(output_dir),
            "--top-k",
            "4",
            "--depth",
            "2",
            "--no-llm",
            "--debug",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    assert "Review: ok" in captured.out
    assert "Validacion Markdown: ok" in captured.out
    assert f"Siguiente paso: barbarion spec validate {output_dir}" in captured.out
    assert "Observabilidad spec mode:" in captured.err
    assert "stages=interpretacion,recuperacion_h3,impacto_h4" in captured.err
    assert "review=ok" in captured.err
    assert "top_k=4" in captured.err
    assert "depth=2" in captured.err


def test_spec_create_review_failure_reports_actionable_error(
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
    assert "H5_REVIEW_TEST" in captured.err
    assert "Accion sugerida" in captured.err
    assert "Traceback" not in captured.err
    assert not (tmp_path / "output" / "specs").exists()


def test_spec_mode_operational_docs_and_pytest_gap_are_documented() -> None:
    cli_doc = Path("docs/CLI.md").read_text(encoding="utf-8")
    tasks = Path("specs/H5-SpecMode/tasks.md").read_text(encoding="utf-8")

    assert "### Spec Mode" in cli_doc
    assert "RequirementAnalyzer -> H3 -> H4 -> SpecSynthesizer" in cli_doc
    assert "barbarion spec create" in cli_doc
    assert "barbarion spec validate RUTA" in cli_doc
    assert "No ejecuta H3, H4, Review ni sintesis" in cli_doc
    assert "el Python empaquetado no tiene `pytest` instalado" in tasks
    assert "--basetemp .pytest-tmp/h5" in tasks


class _FakeSpecCreateService:
    def __init__(self) -> None:
        self.writer = SafeSpecWriter()

    def create(self, request):
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
        draft = _draft()
        issue = ReviewIssue(
            severity=ValidationSeverity.ERROR,
            code="H5_REVIEW_TEST",
            message="Review fixture.",
            draft_section="requirements",
        )
        return SpecCreateResult(
            output_dir=request.output_dir,
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
                'domain = "unit"',
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
