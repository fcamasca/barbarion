"""Golden Markdown para salidas Data-Driven visibles en H4."""

from pathlib import Path

from barbarion.domain.models import Confidence
from barbarion.domain.reverse_engineering import (
    ComponentDescription,
    DependencyDirection,
    DependencyEdge,
    DependencyNode,
    DependencyWalk,
    EvidenceClassification,
    ImpactAnalysis,
    Inventory,
    InventoryFilters,
    InventoryItem,
    InventorySummary,
    ObjectResolution,
    ResolutionStatus,
    TechnicalRelation,
    TechnicalSymbol,
)
from barbarion.infrastructure.markdown import (
    render_component_markdown,
    render_impact_markdown,
    render_inventory_markdown,
)


def test_data_driven_markdown_matches_golden() -> None:
    """Valida Markdown estable para inventario y ficha de configuracion."""
    symbol = _configuration_symbol()
    inventory = Inventory(
        filters=InventoryFilters(technology="configuration"),
        summary=InventorySummary(files=1, symbols=1, references=2, relations=1),
        items=(
            InventoryItem(
                symbol=symbol,
                relative_path="config/pricing/rules.sql",
                outgoing_relations=1,
                incoming_relations=0,
                reference_count=2,
            ),
        ),
    )
    description = ComponentDescription(
        resolution=ObjectResolution(query="pricing_rules.r1", symbol=symbol),
        responsibilities=(
            "registro Data-Driven pricing_rules.r1 de pricing_rules",
            "proviene de la tabla APP_CFG.PRICING_RULES",
        ),
        summary="pricing_rules.r1 es un registro Data-Driven de pricing_rules.",
        no_llm=True,
    )
    dependency = _oracle_function()
    edge = _edge(symbol, dependency)
    walk = DependencyWalk(
        seed_symbol_id=symbol.symbol_id,
        direction=DependencyDirection.OUTGOING,
        max_depth=1,
        node_limit=500,
        nodes=(
            DependencyNode(symbol=symbol, depth=0),
            DependencyNode(symbol=dependency, depth=1),
        ),
        edges=(edge,),
    )
    impact = ImpactAnalysis(
        resolution=ObjectResolution(query="pricing_rules.r1", symbol=symbol),
        walk=walk,
        dependencies=(edge,),
        cross_technology=(edge,),
        risks=("existen cruces entre tecnologias",),
        summary="Impacto Data-Driven de pricing_rules.r1.",
        no_llm=True,
    )

    markdown = "\n---\n".join(
        (
            render_inventory_markdown(
                inventory,
                generated_at="2026-01-01T00:00:00+00:00",
            ),
            render_component_markdown(
                description,
                generated_at="2026-01-01T00:00:00+00:00",
            ),
            render_impact_markdown(
                impact,
                generated_at="2026-01-01T00:00:00+00:00",
            ),
        )
    )

    expected = Path(__file__).with_name("data_driven.md").read_text(encoding="utf-8")
    assert markdown == expected


def _configuration_symbol() -> TechnicalSymbol:
    """Crea un simbolo Data-Driven estable para golden tests."""
    return TechnicalSymbol(
        symbol_id="a" * 64,
        original_name="Base Rule",
        normalized_name="pricing_rules.r1",
        symbol_type="configuration_record",
        technology="configuration",
        extraction_method="data_driven_dml",
        confidence=Confidence.HIGH,
        file_id=7,
        document_id=8,
        chunk_id="chunk-config-1",
        container_name="pricing_rules",
        start_line=3,
        end_line=9,
        metadata={
            "configuration_name": "pricing_rules",
            "record_id": "R1",
            "table": "APP_CFG.PRICING_RULES",
            "operation": "insert",
            "identity_values": ("R1",),
            "display_values": ("Base Rule",),
            "declared_columns": ("RULE_ID", "RULE_NAME", "FORMULA"),
        },
    )


def _oracle_function() -> TechnicalSymbol:
    """Crea una funcion Oracle estable para impacto cruzado."""
    return TechnicalSymbol(
        symbol_id="b" * 64,
        original_name="tax_rate",
        normalized_name="tax_rate",
        symbol_type="function",
        technology="oracle",
        extraction_method="fixture",
        confidence=Confidence.HIGH,
        file_id=9,
        document_id=10,
        chunk_id="chunk-oracle-1",
        start_line=1,
        end_line=4,
    )


def _edge(source: TechnicalSymbol, target: TechnicalSymbol) -> DependencyEdge:
    """Crea una arista Data-Driven hacia Oracle para golden Markdown."""
    relation = TechnicalRelation(
        relation_id="c" * 64,
        reference_id="d" * 64,
        source_symbol_id=source.symbol_id,
        target_symbol_id=target.symbol_id,
        target_key=target.normalized_name,
        relation_type="calls",
        classification=EvidenceClassification.DETECTED,
        resolution_status=ResolutionStatus.RESOLVED,
        confidence=Confidence.HIGH,
        evidence_file_id=7,
        evidence_chunk_id=source.chunk_id,
    )
    return DependencyEdge(
        relation=relation,
        depth=1,
        direction=DependencyDirection.OUTGOING,
        source_symbol=source,
        target_symbol=target,
        target_key=target.normalized_name,
    )
