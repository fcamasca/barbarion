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
    SymbolStatus,
    TechnicalSymbol,
    normalize_symbol_name,
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


def build_configuration_symbols(
    records: tuple[Any, ...],
    configurations: tuple[DataDrivenConfiguration, ...],
) -> ConfigurationSymbolPlan:
    """Construye simbolos H4 en memoria desde registros DML canonicos."""
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
