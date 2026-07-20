"""Pruebas de tokens estaticos en formulas Data-Driven."""

from dataclasses import replace

from barbarion.config import DataDrivenConfiguration
from barbarion.domain.data_driven import (
    build_configuration_references,
    build_configuration_symbols,
)
from barbarion.application.reverse_engineering import relation_from_reference
from barbarion.domain.models import Confidence
from barbarion.domain.reverse_engineering import (
    EvidenceClassification,
    ResolutionStatus,
    SymbolStatus,
    TechnicalSymbol,
    technical_symbol_id,
)
from barbarion.infrastructure.parsers.data_driven_dml import parse_dml_configurations


TOKEN_PATTERNS = (
    r"\{([A-Z_][A-Z0-9_]*)\}",
    r":([A-Z_][A-Z0-9_]*)",
    r"@([A-Z_][A-Z0-9_]*)@",
    r"\[@([A-Z_][A-Z0-9_]*)\]",
    r"\[%([A-Z_][A-Z0-9_]*)\]",
)


def test_formula_tokens_resolve_declared_variables_and_parameters() -> None:
    parsed_records = records(
        """
        INSERT INTO APP_CFG.FORMULAS (
            RULE_ID, RULE_NAME, FORMULA, VARIABLE_NAME, PARAMETER_NAME
        )
        VALUES ('R1', 'Tax Formula', '{AMOUNT} + :RATE', 'AMOUNT', 'RATE');
        """
    )
    symbols = build_configuration_symbols(parsed_records, (configuration(),)).symbols

    plan = build_configuration_references(
        parsed_records,
        (configuration(),),
        source_file_id=1,
        source_chunk_id="chunk-1",
        token_patterns=TOKEN_PATTERNS,
    )

    token_references = {
        reference.raw_text: reference
        for reference in plan.references
        if reference.reference_type == "configuration_token"
    }
    assert set(token_references) == {"AMOUNT", "RATE"}
    assert token_references["AMOUNT"].metadata["token_kind"] == "variable"
    assert token_references["RATE"].metadata["token_kind"] == "parameter"
    for reference in token_references.values():
        relation, candidates = relation_from_reference(reference, symbols) or (
            None,
            (),
        )
        assert relation is not None
        assert relation.resolution_status == ResolutionStatus.RESOLVED
        assert relation.relation_type == "uses"
        assert candidates == ()


def test_formula_function_candidate_resolves_without_evaluating_formula() -> None:
    parsed_records = records(
        """
        INSERT INTO APP_CFG.FORMULAS (
            RULE_ID, RULE_NAME, FORMULA
        )
        VALUES ('R2', 'Function Formula', '{AMOUNT} + TAX_RATE()');
        """
    )
    target = TechnicalSymbol(
        symbol_id=technical_symbol_id(
            normalized_name="tax_rate",
            symbol_type="function",
            technology="oracle",
        ),
        original_name="TAX_RATE",
        normalized_name="tax_rate",
        symbol_type="function",
        technology="oracle",
        extraction_method="fixture",
        confidence=Confidence.HIGH,
    )

    plan = build_configuration_references(
        parsed_records,
        (configuration(),),
        source_file_id=1,
        source_chunk_id="chunk-1",
        token_patterns=TOKEN_PATTERNS,
    )

    function_reference = next(
        reference
        for reference in plan.references
        if reference.metadata["token_kind"] == "function_candidate"
    )
    assert function_reference.raw_text == "TAX_RATE"
    assert function_reference.reference_type == "function_candidate"
    assert function_reference.technology == "unknown"
    assert function_reference.metadata["formula_text"] == "'{AMOUNT} + TAX_RATE()'"
    relation, candidates = relation_from_reference(function_reference, (target,)) or (
        None,
        (),
    )
    assert relation is not None
    assert relation.resolution_status == ResolutionStatus.RESOLVED
    assert relation.relation_type == "calls"
    assert candidates == ()


def test_formula_function_candidate_can_be_ambiguous_or_unresolved() -> None:
    parsed_records = records(
        """
        INSERT INTO APP_CFG.FORMULAS (
            RULE_ID, RULE_NAME, FORMULA
        )
        VALUES ('R4', 'Ambiguous Formula', 'CALCULATE_AMOUNT() + MISSING_FN()');
        """
    )
    first = function_symbol("CALCULATE_AMOUNT", technology="oracle")
    second = function_symbol("CALCULATE_AMOUNT", technology="powerbuilder")

    plan = build_configuration_references(
        parsed_records,
        (configuration(),),
        source_file_id=1,
        source_chunk_id="chunk-1",
        token_patterns=TOKEN_PATTERNS,
    )

    references = {reference.raw_text: reference for reference in plan.references}
    ambiguous_relation, candidates = relation_from_reference(
        references["CALCULATE_AMOUNT"],
        (first, second),
    ) or (None, ())
    assert ambiguous_relation is not None
    assert ambiguous_relation.resolution_status == ResolutionStatus.AMBIGUOUS
    assert ambiguous_relation.classification == EvidenceClassification.TO_CONFIRM
    assert {
        candidate.candidate_symbol_id
        for candidate in candidates
    } == {first.symbol_id, second.symbol_id}
    assert references["MISSING_FN"].resolution_status == ResolutionStatus.UNRESOLVED
    assert relation_from_reference(references["MISSING_FN"], ()) is None


def test_formula_builtin_function_candidate_is_external_and_deduplicated() -> None:
    parsed_records = records(
        """
        INSERT INTO APP_CFG.FORMULAS (
            RULE_ID, RULE_NAME, FORMULA
        )
        VALUES ('R5', 'Builtin Formula', 'ROUND(AMOUNT) + ROUND(TAX)');
        """
    )

    plan = build_configuration_references(
        parsed_records,
        (configuration(),),
        source_file_id=1,
        source_chunk_id="chunk-1",
        token_patterns=TOKEN_PATTERNS,
    )

    function_references = [
        reference
        for reference in plan.references
        if reference.reference_type == "function_candidate"
    ]
    assert [reference.raw_text for reference in function_references] == ["ROUND"]
    relation, candidates = relation_from_reference(function_references[0], ()) or (
        None,
        (),
    )
    assert relation is not None
    assert relation.resolution_status == ResolutionStatus.EXTERNAL
    assert relation.target_key == "round"
    assert candidates == ()


def test_incomplete_or_concatenated_formula_tokens_are_dynamic() -> None:
    parsed_records = records(
        """
        INSERT INTO APP_CFG.FORMULAS (
            RULE_ID, RULE_NAME, FORMULA, VARIABLE_NAME
        )
        VALUES ('R3', 'Dynamic Formula', '{AMOUNT' || '_X', 'AMOUNT');
        """
    )

    plan = build_configuration_references(
        parsed_records,
        (configuration(),),
        source_file_id=1,
        source_chunk_id="chunk-1",
        token_patterns=(r"\{([A-Z_][A-Z0-9_]*)",),
    )

    reference = plan.references[0]
    assert reference.raw_text == "AMOUNT"
    assert reference.resolution_status == ResolutionStatus.DYNAMIC
    assert reference.confidence == Confidence.LOW
    assert reference.metadata["formula_text"] == "'{AMOUNT' || '_X'"
    relation, candidates = relation_from_reference(reference, ()) or (None, ())
    assert relation is not None
    assert relation.resolution_status == ResolutionStatus.DYNAMIC
    assert relation.target_key == reference.normalized_target
    assert candidates == ()


def test_bracket_variable_token_resolves_by_configuration_value_alias() -> None:
    """Resuelve `[@...]` por alias sin alterar la identidad estructural."""
    declared = semantic_configuration()
    parsed = parse_dml_configurations(
        "INSERT INTO APP_CFG.CATALOG_ENTRIES "
        "(ENTRY_KEY, REVISION, VARIABLE_KEY, EXPRESSION_TEXT) "
        "VALUES ('INPUT_ALPHA', 1, 'INPUT_ALPHA', "
        "'ROUND([@INPUT_ALPHA], 2)');",
        (declared,),
        max_statements_per_file=100,
        max_literal_chars=1000,
    )
    assert parsed.diagnostics == ()
    symbols = build_configuration_symbols(parsed.records, (declared,)).symbols
    references = build_configuration_references(
        parsed.records,
        (declared,),
        source_file_id=1,
        token_patterns=TOKEN_PATTERNS,
    ).references

    reference = next(
        item
        for item in references
        if item.reference_type == "configuration_token"
    )
    relation, candidates = relation_from_reference(reference, symbols) or (
        None,
        (),
    )

    assert reference.normalized_target == "catalog_entries.input_alpha"
    assert reference.metadata["token_kind"] == "variable"
    assert relation is not None
    assert relation.resolution_status == ResolutionStatus.RESOLVED
    target = next(
        symbol
        for symbol in symbols
        if symbol.symbol_id == relation.target_symbol_id
    )
    assert target.normalized_name == (
        "catalog_entries.input_alpha.1.configuration_variable.variable_key"
    )
    assert candidates == ()


def test_bracket_parameter_token_does_not_resolve_to_variable_alias() -> None:
    """Impide que `[%...]` enlace una variable con el mismo valor."""
    declared = semantic_configuration()
    parsed = parse_dml_configurations(
        "INSERT INTO APP_CFG.CATALOG_ENTRIES "
        "(ENTRY_KEY, REVISION, VARIABLE_KEY, EXPRESSION_TEXT) "
        "VALUES ('INPUT_ALPHA', 1, 'INPUT_ALPHA', "
        "'ROUND([%INPUT_ALPHA], 2)');",
        (declared,),
        max_statements_per_file=100,
        max_literal_chars=1000,
    )
    symbols = build_configuration_symbols(parsed.records, (declared,)).symbols
    reference = next(
        item
        for item in build_configuration_references(
            parsed.records,
            (declared,),
            source_file_id=1,
            token_patterns=TOKEN_PATTERNS,
        ).references
        if item.reference_type == "configuration_token"
    )

    assert reference.metadata["token_kind"] == "parameter"
    assert relation_from_reference(reference, symbols) is None


def test_bracket_parameter_token_resolves_only_declared_parameter() -> None:
    """Resuelve `[%...]` cuando existe un parametro compatible declarado."""
    declared = semantic_configuration(parameter_columns=("PARAMETER_KEY",))
    parsed = parse_dml_configurations(
        "INSERT INTO APP_CFG.CATALOG_ENTRIES "
        "(ENTRY_KEY, REVISION, VARIABLE_KEY, PARAMETER_KEY, EXPRESSION_TEXT) "
        "VALUES ('INPUT_BETA', 1, 'INPUT_BETA', 'INPUT_ALPHA', "
        "'[%INPUT_ALPHA]');",
        (declared,),
        max_statements_per_file=100,
        max_literal_chars=1000,
    )
    symbols = build_configuration_symbols(parsed.records, (declared,)).symbols
    reference = next(
        item
        for item in build_configuration_references(
            parsed.records,
            (declared,),
            source_file_id=1,
            token_patterns=TOKEN_PATTERNS,
        ).references
        if item.reference_type == "configuration_token"
    )

    relation, _candidates = relation_from_reference(reference, symbols) or (
        None,
        (),
    )
    assert relation is not None
    target = next(
        symbol
        for symbol in symbols
        if symbol.symbol_id == relation.target_symbol_id
    )
    assert target.symbol_type == "configuration_parameter"


def test_configuration_alias_is_ambiguous_only_between_active_matches() -> None:
    """Aplica ambiguedad conservadora e ignora candidatos stale."""
    declared = semantic_configuration()
    parsed = parse_dml_configurations(
        "INSERT INTO APP_CFG.CATALOG_ENTRIES "
        "(ENTRY_KEY, REVISION, VARIABLE_KEY, EXPRESSION_TEXT) "
        "VALUES ('INPUT_ALPHA', 1, 'INPUT_ALPHA', '[@INPUT_ALPHA]');\n"
        "INSERT INTO APP_CFG.CATALOG_ENTRIES "
        "(ENTRY_KEY, REVISION, VARIABLE_KEY, EXPRESSION_TEXT) "
        "VALUES ('INPUT_ALPHA', 2, 'INPUT_ALPHA', NULL);",
        (declared,),
        max_statements_per_file=100,
        max_literal_chars=1000,
    )
    symbols = build_configuration_symbols(parsed.records, (declared,)).symbols
    reference = next(
        item
        for item in build_configuration_references(
            parsed.records,
            (declared,),
            source_file_id=1,
            token_patterns=TOKEN_PATTERNS,
        ).references
        if item.reference_type == "configuration_token"
    )

    ambiguous, candidates = relation_from_reference(reference, symbols) or (
        None,
        (),
    )
    assert ambiguous is not None
    assert ambiguous.resolution_status == ResolutionStatus.AMBIGUOUS
    assert len(candidates) == 2

    variables = [
        symbol
        for symbol in symbols
        if symbol.symbol_type == "configuration_variable"
    ]
    catalog = tuple(
        replace(symbol, status=SymbolStatus.STALE)
        if symbol.symbol_id == variables[1].symbol_id
        else symbol
        for symbol in symbols
    )
    resolved, candidates = relation_from_reference(reference, catalog) or (
        None,
        (),
    )
    assert resolved is not None
    assert resolved.resolution_status == ResolutionStatus.RESOLVED
    assert resolved.target_symbol_id == variables[0].symbol_id
    assert candidates == ()


def configuration() -> DataDrivenConfiguration:
    return DataDrivenConfiguration(
        name="formulas",
        symbol_type="configuration_record",
        tables=("APP_CFG.FORMULAS",),
        identity_columns=("RULE_ID",),
        file_patterns=(),
        default_column_order=(),
        name_columns=("RULE_NAME",),
        description_columns=(),
        rule_columns=(),
        formula_columns=("FORMULA",),
        variable_columns=("VARIABLE_NAME",),
        parameter_columns=("PARAMETER_NAME",),
        mapping_columns=(),
        reference_columns=(),
        parent_columns=(),
        sequence_columns=(),
        status_columns=(),
        effective_from_columns=(),
        effective_to_columns=(),
        metadata_columns=(),
    )


def semantic_configuration(
    *,
    parameter_columns: tuple[str, ...] = (),
) -> DataDrivenConfiguration:
    """Declara un catalogo sintetico de variables y expresiones.

    Args:
        parameter_columns: Columnas que declaran parametros compatibles.

    Returns:
        Configuracion Data-Driven usada por los casos de aliases.
    """
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
        formula_columns=("EXPRESSION_TEXT",),
        variable_columns=("VARIABLE_KEY",),
        parameter_columns=parameter_columns,
        mapping_columns=(),
        reference_columns=(),
        parent_columns=(),
        sequence_columns=(),
        status_columns=(),
        effective_from_columns=(),
        effective_to_columns=(),
        metadata_columns=(),
    )


def function_symbol(name: str, *, technology: str) -> TechnicalSymbol:
    normalized_name = name.lower()
    return TechnicalSymbol(
        symbol_id=technical_symbol_id(
            normalized_name=normalized_name,
            symbol_type="function",
            technology=technology,
        ),
        original_name=name,
        normalized_name=normalized_name,
        symbol_type="function",
        technology=technology,
        extraction_method="fixture",
        confidence=Confidence.HIGH,
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
