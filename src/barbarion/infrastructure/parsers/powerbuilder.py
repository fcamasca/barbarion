"""Parser heuristico de exportaciones textuales PowerBuilder."""

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
    H4Reference,
    H4ResolutionStatus,
    h4_reference_id,
    normalize_symbol_name,
)
from barbarion.infrastructure.parsers.base import BaseParser
from barbarion.infrastructure.parsers.encoding import TextExtractionError, decode_text_source


POWERBUILDER_TEXT_EXTENSIONS = (".srw", ".sru", ".srf", ".srm", ".srj", ".srd")
POWERBUILDER_EXTENSIONS = (*POWERBUILDER_TEXT_EXTENSIONS, ".pbl")
UNSUPPORTED_BINARY_PBL = "UNSUPPORTED_BINARY_PBL"

HEADER_RE = re.compile(
    r"^\s*\$PBExportHeader\$(?P<name>[^.=\s]+)(?:\.(?P<kind>[A-Za-z_][\w]*))?",
    re.IGNORECASE,
)
TYPE_RE = re.compile(
    r"^\s*(?:global\s+)?type\s+(?P<name>[A-Za-z_][\w]*)\s+from\s+(?P<kind>[A-Za-z_][\w]*)",
    re.IGNORECASE,
)
EVENT_START_RE = re.compile(
    r"^\s*(?:event|on)\s+(?P<name>[A-Za-z_][\w]*)\b",
    re.IGNORECASE,
)
EVENT_END_RE = re.compile(r"^\s*end\s+event\b", re.IGNORECASE)
FUNCTION_START_RE = re.compile(
    r"^\s*(?:(?:public|private|protected|global|forward|prototype)\s+)*"
    r"function\s+.*?\b(?P<name>[A-Za-z_][\w]*)\s*\(",
    re.IGNORECASE,
)
FUNCTION_END_RE = re.compile(r"^\s*end\s+function\b", re.IGNORECASE)
RETRIEVE_RE = re.compile(r"\bretrieve\s*=\s*(?P<sql>.+)", re.IGNORECASE)
PB_IDENTIFIER = r"[A-Za-z_][\w]*"
OPEN_RE = re.compile(
    rf"\bopen\s*\(\s*(?P<target>{PB_IDENTIFIER})\b",
    re.IGNORECASE,
)
QUALIFIED_CALL_RE = re.compile(
    rf"\b(?P<target>{PB_IDENTIFIER}\s*\.\s*{PB_IDENTIFIER})\s*\(",
    re.IGNORECASE,
)
TRIGGER_EVENT_RE = re.compile(
    rf"\btrigger\s+event\s+(?P<target>{PB_IDENTIFIER})\b",
    re.IGNORECASE,
)
DATAWINDOW_RE = re.compile(
    rf"\b(?:dataobject|datawindow)\s*=\s*[\"'](?P<target>{PB_IDENTIFIER})[\"']",
    re.IGNORECASE,
)
EMBEDDED_SQL_RE = re.compile(
    rf"\b(?P<kind>FROM|JOIN|UPDATE|INSERT\s+INTO|DELETE\s+FROM)\s+(?P<target>{PB_IDENTIFIER})\b",
    re.IGNORECASE,
)
STORED_PROCEDURE_RE = re.compile(
    rf"\b(?:DECLARE\s+{PB_IDENTIFIER}\s+PROCEDURE\s+FOR|EXECUTE)\s+(?P<target>{PB_IDENTIFIER})\b",
    re.IGNORECASE,
)
DYNAMIC_SQL_RE = re.compile(r"\bEXECUTE\s+IMMEDIATE\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class _PbObject:
    unit_type: str
    name: str
    start_line: int
    confidence: Confidence


@dataclass(frozen=True, slots=True)
class _PbMember:
    unit_type: str
    name: str
    start_line: int
    end_line: int
    confidence: Confidence


class PowerBuilderParser(BaseParser):
    """Extrae objetos y unidades textuales de PowerBuilder."""

    parser_id = "powerbuilder"
    parser_version = "1"
    supported_extensions = POWERBUILDER_EXTENSIONS

    def extract(
        self,
        source: SourceFile,
        context: ExtractionContext,
    ) -> ExtractionResult:
        if source.discovered.extension == ".pbl":
            raise TextExtractionError(
                error_code=UNSUPPORTED_BINARY_PBL,
                message="Los archivos PBL binarios no son soportados por H2.",
                relative_path=source.discovered.relative_path,
                details={"extension": ".pbl"},
            )

        decoded = decode_text_source(
            source,
            encodings=context.encodings,
            max_extracted_chars=context.max_extracted_chars,
        )
        lines = decoded.text.splitlines()
        line_count = max(1, len(lines))
        pb_object = _detect_object(lines, source.discovered.extension)
        if pb_object is None:
            units = (
                LogicalUnit(
                    unit_type="file",
                    name=source.discovered.relative_path.name,
                    confidence=Confidence.LOW,
                    start_line=1,
                    end_line=line_count,
                    metadata={
                        "format": "powerbuilder",
                        "extension": source.discovered.extension,
                    },
                ),
            )
            title = source.discovered.relative_path.name
            warnings = (*decoded.warnings, "POWERBUILDER_OBJECT_NOT_RECOGNIZED")
        else:
            units = _build_units(pb_object, lines=lines, line_count=line_count)
            title = pb_object.name
            warnings = decoded.warnings

        return ExtractionResult(
            text=decoded.text,
            title=title,
            encoding=decoded.encoding,
            units=units,
            metadata={
                "format": "powerbuilder",
                "extension": source.discovered.extension,
            },
            warnings=warnings,
        )


def extract_powerbuilder_references(
    text: str,
    *,
    source_file_id: int,
    source_chunk_id: str | None = None,
    source_symbol_id: str | None = None,
) -> tuple[H4Reference, ...]:
    """Extrae referencias PowerBuilder crudas sin resolver destinos."""
    lines = text.splitlines() or [text]
    masked_lines = _mask_powerbuilder(lines)
    references: list[H4Reference] = []
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
                resolution_status=H4ResolutionStatus.DYNAMIC,
                metadata={"pattern": "powerbuilder_dynamic_sql"},
            )
        for match in OPEN_RE.finditer(line):
            target = match.group("target")
            _append_reference(
                references,
                seen,
                source_file_id=source_file_id,
                source_chunk_id=source_chunk_id,
                source_symbol_id=source_symbol_id,
                raw_text=_evidence(raw_line, match),
                normalized_target=target,
                reference_type="open",
                start_line=line_number,
                confidence=Confidence.HIGH,
                resolution_status=H4ResolutionStatus.UNRESOLVED,
                metadata={"pattern": "powerbuilder_open"},
            )
        for match in QUALIFIED_CALL_RE.finditer(line):
            target = _clean_pb_identifier(match.group("target"))
            if _is_powerbuilder_builtin(target):
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
                resolution_status=H4ResolutionStatus.UNRESOLVED,
                metadata={"pattern": "powerbuilder_qualified_call"},
            )
        for match in TRIGGER_EVENT_RE.finditer(line):
            target = match.group("target")
            _append_reference(
                references,
                seen,
                source_file_id=source_file_id,
                source_chunk_id=source_chunk_id,
                source_symbol_id=source_symbol_id,
                raw_text=_evidence(raw_line, match),
                normalized_target=target,
                reference_type="event",
                start_line=line_number,
                confidence=Confidence.HIGH,
                resolution_status=H4ResolutionStatus.UNRESOLVED,
                metadata={"pattern": "powerbuilder_trigger_event"},
            )
        datawindow_source = raw_line if re.search(r"\b(?:dataobject|datawindow)\s*=", line, re.IGNORECASE) else ""
        for match in DATAWINDOW_RE.finditer(datawindow_source):
            target = match.group("target")
            _append_reference(
                references,
                seen,
                source_file_id=source_file_id,
                source_chunk_id=source_chunk_id,
                source_symbol_id=source_symbol_id,
                raw_text=_evidence(raw_line, match),
                normalized_target=target,
                reference_type="datawindow",
                start_line=line_number,
                confidence=Confidence.HIGH,
                resolution_status=H4ResolutionStatus.UNRESOLVED,
                metadata={"pattern": "powerbuilder_datawindow"},
            )
        for match in EMBEDDED_SQL_RE.finditer(line):
            target = match.group("target")
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
                confidence=Confidence.MEDIUM,
                resolution_status=H4ResolutionStatus.UNRESOLVED,
                metadata={"pattern": "powerbuilder_embedded_sql"},
            )
        for match in STORED_PROCEDURE_RE.finditer(line):
            target = match.group("target")
            if normalize_symbol_name(target) == "immediate":
                continue
            _append_reference(
                references,
                seen,
                source_file_id=source_file_id,
                source_chunk_id=source_chunk_id,
                source_symbol_id=source_symbol_id,
                raw_text=_evidence(raw_line, match),
                normalized_target=target,
                reference_type="stored_procedure",
                start_line=line_number,
                confidence=Confidence.HIGH,
                resolution_status=H4ResolutionStatus.UNRESOLVED,
                metadata={"pattern": "powerbuilder_stored_procedure"},
            )
    return tuple(references)


def _detect_object(lines: list[str], extension: str) -> _PbObject | None:
    header_name: str | None = None
    header_kind: str | None = None
    for index, line in enumerate(lines):
        header_match = HEADER_RE.match(line)
        if header_match is not None:
            header_name = header_match.group("name")
            header_kind = header_match.group("kind")
            continue
        type_match = TYPE_RE.match(line)
        if type_match is not None:
            return _PbObject(
                unit_type=_object_kind(type_match.group("kind"), extension),
                name=type_match.group("name"),
                start_line=index + 1,
                confidence=Confidence.HIGH,
            )
    if header_name is None:
        return None
    return _PbObject(
        unit_type=_object_kind(header_kind, extension),
        name=header_name,
        start_line=1,
        confidence=Confidence.MEDIUM,
    )


def _build_units(
    pb_object: _PbObject,
    *,
    lines: list[str],
    line_count: int,
) -> tuple[LogicalUnit, ...]:
    units: list[LogicalUnit] = [
        LogicalUnit(
            unit_type=pb_object.unit_type,
            name=pb_object.name,
            confidence=pb_object.confidence,
            start_line=pb_object.start_line,
            end_line=line_count,
            metadata={
                "format": "powerbuilder",
                "object_type": pb_object.unit_type,
                "object_name": pb_object.name,
                "breadcrumb": (pb_object.name,),
            },
        )
    ]
    for member in _detect_members(lines):
        units.append(
            LogicalUnit(
                unit_type=member.unit_type,
                name=member.name,
                confidence=member.confidence,
                start_line=member.start_line,
                end_line=member.end_line,
                metadata={
                    "format": "powerbuilder",
                    "object_type": member.unit_type,
                    "object_name": member.name,
                    "parent_type": pb_object.unit_type,
                    "parent_name": pb_object.name,
                    "breadcrumb": (pb_object.name, member.name),
                },
            )
        )
    for datawindow in _detect_datawindow_sql(lines):
        units.append(
            LogicalUnit(
                unit_type=datawindow.unit_type,
                name=datawindow.name,
                confidence=datawindow.confidence,
                start_line=datawindow.start_line,
                end_line=datawindow.end_line,
                metadata={
                    "format": "powerbuilder",
                    "object_type": datawindow.unit_type,
                    "object_name": datawindow.name,
                    "parent_type": pb_object.unit_type,
                    "parent_name": pb_object.name,
                    "breadcrumb": (pb_object.name, datawindow.name),
                },
            )
        )
    return tuple(units)


def _detect_members(lines: list[str]) -> tuple[_PbMember, ...]:
    members: list[_PbMember] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        event_match = EVENT_START_RE.match(line)
        if event_match is not None:
            end_line = _find_end(lines, start_index=index, end_re=EVENT_END_RE)
            if end_line is not None:
                members.append(
                    _PbMember(
                        unit_type="event",
                        name=event_match.group("name"),
                        start_line=index + 1,
                        end_line=end_line,
                        confidence=Confidence.HIGH,
                    )
                )
                index = end_line
                continue
        function_match = FUNCTION_START_RE.match(line)
        if function_match is not None:
            end_line = _find_end(lines, start_index=index, end_re=FUNCTION_END_RE)
            if end_line is not None:
                members.append(
                    _PbMember(
                        unit_type="function",
                        name=function_match.group("name"),
                        start_line=index + 1,
                        end_line=end_line,
                        confidence=Confidence.HIGH,
                    )
                )
                index = end_line
                continue
        index += 1
    return tuple(members)


def _detect_datawindow_sql(lines: list[str]) -> tuple[_PbMember, ...]:
    members: list[_PbMember] = []
    for index, line in enumerate(lines):
        match = RETRIEVE_RE.search(line)
        if match is None:
            continue
        members.append(
            _PbMember(
                unit_type="datawindow_sql",
                name="retrieve",
                start_line=index + 1,
                end_line=index + 1,
                confidence=Confidence.MEDIUM,
            )
        )
    return tuple(members)


def _find_end(lines: list[str], *, start_index: int, end_re: re.Pattern[str]) -> int | None:
    for index in range(start_index + 1, len(lines)):
        if end_re.match(lines[index]):
            return index + 1
    return None


def _object_kind(kind: str | None, extension: str) -> str:
    if kind is not None:
        normalized = kind.lower()
        if normalized in {"window", "userobject", "menu", "application", "structure"}:
            return normalized
        if normalized == "datawindow":
            return "datawindow"
    return {
        ".srw": "window",
        ".sru": "userobject",
        ".srf": "function_object",
        ".srm": "menu",
        ".srj": "project",
        ".srd": "datawindow",
    }.get(extension, "powerbuilder_object")


def _append_reference(
    references: list[H4Reference],
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
    resolution_status: H4ResolutionStatus,
    metadata: dict[str, str],
) -> None:
    normalized = normalize_symbol_name(normalized_target)
    reference_id = h4_reference_id(
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
        H4Reference(
            reference_id=reference_id,
            source_file_id=source_file_id,
            source_symbol_id=source_symbol_id,
            source_chunk_id=source_chunk_id,
            raw_text=raw_text,
            normalized_target=normalized,
            reference_type=reference_type,
            technology="powerbuilder",
            detection_method="regex",
            confidence=confidence,
            resolution_status=resolution_status,
            start_line=start_line,
            end_line=start_line,
            metadata=metadata,
        )
    )


def _mask_powerbuilder(lines: list[str]) -> list[str]:
    masked_lines: list[str] = []
    for line in lines:
        masked = []
        index = 0
        in_string = False
        quote = ""
        while index < len(line):
            current = line[index]
            next_two = line[index : index + 2]
            if in_string:
                if current == quote:
                    masked.append(" ")
                    if index + 1 < len(line) and line[index + 1] == quote:
                        masked.append(" ")
                        index += 2
                        continue
                    in_string = False
                    quote = ""
                else:
                    masked.append(" ")
                index += 1
                continue
            if next_two == "//":
                masked.extend(" " * (len(line) - index))
                break
            if current in {"'", '"'}:
                quote = current
                in_string = True
                masked.append(" ")
                index += 1
                continue
            masked.append(current)
            index += 1
        masked_lines.append("".join(masked))
    return masked_lines


def _evidence(raw_line: str, match: re.Match[str]) -> str:
    evidence = raw_line[match.start() : match.end()].strip()
    return " ".join(evidence.split())


def _clean_pb_identifier(value: str) -> str:
    return ".".join(part.strip() for part in value.split(".") if part.strip())


def _is_powerbuilder_builtin(target: str) -> bool:
    first = normalize_symbol_name(target).split(".")[0]
    return first in {"messagebox", "string", "integer", "long"}


def _is_sql_noise(target: str) -> bool:
    return normalize_symbol_name(target) in {"dual"}
