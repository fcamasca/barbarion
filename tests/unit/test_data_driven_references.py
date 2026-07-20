"""Pruebas de referencias Data-Driven."""

from barbarion.config import (
    DataDrivenConfiguration,
    DataDrivenParentColumn,
    DataDrivenReferenceColumn,
)
from barbarion.domain.data_driven import (
    build_configuration_references,
    build_configuration_symbols,
)
from barbarion.application.reverse_engineering import relation_from_reference
from barbarion.domain.models import Confidence
from barbarion.domain.reverse_engineering import (
    ResolutionStatus,
    TechnicalSymbol,
    technical_symbol_id,
)
from barbarion.infrastructure.parsers.data_driven_dml import parse_dml_configurations


def test_build_configuration_references_resolves_configuration_targets() -> None:
    parsed_records = records(
        """
        INSERT INTO APP_CFG.PRICING_RULES (
            RULE_ID, RULE_NAME, NEXT_RULE_ID, PARENT_RULE_ID
        )
        VALUES ('R1', 'Root Rule', NULL, NULL);
        INSERT INTO APP_CFG.PRICING_RULES (
            RULE_ID, RULE_NAME, NEXT_RULE_ID, PARENT_RULE_ID
        )
        VALUES ('R2', 'Child Rule', 'R1', 'R1');
        """
    )
    symbols = build_configuration_symbols(parsed_records, (configuration(),)).symbols

    plan = build_configuration_references(
        parsed_records,
        (configuration(),),
        source_file_id=1,
        source_chunk_id="chunk-1",
    )

    assert plan.diagnostics == ()
    assert len(plan.references) == 2
    by_type = {reference.reference_type: reference for reference in plan.references}
    explicit = by_type["configuration_reference"]
    parent = by_type["parent_of"]
    assert explicit.normalized_target == "pricing_rules.r1"
    assert explicit.technology == "configuration"
    assert explicit.resolution_status == ResolutionStatus.UNRESOLVED
    assert explicit.metadata["column"] == "NEXT_RULE_ID"
    assert parent.normalized_target == "pricing_rules.r1"
    assert parent.metadata["column"] == "PARENT_RULE_ID"

    explicit_relation, explicit_candidates = relation_from_reference(
        explicit,
        symbols,
    ) or (None, ())
    parent_relation, parent_candidates = relation_from_reference(
        parent,
        symbols,
    ) or (None, ())

    assert explicit_relation is not None
    assert explicit_relation.resolution_status == ResolutionStatus.RESOLVED
    assert explicit_relation.relation_type == "references"
    assert explicit_candidates == ()
    assert parent_relation is not None
    assert parent_relation.resolution_status == ResolutionStatus.RESOLVED
    assert parent_relation.relation_type == "parent_of"
    assert parent_candidates == ()


def test_build_configuration_references_marks_dynamic_placeholders() -> None:
    parsed_records = records(
        """
        INSERT INTO APP_CFG.PRICING_RULES (
            RULE_ID, RULE_NAME, NEXT_RULE_ID
        )
        VALUES ('R3', 'Dynamic Rule', '${NEXT_RULE}');
        """
    )

    plan = build_configuration_references(
        parsed_records,
        (configuration(),),
        source_file_id=1,
        source_chunk_id="chunk-1",
    )

    reference = plan.references[0]
    assert reference.resolution_status == ResolutionStatus.DYNAMIC
    assert reference.confidence == Confidence.LOW
    relation, candidates = relation_from_reference(reference, ()) or (None, ())
    assert relation is not None
    assert relation.resolution_status == ResolutionStatus.DYNAMIC
    assert relation.target_key == "pricing_rules.next_rule"
    assert candidates == ()


def test_build_configuration_references_resolves_oracle_targets() -> None:
    parsed_records = records(
        """
        INSERT INTO APP_CFG.PRICING_RULES (
            RULE_ID, RULE_NAME, PROCEDURE_NAME
        )
        VALUES ('R4', 'Procedure Rule', 'PKG_PRICING.APPLY_RULE');
        """
    )
    target = TechnicalSymbol(
        symbol_id=technical_symbol_id(
            normalized_name="pkg_pricing.apply_rule",
            symbol_type="procedure",
            technology="oracle",
            container_name="pkg_pricing",
        ),
        original_name="PKG_PRICING.APPLY_RULE",
        normalized_name="pkg_pricing.apply_rule",
        symbol_type="procedure",
        technology="oracle",
        extraction_method="fixture",
        confidence=Confidence.HIGH,
        container_name="pkg_pricing",
    )

    plan = build_configuration_references(
        parsed_records,
        (configuration(),),
        source_file_id=1,
        source_chunk_id="chunk-1",
    )

    reference = plan.references[0]
    assert reference.reference_type == "calls"
    assert reference.technology == "oracle"
    assert reference.normalized_target == "pkg_pricing.apply_rule"
    relation, candidates = relation_from_reference(reference, (target,)) or (
        None,
        (),
    )
    assert relation is not None
    assert relation.resolution_status == ResolutionStatus.RESOLVED
    assert relation.relation_type == "calls"
    assert relation.target_symbol_id == target.symbol_id
    assert candidates == ()


def test_sequence_column_is_metadata_until_explicit_next_step_reference() -> None:
    parsed_records = records(
        """
        INSERT INTO APP_CFG.PRICING_RULES (
            RULE_ID, RULE_NAME, DISPLAY_ORDER, NEXT_STEP_ID
        )
        VALUES ('S1', 'First Step', 1, 'S2');
        INSERT INTO APP_CFG.PRICING_RULES (
            RULE_ID, RULE_NAME, DISPLAY_ORDER, NEXT_STEP_ID
        )
        VALUES ('S2', 'Second Step', 2, NULL);
        """
    )
    symbols = build_configuration_symbols(parsed_records, (configuration(),)).symbols

    plan = build_configuration_references(
        parsed_records,
        (configuration(),),
        source_file_id=1,
        source_chunk_id="chunk-1",
    )

    assert len(plan.references) == 1
    reference = plan.references[0]
    assert reference.reference_type == "precedes"
    assert reference.normalized_target == "pricing_rules.s2"
    assert reference.metadata["column"] == "NEXT_STEP_ID"
    relation, candidates = relation_from_reference(reference, symbols) or (None, ())
    assert relation is not None
    assert relation.relation_type == "precedes"
    assert relation.resolution_status == ResolutionStatus.RESOLVED
    assert candidates == ()


def test_explicit_reference_resolves_derived_symbol_by_semantic_alias() -> None:
    """Resuelve una columna arbitraria con el indice semantico compartido."""
    variables = alias_target_configuration()
    bindings = alias_source_configuration()
    variable_records = parse_dml_configurations(
        "INSERT INTO APP_CFG.CATALOG_ENTRIES "
        "(ENTRY_KEY, REVISION, VARIABLE_KEY) "
        "VALUES ('ENTRY_ALPHA', 1, 'INPUT_ALPHA');",
        (variables,),
        max_statements_per_file=100,
        max_literal_chars=1000,
    ).records
    binding_records = parse_dml_configurations(
        "INSERT INTO APP_CFG.ALIAS_BINDINGS (BINDING_ID, VARIABLE_KEY) "
        "VALUES ('BINDING_1', 'INPUT_ALPHA');",
        (bindings,),
        max_statements_per_file=100,
        max_literal_chars=1000,
    ).records
    configurations = (variables, bindings)
    symbols = build_configuration_symbols(
        (*variable_records, *binding_records),
        configurations,
    ).symbols
    reference = build_configuration_references(
        binding_records,
        configurations,
        source_file_id=1,
    ).references[0]

    relation, candidates = relation_from_reference(reference, symbols) or (
        None,
        (),
    )

    assert reference.normalized_target == "catalog_entries.input_alpha"
    assert reference.metadata["target_configuration"] == "catalog_entries"
    assert reference.metadata["target_type"] == "configuration_variable"
    assert relation is not None
    assert relation.resolution_status == ResolutionStatus.RESOLVED
    target = next(
        symbol
        for symbol in symbols
        if symbol.symbol_id == relation.target_symbol_id
    )
    assert target.normalized_name == (
        "catalog_entries.entry_alpha.1.configuration_variable.variable_key"
    )
    assert candidates == ()


def configuration() -> DataDrivenConfiguration:
    return DataDrivenConfiguration(
        name="pricing_rules",
        symbol_type="configuration_record",
        tables=("APP_CFG.PRICING_RULES",),
        identity_columns=("RULE_ID",),
        file_patterns=(),
        default_column_order=(),
        name_columns=("RULE_NAME",),
        description_columns=(),
        rule_columns=(),
        formula_columns=(),
        variable_columns=(),
        parameter_columns=(),
        mapping_columns=(),
        reference_columns=(
            DataDrivenReferenceColumn(
                column="NEXT_RULE_ID",
                target_configuration="pricing_rules",
            ),
            DataDrivenReferenceColumn(
                column="NEXT_STEP_ID",
                target_configuration="pricing_rules",
                relation_type="precedes",
            ),
            DataDrivenReferenceColumn(
                column="PROCEDURE_NAME",
                target_technology="oracle",
                target_type="procedure",
            ),
        ),
        parent_columns=(
            DataDrivenParentColumn(
                column="PARENT_RULE_ID",
                target_configuration="pricing_rules",
            ),
        ),
        sequence_columns=("DISPLAY_ORDER",),
        status_columns=(),
        effective_from_columns=(),
        effective_to_columns=(),
        metadata_columns=(),
    )


def alias_target_configuration() -> DataDrivenConfiguration:
    """Declara un catalogo sintetico usado como destino semantico."""
    return DataDrivenConfiguration(
        name="catalog_entries",
        symbol_type="configuration_record",
        tables=("APP_CFG.CATALOG_ENTRIES",),
        identity_columns=("ENTRY_KEY", "REVISION"),
        file_patterns=(),
        default_column_order=(),
        name_columns=(),
        description_columns=(),
        rule_columns=(),
        formula_columns=(),
        variable_columns=("VARIABLE_KEY",),
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


def alias_source_configuration() -> DataDrivenConfiguration:
    """Declara registros sinteticos que referencian aliases del catalogo."""
    return DataDrivenConfiguration(
        name="alias_bindings",
        symbol_type="configuration_record",
        tables=("APP_CFG.ALIAS_BINDINGS",),
        identity_columns=("BINDING_ID",),
        file_patterns=(),
        default_column_order=(),
        name_columns=(),
        description_columns=(),
        rule_columns=(),
        formula_columns=(),
        variable_columns=(),
        parameter_columns=(),
        mapping_columns=(),
        reference_columns=(
            DataDrivenReferenceColumn(
                column="VARIABLE_KEY",
                target_configuration="catalog_entries",
                target_type="configuration_variable",
            ),
        ),
        parent_columns=(),
        sequence_columns=(),
        status_columns=(),
        effective_from_columns=(),
        effective_to_columns=(),
        metadata_columns=(),
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
