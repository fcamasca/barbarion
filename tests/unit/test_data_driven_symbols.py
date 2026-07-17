"""Pruebas de simbolos Data-Driven."""

from barbarion.config import DataDrivenConfiguration, DataDrivenStatusColumn
from barbarion.domain.data_driven import build_configuration_symbols
from barbarion.domain.reverse_engineering import SymbolStatus
from barbarion.infrastructure.parsers.data_driven_dml import parse_dml_configurations


def configuration() -> DataDrivenConfiguration:
    return DataDrivenConfiguration(
        name="pricing_rules",
        symbol_type="configuration_record",
        tables=("APP_CFG.PRICING_RULES",),
        identity_columns=("RULE_ID",),
        file_patterns=(),
        default_column_order=(),
        name_columns=("RULE_NAME",),
        description_columns=("DESCRIPTION",),
        rule_columns=("RULE_SQL",),
        formula_columns=("FORMULA",),
        variable_columns=("VARIABLE_NAME",),
        parameter_columns=("PARAMETER_NAME",),
        mapping_columns=("MAPPING_NAME",),
        reference_columns=(),
        parent_columns=(),
        sequence_columns=("DISPLAY_ORDER",),
        status_columns=(
            DataDrivenStatusColumn(
                column="STATUS",
                active_values=("A",),
                inactive_values=("I",),
            ),
        ),
        effective_from_columns=(),
        effective_to_columns=(),
        metadata_columns=("OWNER",),
    )


def records(sql: str):
    result = parse_dml_configurations(
        sql,
        (configuration(),),
        max_statements_per_file=100,
        max_literal_chars=1000,
    )
    assert result.diagnostics == ()
    return result.records


def test_build_configuration_symbols_creates_entity_record_and_children() -> None:
    parsed_records = records(
        """
        INSERT INTO APP_CFG.PRICING_RULES (
            RULE_ID, RULE_NAME, RULE_SQL, FORMULA, VARIABLE_NAME,
            PARAMETER_NAME, MAPPING_NAME, DISPLAY_ORDER, STATUS, OWNER, IGNORED
        )
        VALUES (
            'R1', 'Base Rule', 'select 1 from dual', '{A}+{B}', 'A',
            'TENANT', 'CustomerMap', 10, 'A', 'risk', 'no metadata'
        );
        """
    )

    plan = build_configuration_symbols(parsed_records, (configuration(),))

    assert plan.diagnostics == ()
    by_type = {
        (symbol.symbol_type, symbol.original_name): symbol
        for symbol in plan.symbols
    }
    entity = by_type[("configuration_entity", "pricing_rules")]
    record = by_type[("configuration_record", "Base Rule")]
    assert entity.technology == "configuration"
    assert record.parent_symbol_id == entity.symbol_id
    assert record.status == SymbolStatus.ACTIVE
    assert record.metadata["identity"] == {"rule_id": "'R1'"}
    assert record.metadata["display_values"] == {"rule_name": "'Base Rule'"}
    assert record.metadata["values"] == {
        "rule_id": "'R1'",
        "rule_name": "'Base Rule'",
        "rule_sql": "'select 1 from dual'",
        "formula": "'{A}+{B}'",
        "variable_name": "'A'",
        "parameter_name": "'TENANT'",
        "mapping_name": "'CustomerMap'",
        "display_order": "10",
        "status": "'A'",
        "owner": "'risk'",
    }
    assert "ignored" not in record.metadata["values"]
    assert ("configuration_rule", "select 1 from dual") in by_type
    assert ("configuration_formula", "{A}+{B}") in by_type
    assert ("configuration_variable", "A") in by_type
    assert ("configuration_parameter", "TENANT") in by_type
    assert ("configuration_mapping", "CustomerMap") in by_type
    assert ("configuration_step", "10") in by_type


def test_build_configuration_symbols_marks_inactive_status() -> None:
    parsed_records = records(
        """
        INSERT INTO APP_CFG.PRICING_RULES (RULE_ID, RULE_NAME, STATUS)
        VALUES ('R2', 'Inactive Rule', 'I');
        """
    )

    plan = build_configuration_symbols(parsed_records, (configuration(),))

    record = next(
        symbol
        for symbol in plan.symbols
        if symbol.symbol_type == "configuration_record"
    )
    assert record.status == SymbolStatus.STALE


def test_build_configuration_symbols_keeps_update_partial_record_traceable() -> None:
    parsed_records = records(
        """
        UPDATE APP_CFG.PRICING_RULES
           SET RULE_NAME = 'Updated Rule', FORMULA = '{A}'
         WHERE RULE_ID = 'R3';
        """
    )

    plan = build_configuration_symbols(parsed_records, (configuration(),))

    assert plan.diagnostics == ()
    record = next(
        symbol
        for symbol in plan.symbols
        if symbol.symbol_type == "configuration_record"
    )
    assert record.original_name == "Updated Rule"
    assert record.metadata["partial"] is True
    assert record.metadata["operation"] == "update"
    assert record.metadata["identity"] == {"rule_id": "'R3'"}
    assert record.signature == record.metadata["source_hash"]
    formula = next(
        symbol
        for symbol in plan.symbols
        if symbol.symbol_type == "configuration_formula"
    )
    assert formula.parent_symbol_id == record.symbol_id


def test_build_configuration_symbols_reports_duplicate_records() -> None:
    parsed_records = records(
        """
        INSERT INTO APP_CFG.PRICING_RULES (RULE_ID, RULE_NAME) VALUES ('R1', 'One');
        UPDATE APP_CFG.PRICING_RULES SET RULE_NAME = 'Two' WHERE RULE_ID = 'R1';
        """
    )

    plan = build_configuration_symbols(parsed_records, (configuration(),))

    assert [diagnostic.reason for diagnostic in plan.diagnostics] == [
        "duplicate_record",
    ]
    record_symbols = [
        symbol
        for symbol in plan.symbols
        if symbol.symbol_type == "configuration_record"
    ]
    assert len(record_symbols) == 1


def test_build_configuration_symbols_is_deterministic() -> None:
    parsed_records = records(
        """
        INSERT INTO APP_CFG.PRICING_RULES (
            RULE_ID, RULE_NAME, MAPPING_NAME, STATUS
        )
        VALUES ('R4', 'Stable Rule', 'StableMap', 'A');
        """
    )

    first = build_configuration_symbols(parsed_records, (configuration(),))
    second = build_configuration_symbols(parsed_records, (configuration(),))

    first_projection = tuple(
        (
            symbol.symbol_id,
            symbol.normalized_name,
            symbol.parent_symbol_id,
            symbol.symbol_type,
            symbol.status,
        )
        for symbol in first.symbols
    )
    second_projection = tuple(
        (
            symbol.symbol_id,
            symbol.normalized_name,
            symbol.parent_symbol_id,
            symbol.symbol_type,
            symbol.status,
        )
        for symbol in second.symbols
    )
    assert first_projection == second_projection
