"""Golden Markdown H4-T08 para inventario tecnico."""

from pathlib import Path

from barbarion.domain.models import Confidence
from barbarion.domain.reverse_engineering import (
    Inventory,
    InventoryFilters,
    InventoryItem,
    InventorySummary,
    TechnicalSymbol,
    technical_symbol_id,
)
from barbarion.infrastructure.markdown import render_inventory_markdown


def test_inventory_markdown_matches_golden() -> None:
    symbol = TechnicalSymbol(
        symbol_id=technical_symbol_id(
            normalized_name="pkg_demo.procesar",
            symbol_type="procedure",
            technology="oracle",
            container_name="pkg_demo",
        ),
        original_name="PKG_DEMO.PROCESAR",
        normalized_name="pkg_demo.procesar",
        symbol_type="procedure",
        technology="oracle",
        extraction_method="parser",
        confidence=Confidence.HIGH,
        file_id=1,
        document_id=1,
        chunk_id="chunk-1",
        container_name="pkg_demo",
        start_line=10,
        end_line=15,
    )
    inventory = Inventory(
        filters=InventoryFilters(technology="oracle", symbol_type="procedure"),
        summary=InventorySummary(files=1, symbols=1, references=2, relations=1),
        items=(
            InventoryItem(
                symbol=symbol,
                relative_path="oracle/pkg_demo.pkb",
                outgoing_relations=1,
                incoming_relations=0,
                reference_count=2,
            ),
        ),
    )

    markdown = render_inventory_markdown(
        inventory,
        generated_at="2026-01-01T00:00:00+00:00",
    )

    expected = Path(__file__).with_name("inventory.md").read_text(encoding="utf-8")
    assert markdown == expected
