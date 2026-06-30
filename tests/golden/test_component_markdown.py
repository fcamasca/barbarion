"""Golden test para ficha Markdown de componente."""

from pathlib import Path

from barbarion.domain.models import Confidence
from barbarion.domain.reverse_engineering import (
    ComponentDescription,
    DependencyDirection,
    DependencyEdge,
    DependencyNode,
    DependencyWalk,
    EvidenceClassification,
    EvidenceItem,
    ObjectResolution,
    ResolutionStatus,
    TechnicalRelation,
    TechnicalSymbol,
)
from barbarion.infrastructure.markdown import render_component_markdown


def test_component_markdown_matches_golden() -> None:
    root = _symbol("pkg.root", "a")
    dependency = _symbol("pkg.dependency", "b")
    relation = _relation(root, dependency, "c", "d")
    edge = DependencyEdge(
        relation=relation,
        depth=1,
        direction=DependencyDirection.OUTGOING,
        source_symbol=root,
        target_symbol=dependency,
        target_key=dependency.normalized_name,
    )
    walk = DependencyWalk(
        seed_symbol_id=root.symbol_id,
        direction=DependencyDirection.OUTGOING,
        max_depth=1,
        node_limit=500,
        nodes=(
            DependencyNode(symbol=root, depth=0),
            DependencyNode(symbol=dependency, depth=1),
        ),
        edges=(edge,),
    )
    description = ComponentDescription(
        resolution=ObjectResolution(query="pkg.root", symbol=root),
        outgoing=walk,
        responsibilities=("procedure pkg.root en tecnologia oracle",),
        evidence=(
            EvidenceItem(
                source="relation",
                detail="calls resolved",
                reference_id=relation.reference_id,
                relation_id=relation.relation_id,
            ),
        ),
        inferences=("las dependencias salientes sugieren colaboraciones tecnicas",),
        summary="pkg.root es un procedure oracle.",
        no_llm=True,
    )

    markdown = render_component_markdown(
        description,
        generated_at="2026-01-01T00:00:00+00:00",
    )

    expected = Path(__file__).with_name("component.md").read_text(encoding="utf-8")
    assert markdown == expected


def _symbol(name: str, prefix: str) -> TechnicalSymbol:
    return TechnicalSymbol(
        symbol_id=prefix * 64,
        original_name=name,
        normalized_name=name,
        symbol_type="procedure",
        technology="oracle",
        extraction_method="fixture",
        confidence=Confidence.HIGH,
        file_id=1,
        chunk_id=f"chunk-{prefix}",
        container_name="pkg",
        start_line=1,
        end_line=4,
    )


def _relation(
    source: TechnicalSymbol,
    target: TechnicalSymbol,
    reference_prefix: str,
    relation_prefix: str,
) -> TechnicalRelation:
    return TechnicalRelation(
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
