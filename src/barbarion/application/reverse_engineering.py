"""Casos de uso H4 para catalogo de simbolos."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from barbarion.config import Settings
from barbarion.domain.models import Confidence
from barbarion.domain.reverse_engineering import (
    H4AnalysisRunMode,
    H4AnalysisRunStatus,
    H4Classification,
    H4Symbol,
    H4Reference,
    H4Relation,
    H4RelationCandidate,
    H4ResolutionStatus,
    h4_symbol_id,
    h4_relation_id,
    normalize_symbol_name,
)
from barbarion.infrastructure.sqlite import (
    H4SymbolSource,
    SQLiteReverseEngineeringRepository,
)


@dataclass(frozen=True, slots=True)
class SymbolCatalogSummary:
    """Resultado de una corrida H4-T02 de catalogo de simbolos."""

    run_id: int
    status: H4AnalysisRunStatus
    sources_scanned: int
    symbols_detected: int
    duplicates_skipped: int
    unknown_symbols: int
    duration_ms: int


@dataclass(frozen=True, slots=True)
class RelationResolutionSummary:
    """Resultado de una corrida H4-T04 de resolucion de relaciones."""

    run_id: int
    status: H4AnalysisRunStatus
    references_seen: int
    relations_resolved: int
    relations_ambiguous: int
    relations_dynamic: int
    relations_external: int
    unresolved_without_relation: int
    duration_ms: int


@dataclass(frozen=True, slots=True)
class SymbolCatalogService:
    """Puebla el catalogo H4 de simbolos desde chunks H2 vigentes."""

    settings: Settings
    repository: SQLiteReverseEngineeringRepository

    def run(
        self,
        *,
        mode: H4AnalysisRunMode = H4AnalysisRunMode.INCREMENTAL,
    ) -> SymbolCatalogSummary:
        """Ejecuta una corrida simple de catalogacion de simbolos."""
        started = time.monotonic()
        run_id = self.repository.begin_analysis_run(
            mode=mode,
            scope={"domain": self.settings.domain, "stage": "symbols"},
        )
        sources = self.repository.symbol_sources(domain=self.settings.domain)
        seen: set[str] = set()
        duplicates = 0
        unknowns = 0
        for source in sources:
            symbol = symbol_from_source(source)
            if symbol.symbol_id in seen:
                duplicates += 1
                continue
            seen.add(symbol.symbol_id)
            if symbol.symbol_type == "unknown":
                unknowns += 1
            self.repository.upsert_symbol(run_id=run_id, symbol=symbol)

        duration_ms = int((time.monotonic() - started) * 1000)
        status = H4AnalysisRunStatus.COMPLETED
        self.repository.finish_analysis_run(
            run_id=run_id,
            status=status,
            symbols_detected=len(seen),
            duration_ms=duration_ms,
        )
        return SymbolCatalogSummary(
            run_id=run_id,
            status=status,
            sources_scanned=len(sources),
            symbols_detected=len(seen),
            duplicates_skipped=duplicates,
            unknown_symbols=unknowns,
            duration_ms=duration_ms,
        )


@dataclass(frozen=True, slots=True)
class RelationResolutionService:
    """Convierte referencias H4 en relaciones trazables cuando hay evidencia."""

    settings: Settings
    repository: SQLiteReverseEngineeringRepository

    def run(
        self,
        *,
        mode: H4AnalysisRunMode = H4AnalysisRunMode.INCREMENTAL,
    ) -> RelationResolutionSummary:
        """Ejecuta resolucion conservadora de referencias ya persistidas."""
        started = time.monotonic()
        run_id = self.repository.begin_analysis_run(
            mode=mode,
            scope={"domain": self.settings.domain, "stage": "relations"},
        )
        symbols = self.repository.active_symbols()
        references = self.repository.active_references()
        resolved = 0
        ambiguous = 0
        dynamic = 0
        external = 0
        unresolved = 0
        for reference in references:
            decision = relation_from_reference(reference, symbols)
            if decision is None:
                unresolved += 1
                continue
            relation, candidates = decision
            self.repository.upsert_relation(run_id=run_id, relation=relation)
            self.repository.replace_relation_candidates(
                relation_id=relation.relation_id,
                candidates=candidates,
            )
            if relation.resolution_status == H4ResolutionStatus.RESOLVED:
                resolved += 1
            elif relation.resolution_status == H4ResolutionStatus.AMBIGUOUS:
                ambiguous += 1
            elif relation.resolution_status == H4ResolutionStatus.DYNAMIC:
                dynamic += 1
            elif relation.resolution_status == H4ResolutionStatus.EXTERNAL:
                external += 1

        duration_ms = int((time.monotonic() - started) * 1000)
        status = H4AnalysisRunStatus.COMPLETED
        self.repository.finish_analysis_run(
            run_id=run_id,
            status=status,
            references_detected=len(references),
            relations_resolved=resolved,
            relations_unresolved=unresolved + dynamic + external,
            relations_ambiguous=ambiguous,
            duration_ms=duration_ms,
        )
        return RelationResolutionSummary(
            run_id=run_id,
            status=status,
            references_seen=len(references),
            relations_resolved=resolved,
            relations_ambiguous=ambiguous,
            relations_dynamic=dynamic,
            relations_external=external,
            unresolved_without_relation=unresolved,
            duration_ms=duration_ms,
        )


def relation_from_reference(
    reference: H4Reference,
    symbols: tuple[H4Symbol, ...],
) -> tuple[H4Relation, tuple[H4RelationCandidate, ...]] | None:
    """Resuelve una referencia contra simbolos compatibles sin inventar destino."""
    if reference.resolution_status == H4ResolutionStatus.DYNAMIC:
        return (
            _relation(
                reference,
                classification=H4Classification.TO_CONFIRM,
                resolution_status=H4ResolutionStatus.DYNAMIC,
                target_key=reference.normalized_target,
                notes="referencia dinamica conservada sin resolucion exacta",
            ),
            (),
        )
    if _is_external_reference(reference):
        return (
            _relation(
                reference,
                classification=H4Classification.TO_CONFIRM,
                resolution_status=H4ResolutionStatus.EXTERNAL,
                target_key=reference.normalized_target,
                notes="referencia marcada como externa",
            ),
            (),
        )

    candidates = _candidate_symbols(reference, symbols)
    if not candidates:
        return None
    if len(candidates) == 1:
        target = candidates[0]
        return (
            _relation(
                reference,
                classification=H4Classification.DETECTED,
                resolution_status=H4ResolutionStatus.RESOLVED,
                target_symbol_id=target.symbol_id,
                target_key=reference.normalized_target,
            ),
            (),
        )

    relation = _relation(
        reference,
        classification=H4Classification.TO_CONFIRM,
        resolution_status=H4ResolutionStatus.AMBIGUOUS,
        target_key=reference.normalized_target,
        notes="multiples candidatos compatibles",
    )
    return (
        relation,
        tuple(
            H4RelationCandidate(
                relation_id=relation.relation_id,
                candidate_symbol_id=symbol.symbol_id,
                rank=index + 1,
                reason="nombre y tipo compatibles",
            )
            for index, symbol in enumerate(candidates)
        ),
    )


def symbol_from_source(source: H4SymbolSource) -> H4Symbol:
    """Convierte un chunk H2 vigente en un simbolo H4 normalizado."""
    metadata = source.metadata
    original_name = _first_text(
        source.object_name,
        metadata.get("object_name"),
        metadata.get("symbol_name"),
        metadata.get("name"),
    )
    symbol_type = _first_text(
        source.object_type,
        metadata.get("object_type"),
        metadata.get("symbol_kind"),
        source.chunk_type if source.chunk_type != "file" else None,
    )
    unknown = original_name is None or symbol_type is None
    if original_name is None:
        original_name = f"{source.relative_path}#{source.chunk_id}"
    if symbol_type is None:
        symbol_type = "unknown"

    technology = _technology(source.artifact_kind, metadata)
    container_name = None if unknown else _container_name(original_name, metadata)
    normalized_name = normalize_symbol_name(original_name)
    normalized_container = (
        normalize_symbol_name(container_name) if container_name is not None else None
    )
    confidence = _confidence(metadata, fallback=Confidence.LOW if unknown else Confidence.HIGH)
    symbol_id = h4_symbol_id(
        normalized_name=normalized_name,
        symbol_type=symbol_type,
        technology=technology,
        container_name=normalized_container,
    )
    return H4Symbol(
        symbol_id=symbol_id,
        original_name=original_name,
        normalized_name=normalized_name,
        symbol_type=symbol_type.lower(),
        technology=technology,
        extraction_method="inferred" if unknown else "parser",
        confidence=confidence,
        file_id=source.file_id,
        document_id=source.document_id,
        chunk_id=source.chunk_id,
        container_name=normalized_container,
        start_line=source.start_line,
        end_line=source.end_line,
        metadata={
            "artifact_kind": source.artifact_kind,
            "relative_path": source.relative_path,
            "source_chunk_type": source.chunk_type,
        },
    )


def _relation(
    reference: H4Reference,
    *,
    classification: H4Classification,
    resolution_status: H4ResolutionStatus,
    target_symbol_id: str | None = None,
    target_key: str | None = None,
    notes: str | None = None,
) -> H4Relation:
    relation_id = h4_relation_id(
        reference_id=reference.reference_id,
        relation_type=_relation_type(reference),
        target_symbol_id=target_symbol_id,
        target_key=target_key,
    )
    return H4Relation(
        relation_id=relation_id,
        reference_id=reference.reference_id,
        source_symbol_id=reference.source_symbol_id,
        target_symbol_id=target_symbol_id,
        target_key=target_key,
        relation_type=_relation_type(reference),
        classification=classification,
        resolution_status=resolution_status,
        confidence=reference.confidence,
        evidence_file_id=reference.source_file_id,
        evidence_chunk_id=reference.source_chunk_id,
        start_line=reference.start_line,
        end_line=reference.end_line,
        notes=notes,
    )


def _candidate_symbols(
    reference: H4Reference,
    symbols: tuple[H4Symbol, ...],
) -> tuple[H4Symbol, ...]:
    compatible = [
        symbol
        for symbol in symbols
        if symbol.technology == reference.technology
        and _type_compatible(reference.reference_type, symbol.symbol_type)
    ]
    target = normalize_symbol_name(reference.normalized_target)
    parts = target.split(".")
    if len(parts) > 1:
        container = ".".join(parts[:-1])
        leaf = parts[-1]
        matches = [
            symbol
            for symbol in compatible
            if symbol.normalized_name == target
            or (
                symbol.normalized_name == leaf
                and symbol.container_name == container
            )
        ]
        return tuple(_stable_symbols(matches))

    matches = [symbol for symbol in compatible if symbol.normalized_name == target]
    source = _source_symbol(reference, symbols)
    if source is not None and source.container_name is not None:
        same_container = [
            symbol
            for symbol in matches
            if symbol.container_name == source.container_name
        ]
        if same_container:
            matches = same_container
    return tuple(_stable_symbols(matches))


def _stable_symbols(symbols: list[H4Symbol]) -> list[H4Symbol]:
    return sorted(
        symbols,
        key=lambda symbol: (
            symbol.container_name or "",
            symbol.normalized_name,
            symbol.symbol_type,
            symbol.symbol_id,
        ),
    )


def _source_symbol(
    reference: H4Reference,
    symbols: tuple[H4Symbol, ...],
) -> H4Symbol | None:
    if reference.source_symbol_id is None:
        return None
    for symbol in symbols:
        if symbol.symbol_id == reference.source_symbol_id:
            return symbol
    return None


def _type_compatible(reference_type: str, symbol_type: str) -> bool:
    allowed = {
        "call": {"procedure", "function", "event", "function_object"},
        "calls": {"procedure", "function", "event", "function_object"},
        "stored_procedure": {"procedure", "function"},
        "table": {"table", "view", "datawindow"},
        "trigger_table": {"table", "view"},
        "sequence": {"sequence"},
        "open": {"window", "userobject", "menu", "application"},
        "event": {"event"},
        "datawindow": {"datawindow"},
    }.get(reference_type, set())
    return symbol_type in allowed


def _relation_type(reference: H4Reference) -> str:
    return {
        "call": "calls",
        "calls": "calls",
        "stored_procedure": "calls",
        "table": "uses",
        "trigger_table": "uses",
        "sequence": "uses",
        "open": "opens",
        "event": "calls",
        "datawindow": "uses",
        "dynamic_sql": "uses",
    }.get(reference.reference_type, "uses")


def _is_external_reference(reference: H4Reference) -> bool:
    scope = reference.metadata.get("scope")
    if isinstance(scope, str) and scope.lower() == "external":
        return True
    if "@" in reference.raw_text:
        return True
    return reference.normalized_target.startswith("external.")


def _technology(artifact_kind: str, metadata: dict[str, Any]) -> str:
    format_value = _first_text(metadata.get("format"))
    if format_value in {"oracle", "powerbuilder"}:
        return format_value
    if artifact_kind in {"oracle", "powerbuilder"}:
        return artifact_kind
    if artifact_kind in {"markdown", "pdf", "docx", "text"}:
        return "document"
    return "unknown"


def _container_name(original_name: str, metadata: dict[str, Any]) -> str | None:
    explicit = _first_text(
        metadata.get("parent_name"),
        metadata.get("package_name"),
        metadata.get("class_name"),
    )
    if explicit is not None:
        return explicit
    parts = normalize_symbol_name(original_name).split(".")
    if len(parts) > 1:
        return ".".join(parts[:-1])
    return None


def _confidence(metadata: dict[str, Any], *, fallback: Confidence) -> Confidence:
    raw = _first_text(
        metadata.get("logical_unit_confidence"),
        metadata.get("confidence"),
    )
    if raw is None:
        return fallback
    try:
        return Confidence(raw.lower())
    except ValueError:
        return fallback


def _first_text(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
