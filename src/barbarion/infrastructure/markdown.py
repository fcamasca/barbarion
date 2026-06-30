"""Renderers Markdown y escritura segura para artefactos reverse engineering."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from barbarion.domain.reverse_engineering import (
    ComponentDescription,
    DependencyEdge,
    ImpactAnalysis,
    Inventory,
    InventoryFilters,
    InventoryItem,
    TechnicalSymbol,
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


def render_component_markdown(
    description: ComponentDescription,
    *,
    generated_at: str | None = None,
) -> str:
    """Renderiza una ficha de componente en Markdown estable.

    Args:
        description: DTO producido por `DescribeService`.
        generated_at: Marca temporal opcional. Si no se informa, se usa UTC.

    Returns:
        Documento Markdown versionado con secciones canonicas.
    """
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    resolution = description.resolution
    symbol = resolution.symbol
    lines = [
        "# Ficha de componente",
        "",
        "## Metadata",
        f"- generado_en: {generated_at}",
        f"- template_version: {COMPONENT_TEMPLATE_VERSION}",
        f"- parametros: query={resolution.query}",
        f"- modo_llm: {'no_llm' if description.no_llm else 'llm'}",
        "",
        "## Identificacion",
    ]
    if symbol is None:
        lines.extend(_resolution_lines(resolution.status, resolution.candidates))
    else:
        lines.extend(_symbol_lines(symbol))
    lines.extend(
        [
            "",
            "## Resumen",
            f"- {description.summary}",
            "",
            "## Detectado",
        ]
    )
    lines.extend(_component_detected_lines(description))
    lines.extend(
        [
            "",
            "## Inferido",
        ]
    )
    lines.extend(_list_or_empty(description.inferences, "sin inferencias derivadas"))
    lines.extend(
        [
            "",
            "## Por confirmar",
        ]
    )
    lines.extend(_list_or_empty(description.to_confirm, "sin puntos por confirmar"))
    lines.extend(
        [
            "",
            "## Evidencia",
        ]
    )
    lines.extend(_evidence_lines(description.evidence, description.rag_sources))
    lines.extend(
        [
            "",
            "## Limitaciones",
        ]
    )
    lines.extend(_list_or_empty(description.limitations, "sin limitaciones adicionales"))
    lines.append("")
    return "\n".join(lines)


def render_impact_markdown(
    impact: ImpactAnalysis,
    *,
    generated_at: str | None = None,
) -> str:
    """Renderiza un analisis de impacto en Markdown estable.

    Args:
        impact: DTO producido por `ImpactService`.
        generated_at: Marca temporal opcional. Si no se informa, se usa UTC.

    Returns:
        Documento Markdown versionado con secciones canonicas.
    """
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    resolution = impact.resolution
    symbol = resolution.symbol
    walk = impact.walk
    lines = [
        "# Analisis de impacto",
        "",
        "## Metadata",
        f"- generado_en: {generated_at}",
        f"- template_version: {IMPACT_TEMPLATE_VERSION}",
        f"- parametros: query={resolution.query}",
        f"- modo_llm: {'no_llm' if impact.no_llm else 'llm'}",
        "",
        "## Componente",
    ]
    if symbol is None:
        lines.extend(_resolution_lines(resolution.status, resolution.candidates))
    else:
        lines.extend(_symbol_lines(symbol))
    lines.extend(
        [
            "",
            "## Alcance",
            f"- direccion: {walk.direction.value if walk else 'n/a'}",
            f"- profundidad: {walk.max_depth if walk else 'n/a'}",
            f"- limite_nodos: {walk.node_limit if walk else 'n/a'}",
            f"- nodos: {len(walk.nodes) if walk else 0}",
            f"- relaciones: {len(walk.edges) if walk else 0}",
            "",
            "## Resumen",
            f"- {impact.summary}",
            "",
            "## Detectado",
            "### Consumidores",
        ]
    )
    lines.extend(_edge_lines(impact.consumers, "sin consumidores detectados"))
    lines.extend(["", "### Dependencias"])
    lines.extend(_edge_lines(impact.dependencies, "sin dependencias detectadas"))
    lines.extend(["", "### Cruces de tecnologia"])
    lines.extend(_edge_lines(impact.cross_technology, "sin cruces de tecnologia detectados"))
    lines.extend(["", "## Inferido"])
    inferred = (*impact.risks, *(_indirect_lines(impact.indirect)))
    lines.extend(_list_or_empty(inferred, "sin riesgos o impactos indirectos inferidos"))
    lines.extend(["", "## Por confirmar"])
    lines.extend(_list_or_empty(impact.to_confirm, "sin puntos por confirmar"))
    lines.extend(["", "## Evidencia"])
    lines.extend(_evidence_lines(impact.evidence, impact.rag_sources))
    lines.extend(["", "## Limitaciones"])
    lines.extend(_list_or_empty(impact.limitations, "sin limitaciones adicionales"))
    if walk and walk.cycles:
        lines.extend(["", "## Ciclos"])
        lines.extend(f"- {' -> '.join(cycle)}" for cycle in walk.cycles)
    lines.append("")
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


def safe_component_filename(description: ComponentDescription) -> str:
    """Construye un nombre de archivo predecible para fichas de componente.

    Args:
        description: DTO de descripcion usado para derivar el nombre.

    Returns:
        Nombre Markdown en minusculas, sin rutas personales.
    """
    symbol = description.resolution.symbol
    name = symbol.normalized_name if symbol is not None else description.resolution.query
    return f"component-{_slug(name)}.md"


def safe_impact_filename(impact: ImpactAnalysis) -> str:
    """Construye un nombre de archivo predecible para analisis de impacto.

    Args:
        impact: DTO de impacto usado para derivar el nombre.

    Returns:
        Nombre Markdown en minusculas, sin rutas personales.
    """
    symbol = impact.resolution.symbol
    name = symbol.normalized_name if symbol is not None else impact.resolution.query
    return f"impact-{_slug(name)}.md"


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


def _resolution_lines(status: str, candidates: tuple[TechnicalSymbol, ...]) -> list[str]:
    lines = [f"- estado: {status}"]
    if not candidates:
        return lines
    lines.append("- candidatos:")
    lines.extend(
        f"  - `{candidate.normalized_name}` tipo={candidate.symbol_type} "
        f"tecnologia={candidate.technology} id={candidate.symbol_id}"
        for candidate in candidates
    )
    return lines


def _symbol_lines(symbol: TechnicalSymbol) -> list[str]:
    return [
        f"- nombre: {symbol.normalized_name}",
        f"- nombre_original: {symbol.original_name}",
        f"- tipo: {symbol.symbol_type}",
        f"- tecnologia: {symbol.technology}",
        f"- estado: {symbol.status.value}",
        f"- confianza: {symbol.confidence.value}",
        f"- archivo_id: {symbol.file_id if symbol.file_id is not None else 'n/a'}",
        f"- chunk: {symbol.chunk_id or 'n/a'}",
        f"- lineas: {_line_range(symbol.start_line, symbol.end_line)}",
        f"- symbol_id: {symbol.symbol_id}",
    ]


def _component_detected_lines(description: ComponentDescription) -> list[str]:
    lines = []
    lines.extend(
        f"- responsabilidad: {responsibility}"
        for responsibility in description.responsibilities
    )
    if description.outgoing is not None:
        lines.append(f"- dependencias_salientes: {len(description.outgoing.edges)}")
    if description.incoming is not None:
        lines.append(f"- consumidores: {len(description.incoming.edges)}")
    return lines or ["- sin relaciones detectadas"]


def _edge_lines(edges: tuple[DependencyEdge, ...], empty: str) -> list[str]:
    if not edges:
        return [f"- {empty}"]
    return [_edge_line(edge) for edge in edges]


def _edge_line(edge: DependencyEdge) -> str:
    source = (
        edge.source_symbol.normalized_name
        if edge.source_symbol is not None
        else edge.relation.source_symbol_id or "origen_desconocido"
    )
    target = (
        edge.target_symbol.normalized_name
        if edge.target_symbol is not None
        else edge.target_key or edge.relation.target_key or "destino_desconocido"
    )
    cycle = " ciclo=true" if edge.is_cycle else ""
    return (
        f"- `{source}` -> `{target}` tipo={edge.relation.relation_type} "
        f"direccion={edge.direction.value} profundidad={edge.depth} "
        f"estado={edge.relation.resolution_status.value} "
        f"clasificacion={edge.relation.classification.value} "
        f"confianza={edge.relation.confidence.value}{cycle}"
    )


def _indirect_lines(edges: tuple[DependencyEdge, ...]) -> tuple[str, ...]:
    return tuple(
        f"impacto indirecto via {edge.target_key or edge.relation.target_key or edge.relation.relation_id}"
        for edge in edges
    )


def _evidence_lines(evidence: tuple[object, ...], rag_sources: tuple[str, ...]) -> list[str]:
    lines = [
        (
            f"- {item.source}: {item.detail} ref={item.reference_id or 'n/a'} "
            f"rel={item.relation_id or 'n/a'} chunk={item.chunk_id or 'n/a'}"
        )
        for item in evidence
    ]
    lines.extend(f"- rag: {source}" for source in rag_sources)
    return lines or ["- sin evidencia persistida para listar"]


def _list_or_empty(values: tuple[str, ...], empty: str) -> list[str]:
    if not values:
        return [f"- {empty}"]
    return [f"- {value}" for value in values]


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
