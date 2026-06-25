from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from barbarion.domain.models import (
    Confidence,
    DiscoveredFile,
    ExtractionContext,
    SourceFile,
)
from barbarion.infrastructure.parsers.oracle import ORACLE_EXTENSIONS, OracleParser


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


def parse(tmp_path: Path, filename: str, content: str):
    path = tmp_path / filename
    path.write_bytes(content.encode("utf-8"))
    return OracleParser().extract(source_for(path), context())


@pytest.mark.parametrize(
    ("filename", "content", "unit_type", "name"),
    [
        (
            "pkg.pks",
            "CREATE OR REPLACE PACKAGE pkg_demo AS\nEND pkg_demo;",
            "package_spec",
            "pkg_demo",
        ),
        (
            "pkg.pkb",
            "CREATE OR REPLACE PACKAGE BODY pkg_demo AS\nEND pkg_demo;",
            "package_body",
            "pkg_demo",
        ),
        (
            "proc.prc",
            "CREATE OR REPLACE PROCEDURE run_demo AS\nBEGIN\nNULL;\nEND run_demo;",
            "procedure",
            "run_demo",
        ),
        (
            "func.fnc",
            "CREATE FUNCTION calc_demo RETURN NUMBER AS\nBEGIN\nRETURN 1;\nEND calc_demo;",
            "function",
            "calc_demo",
        ),
        (
            "trg.trg",
            "CREATE TRIGGER trg_demo BEFORE INSERT ON t\nBEGIN\nNULL;\nEND;",
            "trigger",
            "trg_demo",
        ),
        (
            "view.vw",
            "CREATE OR REPLACE VIEW vw_demo AS\nSELECT 1 value FROM dual;",
            "view",
            "vw_demo",
        ),
        (
            "type.tps",
            "CREATE TYPE typ_demo AS OBJECT (\nvalue NUMBER\n);",
            "type_spec",
            "typ_demo",
        ),
    ],
)
def test_oracle_parser_detects_main_objects(
    tmp_path: Path,
    filename: str,
    content: str,
    unit_type: str,
    name: str,
) -> None:
    result = parse(tmp_path, filename, content)

    assert result.text == content
    assert result.title == name
    assert result.metadata["format"] == "oracle"
    assert result.units[0].unit_type == unit_type
    assert result.units[0].name == name
    assert result.units[0].confidence == Confidence.HIGH
    assert result.units[0].start_line == 1
    assert result.units[0].end_line == len(content.splitlines())


@pytest.mark.parametrize("extension", ORACLE_EXTENSIONS)
def test_oracle_parser_declares_all_configured_extensions(extension: str) -> None:
    assert extension in OracleParser.supported_extensions


def test_oracle_parser_falls_back_for_generic_script(tmp_path: Path) -> None:
    content = "insert into demo(id) values (1);\ncommit;"
    result = parse(tmp_path, "script.sql", content)

    assert result.title == "script.sql"
    assert result.units[0].unit_type == "file"
    assert result.units[0].confidence == Confidence.LOW
    assert result.units[0].start_line == 1
    assert result.units[0].end_line == 2
    assert "ORACLE_OBJECT_NOT_RECOGNIZED" in result.warnings


def test_oracle_parser_detects_package_subprograms_with_valid_ranges(
    tmp_path: Path,
) -> None:
    content = "\n".join(
        [
            "CREATE OR REPLACE PACKAGE BODY pkg_demo AS",
            "  PROCEDURE first_proc IS",
            "  BEGIN",
            "    NULL;",
            "  END first_proc;",
            "",
            "  FUNCTION second_func RETURN NUMBER IS",
            "  BEGIN",
            "    RETURN 2;",
            "  END second_func;",
            "END pkg_demo;",
        ]
    )

    result = parse(tmp_path, "pkg.pkb", content)

    assert [unit.unit_type for unit in result.units] == [
        "package_body",
        "procedure",
        "function",
    ]
    assert [unit.name for unit in result.units] == [
        "pkg_demo",
        "first_proc",
        "second_func",
    ]
    assert [(unit.start_line, unit.end_line) for unit in result.units] == [
        (1, 11),
        (2, 5),
        (7, 10),
    ]
    assert result.units[1].metadata["parent_name"] == "pkg_demo"
    assert result.units[2].metadata["breadcrumb"] == ("pkg_demo", "second_func")


def test_oracle_parser_ignores_comments_and_strings_when_detecting_units(
    tmp_path: Path,
) -> None:
    content = "\n".join(
        [
            "CREATE OR REPLACE PACKAGE BODY pkg_demo AS",
            "  -- PROCEDURE fake_comment IS",
            "  PROCEDURE real_proc IS",
            "    value VARCHAR2(100) := 'FUNCTION fake_string RETURN NUMBER';",
            "  BEGIN",
            "    NULL;",
            "  END real_proc;",
            "  /* FUNCTION fake_block RETURN NUMBER IS BEGIN RETURN 1; END fake_block; */",
            "END pkg_demo;",
        ]
    )

    result = parse(tmp_path, "pkg.pkb", content)

    assert [unit.name for unit in result.units] == ["pkg_demo", "real_proc"]
    assert result.units[1].start_line == 3
    assert result.units[1].end_line == 7


def test_oracle_parser_skips_ambiguous_subprogram_ranges(tmp_path: Path) -> None:
    content = "\n".join(
        [
            "CREATE OR REPLACE PACKAGE BODY pkg_demo AS",
            "  PROCEDURE outer_proc IS",
            "  BEGIN",
            "    NULL;",
            "  END;",
            "END pkg_demo;",
        ]
    )

    result = parse(tmp_path, "pkg.pkb", content)

    assert [unit.unit_type for unit in result.units] == ["package_body"]
