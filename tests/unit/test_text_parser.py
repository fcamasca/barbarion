from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from barbarion.domain.models import (
    Confidence,
    DiscoveredFile,
    ExtractionContext,
    SourceFile,
)
from barbarion.infrastructure.parsers.encoding import EXTRACTION_LIMIT_EXCEEDED
from barbarion.infrastructure.parsers.encoding import TextExtractionError
from barbarion.infrastructure.parsers.text import TextParser


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


def context(max_extracted_chars: int = 10000) -> ExtractionContext:
    return ExtractionContext(
        encodings=("utf-8", "cp1252", "latin-1"),
        max_extracted_chars=max_extracted_chars,
        max_pdf_pages=10,
    )


@pytest.mark.parametrize(
    ("filename", "content", "expected_format"),
    [
        ("notes.txt", "linea 1\nlinea 2", "text"),
        ("config.yaml", "b: 2\na: 1\n", "config"),
        ("config.yml", "z: true\n", "config"),
        ("data.json", '{\n  "b": 2,\n  "a": 1\n}', "config"),
        ("app.ini", "[main]\nvalue = 1", "config"),
    ],
)
def test_text_parser_preserves_text_and_classifies_formats(
    tmp_path: Path,
    filename: str,
    content: str,
    expected_format: str,
) -> None:
    path = tmp_path / filename
    path.write_bytes(content.encode("utf-8"))

    result = TextParser().extract(source_for(path), context())

    assert result.text == content
    assert result.title == filename
    assert result.metadata["format"] == expected_format
    assert result.metadata["extension"] == path.suffix
    assert len(result.units) == 1
    assert result.units[0].confidence == Confidence.HIGH
    assert result.units[0].metadata["format"] == expected_format
    assert result.units[0].end_line == max(1, len(content.splitlines()))


def test_text_parser_uses_configured_encoding_fallback(tmp_path: Path) -> None:
    path = tmp_path / "legacy.txt"
    path.write_bytes("Precio €".encode("cp1252"))

    result = TextParser().extract(source_for(path), context())

    assert result.text == "Precio €"
    assert result.encoding == "cp1252"


def test_text_parser_reports_extraction_limit(tmp_path: Path) -> None:
    path = tmp_path / "large.txt"
    path.write_bytes(b"abcdef")

    with pytest.raises(TextExtractionError) as raised:
        TextParser().extract(source_for(path), context(max_extracted_chars=5))

    assert EXTRACTION_LIMIT_EXCEEDED in str(raised.value)
