"""Modelos puros para H4 Reverse Engineering.

El modulo define identidades, estados y validaciones de dominio para simbolos,
referencias y relaciones H4. No accede a infraestructura ni persiste datos; su
responsabilidad es mantener contratos inmutables y reproducibles para las capas
de aplicacion e infraestructura.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from barbarion.domain.models import Confidence


class H4AnalysisRunMode(StrEnum):
    """Modo operativo de una corrida H4."""

    INCREMENTAL = "incremental"
    FULL = "full"
    PARTIAL = "partial"


class H4AnalysisRunStatus(StrEnum):
    """Estado persistible de una corrida H4."""

    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class H4SymbolStatus(StrEnum):
    """Estado vigente de un simbolo H4."""

    ACTIVE = "active"
    STALE = "stale"
    DELETED = "deleted"
    AMBIGUOUS = "ambiguous"


class H4ResolutionStatus(StrEnum):
    """Estado de resolucion de una referencia o relacion H4."""

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"
    EXTERNAL = "external"
    DYNAMIC = "dynamic"


class H4Classification(StrEnum):
    """Clasificacion de evidencia de una relacion H4."""

    DETECTED = "detectado"
    INFERRED = "inferido"
    TO_CONFIRM = "por_confirmar"


class H4RelationStatus(StrEnum):
    """Estado vigente de una relacion H4."""

    ACTIVE = "active"
    STALE = "stale"
    DELETED = "deleted"


class H4DependencyDirection(StrEnum):
    """Direccion calculada para recorrer dependencias desde una semilla."""

    INCOMING = "incoming"
    OUTGOING = "outgoing"
    BOTH = "both"


@dataclass(frozen=True, slots=True)
class H4AnalysisRunRecord:
    """Resumen persistido de una corrida H4.

    El registro representa el estado observable de una ejecucion H4. Sus
    conteos nunca son negativos y `scope` se congela para evitar mutaciones
    accidentales despues de construido el objeto.
    """

    id: int
    mode: H4AnalysisRunMode
    status: H4AnalysisRunStatus
    scope: dict[str, Any] = field(default_factory=dict)
    symbols_detected: int = 0
    references_detected: int = 0
    relations_resolved: int = 0
    relations_unresolved: int = 0
    relations_ambiguous: int = 0
    warning_count: int = 0
    error_count: int = 0
    duration_ms: int | None = None

    def __post_init__(self) -> None:
        """Valida invariantes numericas y congela el alcance de la corrida."""
        _require_positive(self.id, "id")
        for field_name in (
            "symbols_detected",
            "references_detected",
            "relations_resolved",
            "relations_unresolved",
            "relations_ambiguous",
            "warning_count",
            "error_count",
        ):
            _require_non_negative(getattr(self, field_name), field_name)
        if self.duration_ms is not None:
            _require_non_negative(self.duration_ms, "duration_ms")
        object.__setattr__(self, "scope", _freeze_mapping(self.scope))


@dataclass(frozen=True, slots=True)
class H4Symbol:
    """Simbolo logico detectado por H4.

    Un simbolo representa la identidad consultable de una unidad tecnica, como
    un package, procedure, evento, ventana o tabla. `symbol_id` es una identidad
    determinista de 64 caracteres y los nombres normalizados deben llegar ya
    preparados por la capa que construye el modelo.

    Note:
        `metadata` se copia y congela durante la inicializacion para preservar
        la inmutabilidad externa de la dataclass.
    """

    symbol_id: str
    original_name: str
    normalized_name: str
    symbol_type: str
    technology: str
    extraction_method: str
    confidence: Confidence
    file_id: int | None = None
    document_id: int | None = None
    chunk_id: str | None = None
    parent_symbol_id: str | None = None
    container_name: str | None = None
    signature: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    status: H4SymbolStatus = H4SymbolStatus.ACTIVE
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Valida identidad, campos obligatorios y rangos de ubicacion."""
        _require_sha256(self.symbol_id, "symbol_id")
        _require_non_empty(self.original_name, "original_name")
        _require_non_empty(self.normalized_name, "normalized_name")
        _require_non_empty(self.symbol_type, "symbol_type")
        _require_non_empty(self.technology, "technology")
        _require_non_empty(self.extraction_method, "extraction_method")
        _validate_optional_positive(self.file_id, "file_id")
        _validate_optional_positive(self.document_id, "document_id")
        if self.chunk_id is not None:
            _require_non_empty(self.chunk_id, "chunk_id")
        if self.parent_symbol_id is not None:
            _require_sha256(self.parent_symbol_id, "parent_symbol_id")
        if self.container_name is not None:
            _require_non_empty(self.container_name, "container_name")
        if self.signature is not None:
            _require_non_empty(self.signature, "signature")
        _validate_optional_range(self.start_line, self.end_line, "line")
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class H4Reference:
    """Referencia textual detectada antes o despues de resolverla.

    La referencia conserva evidencia de origen, objetivo normalizado y estado de
    resolucion. Puede permanecer `unresolved`, `dynamic` o `external` sin que
    exista una relacion exacta hacia un simbolo interno.

    Note:
        El modelo no resuelve por si mismo; solo valida que la evidencia
        recibida sea consistente y trazable.
    """

    reference_id: str
    source_file_id: int
    raw_text: str
    normalized_target: str
    reference_type: str
    technology: str
    detection_method: str
    confidence: Confidence
    resolution_status: H4ResolutionStatus
    source_symbol_id: str | None = None
    source_chunk_id: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Valida identidad, origen, evidencia textual y rangos opcionales."""
        _require_sha256(self.reference_id, "reference_id")
        _require_positive(self.source_file_id, "source_file_id")
        _require_non_empty(self.raw_text, "raw_text")
        _require_non_empty(self.normalized_target, "normalized_target")
        _require_non_empty(self.reference_type, "reference_type")
        _require_non_empty(self.technology, "technology")
        _require_non_empty(self.detection_method, "detection_method")
        if self.source_symbol_id is not None:
            _require_sha256(self.source_symbol_id, "source_symbol_id")
        if self.source_chunk_id is not None:
            _require_non_empty(self.source_chunk_id, "source_chunk_id")
        _validate_optional_range(self.start_line, self.end_line, "line")
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class H4Relation:
    """Relacion canonica `source -> target` derivada de una referencia.

    La relacion almacena origen, destino resuelto o clave objetivo, y evidencia
    de archivo/chunk. La direccion de consulta no se persiste: se calcula segun
    el simbolo desde el que se navega.

    Warning:
        Las relaciones con `resolution_status` dynamic deben conservar
        `classification` como `TO_CONFIRM`.
    """

    relation_id: str
    reference_id: str
    relation_type: str
    classification: H4Classification
    resolution_status: H4ResolutionStatus
    confidence: Confidence
    evidence_file_id: int
    source_symbol_id: str | None = None
    target_symbol_id: str | None = None
    target_key: str | None = None
    evidence_chunk_id: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    notes: str | None = None
    status: H4RelationStatus = H4RelationStatus.ACTIVE

    def __post_init__(self) -> None:
        """Valida identidad, evidencia y restricciones de relaciones dinamicas."""
        _require_sha256(self.relation_id, "relation_id")
        _require_sha256(self.reference_id, "reference_id")
        _require_non_empty(self.relation_type, "relation_type")
        _require_positive(self.evidence_file_id, "evidence_file_id")
        if self.source_symbol_id is not None:
            _require_sha256(self.source_symbol_id, "source_symbol_id")
        if self.target_symbol_id is not None:
            _require_sha256(self.target_symbol_id, "target_symbol_id")
        if self.target_key is not None:
            _require_non_empty(self.target_key, "target_key")
        if self.evidence_chunk_id is not None:
            _require_non_empty(self.evidence_chunk_id, "evidence_chunk_id")
        if self.notes is not None:
            _require_non_empty(self.notes, "notes")
        if (
            self.resolution_status == H4ResolutionStatus.DYNAMIC
            and self.classification != H4Classification.TO_CONFIRM
        ):
            raise ValueError("Las relaciones dynamic requieren clasificacion por_confirmar.")
        _validate_optional_range(self.start_line, self.end_line, "line")


@dataclass(frozen=True, slots=True)
class H4RelationCandidate:
    """Candidato alternativo para una relacion ambigua.

    Se usa cuando una referencia coincide con mas de un simbolo compatible. El
    `rank` expresa el orden estable calculado por el resolvedor, no una certeza
    semantica.
    """

    relation_id: str
    candidate_symbol_id: str
    rank: int
    reason: str

    def __post_init__(self) -> None:
        """Valida identidad de relacion, simbolo candidato y ranking."""
        _require_sha256(self.relation_id, "relation_id")
        _require_sha256(self.candidate_symbol_id, "candidate_symbol_id")
        _require_positive(self.rank, "rank")
        _require_non_empty(self.reason, "reason")


@dataclass(frozen=True, slots=True)
class H4DependencyFilters:
    """Filtros aplicables al recorrido de dependencias H4.

    Los filtros se evaluan sobre relaciones activas ya persistidas. `technology`
    se compara contra los simbolos origen o destino disponibles; las relaciones
    sin simbolo destino siguen siendo visibles si el simbolo origen coincide.
    """

    technology: str | None = None
    relation_type: str | None = None
    resolution_status: H4ResolutionStatus | None = None
    min_confidence: Confidence | None = None


@dataclass(frozen=True, slots=True)
class H4DependencyNode:
    """Nodo visible en un recorrido BFS de dependencias.

    Attributes:
        symbol: Simbolo activo alcanzado por el recorrido.
        depth: Distancia desde el simbolo semilla.
    """

    symbol: H4Symbol
    depth: int

    def __post_init__(self) -> None:
        """Valida que la profundidad del nodo sea no negativa."""
        _require_non_negative(self.depth, "depth")


@dataclass(frozen=True, slots=True)
class H4DependencyEdge:
    """Arista visible derivada de una relacion H4 activa.

    La arista conserva la relacion original y la direccion calculada desde el
    nodo expandido. Si la relacion no tiene destino resuelto, `target_symbol`
    queda en `None` y `target_key` permite mostrar la hoja unresolved, ambiguous,
    dynamic o external.
    """

    relation: H4Relation
    depth: int
    direction: H4DependencyDirection
    source_symbol: H4Symbol | None
    target_symbol: H4Symbol | None
    target_key: str | None
    candidate_symbol_ids: tuple[str, ...] = ()
    is_cycle: bool = False

    def __post_init__(self) -> None:
        """Valida profundidad y candidatos de una arista de dependencia."""
        _require_non_negative(self.depth, "depth")
        for candidate_symbol_id in self.candidate_symbol_ids:
            _require_sha256(candidate_symbol_id, "candidate_symbol_id")


@dataclass(frozen=True, slots=True)
class H4DependencyWalk:
    """Resultado completo de un recorrido BFS de dependencias H4.

    `nodes` contiene simbolos activos alcanzados hasta el limite solicitado.
    `edges` conserva tambien hojas unresolved, ambiguous, dynamic y external,
    porque esas relaciones son evidencia relevante aunque no agreguen nodos al
    recorrido.
    """

    seed_symbol_id: str
    direction: H4DependencyDirection
    max_depth: int
    node_limit: int
    nodes: tuple[H4DependencyNode, ...]
    edges: tuple[H4DependencyEdge, ...]
    cycles: tuple[tuple[str, ...], ...] = ()
    limit_reached: bool = False

    def __post_init__(self) -> None:
        """Valida limites y la identidad de la semilla."""
        _require_sha256(self.seed_symbol_id, "seed_symbol_id")
        _require_non_negative(self.max_depth, "max_depth")
        _require_positive(self.node_limit, "node_limit")


@dataclass(frozen=True, slots=True)
class H4ObjectResolution:
    """Resultado determinista de resolver un objeto tecnico solicitado.

    El resultado evita elegir automaticamente cuando hay multiples simbolos
    compatibles. Los servicios `describe` e `impact` solo continuan con walks
    cuando `symbol` esta presente.
    """

    query: str
    symbol: H4Symbol | None = None
    candidates: tuple[H4Symbol, ...] = ()
    status: str = "resolved"

    def __post_init__(self) -> None:
        """Valida la consulta y el estado declarado de resolucion."""
        _require_non_empty(self.query, "query")
        if self.status not in {"resolved", "not_found", "ambiguous"}:
            raise ValueError("status debe ser resolved, not_found o ambiguous.")


@dataclass(frozen=True, slots=True)
class H4EvidenceItem:
    """Evidencia trazable usada por servicios H4 de descripcion e impacto.

    Attributes:
        source: Origen logico de la evidencia, por ejemplo `symbol`, `relation`
            o `rag`.
        detail: Texto breve y estable que puede mostrarse en salidas futuras.
        reference_id: Identificador opcional de referencia H4.
        relation_id: Identificador opcional de relacion H4.
        chunk_id: Chunk opcional asociado a la evidencia.
    """

    source: str
    detail: str
    reference_id: str | None = None
    relation_id: str | None = None
    chunk_id: str | None = None

    def __post_init__(self) -> None:
        """Valida origen, detalle e identificadores opcionales."""
        _require_non_empty(self.source, "source")
        _require_non_empty(self.detail, "detail")
        if self.reference_id is not None:
            _require_sha256(self.reference_id, "reference_id")
        if self.relation_id is not None:
            _require_sha256(self.relation_id, "relation_id")
        if self.chunk_id is not None:
            _require_non_empty(self.chunk_id, "chunk_id")


@dataclass(frozen=True, slots=True)
class H4ComponentDescription:
    """DTO determinista producido por el servicio `describe`.

    Incluye resolucion del objeto, relaciones relevantes, evidencia,
    limitaciones y una sintesis opcional. Cuando `no_llm` es verdadero, la
    sintesis proviene solo de datos estructurados.
    """

    resolution: H4ObjectResolution
    outgoing: H4DependencyWalk | None = None
    incoming: H4DependencyWalk | None = None
    responsibilities: tuple[str, ...] = ()
    evidence: tuple[H4EvidenceItem, ...] = ()
    inferences: tuple[str, ...] = ()
    to_confirm: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    rag_sources: tuple[str, ...] = ()
    summary: str = ""
    no_llm: bool = True

    def __post_init__(self) -> None:
        """Valida que la sintesis no quede vacia."""
        _require_non_empty(self.summary, "summary")


@dataclass(frozen=True, slots=True)
class H4ImpactAnalysis:
    """DTO determinista producido por el servicio `impact`.

    El impacto se deriva de recorridos de dependencias, no de similitud
    semantica. RAG y LLM pueden aportar evidencia o sintesis, pero no cambian
    los nodos ni aristas seleccionados.
    """

    resolution: H4ObjectResolution
    walk: H4DependencyWalk | None = None
    consumers: tuple[H4DependencyEdge, ...] = ()
    dependencies: tuple[H4DependencyEdge, ...] = ()
    indirect: tuple[H4DependencyEdge, ...] = ()
    cross_technology: tuple[H4DependencyEdge, ...] = ()
    risks: tuple[str, ...] = ()
    to_confirm: tuple[str, ...] = ()
    evidence: tuple[H4EvidenceItem, ...] = ()
    limitations: tuple[str, ...] = ()
    rag_sources: tuple[str, ...] = ()
    summary: str = ""
    no_llm: bool = True

    def __post_init__(self) -> None:
        """Valida que la sintesis de impacto no quede vacia."""
        _require_non_empty(self.summary, "summary")


def normalize_symbol_name(value: str) -> str:
    """Normaliza nombres de simbolos para identidad logica y busqueda.

    Args:
        value: Nombre simple o calificado que puede incluir espacios alrededor
            de los separadores `.` o comillas externas por segmento.

    Returns:
        Nombre normalizado en minusculas, con segmentos no vacios unidos por
        puntos.

    Raises:
        ValueError: Si `value` esta vacio o no contiene identificadores.
    """
    _require_non_empty(value, "value")
    parts = [
        _unquote_identifier(part.strip())
        for part in re.split(r"\s*\.\s*", value.strip())
        if part.strip()
    ]
    if not parts:
        raise ValueError("value debe contener al menos un identificador.")
    return ".".join(part.lower() for part in parts)


def h4_symbol_id(
    *,
    normalized_name: str,
    symbol_type: str,
    technology: str,
    container_name: str | None = None,
) -> str:
    """Calcula la identidad logica determinista de un simbolo vigente.

    Args:
        normalized_name: Nombre logico del simbolo.
        symbol_type: Tipo tecnico del simbolo.
        technology: Tecnologia de origen usada para separar universos.
        container_name: Contenedor normalizado opcional del simbolo.

    Returns:
        SHA-256 hexadecimal estable para la identidad logica del simbolo.
    """
    return _sha256_payload(
        "barbarion.h4.symbol-id.v1",
        {
            "container_name": normalize_symbol_name(container_name)
            if container_name
            else None,
            "normalized_name": normalize_symbol_name(normalized_name),
            "symbol_type": _normalized_token(symbol_type),
            "technology": _normalized_token(technology),
        },
    )


def h4_reference_id(
    *,
    source_file_id: int,
    raw_text: str,
    normalized_target: str,
    reference_type: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    """Calcula un ID estable para una referencia textual.

    Args:
        source_file_id: Archivo donde se detecto la referencia.
        raw_text: Texto original usado como evidencia.
        normalized_target: Objetivo normalizado de la referencia.
        reference_type: Tipo de referencia detectada.
        start_line: Linea inicial opcional de la evidencia.
        end_line: Linea final opcional de la evidencia.

    Returns:
        SHA-256 hexadecimal estable para la ocurrencia textual.

    Raises:
        ValueError: Si el archivo no es positivo o el rango de lineas es
        incompleto o invalido.
    """
    _require_positive(source_file_id, "source_file_id")
    _validate_optional_range(start_line, end_line, "line")
    return _sha256_payload(
        "barbarion.h4.reference-id.v1",
        {
            "end_line": end_line,
            "normalized_target": normalize_symbol_name(normalized_target),
            "raw_text": raw_text.strip(),
            "reference_type": _normalized_token(reference_type),
            "source_file_id": source_file_id,
            "start_line": start_line,
        },
    )


def h4_relation_id(
    *,
    reference_id: str,
    relation_type: str,
    source_symbol_id: str | None = None,
    target_symbol_id: str | None = None,
    target_key: str | None = None,
) -> str:
    """Calcula un ID estable para la relacion canonica `source -> target`.

    Args:
        reference_id: Identidad de la referencia que origina la relacion.
        relation_type: Tipo canonico de relacion.
        source_symbol_id: Simbolo origen opcional.
        target_symbol_id: Simbolo destino cuando la resolucion es exacta.
        target_key: Clave objetivo cuando el destino no tiene simbolo unico.

    Returns:
        SHA-256 hexadecimal estable para la relacion derivada.

    Raises:
        ValueError: Si algun identificador SHA-256 no cumple el formato
        esperado.
    """
    _require_sha256(reference_id, "reference_id")
    if source_symbol_id is not None:
        _require_sha256(source_symbol_id, "source_symbol_id")
    if target_symbol_id is not None:
        _require_sha256(target_symbol_id, "target_symbol_id")
    return _sha256_payload(
        "barbarion.h4.relation-id.v1",
        {
            "reference_id": reference_id,
            "relation_type": _normalized_token(relation_type),
            "source_symbol_id": source_symbol_id,
            "target_key": normalize_symbol_name(target_key) if target_key else None,
            "target_symbol_id": target_symbol_id,
        },
    )


def _sha256_payload(namespace: str, payload: dict[str, Any]) -> str:
    """Serializa un payload canonico y devuelve su SHA-256 hexadecimal."""
    encoded = json.dumps(
        {"namespace": namespace, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalized_token(value: str) -> str:
    """Normaliza tokens tecnicos que no admiten estructura calificada."""
    _require_non_empty(value, "value")
    return value.strip().lower()


def _unquote_identifier(value: str) -> str:
    """Remueve comillas externas simetricas de un identificador."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'", "`"}:
        return value[1:-1]
    return value


def _require_non_empty(value: str, key: str) -> None:
    """Exige que un valor sea texto no vacio."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} debe ser una cadena no vacia.")


def _require_positive(value: int, key: str) -> None:
    """Exige que un valor sea un entero positivo no booleano."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{key} debe ser un entero mayor que 0.")


def _require_non_negative(value: int, key: str) -> None:
    """Exige que un valor sea un entero no negativo no booleano."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} debe ser un entero mayor o igual que 0.")


def _validate_optional_positive(value: int | None, key: str) -> None:
    """Valida un entero positivo cuando el valor esta presente."""
    if value is not None:
        _require_positive(value, key)


def _require_sha256(value: str, key: str) -> None:
    """Exige un SHA-256 hexadecimal en minusculas."""
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{key} debe ser un SHA-256 hexadecimal en minusculas.")


def _validate_optional_range(
    start: int | None,
    end: int | None,
    label: str,
) -> None:
    """Valida que un rango opcional tenga inicio, fin y orden correcto."""
    if start is None and end is None:
        return
    if start is None or end is None:
        raise ValueError(f"El rango {label} debe tener inicio y fin.")
    _require_positive(start, f"start_{label}")
    _require_positive(end, f"end_{label}")
    if end < start:
        raise ValueError(f"El rango {label} debe terminar despues del inicio.")


def _freeze_mapping(values: dict[str, Any]) -> MappingProxyType[str, Any]:
    """Devuelve una copia de solo lectura de un diccionario."""
    return MappingProxyType(dict(values))
