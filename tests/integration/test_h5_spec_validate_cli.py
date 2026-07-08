"""Pruebas de `barbarion spec validate` sobre specs existentes."""

import json
from pathlib import Path

from barbarion import cli
from barbarion.infrastructure.markdown import SafeSpecWriter, render_spec_markdown
from tests.golden.test_h5_markdown import GENERATED_AT, _draft


def test_spec_validate_cli_accepts_existing_rendered_spec(
    tmp_path: Path,
    capsys: object,
) -> None:
    spec_dir = _write_spec(tmp_path)

    exit_code = cli.main(["spec", "validate", str(spec_dir)])
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    assert captured.out.strip() == "Spec valida."
    assert captured.err == ""


def test_spec_validate_cli_reports_json(
    tmp_path: Path,
    capsys: object,
) -> None:
    spec_dir = _write_spec(tmp_path)

    exit_code = cli.main(["spec", "validate", str(spec_dir), "--format", "json"])
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    payload = json.loads(captured.out)
    assert payload["valid"] is True
    assert payload["strict"] is False
    assert payload["strict_valid"] is True
    assert payload["issues"] == []


def test_spec_validate_cli_reports_invalid_citations(
    tmp_path: Path,
    capsys: object,
) -> None:
    spec_dir = _write_spec(tmp_path)
    requirements = spec_dir / "requirements.md"
    requirements.write_text(
        requirements.read_text(encoding="utf-8").replace(
            "[F111111111111]",
            "[F222222222222]",
            1,
        ),
        encoding="utf-8",
    )

    exit_code = cli.main(["spec", "validate", str(spec_dir), "--format", "json"])
    captured = capsys.readouterr()

    assert exit_code == 1
    payload = json.loads(captured.out)
    assert payload["valid"] is False
    assert any(
        issue["code"] == "H5_SPEC_CITATION_MISSING"
        for issue in payload["issues"]
    )


def test_spec_validate_cli_reports_missing_folder(
    tmp_path: Path,
    capsys: object,
) -> None:
    missing = tmp_path / "missing"

    exit_code = cli.main(["spec", "validate", str(missing)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "La carpeta de spec no existe" in captured.err


def test_spec_validate_cli_strict_fails_on_warnings(
    tmp_path: Path,
    capsys: object,
) -> None:
    spec_dir = _write_spec(tmp_path)
    requirements = spec_dir / "requirements.md"
    requirements.write_text(
        requirements.read_text(encoding="utf-8").replace(
            "## Evidencia\n",
            "## Evidencia\n\n- [F333333333333] extra.md:1-2; evidencia extra no citada.\n",
            1,
        ),
        encoding="utf-8",
    )

    non_strict = cli.main(["spec", "validate", str(spec_dir)])
    non_strict_capture = capsys.readouterr()
    strict = cli.main(["spec", "validate", str(spec_dir), "--strict"])
    strict_capture = capsys.readouterr()

    assert non_strict == 0, non_strict_capture.err
    assert "Spec valida con advertencias." in non_strict_capture.out
    assert strict == 1
    assert "H5_SPEC_EVIDENCE_UNUSED" in strict_capture.out
    assert "Modo strict" in strict_capture.err


def _write_spec(tmp_path: Path) -> Path:
    spec_dir = tmp_path / "spec"
    documents = render_spec_markdown(_draft(), generated_at=GENERATED_AT)
    SafeSpecWriter().write(spec_dir, documents)
    return spec_dir
