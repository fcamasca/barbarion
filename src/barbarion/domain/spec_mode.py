"""Modelos puros para H5 Spec Mode.

El modulo define contratos inmutables para representar solicitudes de spec,
evidencia, componentes afectados, reglas existentes, trazabilidad y validacion.
No accede a CLI, SQLite, filesystem, RAG ni LLM; esas integraciones pertenecen
a capas posteriores.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from barbarion.domain.models import SHA256_HEX_LENGTH


class SpecConclusionKind(StrEnum):
    """Clasificacion de una conclusion dentro de Spec Mode."""

    DETECTED = "detectado"
    INFERRED = "inferido"
    ASSUMPTION = "supuesto"
    TO_CONFIRM = "por_confirmar"


class EvidenceSourceType(StrEnum):
    """Tipo de fuente usada como evidencia en una spec."""

    CHUNK = "chunk"
    DOCUMENTATION = "documentacion"
    SYMBOL = "simbolo"
    RELATION = "relacion"
    IMPACT = "impacto"


class AffectedComponentRole(StrEnum):
    """Rol de un componente dentro del analisis de impacto de una spec."""

    DIRECT = "directo"
    CONSUMER = "consumidor"
    DEPENDENCY = "dependencia"
    INDIRECT = "indirecto"
    UNKNOWN = "desconocido"


class SpecItemKind(StrEnum):
    """Tipo de elemento enlazable dentro de una spec."""

    REQUIREMENT = "requirement"
    DESIGN_DECISION = "design_decision"
    TASK = "task"
    TEST = "test"
    EVIDENCE = "evidence"
    QUESTION = "question"


class ValidationSeverity(StrEnum):
    """Severidad de un problema de validacion de spec."""

    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class SpecRequest:
    """Entrada estructurada para iniciar Spec Mode.

    Attributes:
        requirement: Texto original escrito por el usuario.
        name: Nombre logico opcional de la spec.
        retrieval_mode: Modo RAG solicitado, por ejemplo `keyword` o `hybrid`.
        depth: Profundidad H4 para impacto.
        top_k: Cantidad maxima de candidatos RAG iniciales.
        no_llm: Si es verdadero, la spec se sintetiza sin LLM real.
        overwrite: Si permite reemplazar salida existente.
        output_path: Ruta textual opcional; se valida en infraestructura.
        debug: Si habilita diagnostico adicional.
    """

    requirement: str
    name: str | None = None
    retrieval_mode: str = "hybrid"
    depth: int = 1
    top_k: int = 12
    no_llm: bool = False
    overwrite: bool = False
    output_path: str | None = None
    debug: bool = False

    def __post_init__(self) -> None:
        _require_non_empty(self.requirement, "requirement")
        if self.name is not None:
            _require_non_empty(self.name, "name")
        _require_non_empty(self.retrieval_mode, "retrieval_mode")
        _require_non_negative(self.depth, "depth")
        _require_positive(self.top_k, "top_k")
        if self.output_path is not None:
            _require_non_empty(self.output_path, "output_path")

    @property
    def request_id(self) -> str:
        """Identidad determinista de la solicitud normalizada."""
        return _sha256_payload(
            "barbarion.spec-mode.request-id.v1",
            {
                "debug": self.debug,
                "depth": self.depth,
                "name": self.name.strip() if self.name else None,
                "no_llm": self.no_llm,
                "output_path": self.output_path.strip() if self.output_path else None,
                "overwrite": self.overwrite,
                "requirement": self.requirement.strip(),
                "retrieval_mode": self.retrieval_mode.strip().lower(),
                "top_k": self.top_k,
            },
        )


@dataclass(frozen=True, slots=True)
class RequirementIntent:
    """Interpretacion inicial del requerimiento del usuario."""

    original_text: str
    goals: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    search_terms: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_non_empty(self.original_text, "original_text")
        for field_name in (
            "goals",
            "actions",
            "entities",
            "constraints",
            "assumptions",
            "open_questions",
            "search_terms",
        ):
            object.__setattr__(
                self,
                field_name,
                _validate_text_tuple(getattr(self, field_name), field_name),
            )


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """Fuente trazable usada para construir una spec."""

    evidence_id: str
    source_type: EvidenceSourceType
    title: str
    citation: str
    classification: SpecConclusionKind = SpecConclusionKind.DETECTED
    file_path: str | None = None
    chunk_id: str | None = None
    symbol_id: str | None = None
    relation_id: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    detail: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_evidence_id(self.evidence_id, "evidence_id")
        _require_non_empty(self.title, "title")
        _require_non_empty(self.citation, "citation")
        if self.file_path is not None:
            _require_non_empty(self.file_path, "file_path")
        if self.chunk_id is not None:
            _require_non_empty(self.chunk_id, "chunk_id")
        if self.symbol_id is not None:
            _require_sha256(self.symbol_id, "symbol_id")
        if self.relation_id is not None:
            _require_sha256(self.relation_id, "relation_id")
        _validate_optional_range(self.start_line, self.end_line, "line")
        if self.detail:
            _require_non_empty(self.detail, "detail")
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class AffectedComponent:
    """Componente potencialmente afectado por el requerimiento."""

    component_id: str
    name: str
    role: AffectedComponentRole
    technology: str
    classification: SpecConclusionKind
    evidence_ids: tuple[str, ...] = ()
    component_type: str | None = None
    reason: str = ""
    unresolved_reason: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.component_id, "component_id")
        _require_non_empty(self.name, "name")
        _require_non_empty(self.technology, "technology")
        if self.component_type is not None:
            _require_non_empty(self.component_type, "component_type")
        if self.reason:
            _require_non_empty(self.reason, "reason")
        if self.unresolved_reason is not None:
            _require_non_empty(self.unresolved_reason, "unresolved_reason")
        evidence_ids = _validate_evidence_ids(self.evidence_ids)
        if (
            self.classification == SpecConclusionKind.DETECTED
            and not evidence_ids
        ):
            raise ValueError("Los componentes detectados requieren evidencia.")
        object.__setattr__(self, "evidence_ids", evidence_ids)


@dataclass(frozen=True, slots=True)
class ExistingRule:
    """Regla o comportamiento existente identificado para la spec."""

    rule_id: str
    description: str
    classification: SpecConclusionKind
    evidence_ids: tuple[str, ...] = ()
    applies_to: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_prefixed_id(self.rule_id, "REG", "rule_id")
        _require_non_empty(self.description, "description")
        evidence_ids = _validate_evidence_ids(self.evidence_ids)
        if self.classification == SpecConclusionKind.DETECTED and not evidence_ids:
            raise ValueError("Las reglas detectadas requieren evidencia.")
        object.__setattr__(self, "evidence_ids", evidence_ids)
        object.__setattr__(
            self,
            "applies_to",
            _validate_text_tuple(self.applies_to, "applies_to"),
        )
        object.__setattr__(self, "gaps", _validate_text_tuple(self.gaps, "gaps"))


@dataclass(frozen=True, slots=True)
class TraceLink:
    """Enlace trazable entre elementos de la spec y evidencia."""

    source_kind: SpecItemKind
    source_id: str
    target_kind: SpecItemKind
    target_id: str
    relation: str

    def __post_init__(self) -> None:
        _require_non_empty(self.source_id, "source_id")
        _require_non_empty(self.target_id, "target_id")
        _require_non_empty(self.relation, "relation")
        if self.source_kind == self.target_kind and self.source_id == self.target_id:
            raise ValueError("Un trace link no puede apuntar al mismo elemento.")


@dataclass(frozen=True, slots=True)
class SpecDraft:
    """Modelo intermedio de una especificacion antes de renderizar Markdown."""

    draft_id: str
    request: SpecRequest
    intent: RequirementIntent
    evidence: tuple[EvidenceItem, ...] = ()
    affected_components: tuple[AffectedComponent, ...] = ()
    existing_rules: tuple[ExistingRule, ...] = ()
    requirements: tuple[str, ...] = ()
    design_decisions: tuple[str, ...] = ()
    tasks: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    trace_links: tuple[TraceLink, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_sha256(self.draft_id, "draft_id")
        _validate_unique_evidence(self.evidence)
        for field_name in (
            "requirements",
            "design_decisions",
            "tasks",
            "tests",
            "risks",
            "assumptions",
            "open_questions",
            "warnings",
        ):
            object.__setattr__(
                self,
                field_name,
                _validate_text_tuple(getattr(self, field_name), field_name),
            )


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """Problema estructural detectado al validar una spec."""

    severity: ValidationSeverity
    code: str
    message: str
    location: str | None = None
    related_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_non_empty(self.code, "code")
        _require_non_empty(self.message, "message")
        if self.location is not None:
            _require_non_empty(self.location, "location")
        object.__setattr__(
            self,
            "related_ids",
            _validate_text_tuple(self.related_ids, "related_ids"),
        )


@dataclass(frozen=True, slots=True)
class ReviewIssue:
    """Problema detectado sobre un `SpecDraft` antes del render Markdown.

    Review es una etapa interna distinta de la validacion de archivos
    renderizados. Este modelo solo representa el hallazgo; las reglas concretas
    de review pertenecen a la etapa de revisión.
    """

    severity: ValidationSeverity
    code: str
    message: str
    draft_section: str | None = None
    related_ids: tuple[str, ...] = ()
    degradable: bool = False

    def __post_init__(self) -> None:
        _require_non_empty(self.code, "code")
        _require_non_empty(self.message, "message")
        if self.draft_section is not None:
            _require_non_empty(self.draft_section, "draft_section")
        object.__setattr__(
            self,
            "related_ids",
            _validate_text_tuple(self.related_ids, "related_ids"),
        )


def spec_draft_id(request: SpecRequest, intent: RequirementIntent) -> str:
    """Calcula una identidad estable para un draft H5.

    El ID depende de la solicitud y de la interpretacion inicial, no de salidas
    posteriores del LLM. Esto permite comparar corridas deterministas.
    """

    return _sha256_payload(
        "barbarion.spec-mode.draft-id.v1",
        {
            "intent": {
                "actions": intent.actions,
                "constraints": intent.constraints,
                "entities": intent.entities,
                "goals": intent.goals,
                "open_questions": intent.open_questions,
                "search_terms": intent.search_terms,
            },
            "request_id": request.request_id,
        },
    )


def evidence_id(*, source_type: EvidenceSourceType, source_key: str) -> str:
    """Calcula un ID corto y estable para una fuente de evidencia.

    Returns:
        ID con formato `F` seguido de 12 caracteres hexadecimales.
    """

    _require_non_empty(source_key, "source_key")
    digest = _sha256_payload(
        "barbarion.spec-mode.evidence-id.v1",
        {"source_key": source_key.strip(), "source_type": source_type.value},
    )
    return f"F{digest[:12]}"


def _sha256_payload(namespace: str, payload: dict[str, Any]) -> str:
    """Serializa un payload canonico y devuelve su SHA-256 hexadecimal."""
    encoded = json.dumps(
        {"namespace": namespace, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


def _require_sha256(value: str, key: str) -> None:
    """Exige un SHA-256 hexadecimal en minusculas."""
    if (
        not isinstance(value, str)
        or len(value) != SHA256_HEX_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{key} debe ser un SHA-256 hexadecimal en minusculas.")


def _require_evidence_id(value: str, key: str) -> None:
    """Exige IDs de evidencia estables con formato `F<hex>`."""
    if not isinstance(value, str) or not re.fullmatch(r"F[0-9a-f]{12}", value):
        raise ValueError(f"{key} debe tener formato F seguido de 12 hexadecimales.")


def _require_prefixed_id(value: str, prefix: str, key: str) -> None:
    """Exige un ID legible con prefijo y tres digitos."""
    if not isinstance(value, str) or not re.fullmatch(rf"{prefix}-\d{{3}}", value):
        raise ValueError(f"{key} debe tener formato {prefix}-NNN.")


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


def _validate_text_tuple(values: tuple[str, ...], key: str) -> tuple[str, ...]:
    """Valida una tupla de textos no vacios y la normaliza a tuple."""
    if not isinstance(values, tuple):
        values = tuple(values)
    for value in values:
        _require_non_empty(value, key)
    return values


def _validate_evidence_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    """Valida IDs de evidencia y evita duplicados accidentales."""
    if not isinstance(values, tuple):
        values = tuple(values)
    for value in values:
        _require_evidence_id(value, "evidence_id")
    if len(set(values)) != len(values):
        raise ValueError("Los IDs de evidencia no deben repetirse.")
    return values


def _validate_unique_evidence(evidence: tuple[EvidenceItem, ...]) -> None:
    """Valida que la lista de evidencia no repita IDs."""
    ids = [item.evidence_id for item in evidence]
    if len(set(ids)) != len(ids):
        raise ValueError("La evidencia de un draft no debe repetir IDs.")


def _freeze_mapping(values: dict[str, Any]) -> MappingProxyType[str, Any]:
    """Devuelve una copia de solo lectura de un diccionario."""
    return MappingProxyType(dict(values))
