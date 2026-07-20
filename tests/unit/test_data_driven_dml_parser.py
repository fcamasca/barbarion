"""Pruebas del splitter DML Data-Driven."""

from barbarion.config import DataDrivenConfiguration
from barbarion.infrastructure.parsers.data_driven_dml import (
    DmlStatement,
    parse_dml_configurations,
    split_dml_statements,
)


def configuration(
    *,
    default_column_order: tuple[str, ...] = (),
    identity_columns: tuple[str, ...] = ("RULE_ID",),
) -> DataDrivenConfiguration:
    return DataDrivenConfiguration(
        name="pricing_rules",
        symbol_type="configuration_record",
        tables=("APP_CFG.PRICING_RULES",),
        identity_columns=identity_columns,
        file_patterns=(),
        default_column_order=default_column_order,
        name_columns=(),
        description_columns=(),
        rule_columns=(),
        formula_columns=(),
        variable_columns=(),
        parameter_columns=(),
        mapping_columns=(),
        reference_columns=(),
        parent_columns=(),
        sequence_columns=(),
        status_columns=(),
        effective_from_columns=(),
        effective_to_columns=(),
        metadata_columns=(),
    )


def test_split_dml_statements_uses_semicolon_outside_strings() -> None:
    statements = split_dml_statements(
        "INSERT INTO cfg VALUES ('a;b', 'c'';d');\n"
        "UPDATE cfg SET value = 'x' WHERE id = 1;"
    )

    assert statements == (
        DmlStatement(
            text="INSERT INTO cfg VALUES ('a;b', 'c'';d')",
            start_line=1,
            end_line=1,
            terminated=True,
        ),
        DmlStatement(
            text="UPDATE cfg SET value = 'x' WHERE id = 1",
            start_line=2,
            end_line=2,
            terminated=True,
        ),
    )


def test_parse_dml_configurations_parses_supported_insert_values() -> None:
    result = parse_dml_configurations(
        "\n".join(
            [
                "INSERT INTO APP_CFG.PRICING_RULES (",
                "  RULE_ID, RULE_NAME, AMOUNT, ACTIVE_FLAG, VALID_FROM,",
                "  UPDATED_AT, FUNCTION_NAME, PLACEHOLDER_VALUE",
                ") VALUES (",
                "  'R1', 'Base; Rule', 12.50, NULL, DATE '2026-01-01',",
                "  TO_DATE('2026-01-02', 'YYYY-MM-DD'), TAX_RATE(), :tenant",
                ");",
            ]
        ),
        (configuration(),),
        max_statements_per_file=100,
        max_literal_chars=500,
    )

    assert result.diagnostics == ()
    assert len(result.records) == 1
    record = result.records[0]
    assert record.configuration_name == "pricing_rules"
    assert record.table == "APP_CFG.PRICING_RULES"
    assert record.operation == "insert"
    assert record.partial is False
    assert record.identity_values[0].column == "rule_id"
    assert record.identity_values[0].raw == "'R1'"
    assert [(value.column, value.value_type) for value in record.values] == [
        ("rule_id", "string"),
        ("rule_name", "string"),
        ("amount", "number"),
        ("active_flag", "null"),
        ("valid_from", "date_literal"),
        ("updated_at", "function_expression"),
        ("function_name", "function_expression"),
        ("placeholder_value", "placeholder"),
    ]


def test_parse_dml_configurations_uses_default_column_order() -> None:
    result = parse_dml_configurations(
        "INSERT INTO pricing_rules VALUES ('R1', 'Base')",
        (
            configuration(
                default_column_order=("RULE_ID", "RULE_NAME"),
            ),
        ),
        max_statements_per_file=100,
        max_literal_chars=500,
    )

    assert result.diagnostics == ()
    assert result.records[0].terminated is False
    assert [value.column for value in result.records[0].values] == [
        "rule_id",
        "rule_name",
    ]


def test_parse_dml_configurations_reports_unsupported_insert_and_recovers() -> None:
    result = parse_dml_configurations(
        "INSERT ALL INTO APP_CFG.PRICING_RULES VALUES ('R0') SELECT 1 FROM dual;\n"
        "INSERT INTO APP_CFG.PRICING_RULES (RULE_ID) VALUES ('R1');",
        (configuration(),),
        max_statements_per_file=100,
        max_literal_chars=500,
    )

    assert len(result.records) == 1
    assert result.records[0].identity_values[0].raw == "'R1'"
    diagnostics = [
        (diagnostic.statement_ordinal, diagnostic.reason)
        for diagnostic in result.diagnostics
    ]
    assert diagnostics == [
        (1, "unsupported_insert"),
    ]


def test_parse_dml_configurations_parses_supported_update() -> None:
    result = parse_dml_configurations(
        "UPDATE APP_CFG.PRICING_RULES\n"
        "   SET FORMULA = '{A}+{B}', STATUS = 'A'\n"
        " WHERE RULE_ID = 'R2' AND VERSION = 1;",
        (
            configuration(
                identity_columns=("RULE_ID", "VERSION"),
            ),
        ),
        max_statements_per_file=100,
        max_literal_chars=500,
    )

    assert result.diagnostics == ()
    record = result.records[0]
    assert record.operation == "update"
    assert record.partial is True
    assert [(value.column, value.raw) for value in record.identity_values] == [
        ("rule_id", "'R2'"),
        ("version", "1"),
    ]
    assert [(value.column, value.raw) for value in record.values] == [
        ("rule_id", "'R2'"),
        ("version", "1"),
        ("formula", "'{A}+{B}'"),
        ("status", "'A'"),
    ]


def test_parse_dml_configurations_reports_update_without_identity() -> None:
    result = parse_dml_configurations(
        "UPDATE APP_CFG.PRICING_RULES SET FORMULA = 'x' WHERE STATUS = 'A';",
        (configuration(),),
        max_statements_per_file=100,
        max_literal_chars=500,
    )

    assert result.records == ()
    assert result.diagnostics[0].statement_type == "update"
    assert result.diagnostics[0].reason == "missing_identity_where"


def test_parse_dml_configurations_reports_limits() -> None:
    too_many = parse_dml_configurations(
        "INSERT INTO APP_CFG.PRICING_RULES (RULE_ID) VALUES ('R1');\n"
        "INSERT INTO APP_CFG.PRICING_RULES (RULE_ID) VALUES ('R2');",
        (configuration(),),
        max_statements_per_file=1,
        max_literal_chars=500,
    )
    too_long = parse_dml_configurations(
        "INSERT INTO APP_CFG.PRICING_RULES (RULE_ID) VALUES ('R12345');",
        (configuration(),),
        max_statements_per_file=100,
        max_literal_chars=3,
    )

    assert too_many.records == ()
    assert too_many.diagnostics[0].reason == "max_statements_per_file"
    assert too_long.records == ()
    assert too_long.diagnostics[0].reason == "max_literal_chars"


def test_split_dml_statements_ignores_semicolon_inside_comments() -> None:
    statements = split_dml_statements(
        "INSERT INTO cfg VALUES ('A') -- ; ignored\n"
        ";\n"
        "/* ; ignored */ UPDATE cfg SET value = 'B' WHERE id = 1;"
    )

    assert [statement.text for statement in statements] == [
        "INSERT INTO cfg VALUES ('A') -- ; ignored",
        "/* ; ignored */ UPDATE cfg SET value = 'B' WHERE id = 1",
    ]


def test_split_dml_statements_accepts_safe_final_statement_without_semicolon() -> None:
    statements = split_dml_statements(
        "INSERT INTO cfg VALUES ('A');\n"
        "UPDATE cfg SET value = 'B' WHERE id = 1"
    )

    assert statements[-1] == DmlStatement(
        text="UPDATE cfg SET value = 'B' WHERE id = 1",
        start_line=2,
        end_line=2,
        terminated=False,
    )


def test_split_dml_statements_omits_unsafe_final_fragment() -> None:
    statements = split_dml_statements(
        "INSERT INTO cfg VALUES ('A');\n"
        "UPDATE cfg SET value = 'B WHERE id = 1"
    )

    assert statements == (
        DmlStatement(
            text="INSERT INTO cfg VALUES ('A')",
            start_line=1,
            end_line=1,
            terminated=True,
        ),
    )


def test_parse_ignores_sqlplus_lines_and_preserves_insert_locations() -> None:
    """Ignora directivas SQL*Plus sin desplazar la evidencia DML."""
    source = "\n".join(
        [
            "-- Export de configuraciones",
            "PROMPT Cargando primera regla",
            "SET FEEDBACK OFF",
            "SET DEFINE OFF",
            "INSERT INTO APP_CFG.PRICING_RULES (RULE_ID) VALUES ('R1');",
            "PROMPT Cargando segunda regla",
            "INSERT INTO APP_CFG.PRICING_RULES (RULE_ID) VALUES ('R2');",
            "COMMIT;",
        ]
    )

    result = parse_dml_configurations(
        source,
        (configuration(),),
        max_statements_per_file=100,
        max_literal_chars=500,
    )

    assert [record.identity_values[0].raw for record in result.records] == [
        "'R1'",
        "'R2'",
    ]
    assert [
        (record.start_line, record.end_line) for record in result.records
    ] == [(5, 5), (7, 7)]
    assert [
        (
            diagnostic.statement_type,
            diagnostic.reason,
            diagnostic.start_line,
        )
        for diagnostic in result.diagnostics
    ] == [("commit", "unsupported_statement", 8)]


def test_parse_does_not_accept_insert_fragments_inside_plsql_block() -> None:
    """Evita interpretar como registros los INSERT internos de PL/SQL."""
    result = parse_dml_configurations(
        "BEGIN\n"
        "  INSERT INTO APP_CFG.PRICING_RULES (RULE_ID) VALUES ('INNER_1');\n"
        "  INSERT INTO APP_CFG.PRICING_RULES (RULE_ID) VALUES ('INNER_2');\n"
        "END;\n"
        "INSERT INTO APP_CFG.PRICING_RULES (RULE_ID) VALUES ('OUTER');",
        (configuration(),),
        max_statements_per_file=100,
        max_literal_chars=500,
    )

    assert [record.identity_values[0].raw for record in result.records] == [
        "'OUTER'"
    ]
    assert result.records[0].start_line == 5
    assert result.diagnostics[0].statement_type == "plsql_block"
    assert result.diagnostics[0].reason == "unsupported_statement"
