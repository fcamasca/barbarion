"""Renderers Markdown y escritura segura para artefactos reverse engineering."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from barbarion.domain.reverse_engineering import (
    Inventory,
    InventoryFilters,
    InventoryItem,
)


INVENTORY_TEMPLATE_VERSION = "inventory.v1"
COMPONENT_TEMPLATE_VERSION = "component.v1"
IMPACT_TEMPLATE_VERSION = "impact.v1"


def render_inventory_markdown(
    inventory: Inventory,
    *,
    generated_at: str | None = None,
) -> str:
    """Renderiza inventario reverse engineering en Markdown estable.

    Args:
        inventory: Resultado estructurado de inventario.
        generated_at: Marca temporal opcional. Si no se informa, se usa UTC.

    Returns:
        Documento Markdown con secciones versionadas y orden canonico.
    """
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    lines = [
        "# Inventario tecnico",
        "",
        "## Metadata",
        f"- generado_en: {generated_at}",
        f"- template_version: {INVENTORY_TEMPLATE_VERSION}",
        f"- parametros: {_filters_text(inventory.filters)}",
        "",
        "## Resumen",
        f"- archivos: {inventory.summary.files}",
        f"- simbolos: {inventory.summary.symbols}",
        f"- referencias: {inventory.summary.references}",
        f"- relaciones: {inventory.summary.relations}",
        "",
        "## Detectado",
    ]
    if not inventory.items:
        lines.append("- sin simbolos para los filtros indicados")
    else:
        lines.extend(
            _inventory_item_line(item)
            for item in inventory.items
        )
    lines.extend(
        [
            "",
            "## Inferido",
            "- conteos derivados desde tablas vigentes de reverse engineering",
            "",
            "## Por confirmar",
            "- revisar simbolos ambiguos, desconocidos o de baja confianza",
            "",
            "## Evidencia",
        ]
    )
    if not inventory.items:
        lines.append("- sin evidencia persistida para listar")
    else:
        lines.extend(
            _inventory_evidence_line(item)
            for item in inventory.items
        )
    lines.extend(
        [
            "",
            "## Limitaciones",
            "- inventario generado solo desde SQLite; no reescanea archivos",
            "- referencias dinamicas o ambiguas requieren revision humana",
            "",
        ]
    )
    return "\n".join(lines)


def write_text_artifact(
    output_path: Path,
    content: str,
    *,
    overwrite: bool = False,
) -> Path:
    """Escribe un artefacto textual sin sobrescribir por defecto.

    Args:
        output_path: Ruta destino del artefacto.
        content: Contenido textual a escribir en UTF-8.
        overwrite: Permite reemplazar un archivo existente cuando es verdadero.

    Returns:
        Ruta absoluta resuelta del archivo escrito.

    Raises:
        FileExistsError: Si el archivo existe y `overwrite` es falso.
    """
    resolved = output_path.expanduser().resolve(strict=False)
    if resolved.exists() and not overwrite:
        raise FileExistsError(f"El archivo ya existe: {resolved}")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")
    return resolved


def safe_inventory_filename(filters: InventoryFilters) -> str:
    """Construye un nombre de archivo predecible para inventarios reverse engineering.

    Args:
        filters: Filtros usados para incluir pistas en el nombre.

    Returns:
        Nombre Markdown en minusculas, sin rutas personales.
    """
    parts = ["inventory"]
    if filters.technology:
        parts.append(_slug(filters.technology))
    if filters.symbol_type:
        parts.append(_slug(filters.symbol_type))
    if filters.name:
        parts.append(_slug(filters.name))
    return "-".join(part for part in parts if part) + ".md"


def _filters_text(filters: InventoryFilters) -> str:
    values = {
        "technology": filters.technology,
        "type": filters.symbol_type,
        "name": filters.name,
        "path": filters.path,
        "status": filters.status.value if filters.status else None,
        "confidence": filters.confidence.value if filters.confidence else None,
    }
    active = [f"{key}={value}" for key, value in values.items() if value is not None]
    return ", ".join(active) if active else "sin filtros"


def _inventory_item_line(item: InventoryItem) -> str:
    symbol = item.symbol
    location = _location(item)
    return (
        f"- `{symbol.normalized_name}` tipo={symbol.symbol_type} "
        f"tecnologia={symbol.technology} estado={symbol.status.value} "
        f"confianza={symbol.confidence.value} refs={item.reference_count} "
        f"out={item.outgoing_relations} in={item.incoming_relations} {location}"
    )


def _inventory_evidence_line(item: InventoryItem) -> str:
    symbol = item.symbol
    return (
        f"- `{symbol.normalized_name}` archivo={item.relative_path or 'n/a'} "
        f"chunk={symbol.chunk_id or 'n/a'} lineas={_line_range(symbol.start_line, symbol.end_line)}"
    )


def _location(item: InventoryItem) -> str:
    symbol = item.symbol
    path = item.relative_path or "n/a"
    return f"archivo={path} lineas={_line_range(symbol.start_line, symbol.end_line)}"


def _line_range(start_line: int | None, end_line: int | None) -> str:
    if start_line is None or end_line is None:
        return "n/a"
    if start_line == end_line:
        return str(start_line)
    return f"{start_line}-{end_line}"


def _slug(value: str) -> str:
    chars = [
        character.lower() if character.isalnum() else "-"
        for character in value.strip()
    ]
    slug = "".join(chars).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "sin-nombre"
