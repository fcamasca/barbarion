from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from barbarion.domain.models import (
    Confidence,
    DiscoveredFile,
    ExtractionContext,
    SourceFile,
)
from barbarion.infrastructure.parsers.powerbuilder import (
    POWERBUILDER_EXTENSIONS,
    UNSUPPORTED_BINARY_PBL,
    PowerBuilderParser,
)
from barbarion.infrastructure.parsers.encoding import TextExtractionError


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


def parse(tmp_path: Path, filename: str, content: str, encoding: str = "utf-8"):
    path = tmp_path / filename
    path.write_bytes(content.encode(encoding))
    return PowerBuilderParser().extract(source_for(path), context())


@pytest.mark.parametrize(
    ("filename", "content", "unit_type", "name"),
    [
        (
            "w_main.srw",
            "$PBExportHeader$w_main.srw\n"
            "global type w_main from window\n"
            "end type",
            "window",
            "w_main",
        ),
        (
            "uo_customer.sru",
            "$PBExportHeader$uo_customer.sru\n"
            "type uo_customer from userobject\n"
            "end type",
            "userobject",
            "uo_customer",
        ),
        (
            "n_calc.srf",
            "$PBExportHeader$n_calc.srf\n"
            "type n_calc from function_object\n"
            "end type",
            "function_object",
            "n_calc",
        ),
        (
            "m_main.srm",
            "$PBExportHeader$m_main.srm\n"
            "type m_main from menu\n"
            "end type",
            "menu",
            "m_main",
        ),
        (
            "app.srj",
            "$PBExportHeader$app.srj\n"
            "type app from application\n"
            "end type",
            "application",
            "app",
        ),
    ],
)
def test_powerbuilder_parser_detects_object_type_and_name(
    tmp_path: Path,
    filename: str,
    content: str,
    unit_type: str,
    name: str,
) -> None:
    result = parse(tmp_path, filename, content)

    assert result.text == content
    assert result.title == name
    assert result.metadata["format"] == "powerbuilder"
    assert result.units[0].unit_type == unit_type
    assert result.units[0].name == name
    assert result.units[0].confidence == Confidence.HIGH
    assert result.units[0].start_line == 2
    assert result.units[0].end_line == len(content.splitlines())


@pytest.mark.parametrize("extension", POWERBUILDER_EXTENSIONS)
def test_powerbuilder_parser_declares_supported_extensions(extension: str) -> None:
    assert extension in PowerBuilderParser.supported_extensions


def test_powerbuilder_parser_detects_events_functions_and_overloads(
    tmp_path: Path,
) -> None:
    content = "\n".join(
        [
            "$PBExportHeader$w_main.srw",
            "global type w_main from window",
            "end type",
            "",
            "event open;",
            "messagebox('hola', 'mundo')",
            "end event",
            "",
            "public function integer of_save (string name);",
            "return 1",
            "end function",
            "",
            "public function integer of_save (long id);",
            "return 2",
            "end function",
        ]
    )

    result = parse(tmp_path, "w_main.srw", content)

    assert [unit.unit_type for unit in result.units] == [
        "window",
        "event",
        "function",
        "function",
    ]
    assert [unit.name for unit in result.units] == [
        "w_main",
        "open",
        "of_save",
        "of_save",
    ]
    assert [(unit.start_line, unit.end_line) for unit in result.units] == [
        (2, 15),
        (5, 7),
        (9, 11),
        (13, 15),
    ]
    assert result.units[1].metadata["parent_name"] == "w_main"


def test_powerbuilder_parser_detects_datawindow_sql(tmp_path: Path) -> None:
    content = "\n".join(
        [
            "$PBExportHeader$d_customer.srd",
            "type d_customer from datawindow",
            "retrieve=\"SELECT id, name FROM customer WHERE active = 1\"",
            "end type",
        ]
    )

    result = parse(tmp_path, "d_customer.srd", content)

    assert [unit.unit_type for unit in result.units] == [
        "datawindow",
        "datawindow_sql",
    ]
    assert result.units[1].name == "retrieve"
    assert result.units[1].confidence == Confidence.MEDIUM
    assert result.units[1].start_line == 3
    assert result.units[1].metadata["parent_name"] == "d_customer"


def test_powerbuilder_parser_falls_back_for_unknown_variant(tmp_path: Path) -> None:
    content = "forward prototypes\nend prototypes"
    result = parse(tmp_path, "unknown.sru", content)

    assert result.title == "unknown.sru"
    assert result.units[0].unit_type == "file"
    assert result.units[0].confidence == Confidence.LOW
    assert "POWERBUILDER_OBJECT_NOT_RECOGNIZED" in result.warnings


def test_powerbuilder_parser_uses_configured_encoding_fallback(tmp_path: Path) -> None:
    content = "$PBExportHeader$w_ñ.srw\n" "global type w_ñ from window\n" "end type"

    result = parse(tmp_path, "w_legacy.srw", content, encoding="cp1252")

    assert result.text == content
    assert result.encoding == "cp1252"
    assert result.title == "w_ñ"


def test_powerbuilder_parser_rejects_binary_pbl_as_unsupported(tmp_path: Path) -> None:
    path = tmp_path / "legacy.pbl"
    path.write_bytes(b"\x00PBL\xff\x00")

    with pytest.raises(TextExtractionError) as raised:
        PowerBuilderParser().extract(source_for(path), context())

    error = raised.value.to_pipeline_error()
    assert error.error_code == UNSUPPORTED_BINARY_PBL
    assert error.recoverable is True
    assert error.relative_path == PurePosixPath("legacy.pbl")
