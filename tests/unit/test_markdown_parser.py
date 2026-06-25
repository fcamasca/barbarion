from __future__ import annotations

from pathlib import Path, PurePosixPath

from barbarion.domain.models import (
    Confidence,
    DiscoveredFile,
    ExtractionContext,
    SourceFile,
)
from barbarion.infrastructure.parsers.markdown import MarkdownParser


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


def context() -> ExtractionContext:
    return ExtractionContext(
        encodings=("utf-8", "cp1252", "latin-1"),
        max_extracted_chars=10000,
        max_pdf_pages=10,
    )


def test_markdown_parser_detects_atx_headings_breadcrumbs_and_code_fences(
    tmp_path: Path,
) -> None:
    content = "\n".join(
        [
            "# Guia",
            "",
            "Intro",
            "```",
            "# No heading",
            "```",
            "## Instalacion",
            "paso",
            "### Windows",
            "detalle",
            "## Uso",
            "texto",
        ]
    )
    path = tmp_path / "guide.md"
    path.write_bytes(content.encode("utf-8"))

    result = MarkdownParser().extract(source_for(path), context())

    assert result.text == content
    assert result.title == "Guia"
    assert [unit.name for unit in result.units] == [
        "Guia",
        "Instalacion",
        "Windows",
        "Uso",
    ]
    assert result.units[0].start_line == 1
    assert result.units[0].end_line == 12
    assert result.units[1].metadata["breadcrumb"] == ("Guia", "Instalacion")
    assert result.units[2].metadata["breadcrumb"] == (
        "Guia",
        "Instalacion",
        "Windows",
    )
    assert all(unit.confidence == Confidence.HIGH for unit in result.units)


def test_markdown_parser_detects_setext_headings(tmp_path: Path) -> None:
    content = "\n".join(["Titulo", "======", "", "Seccion", "-------", "Texto"])
    path = tmp_path / "setext.md"
    path.write_bytes(content.encode("utf-8"))

    result = MarkdownParser().extract(source_for(path), context())

    assert [unit.name for unit in result.units] == ["Titulo", "Seccion"]
    assert [unit.start_line for unit in result.units] == [1, 4]
    assert [unit.metadata["heading_level"] for unit in result.units] == [1, 2]


def test_markdown_parser_falls_back_to_file_unit_without_headings(
    tmp_path: Path,
) -> None:
    content = "solo texto\nsin headings"
    path = tmp_path / "plain.md"
    path.write_bytes(content.encode("utf-8"))

    result = MarkdownParser().extract(source_for(path), context())

    assert result.text == content
    assert result.title == "plain.md"
    assert len(result.units) == 1
    assert result.units[0].unit_type == "file"
    assert result.units[0].confidence == Confidence.LOW
    assert result.units[0].start_line == 1
    assert result.units[0].end_line == 2
