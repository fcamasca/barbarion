from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest
from pypdf import PdfWriter
from reportlab.pdfgen import canvas

from barbarion.domain.models import (
    Confidence,
    DiscoveredFile,
    ExtractionContext,
    SourceFile,
)
from barbarion.infrastructure.parsers.encoding import (
    DOCUMENT_CORRUPT,
    EXTRACTION_LIMIT_EXCEEDED,
    TextExtractionError,
)
from barbarion.infrastructure.parsers.pdf import (
    PDF_ENCRYPTED,
    PDF_NO_EXTRACTABLE_TEXT,
    PdfParser,
)


def source_for(path: Path, root: Path | None = None) -> SourceFile:
    effective_root = path.parent if root is None else root
    stat_result = path.stat()
    return SourceFile(
        discovered=DiscoveredFile(
            root=effective_root,
            relative_path=PurePosixPath(path.relative_to(effective_root).as_posix()),
            runtime_path=path,
            extension=path.suffix,
            size_bytes=stat_result.st_size,
            mtime_ns=stat_result.st_mtime_ns,
        )
    )


def context(
    *,
    max_extracted_chars: int = 10000,
    max_pdf_pages: int = 10,
) -> ExtractionContext:
    return ExtractionContext(
        encodings=("utf-8", "cp1252", "latin-1"),
        max_extracted_chars=max_extracted_chars,
        max_pdf_pages=max_pdf_pages,
    )


def write_text_pdf(path: Path, pages: tuple[str, ...]) -> None:
    pdf_canvas = canvas.Canvas(str(path))
    for page_text in pages:
        pdf_canvas.drawString(72, 720, page_text)
        pdf_canvas.showPage()
    pdf_canvas.save()


def test_pdf_parser_extracts_text_by_page(tmp_path: Path) -> None:
    path = tmp_path / "manual.pdf"
    write_text_pdf(path, ("Primera pagina", "Segunda pagina"))

    result = PdfParser().extract(source_for(path), context())

    assert "Primera pagina" in result.text
    assert "Segunda pagina" in result.text
    assert result.metadata["format"] == "pdf"
    assert result.metadata["pages"] == 2
    assert [unit.unit_type for unit in result.units] == ["page", "page"]
    assert [unit.page_start for unit in result.units] == [1, 2]
    assert all(unit.confidence == Confidence.HIGH for unit in result.units)


def test_pdf_parser_reports_encrypted_pdf(tmp_path: Path) -> None:
    path = tmp_path / "encrypted.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt("secret")
    with path.open("wb") as output:
        writer.write(output)

    with pytest.raises(TextExtractionError) as raised:
        PdfParser().extract(source_for(path), context())

    assert raised.value.to_pipeline_error().error_code == PDF_ENCRYPTED


def test_pdf_parser_reports_pdf_without_text(tmp_path: Path) -> None:
    path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with path.open("wb") as output:
        writer.write(output)

    with pytest.raises(TextExtractionError) as raised:
        PdfParser().extract(source_for(path), context())

    assert raised.value.to_pipeline_error().error_code == PDF_NO_EXTRACTABLE_TEXT


def test_pdf_parser_reports_corrupt_pdf(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.pdf"
    path.write_bytes(b"not a pdf")

    with pytest.raises(TextExtractionError) as raised:
        PdfParser().extract(source_for(path), context())

    assert raised.value.to_pipeline_error().error_code == DOCUMENT_CORRUPT


def test_pdf_parser_applies_page_limit(tmp_path: Path) -> None:
    path = tmp_path / "manual.pdf"
    write_text_pdf(path, ("uno", "dos"))

    with pytest.raises(TextExtractionError) as raised:
        PdfParser().extract(source_for(path), context(max_pdf_pages=1))

    error = raised.value.to_pipeline_error()
    assert error.error_code == EXTRACTION_LIMIT_EXCEEDED
    assert error.details["max_pdf_pages"] == 1
