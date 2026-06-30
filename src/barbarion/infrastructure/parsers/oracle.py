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
from barbarion.domain.reverse_engineering import (
    TechnicalReference,
    ResolutionStatus,
    technical_reference_id,
    normalize_symbol_name,
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
QUALIFIED_CALL_RE = re.compile(
    rf"(?<!\.)\b(?P<target>{IDENTIFIER}\s*\.\s*(?P<member>\"[^\"]+\"|[A-Za-z][\w$#]*))\s*\(",
    re.IGNORECASE,
)
CALL_STATEMENT_RE = re.compile(
    rf"\bCALL\s+(?P<target>{IDENTIFIER})\s*(?:\(|;)",
    re.IGNORECASE,
)
TABLE_REF_RE = re.compile(
    rf"\b(?P<kind>FROM|JOIN|UPDATE|INSERT\s+INTO|MERGE\s+INTO|DELETE\s+FROM)\s+(?P<target>{IDENTIFIER})\b",
    re.IGNORECASE,
)
SEQUENCE_RE = re.compile(
    rf"\b(?P<target>{IDENTIFIER})\s*\.\s*(?:NEXTVAL|CURRVAL)\b",
    re.IGNORECASE,
)
TRIGGER_ON_RE = re.compile(
    rf"\bCREATE\s+(?:OR\s+REPLACE\s+)?TRIGGER\s+{IDENTIFIER}.*?\bON\s+(?P<target>{IDENTIFIER})\b",
    re.IGNORECASE,
)
DYNAMIC_SQL_RE = re.compile(
    r"\b(?:EXECUTE\s+IMMEDIATE|OPEN\s+\w+\s+FOR)\b",
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


def extract_oracle_references(
    text: str,
    *,
    source_file_id: int,
    source_chunk_id: str | None = None,
    source_symbol_id: str | None = None,
) -> tuple[TechnicalReference, ...]:
    """Extrae referencias Oracle crudas sin resolver destinos."""
    lines = text.splitlines() or [text]
    masked_lines = _mask_plsql(lines)
    references: list[TechnicalReference] = []
    seen: set[str] = set()
    for line_number, line in enumerate(masked_lines, start=1):
        raw_line = lines[line_number - 1]
        for match in DYNAMIC_SQL_RE.finditer(line):
            _append_reference(
                references,
                seen,
                source_file_id=source_file_id,
                source_chunk_id=source_chunk_id,
                source_symbol_id=source_symbol_id,
                raw_text=_evidence(raw_line, match),
                normalized_target="dynamic.sql",
                reference_type="dynamic_sql",
                start_line=line_number,
                confidence=Confidence.LOW,
                resolution_status=ResolutionStatus.DYNAMIC,
                metadata={"pattern": "oracle_dynamic_sql"},
            )
        for match in SEQUENCE_RE.finditer(line):
            target = _clean_identifier(match.group("target"))
            _append_reference(
                references,
                seen,
                source_file_id=source_file_id,
                source_chunk_id=source_chunk_id,
                source_symbol_id=source_symbol_id,
                raw_text=_evidence(raw_line, match),
                normalized_target=target,
                reference_type="sequence",
                start_line=line_number,
                confidence=Confidence.HIGH,
                resolution_status=ResolutionStatus.UNRESOLVED,
                metadata={"pattern": "oracle_sequence"},
            )
        for match in TRIGGER_ON_RE.finditer(line):
            target = _clean_identifier(match.group("target"))
            _append_reference(
                references,
                seen,
                source_file_id=source_file_id,
                source_chunk_id=source_chunk_id,
                source_symbol_id=source_symbol_id,
                raw_text=_evidence(raw_line, match),
                normalized_target=target,
                reference_type="trigger_table",
                start_line=line_number,
                confidence=Confidence.HIGH,
                resolution_status=ResolutionStatus.UNRESOLVED,
                metadata={"pattern": "oracle_trigger_on"},
            )
        for match in TABLE_REF_RE.finditer(line):
            target = _clean_identifier(match.group("target"))
            if _is_sql_noise(target):
                continue
            _append_reference(
                references,
                seen,
                source_file_id=source_file_id,
                source_chunk_id=source_chunk_id,
                source_symbol_id=source_symbol_id,
                raw_text=_evidence(raw_line, match),
                normalized_target=target,
                reference_type="table",
                start_line=line_number,
                confidence=Confidence.HIGH,
                resolution_status=ResolutionStatus.UNRESOLVED,
                metadata={"pattern": "oracle_sql_table"},
            )
        for match in CALL_STATEMENT_RE.finditer(line):
            target = _clean_identifier(match.group("target"))
            if _is_sql_noise(target):
                continue
            _append_reference(
                references,
                seen,
                source_file_id=source_file_id,
                source_chunk_id=source_chunk_id,
                source_symbol_id=source_symbol_id,
                raw_text=_evidence(raw_line, match),
                normalized_target=target,
                reference_type="call",
                start_line=line_number,
                confidence=Confidence.HIGH,
                resolution_status=ResolutionStatus.UNRESOLVED,
                metadata={"pattern": "oracle_call_statement"},
            )
        for match in QUALIFIED_CALL_RE.finditer(line):
            target = _clean_identifier(match.group("target"))
            if _is_sql_noise(target):
                continue
            _append_reference(
                references,
                seen,
                source_file_id=source_file_id,
                source_chunk_id=source_chunk_id,
                source_symbol_id=source_symbol_id,
                raw_text=_evidence(raw_line, match),
                normalized_target=target,
                reference_type="call",
                start_line=line_number,
                confidence=Confidence.MEDIUM,
                resolution_status=ResolutionStatus.UNRESOLVED,
                metadata={"pattern": "oracle_qualified_call"},
            )
    return tuple(references)


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


def _append_reference(
    references: list[TechnicalReference],
    seen: set[str],
    *,
    source_file_id: int,
    source_chunk_id: str | None,
    source_symbol_id: str | None,
    raw_text: str,
    normalized_target: str,
    reference_type: str,
    start_line: int,
    confidence: Confidence,
    resolution_status: ResolutionStatus,
    metadata: dict[str, str],
) -> None:
    normalized = normalize_symbol_name(normalized_target)
    reference_id = technical_reference_id(
        source_file_id=source_file_id,
        raw_text=raw_text,
        normalized_target=normalized,
        reference_type=reference_type,
        start_line=start_line,
        end_line=start_line,
    )
    seen_key = f"{source_file_id}:{start_line}:{reference_type}:{normalized}"
    if seen_key in seen:
        return
    seen.add(seen_key)
    references.append(
        TechnicalReference(
            reference_id=reference_id,
            source_file_id=source_file_id,
            source_symbol_id=source_symbol_id,
            source_chunk_id=source_chunk_id,
            raw_text=raw_text,
            normalized_target=normalized,
            reference_type=reference_type,
            technology="oracle",
            detection_method="regex",
            confidence=confidence,
            resolution_status=resolution_status,
            start_line=start_line,
            end_line=start_line,
            metadata=metadata,
        )
    )


def _evidence(raw_line: str, match: re.Match[str]) -> str:
    evidence = raw_line[match.start() : match.end()].strip()
    return " ".join(evidence.split())


def _is_sql_noise(target: str) -> bool:
    first = normalize_symbol_name(target).split(".")[0]
    return first in {
        "case",
        "cursor",
        "dbms_output",
        "dual",
        "if",
        "loop",
        "raise",
        "return",
        "select",
        "sysdate",
    }
