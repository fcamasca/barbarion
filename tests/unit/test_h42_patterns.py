from __future__ import annotations

import hashlib

from barbarion.domain.models import Confidence
from barbarion.domain.reverse_engineering import (
    EvidenceClassification,
    RelationStatus,
    ResolutionStatus,
    TechnicalRelation,
    TechnicalSymbol,
)
from barbarion.domain.technical_patterns import (
    PatternResultStatus,
    PatternPolicy,
    detect_patterns,
)


def test_not_evaluated_is_a_first_class_result_status() -> None:
    assert PatternResultStatus("not_evaluated") is PatternResultStatus.NOT_EVALUATED


def _id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _symbol(name: str, file_id: int) -> TechnicalSymbol:
    return TechnicalSymbol(
        symbol_id=_id(name),
        original_name=name,
        normalized_name=name.lower(),
        symbol_type="procedure",
        technology="oracle",
        extraction_method="test",
        confidence=Confidence.HIGH,
        file_id=file_id,
    )


def _relation(name: str, source: TechnicalSymbol, target: TechnicalSymbol, file_id: int) -> TechnicalRelation:
    return TechnicalRelation(
        relation_id=_id(name),
        reference_id=_id(f"ref:{name}"),
        relation_type="calls",
        classification=EvidenceClassification.DETECTED,
        resolution_status=ResolutionStatus.RESOLVED,
        confidence=Confidence.HIGH,
        evidence_file_id=file_id,
        source_symbol_id=source.symbol_id,
        target_symbol_id=target.symbol_id,
    )


def test_component_reuse_deduplicates_same_source_symbol() -> None:
    a, b, x = _symbol("A", 1), _symbol("B", 2), _symbol("X", 3)
    results = detect_patterns(
        (a, b, x),
        (_relation("a1", a, x, 1), _relation("a2", a, x, 1), _relation("b1", b, x, 2)),
    )
    result = next(r for r in results if r.pattern_type == "component_reuse" and r.subject_symbol_id == x.symbol_id)
    assert result.metrics_primary == {"distinct_source_symbols": 2}
    assert result.metrics_secondary["inbound_relation_count"] == 3
    assert result.metrics_secondary["repeated_relation_count"] == 1
    assert result.status.value == "not_evaluated"


def test_structural_centrality_uses_distinct_total_neighbors_only() -> None:
    a, b, x = _symbol("A", 1), _symbol("B", 2), _symbol("X", 3)
    results = detect_patterns(
        (a, b, x),
        (_relation("a1", a, x, 1), _relation("a2", a, x, 1), _relation("x1", x, b, 2)),
    )
    result = next(r for r in results if r.pattern_type == "structural_centrality" and r.subject_symbol_id == x.symbol_id)
    assert result.metrics_primary == {"distinct_total_neighbors": 2}
    assert result.metrics_secondary["inbound_relation_count"] == 2
    assert result.metrics_secondary["outbound_relation_count"] == 1


def test_logical_identity_is_stable_but_fingerprint_changes_with_graph() -> None:
    a, b, x = _symbol("A", 1), _symbol("B", 2), _symbol("X", 3)
    first = detect_patterns((a, b, x), (_relation("a", a, x, 1),))[0]
    second = detect_patterns((a, b, x), (_relation("a", a, x, 1), _relation("b", b, x, 2)))[0]
    assert first.logical_identity == second.logical_identity
    assert first.result_fingerprint != second.result_fingerprint


def test_incomplete_provenance_keeps_file_without_fabricating_chunk() -> None:
    a, x = _symbol("A", 1), _symbol("X", 2)
    result = next(
        r for r in detect_patterns((a, x), (_relation("a", a, x, 7),))
        if r.pattern_type == "component_reuse" and r.subject_symbol_id == x.symbol_id
    )
    assert result.evidence_file_ids == (7,)
    assert result.evidence_chunk_ids == ()
    assert result.reference_ids


def test_no_eligible_relations_is_insufficient_evidence() -> None:
    a, x = _symbol("A", 1), _symbol("X", 2)
    result = next(
        r for r in detect_patterns((a, x), ())
        if r.pattern_type == "component_reuse" and r.subject_symbol_id == x.symbol_id
    )
    assert result.status is PatternResultStatus.INSUFFICIENT_EVIDENCE
