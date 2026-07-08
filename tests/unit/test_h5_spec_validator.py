"""Pruebas del validador de Markdown H5 renderizado."""

from barbarion.application.spec_mode import SpecValidator
from barbarion.infrastructure.markdown import render_spec_markdown
from tests.golden.test_h5_markdown import GENERATED_AT, _draft


def test_spec_validator_accepts_rendered_spec_documents() -> None:
    documents = render_spec_markdown(_draft(), generated_at=GENERATED_AT)

    result = SpecValidator().validate(documents)

    assert result.valid is True
    assert result.issues == ()
    assert result.to_jsonable() == {"valid": True, "issues": []}
    assert result.to_text() == "Spec valida."


def test_spec_validator_reports_missing_document_and_section() -> None:
    documents = render_spec_markdown(_draft(), generated_at=GENERATED_AT)
    documents.pop("design.md")
    documents["requirements.md"] = documents["requirements.md"].replace(
        "## Evidencia\n",
        "## Fuentes\n",
    )

    result = SpecValidator().validate(documents)

    assert result.valid is False
    assert {issue.code for issue in result.errors} == {
        "H5_SPEC_DOCUMENT_MISSING",
        "H5_SPEC_SECTION_MISSING",
    }


def test_spec_validator_reports_missing_citation_and_unused_evidence() -> None:
    documents = render_spec_markdown(_draft(), generated_at=GENERATED_AT)
    documents["requirements.md"] = documents["requirements.md"].replace(
        "[F111111111111]",
        "[F222222222222]",
        1,
    )
    documents["design.md"] = documents["design.md"].replace(
        "[F111111111111]",
        "por_confirmar",
    )

    result = SpecValidator().validate(documents)

    assert result.valid is False
    assert any(issue.code == "H5_SPEC_CITATION_MISSING" for issue in result.errors)
    assert "F222222222222" in result.errors[0].related_ids


def test_spec_validator_reports_duplicate_ids() -> None:
    documents = render_spec_markdown(_draft(), generated_at=GENERATED_AT)
    documents["tasks.md"] = documents["tasks.md"].replace(
        "### TASK-002 - Implementar cambio funcional",
        "### TASK-001 - Implementar cambio funcional",
    )
    documents["test-plan.md"] = documents["test-plan.md"].replace(
        "| REQ-001 | TEST-002 | integracion |",
        "| REQ-001 | TEST-001 | integracion |",
    )

    result = SpecValidator().validate(documents)

    assert result.valid is False
    assert any(issue.code == "H5_SPEC_TASK_ID_DUPLICATED" for issue in result.errors)
    assert any(issue.code == "H5_SPEC_TEST_ID_DUPLICATED" for issue in result.errors)


def test_spec_validator_reports_broken_traceability() -> None:
    documents = render_spec_markdown(_draft(), generated_at=GENERATED_AT)
    documents["tasks.md"] = documents["tasks.md"].replace(
        "**Requisito:** REQ-001.",
        "**Requisito:** por confirmar.",
        1,
    )
    documents["test-plan.md"] = documents["test-plan.md"].replace(
        "| REQ-001 | TEST-002 | integracion |",
        "| REQ-999 | TEST-002 | integracion |",
    )

    result = SpecValidator().validate(documents)

    assert result.valid is False
    assert any(issue.code == "H5_SPEC_TASK_WITHOUT_REQUIREMENT" for issue in result.errors)
    assert any(
        issue.code == "H5_SPEC_REQUIREMENT_REFERENCE_MISSING"
        for issue in result.errors
    )


def test_spec_validator_requires_single_last_acceptance_task() -> None:
    documents = render_spec_markdown(_draft(), generated_at=GENERATED_AT)
    documents["tasks.md"] = documents["tasks.md"].replace(
        "### TASK-003 - Validacion y aceptacion integral",
        "### TASK-003 - Validacion final",
    )

    result = SpecValidator().validate(documents)

    assert result.valid is False
    assert any(
        issue.code == "H5_SPEC_ACCEPTANCE_TASK_COUNT"
        for issue in result.errors
    )


def test_spec_validator_detected_lines_need_citation() -> None:
    documents = render_spec_markdown(_draft(), generated_at=GENERATED_AT)
    documents["design.md"] = documents["design.md"].replace(
        " clasificacion=detectado evidencia=[F111111111111]",
        " clasificacion=detectado evidencia=por_confirmar",
        1,
    )

    result = SpecValidator().validate(documents)

    assert result.valid is False
    assert any(
        issue.code == "H5_SPEC_DETECTED_WITHOUT_EVIDENCE"
        for issue in result.errors
    )
