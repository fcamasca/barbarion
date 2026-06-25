"""Parser heuristico de Oracle/PLSQL."""

from __future__ import annotations

import re
from dataclasses import dataclass

from barbarion.domain.models import (
    Confidence,
    ExtractionContext,
    ExtractionResult,
    LogicalUnit,
    SourceFile,
)
from barbarion.infrastructure.parsers.base import BaseParser
from barbarion.infrastructure.parsers.encoding import decode_text_source


ORACLE_EXTENSIONS = (
    ".sql",
    ".pks",
    ".pkb",
    ".prc",
    ".fnc",
    ".trg",
    ".pck",
    ".vw",
    ".vws",
    ".pkg",
    ".tps",
)

IDENTIFIER = r'(?:"[^"]+"|[A-Za-z][\w$#]*)(?:\s*\.\s*(?:"[^"]+"|[A-Za-z][\w$#]*))*'
CREATE_RE = re.compile(
    rf"""
    \bCREATE\s+
    (?:OR\s+REPLACE\s+)?
    (?:(?:EDITIONABLE|NONEDITIONABLE)\s+)?
    (?P<kind>PACKAGE\s+BODY|PACKAGE|TYPE\s+BODY|TYPE|VIEW|PROCEDURE|FUNCTION|TRIGGER)
    \s+(?P<name>{IDENTIFIER})
    """,
    re.IGNORECASE | re.VERBOSE,
)
SUBPROGRAM_RE = re.compile(
    rf"""
    ^\s*
    (?:(?:CREATE\s+(?:OR\s+REPLACE\s+)?)|(?:MEMBER|STATIC)\s+)?
    (?P<kind>PROCEDURE|FUNCTION)
    \s+(?P<name>{IDENTIFIER})
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)
END_RE = re.compile(
    rf"\bEND\s+(?P<name>{IDENTIFIER})\s*;",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class _OracleObject:
    unit_type: str
    name: str
    start_line: int


@dataclass(frozen=True, slots=True)
class _Subprogram:
    unit_type: str
    name: str
    start_line: int
    end_line: int


class OracleParser(BaseParser):
    """Extrae objetos Oracle principales y subprogramas confiables."""

    parser_id = "oracle"
    parser_version = "1"
    supported_extensions = ORACLE_EXTENSIONS

    def extract(
        self,
        source: SourceFile,
        context: ExtractionContext,
    ) -> ExtractionResult:
        decoded = decode_text_source(
            source,
            encodings=context.encodings,
            max_extracted_chars=context.max_extracted_chars,
        )
        lines = decoded.text.splitlines()
        line_count = max(1, len(lines))
        masked_lines = _mask_plsql(lines)
        oracle_object = _detect_main_object(masked_lines)
        if oracle_object is None:
            units = (
                LogicalUnit(
                    unit_type="file",
                    name=source.discovered.relative_path.name,
                    confidence=Confidence.LOW,
                    start_line=1,
                    end_line=line_count,
                    metadata={
                        "format": "oracle",
                        "extension": source.discovered.extension,
                    },
                ),
            )
            title = source.discovered.relative_path.name
            warnings = (*decoded.warnings, "ORACLE_OBJECT_NOT_RECOGNIZED")
        else:
            units = _build_units(
                oracle_object,
                masked_lines=masked_lines,
                line_count=line_count,
            )
            title = oracle_object.name
            warnings = decoded.warnings

        return ExtractionResult(
            text=decoded.text,
            title=title,
            encoding=decoded.encoding,
            units=units,
            metadata={
                "format": "oracle",
                "extension": source.discovered.extension,
            },
            warnings=warnings,
        )


def _detect_main_object(masked_lines: list[str]) -> _OracleObject | None:
    for index, line in enumerate(masked_lines):
        match = CREATE_RE.search(line)
        if match is None:
            continue
        return _OracleObject(
            unit_type=_unit_type(match.group("kind")),
            name=_clean_identifier(match.group("name")),
            start_line=index + 1,
        )
    return None


def _build_units(
    oracle_object: _OracleObject,
    *,
    masked_lines: list[str],
    line_count: int,
) -> tuple[LogicalUnit, ...]:
    units: list[LogicalUnit] = [
        LogicalUnit(
            unit_type=oracle_object.unit_type,
            name=oracle_object.name,
            confidence=Confidence.HIGH,
            start_line=oracle_object.start_line,
            end_line=line_count,
            metadata={
                "format": "oracle",
                "object_type": oracle_object.unit_type,
                "object_name": oracle_object.name,
                "breadcrumb": (oracle_object.name,),
            },
        )
    ]
    if oracle_object.unit_type != "package_body":
        return tuple(units)

    for subprogram in _detect_subprograms(masked_lines[oracle_object.start_line :]):
        units.append(
            LogicalUnit(
                unit_type=subprogram.unit_type,
                name=subprogram.name,
                confidence=Confidence.HIGH,
                start_line=subprogram.start_line + oracle_object.start_line,
                end_line=subprogram.end_line + oracle_object.start_line,
                metadata={
                    "format": "oracle",
                    "object_type": subprogram.unit_type,
                    "object_name": subprogram.name,
                    "parent_type": oracle_object.unit_type,
                    "parent_name": oracle_object.name,
                    "breadcrumb": (oracle_object.name, subprogram.name),
                },
            )
        )
    return tuple(units)


def _detect_subprograms(masked_lines: list[str]) -> tuple[_Subprogram, ...]:
    declarations: list[tuple[str, str, int]] = []
    for index, line in enumerate(masked_lines):
        match = SUBPROGRAM_RE.match(line)
        if match is None:
            continue
        declarations.append(
            (
                match.group("kind").lower(),
                _clean_identifier(match.group("name")),
                index + 1,
            )
        )

    subprograms: list[_Subprogram] = []
    for unit_type, name, start_line in declarations:
        end_line = _find_named_end(masked_lines, name=name, start_line=start_line)
        if end_line is None:
            continue
        if _has_nested_declaration(masked_lines, start_line=start_line, end_line=end_line):
            continue
        subprograms.append(
            _Subprogram(
                unit_type=unit_type,
                name=name,
                start_line=start_line,
                end_line=end_line,
            )
        )
    return tuple(subprograms)


def _find_named_end(
    masked_lines: list[str],
    *,
    name: str,
    start_line: int,
) -> int | None:
    normalized_name = _normalize_identifier(name)
    for index in range(start_line - 1, len(masked_lines)):
        for match in END_RE.finditer(masked_lines[index]):
            if _normalize_identifier(_clean_identifier(match.group("name"))) == normalized_name:
                return index + 1
    return None


def _has_nested_declaration(
    masked_lines: list[str],
    *,
    start_line: int,
    end_line: int,
) -> bool:
    for index in range(start_line, end_line - 1):
        if SUBPROGRAM_RE.match(masked_lines[index]):
            return True
    return False


def _unit_type(kind: str) -> str:
    normalized = " ".join(kind.lower().split())
    return {
        "package body": "package_body",
        "package": "package_spec",
        "type body": "type_body",
        "type": "type_spec",
        "view": "view",
        "procedure": "procedure",
        "function": "function",
        "trigger": "trigger",
    }[normalized]


def _clean_identifier(value: str) -> str:
    parts = [
        part.strip().strip('"')
        for part in re.split(r"\s*\.\s*", value.strip())
        if part.strip()
    ]
    return ".".join(parts)


def _normalize_identifier(value: str) -> str:
    return _clean_identifier(value).lower()


def _mask_plsql(lines: list[str]) -> list[str]:
    masked_lines: list[str] = []
    in_block_comment = False
    for line in lines:
        masked = []
        index = 0
        in_string = False
        while index < len(line):
            current = line[index]
            next_two = line[index : index + 2]
            if in_block_comment:
                if next_two == "*/":
                    masked.extend("  ")
                    index += 2
                    in_block_comment = False
                else:
                    masked.append(" ")
                    index += 1
                continue
            if in_string:
                if current == "'":
                    masked.append(" ")
                    if index + 1 < len(line) and line[index + 1] == "'":
                        masked.append(" ")
                        index += 2
                        continue
                    index += 1
                    in_string = False
                else:
                    masked.append(" ")
                    index += 1
                continue
            if next_two == "--":
                masked.extend(" " * (len(line) - index))
                break
            if next_two == "/*":
                masked.extend("  ")
                index += 2
                in_block_comment = True
                continue
            if current == "'":
                masked.append(" ")
                index += 1
                in_string = True
                continue
            masked.append(current)
            index += 1
        masked_lines.append("".join(masked))
    return masked_lines
