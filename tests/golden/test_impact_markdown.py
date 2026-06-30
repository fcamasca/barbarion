"""Golden test para Markdown de impacto."""

from pathlib import Path

from barbarion.domain.models import Confidence
from barbarion.domain.reverse_engineering import (
    DependencyDirection,
    DependencyEdge,
    DependencyNode,
    DependencyWalk,
    EvidenceClassification,
    EvidenceItem,
    ImpactAnalysis,
    ObjectResolution,
    ResolutionStatus,
    TechnicalRelation,
    TechnicalSymbol,
)
from barbarion.infrastructure.markdown import render_impact_markdown


def test_impact_markdown_matches_golden() -> None:
    root = _symbol("pkg.root", "a", technology="oracle")
    consumer = _symbol("w.root", "b", technology="powerbuilder")
    dependency = _symbol("pkg.dependency", "c", technology="oracle")
    incoming = _edge(consumer, root, DependencyDirection.INCOMING, "d", "e")
    outgoing = _edge(root, dependency, DependencyDirection.OUTGOING, "f", "1")
    walk = DependencyWalk(
        seed_symbol_id=root.symbol_id,
        direction=DependencyDirection.BOTH,
        max_depth=2,
        node_limit=500,
        nodes=(
            DependencyNode(symbol=root, depth=0),
            DependencyNode(symbol=consumer, depth=1),
            DependencyNode(symbol=dependency, depth=1),
        ),
        edges=(incoming, outgoing),
    )
    impact = ImpactAnalysis(
        resolution=ObjectResolution(query="pkg.root", symbol=root),
        walk=walk,
        consumers=(incoming,),
        dependencies=(outgoing,),
        cross_technology=(incoming,),
        risks=("hay consumidores que podrian requerir verificacion",),
        evidence=(
            EvidenceItem(
                source="relation",
                detail="calls resolved",
                reference_id=incoming.relation.reference_id,
                relation_id=incoming.relation.relation_id,
            ),
        ),
        summary="Impacto basico de pkg.root.",
        no_llm=True,
    )

    markdown = render_impact_markdown(
        impact,
        generated_at="2026-01-01T00:00:00+00:00",
    )

    expected = Path(__file__).with_name("impact.md").read_text(encoding="utf-8")
    assert markdown == expected


def _symbol(name: str, prefix: str, *, technology: str) -> TechnicalSymbol:
    return TechnicalSymbol(
        symbol_id=prefix * 64,
        original_name=name,
        normalized_name=name,
        symbol_type="procedure",
        technology=technology,
        extraction_method="fixture",
        confidence=Confidence.HIGH,
        file_id=1,
        chunk_id=f"chunk-{prefix}",
        container_name="pkg",
        start_line=1,
        end_line=4,
    )


def _edge(
    source: TechnicalSymbol,
    target: TechnicalSymbol,
    direction: DependencyDirection,
    reference_prefix: str,
    relation_prefix: str,
) -> DependencyEdge:
    relation = TechnicalRelation(
        relation_id=relation_prefix * 64,
        reference_id=reference_prefix * 64,
        source_symbol_id=source.symbol_id,
        target_symbol_id=target.symbol_id,
        target_key=target.normalized_name,
        relation_type="calls",
        classification=EvidenceClassification.DETECTED,
        resolution_status=ResolutionStatus.RESOLVED,
        confidence=Confidence.MEDIUM,
        evidence_file_id=1,
    )
    return DependencyEdge(
        relation=relation,
        depth=1,
        direction=direction,
        source_symbol=source,
        target_symbol=target,
        target_key=target.normalized_name,
    )
