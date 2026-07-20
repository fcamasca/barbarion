"""Parser DML acotado para configuraciones Data-Driven.

El modulo trabaja sobre el contenido completo de un documento SQL y no ejecuta
sentencias. Solo reconoce un subconjunto conservador de `INSERT` y `UPDATE`
orientado a extraer registros de configuracion declarados por TOML.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from barbarion.config import DataDrivenConfiguration

_IDENTIFIER = r'(?:"[^"]+"|[A-Za-z][\w$#]*)(?:\s*\.\s*(?:"[^"]+"|[A-Za-z][\w$#]*))*'
_INSERT_RE = re.compile(
    rf"""
    ^\s*INSERT\s+INTO\s+
    (?P<table>{_IDENTIFIER})
    \s*
    (?:
        \((?P<columns>.*?)\)
        \s*
    )?
    VALUES\s*
    \((?P<values>.*)\)
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_UPDATE_RE = re.compile(
    rf"""
    ^\s*UPDATE\s+
    (?P<table>{_IDENTIFIER})
    \s+SET\s+
    (?P<set>.*?)
    \s+WHERE\s+
    (?P<where>.*)
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_DATE_LITERAL_RE = re.compile(
    r"^DATE\s+'[^']*(?:''[^']*)*'$",
    re.IGNORECASE | re.DOTALL,
)
_TIMESTAMP_LITERAL_RE = re.compile(
    r"^TIMESTAMP\s+'[^']*(?:''[^']*)*'$",
    re.IGNORECASE | re.DOTALL,
)
_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
_PLACEHOLDER_RE = re.compile(
    r"^(?::[A-Za-z_][A-Za-z0-9_]*|&[A-Za-z_][A-Za-z0-9_]*|\$\{[^}]+\})$"
)
_SQLPLUS_DIRECTIVE_RE = re.compile(
    r"^[ \t]*(?:PROMPT\b|SET\b(?![^\r\n]*=))",
    re.IGNORECASE,
)
_PLSQL_BLOCK_END_RE = re.compile(
    r"^END(?:\s+[A-Za-z_][A-Za-z0-9_$#]*)?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class DmlStatement:
    """Sentencia DML detectada por el splitter.

    Attributes:
        text: Texto de la sentencia sin el terminador final.
        start_line: Linea inicial dentro del documento completo.
        end_line: Linea final dentro del documento completo.
        terminated: Indica si la sentencia termino con `;`.
    """

    text: str
    start_line: int
    end_line: int
    terminated: bool


@dataclass(frozen=True, slots=True)
class DmlValue:
    """Valor estatico extraido de una columna DML.

    Attributes:
        column: Nombre normalizado de la columna.
        raw: Texto original del literal o expresion aceptada.
        value_type: Clasificacion estatica del valor.
        position: Posicion ordinal dentro de la lista de valores.
    """

    column: str
    raw: str
    value_type: str
    position: int


@dataclass(frozen=True, slots=True)
class DmlConfigurationRecord:
    """Registro de configuracion canonico derivado de una sentencia DML.

    Los registros parciales producidos por `UPDATE` conservan solo las columnas
    presentes en la sentencia y en el `WHERE`; no reconstruyen el estado real de
    la base de datos.

    Attributes:
        record_id: Identidad determinista calculada desde la configuracion y su clave.
        configuration_name: Nombre declarativo de la configuracion TOML.
        table: Tabla objetivo tal como fue detectada.
        operation: Operacion DML soportada.
        identity_values: Valores usados como identidad del registro.
        values: Valores disponibles en la sentencia.
        statement_ordinal: Posicion de la sentencia dentro del documento.
        start_line: Linea inicial de la sentencia.
        end_line: Linea final de la sentencia.
        partial: Indica si el registro proviene de un `UPDATE`.
        terminated: Indica si la sentencia termino con `;`.
    """

    record_id: str
    configuration_name: str
    table: str
    operation: str
    identity_values: tuple[DmlValue, ...]
    values: tuple[DmlValue, ...]
    statement_ordinal: int
    start_line: int
    end_line: int
    partial: bool
    terminated: bool


@dataclass(frozen=True, slots=True)
class DmlDiagnostic:
    """Diagnostico recuperable producido durante el parsing DML.

    Attributes:
        statement_ordinal: Posicion de la sentencia o fragmento diagnosticado.
        start_line: Linea inicial de la evidencia.
        end_line: Linea final de la evidencia.
        statement_type: Tipo de sentencia detectado de forma estatica.
        reason: Codigo estable del motivo de descarte.
    """

    statement_ordinal: int
    start_line: int
    end_line: int
    statement_type: str
    reason: str


@dataclass(frozen=True, slots=True)
class DmlParseResult:
    """Resultado del parsing estatico de un documento SQL.

    Attributes:
        records: Registros de configuracion extraidos con exito.
        diagnostics: Advertencias recuperables para sentencias omitidas.
    """

    records: tuple[DmlConfigurationRecord, ...]
    diagnostics: tuple[DmlDiagnostic, ...]


def split_dml_statements(source: str) -> tuple[DmlStatement, ...]:
    """Separa sentencias DML sin dividir literales ni comentarios.

    Usa `;` como terminador solamente cuando aparece fuera de strings,
    identificadores delimitados y comentarios. Si el contenido termina con un
    fragmento cerrado de forma segura, lo acepta aunque no tenga `;`.

    Args:
        source: Contenido completo del documento SQL.

    Returns:
        Sentencias detectadas en orden de aparicion.
    """
    source = _mask_sqlplus_directives(source)
    statements: list[DmlStatement] = []
    buffer: list[str] = []
    state = "normal"
    line = 1
    start_line: int | None = None
    index = 0

    def append(character: str, *, starts_statement: bool = True) -> None:
        nonlocal start_line
        if start_line is None and starts_statement and not character.isspace():
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
                append(character, starts_statement=False)
                append(next_character, starts_statement=False)
                state = "line_comment"
                index += 2
                continue
            if character == "/" and next_character == "*":
                append(character, starts_statement=False)
                append(next_character, starts_statement=False)
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
            append(character, starts_statement=False)
            if character == "\n":
                line += 1
                state = "normal"
            index += 1
            continue

        if state == "block_comment":
            append(character, starts_statement=False)
            if character == "\n":
                line += 1
            if character == "*" and next_character == "/":
                append(next_character, starts_statement=False)
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


def parse_dml_configurations(
    source: str,
    configurations: tuple[DataDrivenConfiguration, ...],
    *,
    max_statements_per_file: int,
    max_literal_chars: int,
) -> DmlParseResult:
    """Extrae registros declarados desde un documento SQL completo.

    Solo interpreta formas acotadas de `INSERT` y `UPDATE`; cualquier sentencia
    fuera de ese subconjunto se informa como diagnostico recuperable. El parser
    no ejecuta SQL ni evalua expresiones.

    Args:
        source: Contenido completo del documento SQL.
        configurations: Declaraciones Data-Driven habilitadas.
        max_statements_per_file: Limite defensivo de sentencias por documento.
        max_literal_chars: Longitud maxima permitida para literales.

    Returns:
        Registros extraidos y diagnosticos de sentencias descartadas.
    """
    statements = split_dml_statements(source)
    if len(statements) > max_statements_per_file:
        return DmlParseResult(
            records=(),
            diagnostics=(
                DmlDiagnostic(
                    statement_ordinal=max_statements_per_file + 1,
                    start_line=1,
                    end_line=1,
                    statement_type="limit",
                    reason="max_statements_per_file",
                ),
            ),
        )

    records: list[DmlConfigurationRecord] = []
    diagnostics: list[DmlDiagnostic] = []
    inside_plsql_block = False
    for ordinal, statement in enumerate(statements, start=1):
        text = _strip_sql_comments(statement.text).strip()
        statement_type = _statement_type(text)
        if inside_plsql_block:
            if _PLSQL_BLOCK_END_RE.match(text):
                inside_plsql_block = False
            continue
        if statement_type == "plsql_block":
            inside_plsql_block = True
            diagnostics.append(
                _diagnostic(
                    statement,
                    ordinal,
                    statement_type,
                    "unsupported_statement",
                )
            )
            continue
        record, diagnostic = _parse_statement(
            statement,
            ordinal,
            configurations,
            max_literal_chars=max_literal_chars,
        )
        if record is not None:
            records.append(record)
        if diagnostic is not None:
            diagnostics.append(diagnostic)
    return DmlParseResult(records=tuple(records), diagnostics=tuple(diagnostics))


def _parse_statement(
    statement: DmlStatement,
    ordinal: int,
    configurations: tuple[DataDrivenConfiguration, ...],
    *,
    max_literal_chars: int,
) -> tuple[DmlConfigurationRecord | None, DmlDiagnostic | None]:
    """Despacha una sentencia soportada y convierte rechazos en diagnosticos."""
    text = _strip_sql_comments(statement.text).strip()
    statement_type = _statement_type(text)
    if statement_type == "insert":
        return _parse_insert(
            text,
            statement,
            ordinal,
            configurations,
            max_literal_chars=max_literal_chars,
        )
    if statement_type == "update":
        return _parse_update(
            text,
            statement,
            ordinal,
            configurations,
            max_literal_chars=max_literal_chars,
        )
    return None, _diagnostic(
        statement,
        ordinal,
        statement_type,
        "unsupported_statement",
    )


def _parse_insert(
    text: str,
    statement: DmlStatement,
    ordinal: int,
    configurations: tuple[DataDrivenConfiguration, ...],
    *,
    max_literal_chars: int,
) -> tuple[DmlConfigurationRecord | None, DmlDiagnostic | None]:
    """Parsea `INSERT INTO ... VALUES ...` contra tablas declaradas."""
    if _contains_unsupported_insert_shape(text):
        return None, _diagnostic(statement, ordinal, "insert", "unsupported_insert")
    match = _INSERT_RE.match(text)
    if match is None:
        return None, _diagnostic(statement, ordinal, "insert", "malformed_insert")

    table = _normalize_table_name(match.group("table"))
    configuration = _configuration_for_table(configurations, table)
    if configuration is None:
        return None, _diagnostic(statement, ordinal, "insert", "undeclared_table")

    columns_text = match.group("columns")
    if columns_text is None:
        if not configuration.default_column_order:
            return None, _diagnostic(
                statement,
                ordinal,
                "insert",
                "missing_default_column_order",
            )
        columns = configuration.default_column_order
    else:
        columns = tuple(
            _normalize_identifier(column)
            for column in _split_top_level(columns_text)
        )

    raw_values = _split_top_level(match.group("values"))
    if len(columns) != len(raw_values):
        return None, _diagnostic(statement, ordinal, "insert", "column_value_mismatch")
    values, diagnostic = _build_values(
        columns,
        raw_values,
        statement,
        ordinal,
        "insert",
        max_literal_chars=max_literal_chars,
    )
    if diagnostic is not None:
        return None, diagnostic

    identities = _identity_values(configuration, values)
    if len(identities) != len(configuration.identity_columns):
        return None, _diagnostic(statement, ordinal, "insert", "missing_identity")
    return (
        _record(
            configuration=configuration,
            table=match.group("table"),
            operation="insert",
            identity_values=identities,
            values=values,
            statement=statement,
            ordinal=ordinal,
            partial=False,
        ),
        None,
    )


def _parse_update(
    text: str,
    statement: DmlStatement,
    ordinal: int,
    configurations: tuple[DataDrivenConfiguration, ...],
    *,
    max_literal_chars: int,
) -> tuple[DmlConfigurationRecord | None, DmlDiagnostic | None]:
    """Parsea `UPDATE ... SET ... WHERE ...` como registro parcial trazable."""
    if _contains_unsupported_update_shape(text):
        return None, _diagnostic(statement, ordinal, "update", "unsupported_update")
    match = _UPDATE_RE.match(text)
    if match is None:
        return None, _diagnostic(statement, ordinal, "update", "malformed_update")

    table = _normalize_table_name(match.group("table"))
    configuration = _configuration_for_table(configurations, table)
    if configuration is None:
        return None, _diagnostic(statement, ordinal, "update", "undeclared_table")

    set_pairs = _parse_assignments(match.group("set"), separator=",")
    if not set_pairs:
        return None, _diagnostic(statement, ordinal, "update", "missing_set")
    where_pairs = _parse_assignments(match.group("where"), separator="AND")
    if not where_pairs:
        return None, _diagnostic(statement, ordinal, "update", "unsupported_where")

    where_columns = {_normalize_identifier(column) for column, _value in where_pairs}
    required_identities = {
        _normalize_identifier(column) for column in configuration.identity_columns
    }
    if not required_identities.issubset(where_columns):
        return None, _diagnostic(statement, ordinal, "update", "missing_identity_where")

    combined_pairs = (*where_pairs, *set_pairs)
    columns = tuple(_normalize_identifier(column) for column, _value in combined_pairs)
    raw_values = tuple(value for _column, value in combined_pairs)
    values, diagnostic = _build_values(
        columns,
        raw_values,
        statement,
        ordinal,
        "update",
        max_literal_chars=max_literal_chars,
    )
    if diagnostic is not None:
        return None, diagnostic
    identities = _identity_values(configuration, values)
    return (
        _record(
            configuration=configuration,
            table=match.group("table"),
            operation="update",
            identity_values=identities,
            values=values,
            statement=statement,
            ordinal=ordinal,
            partial=True,
        ),
        None,
    )


def _build_values(
    columns: tuple[str, ...],
    raw_values: tuple[str, ...],
    statement: DmlStatement,
    ordinal: int,
    statement_type: str,
    *,
    max_literal_chars: int,
) -> tuple[tuple[DmlValue, ...], DmlDiagnostic | None]:
    """Normaliza columnas y valores preservando el texto original aceptado."""
    values: list[DmlValue] = []
    for position, (column, raw_value) in enumerate(zip(columns, raw_values), start=1):
        raw = raw_value.strip()
        if len(raw) > max_literal_chars:
            return (), _diagnostic(
                statement,
                ordinal,
                statement_type,
                "max_literal_chars",
            )
        if _contains_subquery(raw):
            return (), _diagnostic(statement, ordinal, statement_type, "subquery")
        values.append(
            DmlValue(
                column=_normalize_identifier(column),
                raw=raw,
                value_type=_value_type(raw),
                position=position,
            )
        )
    return tuple(values), None


def _record(
    *,
    configuration: DataDrivenConfiguration,
    table: str,
    operation: str,
    identity_values: tuple[DmlValue, ...],
    values: tuple[DmlValue, ...],
    statement: DmlStatement,
    ordinal: int,
    partial: bool,
) -> DmlConfigurationRecord:
    """Construye el registro canonico y conserva si la operacion fue parcial."""
    normalized_table = _normalize_table_name(table)
    record_id = _record_id(configuration.name, normalized_table, identity_values)
    return DmlConfigurationRecord(
        record_id=record_id,
        configuration_name=configuration.name,
        table=table,
        operation=operation,
        identity_values=identity_values,
        values=values,
        statement_ordinal=ordinal,
        start_line=statement.start_line,
        end_line=statement.end_line,
        partial=partial,
        terminated=statement.terminated,
    )


def _record_id(
    configuration_name: str,
    normalized_table: str,
    identity_values: tuple[DmlValue, ...],
) -> str:
    payload = "|".join(
        (
            "barbarion.configuration.record.v1",
            configuration_name,
            normalized_table,
            *(
                f"{value.column}={value.raw}"
                for value in sorted(identity_values, key=lambda item: item.column)
            ),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _identity_values(
    configuration: DataDrivenConfiguration,
    values: tuple[DmlValue, ...],
) -> tuple[DmlValue, ...]:
    required = {
        _normalize_identifier(column)
        for column in configuration.identity_columns
    }
    return tuple(value for value in values if value.column in required)


def _configuration_for_table(
    configurations: tuple[DataDrivenConfiguration, ...],
    table: str,
) -> DataDrivenConfiguration | None:
    normalized = _normalize_table_name(table)
    unqualified = normalized.rsplit(".", 1)[-1]
    for configuration in configurations:
        for configured_table in configuration.tables:
            configured = _normalize_table_name(configured_table)
            if normalized == configured or unqualified == configured.rsplit(".", 1)[-1]:
                return configuration
    return None


def _parse_assignments(text: str, *, separator: str) -> tuple[tuple[str, str], ...]:
    """Extrae asignaciones `columna = valor` separadas a nivel superior."""
    parts = (
        _split_top_level(text)
        if separator == ","
        else _split_top_level_keyword(text, separator)
    )
    assignments: list[tuple[str, str]] = []
    for part in parts:
        left, right = _split_assignment(part)
        if left is None or right is None:
            return ()
        assignments.append((_normalize_identifier(left), right.strip()))
    return tuple(assignments)


def _split_assignment(text: str) -> tuple[str | None, str | None]:
    state = "normal"
    depth = 0
    index = 0
    while index < len(text):
        character = text[index]
        next_character = text[index + 1] if index + 1 < len(text) else ""
        if state == "normal":
            if character == "'":
                state = "single_quote"
            elif character == '"':
                state = "double_quote"
            elif character == "(":
                depth += 1
            elif character == ")":
                depth = max(0, depth - 1)
            elif character == "=" and depth == 0:
                return text[:index].strip(), text[index + 1 :].strip()
        elif state == "single_quote":
            if character == "'" and next_character == "'":
                index += 1
            elif character == "'":
                state = "normal"
        elif state == "double_quote" and character == '"':
            state = "normal"
        index += 1
    return None, None


def _split_top_level(text: str) -> tuple[str, ...]:
    return _split_top_level_character(text, ",")


def _split_top_level_character(text: str, separator: str) -> tuple[str, ...]:
    """Divide por un caracter sin entrar en strings ni parentesis anidados."""
    parts: list[str] = []
    start = 0
    state = "normal"
    depth = 0
    index = 0
    while index < len(text):
        character = text[index]
        next_character = text[index + 1] if index + 1 < len(text) else ""
        if state == "normal":
            if character == "'":
                state = "single_quote"
            elif character == '"':
                state = "double_quote"
            elif character == "(":
                depth += 1
            elif character == ")":
                depth = max(0, depth - 1)
            elif character == separator and depth == 0:
                parts.append(text[start:index].strip())
                start = index + 1
        elif state == "single_quote":
            if character == "'" and next_character == "'":
                index += 1
            elif character == "'":
                state = "normal"
        elif state == "double_quote" and character == '"':
            state = "normal"
        index += 1
    parts.append(text[start:].strip())
    return tuple(part for part in parts if part)


def _split_top_level_keyword(text: str, keyword: str) -> tuple[str, ...]:
    """Divide por una palabra clave solo cuando esta fuera de literales."""
    parts: list[str] = []
    start = 0
    state = "normal"
    depth = 0
    upper_text = text.upper()
    upper_keyword = keyword.upper()
    index = 0
    while index < len(text):
        character = text[index]
        next_character = text[index + 1] if index + 1 < len(text) else ""
        if state == "normal":
            if character == "'":
                state = "single_quote"
            elif character == '"':
                state = "double_quote"
            elif character == "(":
                depth += 1
            elif character == ")":
                depth = max(0, depth - 1)
            elif (
                depth == 0
                and upper_text.startswith(upper_keyword, index)
                and _keyword_boundary(text, index, len(keyword))
            ):
                parts.append(text[start:index].strip())
                index += len(keyword)
                start = index
                continue
        elif state == "single_quote":
            if character == "'" and next_character == "'":
                index += 1
            elif character == "'":
                state = "normal"
        elif state == "double_quote" and character == '"':
            state = "normal"
        index += 1
    parts.append(text[start:].strip())
    return tuple(part for part in parts if part)


def _keyword_boundary(text: str, start: int, length: int) -> bool:
    before = text[start - 1] if start > 0 else " "
    after = text[start + length] if start + length < len(text) else " "
    return not (_is_identifier_character(before) or _is_identifier_character(after))


def _is_identifier_character(character: str) -> bool:
    return character.isalnum() or character in {"_", "$", "#"}


def _strip_sql_comments(text: str) -> str:
    """Elimina comentarios SQL conservando strings e identificadores."""
    output: list[str] = []
    state = "normal"
    index = 0
    while index < len(text):
        character = text[index]
        next_character = text[index + 1] if index + 1 < len(text) else ""
        if state == "normal":
            if character == "-" and next_character == "-":
                state = "line_comment"
                index += 2
                continue
            if character == "/" and next_character == "*":
                state = "block_comment"
                index += 2
                continue
            if character == "'":
                state = "single_quote"
            elif character == '"':
                state = "double_quote"
            output.append(character)
        elif state == "line_comment":
            if character == "\n":
                output.append(character)
                state = "normal"
        elif state == "block_comment":
            if character == "\n":
                output.append(character)
            if character == "*" and next_character == "/":
                state = "normal"
                index += 1
        elif state == "single_quote":
            output.append(character)
            if character == "'" and next_character == "'":
                output.append(next_character)
                index += 1
            elif character == "'":
                state = "normal"
        elif state == "double_quote":
            output.append(character)
            if character == '"':
                state = "normal"
        index += 1
    return "".join(output)


def _value_type(raw: str) -> str:
    stripped = raw.strip()
    if stripped.upper() == "NULL":
        return "null"
    if _is_quoted_string(stripped):
        return "string"
    if _NUMBER_RE.match(stripped):
        return "number"
    if _DATE_LITERAL_RE.match(stripped):
        return "date_literal"
    if _TIMESTAMP_LITERAL_RE.match(stripped):
        return "timestamp_literal"
    if _PLACEHOLDER_RE.match(stripped):
        return "placeholder"
    if _looks_like_function(stripped):
        return "function_expression"
    return "raw_expression"


def _is_quoted_string(value: str) -> bool:
    return len(value) >= 2 and value[0] == "'" and value[-1] == "'"


def _looks_like_function(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_$#]*\s*\(.*\)$", value, re.DOTALL))


def _contains_unsupported_insert_shape(text: str) -> bool:
    upper = text.upper()
    return (
        upper.startswith("INSERT ALL")
        or _contains_keyword_outside_literals(text, "RETURNING")
        or _contains_keyword_outside_literals(text, "SELECT")
    )


def _contains_unsupported_update_shape(text: str) -> bool:
    return (
        _contains_keyword_outside_literals(text, "RETURNING")
        or _contains_keyword_outside_literals(text, "FROM")
        or _contains_keyword_outside_literals(text, "OR")
        or _contains_keyword_outside_literals(text, "IN")
        or _contains_keyword_outside_literals(text, "LIKE")
        or _contains_subquery(text)
    )


def _contains_subquery(text: str) -> bool:
    scrubbed = _scrub_literals(text)
    return re.search(r"\(\s*SELECT\b", scrubbed, re.IGNORECASE | re.DOTALL) is not None


def _contains_keyword_outside_literals(text: str, keyword: str) -> bool:
    scrubbed = _scrub_literals(text)
    return re.search(rf"\b{re.escape(keyword)}\b", scrubbed, re.IGNORECASE) is not None


def _scrub_literals(text: str) -> str:
    """Reemplaza strings por espacios para buscar palabras clave estructurales."""
    output: list[str] = []
    state = "normal"
    index = 0
    while index < len(text):
        character = text[index]
        next_character = text[index + 1] if index + 1 < len(text) else ""
        if state == "normal":
            if character == "'":
                output.append(" ")
                state = "single_quote"
            else:
                output.append(character)
        elif state == "single_quote":
            output.append(" ")
            if character == "'" and next_character == "'":
                output.append(" ")
                index += 1
            elif character == "'":
                state = "normal"
        index += 1
    return "".join(output)


def _statement_type(text: str) -> str:
    stripped = text.lstrip()
    if re.match(r"^INSERT\b", stripped, re.IGNORECASE):
        return "insert"
    if re.match(r"^UPDATE\b", stripped, re.IGNORECASE):
        return "update"
    if re.match(r"^(BEGIN|DECLARE)\b", stripped, re.IGNORECASE):
        return "plsql_block"
    if re.match(r"^COMMIT\b", stripped, re.IGNORECASE):
        return "commit"
    return "unknown"


def _mask_sqlplus_directives(source: str) -> str:
    """Neutraliza directivas SQL*Plus sin alterar posiciones ni lineas.

    Cada caracter de una linea `PROMPT` o `SET` se sustituye por un espacio,
    excepto sus terminadores `CR` y `LF`. De esta forma las directivas no se
    mezclan con una sentencia SQL y la trazabilidad conserva las lineas del
    documento original.

    Args:
        source: Contenido completo del documento SQL.

    Returns:
        Contenido con las directivas SQL*Plus neutralizadas.
    """
    masked_lines: list[str] = []
    for line in source.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        ending = line[len(content) :]
        if _SQLPLUS_DIRECTIVE_RE.match(content):
            masked_lines.append((" " * len(content)) + ending)
        else:
            masked_lines.append(line)
    return "".join(masked_lines)


def _diagnostic(
    statement: DmlStatement,
    ordinal: int,
    statement_type: str,
    reason: str,
) -> DmlDiagnostic:
    return DmlDiagnostic(
        statement_ordinal=ordinal,
        start_line=statement.start_line,
        end_line=statement.end_line,
        statement_type=statement_type,
        reason=reason,
    )


def _normalize_identifier(identifier: str) -> str:
    return identifier.strip().strip('"').lower()


def _normalize_table_name(table: str) -> str:
    return ".".join(
        _normalize_identifier(part)
        for part in re.split(r"\s*\.\s*", table.strip())
        if part.strip()
    )
