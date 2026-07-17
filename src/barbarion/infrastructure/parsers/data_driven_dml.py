"""Splitter acotado para DML Data-Driven."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DmlStatement:
    """Sentencia DML detectada sin ejecutar ni interpretar SQL."""

    text: str
    start_line: int
    end_line: int
    terminated: bool


def split_dml_statements(source: str) -> tuple[DmlStatement, ...]:
    """Separa sentencias por punto y coma fuera de strings y comentarios."""
    statements: list[DmlStatement] = []
    buffer: list[str] = []
    state = "normal"
    line = 1
    start_line: int | None = None
    index = 0

    def append(character: str) -> None:
        nonlocal start_line
        if start_line is None and not character.isspace():
            start_line = line
        buffer.append(character)

    def flush(*, terminated: bool) -> None:
        nonlocal start_line
        text = "".join(buffer).strip()
        if text:
            statements.append(
                DmlStatement(
                    text=text,
                    start_line=start_line or line,
                    end_line=line,
                    terminated=terminated,
                )
            )
        buffer.clear()
        start_line = None

    while index < len(source):
        character = source[index]
        next_character = source[index + 1] if index + 1 < len(source) else ""

        if state == "normal":
            if character == "-" and next_character == "-":
                append(character)
                append(next_character)
                state = "line_comment"
                index += 2
                continue
            if character == "/" and next_character == "*":
                append(character)
                append(next_character)
                state = "block_comment"
                index += 2
                continue
            if character == "'":
                append(character)
                state = "single_quote"
                index += 1
                continue
            if character == '"':
                append(character)
                state = "double_quote"
                index += 1
                continue
            if character == ";":
                flush(terminated=True)
                index += 1
                continue

            append(character)
            if character == "\n":
                line += 1
            index += 1
            continue

        if state == "line_comment":
            append(character)
            if character == "\n":
                line += 1
                state = "normal"
            index += 1
            continue

        if state == "block_comment":
            append(character)
            if character == "\n":
                line += 1
            if character == "*" and next_character == "/":
                append(next_character)
                state = "normal"
                index += 2
            else:
                index += 1
            continue

        if state == "single_quote":
            append(character)
            if character == "\n":
                line += 1
            if character == "'" and next_character == "'":
                append(next_character)
                index += 2
                continue
            if character == "'":
                state = "normal"
            index += 1
            continue

        if state == "double_quote":
            append(character)
            if character == "\n":
                line += 1
            if character == '"' and next_character == '"':
                append(next_character)
                index += 2
                continue
            if character == '"':
                state = "normal"
            index += 1
            continue

    if state in {"normal", "line_comment"}:
        flush(terminated=False)

    return tuple(statements)
