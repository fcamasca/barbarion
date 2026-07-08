"""Renderers Markdown y escritura segura para artefactos reverse engineering."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
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
from barbarion.domain.spec_mode import (
    AffectedComponent,
    EvidenceItem as SpecEvidenceItem,
    ExistingRule,
    SpecDraft,
)


INVENTORY_TEMPLATE_VERSION = "inventory.v1"
COMPONENT_TEMPLATE_VERSION = "component.v1"
IMPACT_TEMPLATE_VERSION = "impact.v1"
SPEC_TEMPLATE_VERSION = "spec.v1"
SPEC_MARKDOWN_FILES = (
    "requirements.md",
    "design.md",
    "tasks.md",
    "test-plan.md",
)


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


def render_spec_markdown(
    draft: SpecDraft,
    *,
    generated_at: str | None = None,
) -> dict[str, str]:
    """Renderiza los cuatro documentos Markdown H5 `spec.v1`.

    Args:
        draft: Modelo intermedio revisado.
        generated_at: Marca temporal opcional. Si no se informa, se usa UTC.

    Returns:
        Diccionario con `requirements.md`, `design.md`, `tasks.md` y
        `test-plan.md`.
    """
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    return {
        "requirements.md": _render_spec_requirements(draft, generated_at),
        "design.md": _render_spec_design(draft, generated_at),
        "tasks.md": _render_spec_tasks(draft, generated_at),
        "test-plan.md": _render_spec_test_plan(draft, generated_at),
    }


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


class SafeSpecWriter:
    """Escribe una spec H5 completa sin sobrescribir por defecto."""

    def write(
        self,
        output_dir: Path,
        documents: Mapping[str, str],
        *,
        overwrite: bool = False,
    ) -> tuple[Path, ...]:
        """Escribe documentos Markdown H5 en un directorio seguro.

        La escritura hace preflight antes de crear archivos: valida nombres
        esperados, directorio destino y no-overwrite. Con `overwrite=True` solo
        reemplaza los cuatro archivos esperados; no elimina contenido extra.
        """
        resolved_dir = output_dir.expanduser().resolve(strict=False)
        _validate_spec_output_dir(resolved_dir)
        _validate_spec_documents_for_write(documents)
        if resolved_dir.exists() and not resolved_dir.is_dir():
            raise FileExistsError(f"La ruta de salida no es un directorio: {resolved_dir}")
        if resolved_dir.exists() and not overwrite:
            raise FileExistsError(
                f"La spec ya existe en {resolved_dir}. Usa --overwrite para reemplazar."
            )
        targets = tuple((resolved_dir / filename) for filename in SPEC_MARKDOWN_FILES)
        resolved_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for path in targets:
            path.write_text(documents[path.name], encoding="utf-8")
            written.append(path)
        return tuple(written)


class SpecDocumentReader:
    """Lee los documentos Markdown esperados de una spec H5 existente."""

    def read(self, input_dir: Path) -> dict[str, str]:
        """Carga archivos Markdown H5 desde un directorio.

        Los documentos faltantes se omiten para que `SpecValidator` reporte la
        inconsistencia con sus codigos estructurales. Las rutas que no son
        carpetas o entradas que deberian ser archivos se tratan como errores de
        operacion.
        """
        resolved_dir = input_dir.expanduser().resolve(strict=False)
        if not resolved_dir.exists():
            raise FileNotFoundError(f"La carpeta de spec no existe: {resolved_dir}")
        if not resolved_dir.is_dir():
            raise NotADirectoryError(
                f"La ruta de spec no es un directorio: {resolved_dir}"
            )

        documents: dict[str, str] = {}
        for filename in SPEC_MARKDOWN_FILES:
            path = resolved_dir / filename
            if not path.exists():
                continue
            if not path.is_file():
                raise IsADirectoryError(
                    f"La entrada esperada no es un archivo: {path}"
                )
            documents[filename] = path.read_text(encoding="utf-8")
        return documents


def safe_spec_slug(value: str) -> str:
    """Construye un slug seguro para carpetas de spec."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_text.lower()).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:80].strip("-") or "spec"


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


def _render_spec_requirements(draft: SpecDraft, generated_at: str) -> str:
    requirement = _primary_requirement(draft)
    lines = [
        f"# Requisitos - {_spec_title(draft)}",
        "",
        "## Metadata",
        f"- generado_en: {generated_at}",
        f"- template_version: {SPEC_TEMPLATE_VERSION}",
        f"- draft_id: {draft.draft_id}",
        f"- modo: {draft.request.retrieval_mode}",
        "",
        "## Objetivo",
        f"- {draft.intent.original_text}",
        "",
        "## Alcance",
        f"- {requirement}",
        "",
        "## Fuera de alcance",
        "- generacion automatica de codigo",
        "- aprobacion funcional sin revision humana",
        "",
        "## Historias de usuario",
        f"- HU-001 Como mantenedor, quiero {draft.intent.original_text} para evolucionar el sistema con trazabilidad.",
        "",
        "## Requisitos funcionales",
    ]
    lines.extend(_render_requirements(draft))
    lines.extend(
        [
            "",
            "## Requisitos no funcionales",
            "- RNF-001 Mantener trazabilidad entre requisitos, decisiones, tareas, pruebas y evidencia.",
            "- RNF-002 Generar Markdown estable y editable.",
            "",
            "## Supuestos",
        ]
    )
    lines.extend(_list_or_empty(draft.assumptions, "sin supuestos declarados"))
    lines.extend(["", "## Preguntas abiertas"])
    lines.extend(_list_or_empty(draft.open_questions, "sin preguntas abiertas"))
    lines.extend(["", "## Evidencia"])
    lines.extend(_spec_evidence_lines(draft.evidence))
    lines.extend(
        [
            "",
            "## Trazabilidad",
            "- REQ-001 -> TASK-001, TEST-001",
            "",
        ]
    )
    return "\n".join(lines)


def _render_spec_design(draft: SpecDraft, generated_at: str) -> str:
    lines = [
        f"# Diseno - {_spec_title(draft)}",
        "",
        "## Metadata",
        f"- generado_en: {generated_at}",
        f"- template_version: {SPEC_TEMPLATE_VERSION}",
        f"- draft_id: {draft.draft_id}",
        "",
        "## Contexto",
        f"- requerimiento: {draft.intent.original_text}",
        "",
        "## Arquitectura funcional",
        "- Spec Mode coordina evidencia documental H3, impacto H4 y sintesis conservadora.",
        "",
        "## Integracion con sistema existente",
    ]
    lines.extend(_spec_component_lines(draft.affected_components))
    lines.extend(
        [
            "",
            "## Flujo propuesto",
            "1. Confirmar reglas existentes con evidencia citada.",
            "2. Revisar componentes afectados y relaciones por confirmar.",
            "3. Implementar el cambio manteniendo pruebas asociadas a REQ-001.",
            "",
            "## Componentes afectados",
        ]
    )
    lines.extend(_spec_component_lines(draft.affected_components))
    lines.extend(["", "## Cambios propuestos"])
    lines.extend(_render_existing_rules(draft.existing_rules))
    lines.extend(
        [
            "",
            "## Modelo de datos si aplica",
            "- por confirmar durante diseno detallado",
            "",
            "## CLI o interfaz si aplica",
            "- por confirmar durante refinamiento",
            "",
            "## Manejo de errores",
            "- fallar con mensajes accionables en espanol para errores esperados",
            "",
            "## Decisiones tecnicas",
        ]
    )
    lines.extend(_list_or_empty(draft.design_decisions, "sin decisiones tecnicas adicionales"))
    lines.extend(["", "## Riesgos y limites"])
    lines.extend(_list_or_empty(draft.risks, "sin riesgos adicionales detectados"))
    lines.extend(
        [
            "",
            "## Diagramas Mermaid",
            "```mermaid",
            "flowchart LR",
            '    REQ["REQ-001 Requerimiento"] --> H3["Evidencia H3"]',
            '    REQ --> H4["Impacto H4"]',
            '    H3 --> SPEC["SpecDraft"]',
            '    H4 --> SPEC',
            '    SPEC --> REVIEW["Review"]',
            '    REVIEW --> MD["Markdown spec.v1"]',
            "```",
            "",
            "## Evidencia",
        ]
    )
    lines.extend(_spec_evidence_lines(draft.evidence))
    lines.append("")
    return "\n".join(lines)


def _render_spec_tasks(draft: SpecDraft, generated_at: str) -> str:
    lines = [
        f"# Tareas - {_spec_title(draft)}",
        "",
        "## Metadata",
        f"- generado_en: {generated_at}",
        f"- template_version: {SPEC_TEMPLATE_VERSION}",
        f"- draft_id: {draft.draft_id}",
        "",
        "## Reglas",
        "- implementar tareas en orden",
        "- no generar codigo automaticamente fuera del alcance de la spec",
        "- mantener trazabilidad con REQ-001",
        "",
        "## Tareas implementables",
        "### TASK-001 - Analizar alcance detallado",
        "**Objetivo:** confirmar alcance y evidencia de REQ-001.",
        "**Descripcion:** revisar reglas, componentes afectados, riesgos y preguntas abiertas.",
        "**Dependencias:** ninguna.",
        "**Resultado esperado:** alcance confirmado o vacios documentados.",
        "**Requisito:** REQ-001.",
        "",
        "### TASK-002 - Implementar cambio funcional",
        "**Objetivo:** aplicar el cambio de REQ-001.",
        "**Descripcion:** modificar solo los componentes confirmados y conservar trazabilidad.",
        "**Dependencias:** TASK-001.",
        "**Resultado esperado:** cambio implementado con pruebas unitarias o de integracion.",
        "**Requisito:** REQ-001.",
        "",
        "### TASK-003 - Validacion y aceptacion integral",
        "**Objetivo:** ejecutar validacion final de REQ-001.",
        "**Descripcion:** correr pruebas, revisar evidencia, validar regresion y registrar aceptacion humana.",
        "**Dependencias:** TASK-002.",
        "**Resultado esperado:** spec lista para aceptacion o feedback documentado.",
        "**Requisito:** REQ-001.",
        "",
        "## Orden de ejecucion",
        "```mermaid",
        "flowchart LR",
        '    T1["TASK-001"] --> T2["TASK-002"]',
        '    T2 --> T3["TASK-003 Aceptacion integral"]',
        "```",
        "",
        "## Trazabilidad",
        "| Tarea | Requisito | Prueba |",
        "|---|---|---|",
        "| TASK-001 | REQ-001 | TEST-001 |",
        "| TASK-002 | REQ-001 | TEST-002 |",
        "| TASK-003 | REQ-001 | TEST-003 |",
        "",
        "## Ultima tarea de validacion y aceptacion integral",
        "- TASK-003 concentra la aceptacion integral.",
        "",
    ]
    return "\n".join(lines)


def _render_spec_test_plan(draft: SpecDraft, generated_at: str) -> str:
    lines = [
        f"# Plan de pruebas - {_spec_title(draft)}",
        "",
        "## Metadata",
        f"- generado_en: {generated_at}",
        f"- template_version: {SPEC_TEMPLATE_VERSION}",
        f"- draft_id: {draft.draft_id}",
        "",
        "## Estrategia",
        "- validar REQ-001 con pruebas proporcionales al impacto y evidencia recuperada",
        "",
        "## Unitarias",
        "- TEST-001 cubrir reglas puras o transformaciones deterministicas de REQ-001",
        "",
        "## Integracion",
        "- TEST-002 cubrir componentes afectados confirmados por H4",
        "",
        "## CLI",
        "- verificar comandos o flujos de usuario cuando aplique",
        "",
        "## Regresion",
        "- ejecutar regresion sobre funcionalidades vecinas y consumidores identificados",
        "",
        "## Casos negativos",
        "- validar errores esperados y condiciones limite",
        "",
        "## Golden files si aplica",
        "- usar golden files cuando el cambio produzca Markdown o salida estable",
        "",
        "## Evidencia esperada",
    ]
    lines.extend(_spec_evidence_lines(draft.evidence))
    lines.extend(
        [
            "",
            "## Matriz requisito-prueba",
            "| Requisito | Prueba | Tipo |",
            "|---|---|---|",
            "| REQ-001 | TEST-001 | unitaria |",
            "| REQ-001 | TEST-002 | integracion |",
            "| REQ-001 | TEST-003 | regresion |",
            "",
        ]
    )
    return "\n".join(lines)


def _spec_title(draft: SpecDraft) -> str:
    return draft.request.name or "spec generada"


def _primary_requirement(draft: SpecDraft) -> str:
    if draft.requirements:
        return draft.requirements[0]
    citations = _supporting_evidence_refs(draft.existing_rules)
    suffix = f" {citations}" if citations else " (evidencia insuficiente)"
    return f"REQ-001 {draft.intent.original_text}{suffix}"


def _render_requirements(draft: SpecDraft) -> list[str]:
    if draft.requirements:
        return [f"- {requirement}" for requirement in draft.requirements]
    return [f"- {_primary_requirement(draft)}"]


def _render_existing_rules(rules: tuple[ExistingRule, ...]) -> list[str]:
    if not rules:
        return ["- por confirmar: no hay reglas existentes detectadas con evidencia documental"]
    return [
        f"- {rule.rule_id} {rule.description} {_supporting_evidence_refs((rule,))}"
        for rule in rules
    ]


def _supporting_evidence_refs(rules: tuple[ExistingRule, ...]) -> str:
    ids: list[str] = []
    seen: set[str] = set()
    for rule in rules:
        for evidence_id in rule.evidence_ids:
            if evidence_id in seen:
                continue
            ids.append(f"[{evidence_id}]")
            seen.add(evidence_id)
    return " ".join(ids)


def _spec_component_lines(components: tuple[AffectedComponent, ...]) -> list[str]:
    if not components:
        return ["- sin componentes afectados confirmados"]
    return [
        (
            f"- `{component.name}` rol={component.role.value} "
            f"tecnologia={component.technology} "
            f"clasificacion={component.classification.value} "
            f"evidencia={_inline_refs(component.evidence_ids)}"
        )
        for component in components
    ]


def _spec_evidence_lines(evidence: tuple[SpecEvidenceItem, ...]) -> list[str]:
    if not evidence:
        return ["- evidencia insuficiente"]
    return [
        (
            f"- [{item.evidence_id}] {item.source_type.value}: "
            f"{item.title}; {item.citation}"
        )
        for item in evidence
    ]


def _inline_refs(evidence_ids: tuple[str, ...]) -> str:
    if not evidence_ids:
        return "por_confirmar"
    return " ".join(f"[{evidence_id}]" for evidence_id in evidence_ids)


def _validate_spec_documents_for_write(documents: Mapping[str, str]) -> None:
    names = tuple(documents)
    if names != SPEC_MARKDOWN_FILES:
        expected = ", ".join(SPEC_MARKDOWN_FILES)
        received = ", ".join(names)
        raise ValueError(
            f"Los documentos H5 deben ser exactamente: {expected}. Recibido: {received}."
        )
    for filename, content in documents.items():
        if "/" in filename or "\\" in filename or Path(filename).name != filename:
            raise ValueError(f"Nombre de documento no permitido: {filename}.")
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"Documento H5 vacio: {filename}.")


def _validate_spec_output_dir(output_dir: Path) -> None:
    parts = output_dir.parts
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"Ruta de salida no valida: {output_dir}.")


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
