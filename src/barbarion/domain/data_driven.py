"""Modelos y constructores puros para configuraciones Data-Driven."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from barbarion.config import DataDrivenConfiguration
from barbarion.domain.models import Confidence
from barbarion.domain.reverse_engineering import (
    ResolutionStatus,
    SymbolStatus,
    TechnicalReference,
    TechnicalSymbol,
    normalize_symbol_name,
    technical_reference_id,
    technical_symbol_id,
)


@dataclass(frozen=True, slots=True)
class ConfigurationSymbolDiagnostic:
    """Advertencia recuperable al construir simbolos Data-Driven."""

    record_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class ConfigurationSymbolPlan:
    """Simbolos Data-Driven listos para persistencia posterior."""

    symbols: tuple[TechnicalSymbol, ...]
    diagnostics: tuple[ConfigurationSymbolDiagnostic, ...] = ()


@dataclass(frozen=True, slots=True)
class ConfigurationReferencePlan:
    """Referencias Data-Driven listas para persistencia posterior."""

    references: tuple[TechnicalReference, ...]
    diagnostics: tuple[ConfigurationSymbolDiagnostic, ...] = ()


def build_configuration_symbols(
    records: tuple[Any, ...],
    configurations: tuple[DataDrivenConfiguration, ...],
) -> ConfigurationSymbolPlan:
    """Construye simbolos tecnicos en memoria desde registros DML canonicos."""
    symbols: list[TechnicalSymbol] = []
    diagnostics: list[ConfigurationSymbolDiagnostic] = []
    seen_record_ids: set[str] = set()

    for record in records:
        configuration = _configuration_by_name(
            configurations,
            record.configuration_name,
        )
        if configuration is None:
            diagnostics.append(
                ConfigurationSymbolDiagnostic(
                    record_id=record.record_id,
                    reason="undeclared_configuration",
                )
            )
            continue
        if not record.identity_values:
            diagnostics.append(
                ConfigurationSymbolDiagnostic(
                    record_id=record.record_id,
                    reason="missing_identity",
                )
            )
            continue
        if record.record_id in seen_record_ids:
            diagnostics.append(
                ConfigurationSymbolDiagnostic(
                    record_id=record.record_id,
                    reason="duplicate_record",
                )
            )
        seen_record_ids.add(record.record_id)

        entity = _entity_symbol(configuration, record)
        record_symbol = _record_symbol(configuration, record, entity.symbol_id)
        symbols.append(entity)
        symbols.append(record_symbol)
        symbols.extend(_derived_symbols(configuration, record, record_symbol))

    return ConfigurationSymbolPlan(
        symbols=_deduplicate_symbols(tuple(symbols)),
        diagnostics=tuple(diagnostics),
    )


def build_configuration_references(
    records: tuple[Any, ...],
    configurations: tuple[DataDrivenConfiguration, ...],
    *,
    source_file_id: int,
    source_chunk_id: str | None = None,
    token_patterns: tuple[str, ...] = (),
) -> ConfigurationReferencePlan:
    """Construye referencias tecnicas desde columnas Data-Driven declaradas."""
    references: list[TechnicalReference] = []
    diagnostics: list[ConfigurationSymbolDiagnostic] = []
    for record in records:
        configuration = _configuration_by_name(
            configurations,
            record.configuration_name,
        )
        if configuration is None:
            diagnostics.append(
                ConfigurationSymbolDiagnostic(
                    record_id=record.record_id,
                    reason="undeclared_configuration",
                )
            )
            continue
        if not record.identity_values:
            diagnostics.append(
                ConfigurationSymbolDiagnostic(
                    record_id=record.record_id,
                    reason="missing_identity",
                )
            )
            continue
        source_symbol = _record_symbol(
            configuration,
            record,
            _entity_symbol(configuration, record).symbol_id,
        )
        values_by_column = {value.column: value for value in record.values}
        for column in configuration.reference_columns:
            value = values_by_column.get(_normalize_identifier(column.column))
            if value is None or value.value_type == "null":
                continue
            references.append(
                _reference_from_declared_column(
                    record=record,
                    value=value,
                    source_symbol=source_symbol,
                    source_file_id=source_file_id,
                    source_chunk_id=source_chunk_id,
                    column=column.column,
                    target_configuration=column.target_configuration,
                    target_technology=column.target_technology,
                    target_type=column.target_type,
                    reference_type=_reference_type(
                        relation_type=column.relation_type,
                        target_configuration=column.target_configuration,
                        target_type=column.target_type,
                    ),
                )
            )
        for column in configuration.parent_columns:
            value = values_by_column.get(_normalize_identifier(column.column))
            if value is None or value.value_type == "null":
                continue
            references.append(
                _reference_from_declared_column(
                    record=record,
                    value=value,
                    source_symbol=source_symbol,
                    source_file_id=source_file_id,
                    source_chunk_id=source_chunk_id,
                    column=column.column,
                    target_configuration=column.target_configuration,
                    target_technology="configuration",
                    target_type="configuration_record",
                    reference_type="parent_of",
                )
            )
        references.extend(
            _formula_token_references(
                configuration=configuration,
                record=record,
                source_symbol=source_symbol,
                source_file_id=source_file_id,
                source_chunk_id=source_chunk_id,
                token_patterns=token_patterns,
            )
        )
    return ConfigurationReferencePlan(
        references=_deduplicate_references(tuple(references)),
        diagnostics=tuple(diagnostics),
    )


def _entity_symbol(
    configuration: DataDrivenConfiguration,
    record: Any,
) -> TechnicalSymbol:
    normalized_name = normalize_symbol_name(configuration.name)
    return TechnicalSymbol(
        symbol_id=technical_symbol_id(
            normalized_name=normalized_name,
            symbol_type="configuration_entity",
            technology="configuration",
        ),
        original_name=configuration.name,
        normalized_name=normalized_name,
        symbol_type="configuration_entity",
        technology="configuration",
        extraction_method="data_driven_dml",
        confidence=Confidence.HIGH,
        start_line=record.start_line,
        end_line=record.end_line,
        metadata={
            "configuration_name": configuration.name,
            "table_name": record.table,
            "normalized_table_name": _normalize_table_name(record.table),
            "declared_columns": tuple(configuration.identity_columns),
        },
    )


def _record_symbol(
    configuration: DataDrivenConfiguration,
    record: Any,
    parent_symbol_id: str,
) -> TechnicalSymbol:
    identity = _identity_mapping(record)
    normalized_name = _record_normalized_name(configuration.name, record)
    original_name = _record_original_name(configuration, record, identity)
    status = _record_status(configuration, record)
    metadata = _record_metadata(configuration, record)
    return TechnicalSymbol(
        symbol_id=technical_symbol_id(
            normalized_name=normalized_name,
            symbol_type="configuration_record",
            technology="configuration",
            container_name=configuration.name,
        ),
        original_name=original_name,
        normalized_name=normalized_name,
        symbol_type="configuration_record",
        technology="configuration",
        extraction_method="data_driven_dml",
        confidence=Confidence.MEDIUM if record.partial else Confidence.HIGH,
        parent_symbol_id=parent_symbol_id,
        container_name=normalize_symbol_name(configuration.name),
        signature=metadata["source_hash"],
        start_line=record.start_line,
        end_line=record.end_line,
        status=status,
        metadata=metadata,
    )


def _derived_symbols(
    configuration: DataDrivenConfiguration,
    record: Any,
    parent: TechnicalSymbol,
) -> tuple[TechnicalSymbol, ...]:
    specs = (
        ("configuration_rule", configuration.rule_columns),
        ("configuration_formula", configuration.formula_columns),
        ("configuration_variable", configuration.variable_columns),
        ("configuration_parameter", configuration.parameter_columns),
        ("configuration_mapping", configuration.mapping_columns),
        ("configuration_step", configuration.sequence_columns),
    )
    symbols: list[TechnicalSymbol] = []
    values_by_column = {value.column: value for value in record.values}
    for symbol_type, columns in specs:
        for column in columns:
            value = values_by_column.get(_normalize_identifier(column))
            if value is None or value.value_type == "null":
                continue
            original_name = _display_raw(value.raw)
            normalized_name = normalize_symbol_name(
                f"{parent.normalized_name}.{symbol_type}.{column}.{original_name}"
            )
            metadata = {
                **_record_metadata(configuration, record),
                "column": column,
                "value": value.raw,
                "value_type": value.value_type,
            }
            symbols.append(
                TechnicalSymbol(
                    symbol_id=technical_symbol_id(
                        normalized_name=normalized_name,
                        symbol_type=symbol_type,
                        technology="configuration",
                        container_name=parent.normalized_name,
                    ),
                    original_name=original_name,
                    normalized_name=normalized_name,
                    symbol_type=symbol_type,
                    technology="configuration",
                    extraction_method="data_driven_dml",
                    confidence=Confidence.MEDIUM,
                    parent_symbol_id=parent.symbol_id,
                    container_name=parent.normalized_name,
                    signature=metadata["source_hash"],
                    start_line=record.start_line,
                    end_line=record.end_line,
                    status=parent.status,
                    metadata=metadata,
                )
            )
    return tuple(symbols)


def _record_metadata(
    configuration: DataDrivenConfiguration,
    record: Any,
) -> dict[str, Any]:
    identity = _identity_mapping(record)
    values = {value.column: value.raw for value in record.values}
    metadata = {
        "configuration_name": configuration.name,
        "table_name": record.table,
        "normalized_table_name": _normalize_table_name(record.table),
        "operation": record.operation,
        "statement_ordinal": record.statement_ordinal,
        "identity": identity,
        "display_values": _display_values(configuration, record),
        "declared_columns": _declared_columns(configuration),
        "source_hash": _source_hash(record),
        "partial": record.partial,
        "values": {
            column: values[column]
            for column in _metadata_columns(configuration, record)
            if column in values
        },
    }
    return metadata


def _record_status(
    configuration: DataDrivenConfiguration,
    record: Any,
) -> SymbolStatus:
    values = {value.column: _unquote(value.raw).lower() for value in record.values}
    for status_column in configuration.status_columns:
        column = _normalize_identifier(status_column.column)
        value = values.get(column)
        if value is None:
            continue
        active_values = {
            _normalize_status(item)
            for item in status_column.active_values
        }
        inactive_values = {
            _normalize_status(item) for item in status_column.inactive_values
        }
        if value in active_values:
            return SymbolStatus.ACTIVE
        if value in inactive_values:
            return SymbolStatus.STALE
    return SymbolStatus.ACTIVE


def _record_original_name(
    configuration: DataDrivenConfiguration,
    record: Any,
    identity: dict[str, str],
) -> str:
    values = {value.column: value.raw for value in record.values}
    for column in configuration.name_columns:
        value = values.get(_normalize_identifier(column))
        if value is not None:
            return _display_raw(value)
    return ".".join(_display_raw(value) for value in identity.values())


def _record_normalized_name(configuration_name: str, record: Any) -> str:
    identity_values = ".".join(
        _safe_name_part(_display_raw(value.raw)) for value in record.identity_values
    )
    return normalize_symbol_name(f"{configuration_name}.{identity_values}")


def _identity_mapping(record: Any) -> dict[str, str]:
    return {
        value.column: value.raw
        for value in sorted(record.identity_values, key=lambda item: item.column)
    }


def _display_values(
    configuration: DataDrivenConfiguration,
    record: Any,
) -> dict[str, str]:
    values = {value.column: value.raw for value in record.values}
    return {
        _normalize_identifier(column): values[_normalize_identifier(column)]
        for column in configuration.name_columns
        if _normalize_identifier(column) in values
    }


def _declared_columns(configuration: DataDrivenConfiguration) -> tuple[str, ...]:
    columns: list[str] = []
    for group in (
        configuration.identity_columns,
        configuration.default_column_order,
        configuration.name_columns,
        configuration.description_columns,
        configuration.rule_columns,
        configuration.formula_columns,
        configuration.variable_columns,
        configuration.parameter_columns,
        configuration.mapping_columns,
        configuration.sequence_columns,
        configuration.effective_from_columns,
        configuration.effective_to_columns,
        configuration.metadata_columns,
    ):
        columns.extend(_normalize_identifier(column) for column in group)
    for item in configuration.status_columns:
        columns.append(_normalize_identifier(item.column))
    return tuple(dict.fromkeys(columns))


def _metadata_columns(
    configuration: DataDrivenConfiguration,
    record: Any,
) -> tuple[str, ...]:
    declared = set(_declared_columns(configuration))
    return tuple(value.column for value in record.values if value.column in declared)


def _reference_from_declared_column(
    *,
    record: Any,
    value: Any,
    source_symbol: TechnicalSymbol,
    source_file_id: int,
    source_chunk_id: str | None,
    column: str,
    target_configuration: str | None,
    target_technology: str | None,
    target_type: str | None,
    reference_type: str,
) -> TechnicalReference:
    raw_text = value.raw
    normalized_target = _reference_target(
        raw_text,
        target_configuration=target_configuration,
    )
    resolution_status = (
        ResolutionStatus.DYNAMIC
        if _is_dynamic_reference_value(raw_text)
        else ResolutionStatus.UNRESOLVED
    )
    reference_id = technical_reference_id(
        source_file_id=source_file_id,
        raw_text=raw_text,
        normalized_target=normalized_target,
        reference_type=reference_type,
        start_line=record.start_line,
        end_line=record.end_line,
    )
    return TechnicalReference(
        reference_id=reference_id,
        source_file_id=source_file_id,
        source_symbol_id=source_symbol.symbol_id,
        source_chunk_id=source_chunk_id,
        raw_text=raw_text,
        normalized_target=normalized_target,
        reference_type=reference_type,
        technology=target_technology or "configuration",
        detection_method="data_driven_dml",
        confidence=Confidence.LOW if resolution_status == ResolutionStatus.DYNAMIC else Confidence.HIGH,
        resolution_status=resolution_status,
        start_line=record.start_line,
        end_line=record.end_line,
        metadata={
            "configuration_name": record.configuration_name,
            "table_name": record.table,
            "column": column,
            "target_configuration": target_configuration,
            "target_technology": target_technology or "configuration",
            "target_type": target_type,
            "statement_ordinal": record.statement_ordinal,
            "source_record_id": record.record_id,
            "value_type": value.value_type,
        },
    )


def _formula_token_references(
    *,
    configuration: DataDrivenConfiguration,
    record: Any,
    source_symbol: TechnicalSymbol,
    source_file_id: int,
    source_chunk_id: str | None,
    token_patterns: tuple[str, ...],
) -> tuple[TechnicalReference, ...]:
    references: list[TechnicalReference] = []
    values_by_column = {value.column: value for value in record.values}
    token_targets = _token_targets(configuration, record)
    formula_columns = {_normalize_identifier(column) for column in configuration.formula_columns}
    scanned_columns = tuple(
        dict.fromkeys(
            _normalize_identifier(column)
            for column in (*configuration.formula_columns, *configuration.rule_columns)
        )
    )
    for column in scanned_columns:
        value = values_by_column.get(column)
        if value is None or value.value_type == "null":
            continue
        expression = _display_raw(value.raw)
        dynamic = _is_dynamic_formula_expression(expression)
        seen_tokens: set[str] = set()
        for token in _tokens_from_patterns(expression, token_patterns):
            normalized_token = _safe_name_part(token)
            if normalized_token.lower() in seen_tokens:
                continue
            seen_tokens.add(normalized_token.lower())
            target = token_targets.get(normalized_token.lower())
            if target is None:
                references.append(
                    _formula_reference(
                        record=record,
                        value=value,
                        source_symbol=source_symbol,
                        source_file_id=source_file_id,
                        source_chunk_id=source_chunk_id,
                        column=column,
                        raw_text=token,
                        normalized_target=normalize_symbol_name(token),
                        reference_type="configuration_token",
                        resolution_status=ResolutionStatus.DYNAMIC if dynamic else ResolutionStatus.UNRESOLVED,
                        confidence=Confidence.LOW if dynamic else Confidence.MEDIUM,
                        metadata={"token_kind": "unknown"},
                    )
                )
                continue
            references.append(
                _formula_reference(
                    record=record,
                    value=value,
                    source_symbol=source_symbol,
                    source_file_id=source_file_id,
                    source_chunk_id=source_chunk_id,
                    column=column,
                    raw_text=token,
                    normalized_target=target[1],
                    reference_type="configuration_token",
                    resolution_status=ResolutionStatus.DYNAMIC if dynamic else ResolutionStatus.UNRESOLVED,
                    confidence=Confidence.LOW if dynamic else Confidence.HIGH,
                    metadata={"token_kind": target[0]},
                )
            )
        if column in formula_columns:
            seen_functions: set[str] = set()
            for function_name in _function_candidates(expression):
                normalized_function = normalize_symbol_name(function_name)
                if normalized_function in seen_functions:
                    continue
                seen_functions.add(normalized_function)
                metadata = {"token_kind": "function_candidate"}
                if _is_external_formula_function(function_name):
                    metadata["scope"] = "external"
                references.append(
                    _formula_reference(
                        record=record,
                        value=value,
                        source_symbol=source_symbol,
                        source_file_id=source_file_id,
                        source_chunk_id=source_chunk_id,
                        column=column,
                        raw_text=function_name,
                        normalized_target=normalized_function,
                        reference_type="function_candidate",
                        target_technology="unknown",
                        resolution_status=ResolutionStatus.DYNAMIC if dynamic else ResolutionStatus.UNRESOLVED,
                        confidence=Confidence.LOW if dynamic else Confidence.MEDIUM,
                        metadata=metadata,
                    )
                )
    return tuple(references)


def _formula_reference(
    *,
    record: Any,
    value: Any,
    source_symbol: TechnicalSymbol,
    source_file_id: int,
    source_chunk_id: str | None,
    column: str,
    raw_text: str,
    normalized_target: str,
    reference_type: str,
    resolution_status: ResolutionStatus,
    confidence: Confidence,
    metadata: dict[str, Any],
    target_technology: str = "configuration",
) -> TechnicalReference:
    reference_id = technical_reference_id(
        source_file_id=source_file_id,
        raw_text=raw_text,
        normalized_target=normalized_target,
        reference_type=reference_type,
        start_line=record.start_line,
        end_line=record.end_line,
    )
    return TechnicalReference(
        reference_id=reference_id,
        source_file_id=source_file_id,
        source_symbol_id=source_symbol.symbol_id,
        source_chunk_id=source_chunk_id,
        raw_text=raw_text,
        normalized_target=normalized_target,
        reference_type=reference_type,
        technology=target_technology,
        detection_method="data_driven_formula",
        confidence=confidence,
        resolution_status=resolution_status,
        start_line=record.start_line,
        end_line=record.end_line,
        metadata={
            **metadata,
            "configuration_name": record.configuration_name,
            "table_name": record.table,
            "column": column,
            "statement_ordinal": record.statement_ordinal,
            "source_record_id": record.record_id,
            "formula_text": value.raw,
            "value_type": value.value_type,
        },
    )


def _token_targets(
    configuration: DataDrivenConfiguration,
    record: Any,
) -> dict[str, tuple[str, str]]:
    values_by_column = {value.column: value for value in record.values}
    targets: dict[str, tuple[str, str]] = {}
    record_name = _record_normalized_name(configuration.name, record)
    for kind, symbol_type, columns in (
        ("variable", "configuration_variable", configuration.variable_columns),
        ("parameter", "configuration_parameter", configuration.parameter_columns),
    ):
        for column in columns:
            value = values_by_column.get(_normalize_identifier(column))
            if value is None or value.value_type == "null":
                continue
            display = _display_raw(value.raw)
            token = _safe_name_part(display).lower()
            normalized_name = normalize_symbol_name(
                f"{record_name}.{symbol_type}.{column}.{display}"
            )
            targets[token] = (kind, normalized_name)
    return targets


def _tokens_from_patterns(
    expression: str,
    token_patterns: tuple[str, ...],
) -> tuple[str, ...]:
    tokens: list[str] = []
    for pattern in token_patterns:
        regex = re.compile(pattern)
        for match in regex.finditer(expression):
            value = next(
                (
                    group
                    for group in match.groups()
                    if isinstance(group, str) and group.strip()
                ),
                match.group(0),
            )
            tokens.append(value.strip())
    return tuple(tokens)


def _function_candidates(expression: str) -> tuple[str, ...]:
    candidates = re.findall(r"\b([A-Za-z_][A-Za-z0-9_$#]*)\s*\(", expression)
    ignored = {"case"}
    return tuple(dict.fromkeys(candidate for candidate in candidates if candidate.lower() not in ignored))


def _is_external_formula_function(name: str) -> bool:
    return name.lower() in {
        "abs",
        "ceil",
        "coalesce",
        "decode",
        "floor",
        "greatest",
        "least",
        "lower",
        "nvl",
        "nullif",
        "power",
        "round",
        "substr",
        "to_char",
        "to_date",
        "trunc",
        "upper",
    }


def _is_dynamic_formula_expression(expression: str) -> bool:
    return (
        "||" in expression
        or expression.count("(") != expression.count(")")
        or expression.count("{") != expression.count("}")
    )


def _reference_target(
    raw_text: str,
    *,
    target_configuration: str | None,
) -> str:
    display = _display_reference_value(raw_text)
    if target_configuration is None:
        return normalize_symbol_name(display)
    return normalize_symbol_name(f"{target_configuration}.{_safe_name_part(display)}")


def _reference_type(
    *,
    relation_type: str | None = None,
    target_configuration: str | None,
    target_type: str | None,
) -> str:
    if relation_type == "precedes":
        return "precedes"
    if relation_type == "parent_of":
        return "parent_of"
    if relation_type == "calls":
        return "calls"
    if relation_type == "uses":
        return "uses"
    if target_configuration is not None:
        return "configuration_reference"
    if target_type is None:
        return "uses"
    normalized = _normalize_identifier(target_type)
    if normalized in {"procedure", "function", "event", "function_object"}:
        return "calls"
    if normalized in {"table", "view", "datawindow"}:
        return "table"
    return normalized


def _is_dynamic_reference_value(raw_text: str) -> bool:
    value = _display_raw(raw_text)
    return (
        "||" in value
        or "${" in value
        or "{" in value
        or "}" in value
        or value.startswith(":")
        or value.startswith("&")
    )


def _display_reference_value(raw_text: str) -> str:
    value = _display_raw(raw_text)
    if value.startswith("${") and value.endswith("}"):
        return value[2:-1]
    if value.startswith(":") or value.startswith("&"):
        return value[1:]
    return value


def _deduplicate_references(
    references: tuple[TechnicalReference, ...],
) -> tuple[TechnicalReference, ...]:
    by_id: dict[str, TechnicalReference] = {}
    for reference in references:
        by_id.setdefault(reference.reference_id, reference)
    return tuple(by_id.values())


def _source_hash(record: Any) -> str:
    payload = {
        "operation": record.operation,
        "table": _normalize_table_name(record.table),
        "values": [
            (value.column, value.raw, value.value_type)
            for value in record.values
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _deduplicate_symbols(
    symbols: tuple[TechnicalSymbol, ...],
) -> tuple[TechnicalSymbol, ...]:
    by_id: dict[str, TechnicalSymbol] = {}
    for symbol in symbols:
        by_id.setdefault(symbol.symbol_id, symbol)
    return tuple(by_id.values())


def _configuration_by_name(
    configurations: tuple[DataDrivenConfiguration, ...],
    name: str,
) -> DataDrivenConfiguration | None:
    normalized = normalize_symbol_name(name)
    for configuration in configurations:
        if normalize_symbol_name(configuration.name) == normalized:
            return configuration
    return None


def _normalize_table_name(table: str) -> str:
    return ".".join(
        _normalize_identifier(part)
        for part in re.split(r"\s*\.\s*", table.strip())
        if part.strip()
    )


def _normalize_identifier(identifier: str) -> str:
    return identifier.strip().strip('"').lower()


def _normalize_status(value: str) -> str:
    return value.strip().strip("'").lower()


def _display_raw(raw: str) -> str:
    return _unquote(raw).strip() or raw


def _unquote(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def _safe_name_part(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_$#]+", "_", value.strip())
    return safe.strip("_") or "value"
