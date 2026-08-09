"""Detección determinista de patrones estructurales H4.2.

Este módulo calcula métricas; no interpreta criticidad ni aplica umbrales de
negocio. Las relaciones elegibles se deduplican por identidad estructural antes
de calcular los conteos.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable

from barbarion.domain.reverse_engineering import (
    RelationStatus,
    ResolutionStatus,
    TechnicalRelation,
    TechnicalSymbol,
)


class PatternResultStatus(StrEnum):
    DETECTED = "detected"
    NOT_DETECTED = "not_detected"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    AMBIGUOUS = "ambiguous"
    NOT_EVALUATED = "not_evaluated"


@dataclass(frozen=True, slots=True)
class PatternPolicy:
    """Política explícita de elegibilidad y evaluación.

    ``decision_mode=descriptive`` expone métricas sin inventar thresholds.
    """

    policy_id: str = "descriptive_v1"
    schema_version: str = "h42-pattern-result-v1"
    relation_types: frozenset[str] = frozenset()
    decision_mode: str = "descriptive"


@dataclass(frozen=True, slots=True)
class PatternResult:
    pattern_type: str
    subject_symbol_id: str
    logical_identity: str
    result_fingerprint: str
    status: PatternResultStatus
    metrics_primary: dict[str, Any]
    metrics_secondary: dict[str, Any]
    symbol_ids: tuple[str, ...]
    relation_ids: tuple[str, ...]
    reference_ids: tuple[str, ...]
    evidence_file_ids: tuple[int, ...]
    evidence_chunk_ids: tuple[str, ...]
    limitations: tuple[str, ...] = ()


def detect_patterns(
    symbols: Iterable[TechnicalSymbol],
    relations: Iterable[TechnicalRelation],
    *,
    policy: PatternPolicy = PatternPolicy(),
    pattern_types: frozenset[str] = frozenset(
        {"component_reuse", "structural_centrality"}
    ),
) -> tuple[PatternResult, ...]:
    """Calcula resultados H4.2 en orden estable, sin umbrales numéricos."""
    symbol_by_id = {symbol.symbol_id: symbol for symbol in symbols}
    eligible = tuple(
        relation
        for relation in relations
        if _eligible(relation, symbol_by_id, policy)
    )
    results: list[PatternResult] = []
    for subject_id in sorted(symbol_by_id):
        for pattern_type in sorted(pattern_types):
            if pattern_type not in {"component_reuse", "structural_centrality"}:
                raise ValueError(f"Patrón no soportado: {pattern_type}")
            primary, secondary, contributing = _metrics_for(
                pattern_type, subject_id, eligible
            )
            results.append(
                _result(
                    pattern_type,
                    subject_id,
                    primary,
                    secondary,
                    contributing,
                    policy,
                )
            )
    return tuple(results)


def _eligible(
    relation: TechnicalRelation,
    symbols: dict[str, TechnicalSymbol],
    policy: PatternPolicy,
) -> bool:
    return (
        relation.status == RelationStatus.ACTIVE
        and relation.resolution_status == ResolutionStatus.RESOLVED
        and relation.source_symbol_id in symbols
        and relation.target_symbol_id in symbols
        and symbols[relation.source_symbol_id].status.value == "active"
        and symbols[relation.target_symbol_id].status.value == "active"
        and (
            not policy.relation_types
            or relation.relation_type in policy.relation_types
        )
    )


def _metrics_for(
    pattern_type: str,
    subject_id: str,
    relations: tuple[TechnicalRelation, ...],
) -> tuple[dict[str, Any], dict[str, Any], tuple[TechnicalRelation, ...]]:
    incoming = tuple(r for r in relations if r.target_symbol_id == subject_id)
    outgoing = tuple(r for r in relations if r.source_symbol_id == subject_id)
    if pattern_type == "component_reuse":
        sources = {r.source_symbol_id for r in incoming}
        primary = {"distinct_source_symbols": len(sources)}
        secondary = {
            "inbound_relation_count": len(incoming),
            "distinct_source_files": len({r.evidence_file_id for r in incoming}),
            "relation_type_distribution": _distribution(incoming),
            "repeated_relation_count": len(incoming) - len(sources),
        }
        return primary, secondary, incoming

    inbound = {r.source_symbol_id for r in incoming}
    outbound = {r.target_symbol_id for r in outgoing}
    primary = {"distinct_total_neighbors": len(inbound | outbound)}
    secondary = {
        "distinct_inbound_neighbors": len(inbound),
        "distinct_outbound_neighbors": len(outbound),
        "inbound_relation_count": len(incoming),
        "outbound_relation_count": len(outgoing),
        "relation_type_distribution": _distribution(incoming + outgoing),
    }
    return primary, secondary, tuple(sorted(set(incoming + outgoing), key=lambda r: r.relation_id))


def _result(pattern_type: str, subject_id: str, primary: dict[str, Any], secondary: dict[str, Any], relations: tuple[TechnicalRelation, ...], policy: PatternPolicy) -> PatternResult:
    relation_ids = tuple(r.relation_id for r in relations)
    status = (
        PatternResultStatus.INSUFFICIENT_EVIDENCE
        if not relations
        else (
            PatternResultStatus.NOT_EVALUATED
            if policy.decision_mode == "descriptive"
            else PatternResultStatus.INSUFFICIENT_EVIDENCE
        )
    )
    logical_payload = [policy.schema_version, pattern_type, subject_id, policy.policy_id]
    logical_identity = _hash(logical_payload)
    fingerprint = _hash([logical_identity, relation_ids, primary, secondary, status.value])
    limitations = (
        ("threshold_pending_baseline",)
        if status == PatternResultStatus.NOT_EVALUATED
        else ("no_eligible_relations",)
    )
    return PatternResult(
        pattern_type=pattern_type,
        subject_symbol_id=subject_id,
        logical_identity=logical_identity,
        result_fingerprint=fingerprint,
        status=status,
        metrics_primary=primary,
        metrics_secondary=secondary,
        symbol_ids=tuple(sorted({subject_id} | {x for r in relations for x in (r.source_symbol_id, r.target_symbol_id) if x})),
        relation_ids=relation_ids,
        reference_ids=tuple(sorted({r.reference_id for r in relations})),
        evidence_file_ids=tuple(sorted({r.evidence_file_id for r in relations})),
        evidence_chunk_ids=tuple(sorted({r.evidence_chunk_id for r in relations if r.evidence_chunk_id})),
        limitations=limitations,
    )


def _distribution(relations: Iterable[TechnicalRelation]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for relation in relations:
        counts[relation.relation_type] = counts.get(relation.relation_type, 0) + 1
    return dict(sorted(counts.items()))


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
