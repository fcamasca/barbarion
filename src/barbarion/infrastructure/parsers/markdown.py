"""Parser heuristico de Markdown."""

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


ATX_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t#]*$")
SETEXT_RE = re.compile(r"^[ \t]*(=+|-+)[ \t]*$")


@dataclass(frozen=True, slots=True)
class _Heading:
    level: int
    title: str
    line: int


class MarkdownParser(BaseParser):
    """Extrae secciones Markdown sin modificar el contenido."""

    parser_id = "markdown"
    parser_version = "1"
    supported_extensions = (".md",)

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
        headings = _detect_headings(lines)
        units = _build_units(headings, line_count=len(lines))
        if not units:
            units = (
                LogicalUnit(
                    unit_type="file",
                    name=source.discovered.relative_path.name,
                    confidence=Confidence.LOW,
                    start_line=1,
                    end_line=max(1, len(lines)),
                    metadata={"format": "markdown", "breadcrumb": ()},
                ),
            )
        title = headings[0].title if headings else source.discovered.relative_path.name
        return ExtractionResult(
            text=decoded.text,
            title=title,
            encoding=decoded.encoding,
            units=units,
            metadata={"format": "markdown"},
            warnings=decoded.warnings,
        )


def _detect_headings(lines: list[str]) -> tuple[_Heading, ...]:
    headings: list[_Heading] = []
    in_fence = False
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        match = ATX_HEADING_RE.match(line)
        if match is not None:
            headings.append(
                _Heading(
                    level=len(match.group(1)),
                    title=match.group(2).strip(),
                    line=index + 1,
                )
            )
            continue

        if index == 0:
            continue
        previous = lines[index - 1].strip()
        if not previous:
            continue
        setext = SETEXT_RE.match(line)
        if setext is None:
            continue
        level = 1 if setext.group(1).startswith("=") else 2
        headings.append(_Heading(level=level, title=previous, line=index))
    return tuple(headings)


def _build_units(headings: tuple[_Heading, ...], *, line_count: int) -> tuple[LogicalUnit, ...]:
    units: list[LogicalUnit] = []
    stack: list[_Heading] = []
    for index, heading in enumerate(headings):
        while stack and stack[-1].level >= heading.level:
            stack.pop()
        stack.append(heading)
        next_line = _next_sibling_or_parent_line(headings[index + 1 :], heading)
        end_line = (next_line - 1) if next_line is not None else max(heading.line, line_count)
        breadcrumb = tuple(item.title for item in stack)
        units.append(
            LogicalUnit(
                unit_type="section",
                name=heading.title,
                confidence=Confidence.HIGH,
                start_line=heading.line,
                end_line=end_line,
                metadata={
                    "format": "markdown",
                    "heading_level": heading.level,
                    "breadcrumb": breadcrumb,
                },
            )
        )
    return tuple(units)


def _next_sibling_or_parent_line(
    headings: tuple[_Heading, ...],
    current: _Heading,
) -> int | None:
    for heading in headings:
        if heading.level <= current.level:
            return heading.line
    return None
