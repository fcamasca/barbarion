"""Servicios de aplicacion para H5 Spec Mode."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from barbarion.application.reverse_engineering import ImpactRequest, ObjectRequest
from barbarion.domain.rag import (
    ContextBuildResult,
    RetrievalFilter,
    RetrievalMode,
    SearchRequest,
)
from barbarion.domain.reverse_engineering import (
    DependencyDirection,
    DependencyEdge,
    ImpactAnalysis,
    ResolutionStatus,
    TechnicalRelation,
    TechnicalSymbol,
)
from barbarion.domain.spec_mode import (
    AffectedComponent,
    AffectedComponentRole,
    EvidenceItem,
    EvidenceSourceType,
    ExistingRule,
    RequirementIntent,
    ReviewIssue,
    SpecConclusionKind,
    SpecDraft,
    SpecRequest,
    ValidationSeverity,
    ValidationIssue,
    evidence_id,
    spec_draft_id,
)


SPEC_REQUIRED_DOCUMENTS = (
    "requirements.md",
    "design.md",
    "tasks.md",
    "test-plan.md",
)

SPEC_REQUIRED_SECTIONS = {
    "requirements.md": (
        "Objetivo",
        "Alcance",
        "Fuera de alcance",
        "Historias de usuario",
        "Requisitos funcionales",
        "Requisitos no funcionales",
        "Supuestos",
        "Preguntas abiertas",
        "Evidencia",
        "Trazabilidad",
    ),
    "design.md": (
        "Contexto",
        "Arquitectura funcional",
        "Integracion con sistema existente",
        "Flujo propuesto",
        "Componentes afectados",
        "Cambios propuestos",
        "Modelo de datos si aplica",
        "CLI o interfaz si aplica",
        "Manejo de errores",
        "Decisiones tecnicas",
        "Riesgos y limites",
        "Diagramas Mermaid",
        "Evidencia",
    ),
    "tasks.md": (
        "Reglas",
        "Tareas implementables",
        "Orden de ejecucion",
        "Trazabilidad",
        "Ultima tarea de validacion y aceptacion integral",
    ),
    "test-plan.md": (
        "Estrategia",
        "Unitarias",
        "Integracion",
        "CLI",
        "Regresion",
        "Casos negativos",
        "Golden files si aplica",
        "Evidencia esperada",
        "Matriz requisito-prueba",
    ),
}


@dataclass(frozen=True, slots=True)
class RequirementAnalyzer:
    """Interpreta un requerimiento funcional sin consultar infraestructura.

    La interpretacion inicial es conservadora y determinista: conserva el texto
    original, deriva terminos de busqueda y senala ambiguedades. La sintesis
    asistida queda fuera de esta clase para no introducir dependencia de LLM en
    H5-T02.
    """

    def analyze(self, request: SpecRequest | str) -> RequirementIntent:
        """Convierte la entrada del usuario en una intencion estructurada."""
        text = request.requirement if isinstance(request, SpecRequest) else request
        original = _compact_whitespace(text)
        if not original:
            raise ValueError("requirement debe ser una cadena no vacia.")
        normalized = _normalize_text(original)
        tokens = _important_tokens(normalized)
        actions = _extract_actions(tokens)
        entities = _extract_entities(original, normalized, tokens)
        constraints = _extract_constraints(original)
        assumptions = _extract_assumptions(original)
        search_terms = _search_terms(actions, entities, tokens)
        open_questions = _open_questions(
            actions=actions,
            entities=entities,
            constraints=constraints,
            original=original,
        )
        return RequirementIntent(
            original_text=original,
            goals=(original,),
            actions=actions,
            entities=entities,
            constraints=constraints,
            assumptions=assumptions,
            open_questions=open_questions,
            search_terms=search_terms,
        )


@dataclass(frozen=True, slots=True)
class DocumentEvidenceRequest:
    """Solicitud para recuperar evidencia documental usando H3."""

    intent: RequirementIntent
    mode: RetrievalMode = RetrievalMode.HYBRID
    filters: RetrievalFilter = RetrievalFilter()
    top_k: int = 12
    candidate_k: int | None = None
    similarity_threshold: float = 0.0
    debug: bool = False

    def __post_init__(self) -> None:
        if self.top_k <= 0:
            raise ValueError("top_k debe ser mayor que 0.")
        if self.candidate_k is not None and self.candidate_k < self.top_k:
            raise ValueError("candidate_k debe ser mayor o igual que top_k.")


@dataclass(frozen=True, slots=True)
class DocumentEvidenceResult:
    """Evidencia documental recuperada mediante H3."""

    query: str
    evidence: tuple[EvidenceItem, ...]
    context: ContextBuildResult
    omitted: tuple[dict[str, object], ...] = ()
    insufficient_evidence: bool = False


@dataclass(frozen=True, slots=True)
class DocumentEvidenceCollector:
    """Coordina SearchService y ContextBuilder de H3 para evidencia H5.

    Esta clase no rankea, no deduplica y no arma contexto por su cuenta. Solo
    construye el `SearchRequest`, llama a los servicios H3 existentes y mapea
    las fuentes finales a `EvidenceItem` de Spec Mode.
    """

    search_service: object
    context_builder: object

    def collect(self, request: DocumentEvidenceRequest) -> DocumentEvidenceResult:
        """Recupera evidencia documental usando exclusivamente contratos H3."""
        query = _evidence_query(request.intent)
        candidate_k = request.candidate_k or max(request.top_k, request.top_k * 4)
        search = self.search_service.search(
            SearchRequest(
                query=query,
                mode=request.mode,
                filters=request.filters,
                top_k=request.top_k,
                candidate_k=candidate_k,
                similarity_threshold=request.similarity_threshold,
                debug=request.debug,
            )
        )
        context = self.context_builder.build(search.candidates, debug=request.debug)
        evidence = tuple(_evidence_from_context_source(source) for source in context.sources)
        return DocumentEvidenceResult(
            query=query,
            evidence=evidence,
            context=context,
            omitted=tuple(context.omitted),
            insufficient_evidence=not evidence,
        )


@dataclass(frozen=True, slots=True)
class TechnicalImpactRequest:
    """Solicitud H5 para consumir impacto tecnico H4."""

    intent: RequirementIntent
    direction: DependencyDirection = DependencyDirection.BOTH
    depth: int = 1
    node_limit: int = 500
    include_rag: bool = False

    def __post_init__(self) -> None:
        if self.depth < 0:
            raise ValueError("depth debe ser mayor o igual que 0.")
        if self.node_limit <= 0:
            raise ValueError("node_limit debe ser mayor que 0.")


@dataclass(frozen=True, slots=True)
class TechnicalImpactResult:
    """Componentes, relaciones y advertencias obtenidos desde H4."""

    components: tuple[AffectedComponent, ...]
    evidence: tuple[EvidenceItem, ...]
    analyses: tuple[ImpactAnalysis, ...] = ()
    warnings: tuple[str, ...] = ()
    insufficient_catalog: bool = False


@dataclass(frozen=True, slots=True)
class SpecSynthesisRequest:
    """Entrada para construir el draft analitico de H5."""

    request: SpecRequest
    intent: RequirementIntent
    document_evidence: DocumentEvidenceResult | None = None
    technical_impact: TechnicalImpactResult | None = None
    no_llm: bool = True


@dataclass(frozen=True, slots=True)
class SpecSynthesizer:
    """Sintetiza hallazgos H5 de forma conservadora.

    En modo deterministico, una regla `detectado` solo se crea desde evidencia
    documental citada. La evidencia H4 aporta impacto, riesgos y preguntas; no
    se transforma en regla funcional por si sola.
    """

    def synthesize(self, request: SpecSynthesisRequest) -> SpecDraft:
        """Construye un `SpecDraft` con reglas, riesgos y preguntas abiertas."""
        document_evidence = request.document_evidence
        technical_impact = request.technical_impact
        evidence = _merge_evidence(
            document_evidence.evidence if document_evidence is not None else (),
            technical_impact.evidence if technical_impact is not None else (),
        )
        components = technical_impact.components if technical_impact is not None else ()
        existing_rules = _existing_rules_from_document_evidence(
            request.intent,
            document_evidence.evidence if document_evidence is not None else (),
        )
        risks = _synthesis_risks(document_evidence, technical_impact, components)
        assumptions = _merge_text(request.intent.assumptions)
        open_questions = _synthesis_open_questions(
            request.intent,
            existing_rules,
            document_evidence,
            technical_impact,
            components,
        )
        warnings = _synthesis_warnings(
            document_evidence,
            technical_impact,
            existing_rules,
        )
        return SpecDraft(
            draft_id=spec_draft_id(request.request, request.intent),
            request=request.request,
            intent=request.intent,
            evidence=evidence,
            affected_components=components,
            existing_rules=existing_rules,
            risks=risks,
            assumptions=assumptions,
            open_questions=open_questions,
            warnings=warnings,
        )


@dataclass(frozen=True, slots=True)
class SpecReviewResult:
    """Resultado del Review interno previo al render Markdown."""

    draft: SpecDraft
    issues: tuple[ReviewIssue, ...] = ()

    @property
    def has_errors(self) -> bool:
        """Indica si existe algun bloqueo no renderizable."""
        return any(issue.severity == ValidationSeverity.ERROR for issue in self.issues)

    @property
    def can_render(self) -> bool:
        """Permite renderizar si no hay errores duros."""
        return not self.has_errors

    @property
    def degraded(self) -> bool:
        """Indica si hay advertencias degradables."""
        return any(issue.degradable for issue in self.issues)


@dataclass(frozen=True, slots=True)
class SpecReviewer:
    """Review automatico conservador sobre `SpecDraft`.

    T06 revisa el modelo antes del render. La validacion estructural de archivos
    Markdown completos queda para H5-T07.
    """

    def review(self, draft: SpecDraft) -> SpecReviewResult:
        """Verifica evidencia, referencias basicas y degradaciones posibles."""
        issues: list[ReviewIssue] = []
        evidence_ids = {item.evidence_id for item in draft.evidence}
        _review_detected_rules(draft, evidence_ids, issues)
        _review_detected_components(draft, evidence_ids, issues)
        _review_citations(draft, evidence_ids, issues)
        _review_projected_items(draft, issues)
        _review_minimum_evidence(draft, issues)
        return SpecReviewResult(draft=draft, issues=tuple(issues))


@dataclass(frozen=True, slots=True)
class SpecValidationResult:
    """Resultado de validar documentos Markdown H5 ya renderizados."""

    issues: tuple[ValidationIssue, ...] = ()

    @property
    def valid(self) -> bool:
        """Indica si no hay errores estructurales."""
        return not any(issue.severity == ValidationSeverity.ERROR for issue in self.issues)

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        """Errores bloqueantes."""
        return tuple(
            issue for issue in self.issues if issue.severity == ValidationSeverity.ERROR
        )

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        """Advertencias no bloqueantes."""
        return tuple(
            issue for issue in self.issues if issue.severity == ValidationSeverity.WARNING
        )

    def to_text(self) -> str:
        """Renderiza issues como texto accionable para CLI."""
        if self.valid and not self.warnings:
            return "Spec valida."
        lines = ["Spec valida con advertencias." if self.valid else "Spec invalida."]
        for issue in self.issues:
            location = f" en {issue.location}" if issue.location else ""
            related = (
                f" ({', '.join(issue.related_ids)})" if issue.related_ids else ""
            )
            lines.append(
                f"- {issue.severity.value} {issue.code}{location}: "
                f"{issue.message}{related}"
            )
        return "\n".join(lines)

    def to_jsonable(self) -> dict[str, object]:
        """Devuelve una estructura serializable a JSON."""
        return {
            "valid": self.valid,
            "issues": [
                {
                    "severity": issue.severity.value,
                    "code": issue.code,
                    "message": issue.message,
                    "location": issue.location,
                    "related_ids": list(issue.related_ids),
                }
                for issue in self.issues
            ],
        }


@dataclass(frozen=True, slots=True)
class SpecCreateRequest:
    """Solicitud de aplicacion para crear una spec H5 completa."""

    spec_request: SpecRequest
    output_dir: Path


@dataclass(frozen=True, slots=True)
class SpecCreateResult:
    """Resultado del pipeline `spec create`."""

    output_dir: Path
    draft: SpecDraft
    review: SpecReviewResult
    validation: SpecValidationResult
    documents: Mapping[str, str]
    written_paths: tuple[Path, ...] = ()

    @property
    def written(self) -> bool:
        """Indica si se escribieron artefactos."""
        return bool(self.written_paths)


@dataclass(frozen=True, slots=True)
class SpecCreateService:
    """Orquesta el pipeline H5 de creacion de specs.

    La CLI solo debe construir esta clase, pasar argumentos y presentar el
    resultado. La recuperacion H3, impacto H4, sintesis, Review, Markdown,
    validacion y escritura viven en servicios dedicados.
    """

    analyzer: RequirementAnalyzer
    evidence_collector: DocumentEvidenceCollector
    impact_collector: TechnicalImpactCollector
    synthesizer: SpecSynthesizer
    reviewer: SpecReviewer
    renderer: Callable[[SpecDraft], Mapping[str, str]]
    validator: SpecValidator
    writer: object

    def create(self, request: SpecCreateRequest) -> SpecCreateResult:
        """Ejecuta el pipeline completo y escribe si Review/validacion pasan."""
        spec_request = request.spec_request
        intent = self.analyzer.analyze(spec_request)
        document_result = self.evidence_collector.collect(
            DocumentEvidenceRequest(
                intent=intent,
                mode=RetrievalMode(spec_request.retrieval_mode),
                top_k=spec_request.top_k,
                candidate_k=max(spec_request.top_k, spec_request.top_k * 4),
                debug=spec_request.debug,
            )
        )
        impact_result = self.impact_collector.collect(
            TechnicalImpactRequest(
                intent=intent,
                depth=spec_request.depth,
                include_rag=False,
            )
        )
        draft = self.synthesizer.synthesize(
            SpecSynthesisRequest(
                request=spec_request,
                intent=intent,
                document_evidence=document_result,
                technical_impact=impact_result,
                no_llm=spec_request.no_llm,
            )
        )
        review = self.reviewer.review(draft)
        documents: Mapping[str, str] = {}
        validation = SpecValidationResult()
        written_paths: tuple[Path, ...] = ()
        if review.can_render:
            documents = self.renderer(review.draft)
            validation = self.validator.validate(documents)
            if validation.valid:
                written_paths = tuple(
                    self.writer.write(
                        request.output_dir,
                        documents,
                        overwrite=spec_request.overwrite,
                    )
                )
        return SpecCreateResult(
            output_dir=request.output_dir,
            draft=draft,
            review=review,
            validation=validation,
            documents=documents,
            written_paths=written_paths,
        )


@dataclass(frozen=True, slots=True)
class SpecValidator:
    """Valida estructura Markdown, IDs, citas y trazabilidad documental.

    Esta clase no infiere reglas de negocio ni vuelve a evaluar evidencia
    funcional; ese limite pertenece al Review previo sobre `SpecDraft`.
    """

    def validate(self, documents: Mapping[str, str]) -> SpecValidationResult:
        """Valida los cuatro documentos Markdown H5 renderizados."""
        issues: list[ValidationIssue] = []
        normalized = {str(name): content for name, content in documents.items()}
        _validate_required_documents(normalized, issues)
        for filename in SPEC_REQUIRED_DOCUMENTS:
            content = normalized.get(filename)
            if content is None:
                continue
            _validate_document_text(filename, content, issues)
            _validate_required_sections(filename, content, issues)
        if issues and any(
            issue.code == "H5_SPEC_DOCUMENT_MISSING" for issue in issues
        ):
            return SpecValidationResult(tuple(issues))
        _validate_ids(normalized, issues)
        _validate_citations(normalized, issues)
        _validate_traceability(normalized, issues)
        _validate_single_acceptance_task(normalized.get("tasks.md", ""), issues)
        _validate_detected_lines_have_evidence(normalized, issues)
        return SpecValidationResult(tuple(issues))


@dataclass(frozen=True, slots=True)
class TechnicalImpactCollector:
    """Consume `ImpactService` de H4 para poblar impacto H5.

    No resuelve simbolos, no recorre relaciones y no recalcula impacto. H5 solo
    construye solicitudes H4 y mapea `ImpactAnalysis` a DTOs de Spec Mode.
    """

    impact_service: object

    def collect(self, request: TechnicalImpactRequest) -> TechnicalImpactResult:
        """Consulta impacto H4 para las entidades candidatas del requerimiento."""
        queries = _impact_queries(request.intent)
        if not queries:
            return TechnicalImpactResult(
                components=(),
                evidence=(),
                warnings=("No hay entidades candidatas para consultar impacto H4.",),
                insufficient_catalog=True,
            )

        components: list[AffectedComponent] = []
        evidence: list[EvidenceItem] = []
        analyses: list[ImpactAnalysis] = []
        warnings: list[str] = []
        seen_components: set[tuple[str, AffectedComponentRole]] = set()
        seen_evidence: set[str] = set()
        for query in queries:
            analysis = self.impact_service.analyze(
                ImpactRequest(
                    target=ObjectRequest(query=query),
                    direction=request.direction,
                    depth=request.depth,
                    node_limit=request.node_limit,
                    no_llm=True,
                    include_rag=request.include_rag,
                )
            )
            analyses.append(analysis)
            if analysis.resolution.symbol is None:
                warnings.append(_resolution_warning(query, analysis))
                for candidate in analysis.resolution.candidates:
                    _append_component(
                        components,
                        seen_components,
                        _component_from_symbol(
                            candidate,
                            role=AffectedComponentRole.UNKNOWN,
                            classification=SpecConclusionKind.TO_CONFIRM,
                            evidence_ids=(),
                            reason="candidato ambiguo reportado por H4",
                            unresolved_reason="resolucion ambigua",
                        ),
                    )
                continue

            symbol = analysis.resolution.symbol
            direct_evidence = _evidence_from_symbol(symbol, prefix="impact-target")
            _append_evidence(evidence, seen_evidence, direct_evidence)
            _append_component(
                components,
                seen_components,
                _component_from_symbol(
                    symbol,
                    role=AffectedComponentRole.DIRECT,
                    classification=SpecConclusionKind.DETECTED,
                    evidence_ids=(direct_evidence.evidence_id,),
                    reason="simbolo semilla resuelto por H4",
                ),
            )

            for edge in analysis.dependencies:
                _append_edge_component_and_evidence(
                    components,
                    evidence,
                    seen_components,
                    seen_evidence,
                    edge=edge,
                    role=AffectedComponentRole.DEPENDENCY,
                )
            for edge in analysis.consumers:
                _append_edge_component_and_evidence(
                    components,
                    evidence,
                    seen_components,
                    seen_evidence,
                    edge=edge,
                    role=AffectedComponentRole.CONSUMER,
                )
            for edge in analysis.indirect:
                _append_edge_component_and_evidence(
                    components,
                    evidence,
                    seen_components,
                    seen_evidence,
                    edge=edge,
                    role=AffectedComponentRole.INDIRECT,
                )
            for target_key in analysis.to_confirm:
                _append_component(
                    components,
                    seen_components,
                    AffectedComponent(
                        component_id=f"unresolved:{target_key}",
                        name=target_key,
                        role=AffectedComponentRole.UNKNOWN,
                        technology="unknown",
                        classification=SpecConclusionKind.TO_CONFIRM,
                        unresolved_reason="relacion H4 no resuelta o dinamica",
                    ),
                )
        return TechnicalImpactResult(
            components=tuple(components),
            evidence=tuple(evidence),
            analyses=tuple(analyses),
            warnings=tuple(warnings),
            insufficient_catalog=bool(warnings) and not evidence,
        )


def _merge_evidence(
    *groups: tuple[EvidenceItem, ...],
) -> tuple[EvidenceItem, ...]:
    """Une evidencia preservando orden y evitando IDs repetidos."""
    merged: list[EvidenceItem] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            _append_evidence(merged, seen, item)
    return tuple(merged)


def _existing_rules_from_document_evidence(
    intent: RequirementIntent,
    evidence: tuple[EvidenceItem, ...],
) -> tuple[ExistingRule, ...]:
    """Deriva reglas detectadas solo desde evidencia documental."""
    rules: list[ExistingRule] = []
    for item in evidence:
        if item.source_type not in {
            EvidenceSourceType.CHUNK,
            EvidenceSourceType.DOCUMENTATION,
        }:
            continue
        if not _evidence_supports_intent(item, intent):
            continue
        rules.append(
            ExistingRule(
                rule_id=f"REG-{len(rules) + 1:03d}",
                description=_rule_description(item, intent),
                classification=SpecConclusionKind.DETECTED,
                evidence_ids=(item.evidence_id,),
                applies_to=_rule_applies_to(item, intent),
            )
        )
    return tuple(rules)


def _evidence_supports_intent(item: EvidenceItem, intent: RequirementIntent) -> bool:
    """Comprueba solapamiento minimo entre evidencia textual e intencion."""
    text = _normalize_text(" ".join((item.title, item.detail, item.citation)))
    if not text:
        return False
    action_hit = any(action in text for action in intent.actions)
    entity_hit = any(_entity_matches_text(entity, text) for entity in intent.entities)
    term_hit = any(_normalize_text(term) in text for term in intent.search_terms)
    if intent.actions and intent.entities:
        return action_hit and entity_hit
    return action_hit or entity_hit or term_hit


def _entity_matches_text(entity: str, text: str) -> bool:
    """Evalua una entidad normalizada contra texto normalizado."""
    normalized = _normalize_text(entity)
    return normalized in text or normalized.replace("_", " ") in text


def _rule_description(item: EvidenceItem, intent: RequirementIntent) -> str:
    """Crea una descripcion conservadora de una regla respaldada."""
    subject = _first_text(intent.entities, "requerimiento")
    action = _first_text(intent.actions, "comportamiento")
    snippet = _compact_whitespace(item.detail or item.title)
    if len(snippet) > 160:
        snippet = f"{snippet[:157].rstrip()}..."
    return (
        f"Evidencia documental indica {action} relacionado con "
        f"{subject}: {snippet}"
    )


def _rule_applies_to(
    item: EvidenceItem,
    intent: RequirementIntent,
) -> tuple[str, ...]:
    """Asocia la regla a entidades explicitas o a la fuente documental."""
    if intent.entities:
        return intent.entities[:4]
    if item.file_path:
        return (item.file_path,)
    return ()


def _synthesis_risks(
    document_evidence: DocumentEvidenceResult | None,
    technical_impact: TechnicalImpactResult | None,
    components: tuple[AffectedComponent, ...],
) -> tuple[str, ...]:
    """Produce riesgos conservadores desde evidencia y advertencias previas."""
    risks: list[str] = []
    if document_evidence is None or document_evidence.insufficient_evidence:
        risks.append(
            "Evidencia documental insuficiente para confirmar reglas existentes."
        )
    if technical_impact is None or technical_impact.insufficient_catalog:
        risks.append(
            "Catalogo H4 insuficiente o no concluyente para cerrar impacto tecnico."
        )
    uncertain = tuple(
        component
        for component in components
        if component.classification == SpecConclusionKind.TO_CONFIRM
    )
    if uncertain:
        risks.append(
            "Existen componentes o relaciones H4 por confirmar: "
            f"{_component_list(uncertain)}."
        )
    technologies = {
        component.technology
        for component in components
        if component.technology and component.technology != "unknown"
    }
    if len(technologies) > 1:
        risks.append(
            "El impacto cruza tecnologias y requiere validar flujo extremo a extremo: "
            f"{', '.join(sorted(technologies))}."
        )
    return _merge_text(tuple(risks))


def _synthesis_open_questions(
    intent: RequirementIntent,
    existing_rules: tuple[ExistingRule, ...],
    document_evidence: DocumentEvidenceResult | None,
    technical_impact: TechnicalImpactResult | None,
    components: tuple[AffectedComponent, ...],
) -> tuple[str, ...]:
    """Conserva vacios como preguntas en vez de inventar conclusiones."""
    questions: list[str] = list(intent.open_questions)
    if not existing_rules:
        questions.append(
            "Que regla existente debe confirmarse funcionalmente con evidencia documental?"
        )
    if document_evidence is not None and document_evidence.insufficient_evidence:
        questions.append(
            "Que documentos o chunks adicionales describen el comportamiento actual?"
        )
    uncertain = tuple(
        component
        for component in components
        if component.classification == SpecConclusionKind.TO_CONFIRM
    )
    if uncertain:
        questions.append(
            "Que componentes H4 por confirmar deben resolverse antes de cerrar la spec: "
            f"{_component_list(uncertain)}?"
        )
    if technical_impact is not None and technical_impact.insufficient_catalog:
        questions.append(
            "El catalogo H4 esta actualizado para las entidades tecnicas consultadas?"
        )
    return _merge_text(tuple(questions))


def _synthesis_warnings(
    document_evidence: DocumentEvidenceResult | None,
    technical_impact: TechnicalImpactResult | None,
    existing_rules: tuple[ExistingRule, ...],
) -> tuple[str, ...]:
    """Agrupa advertencias operativas para etapas posteriores."""
    warnings: list[str] = []
    if document_evidence is None:
        warnings.append("No se recibio resultado de recuperacion documental H3.")
    elif document_evidence.insufficient_evidence:
        warnings.append("H3 no devolvio evidencia documental suficiente.")
    if technical_impact is None:
        warnings.append("No se recibio resultado de impacto tecnico H4.")
    else:
        warnings.extend(technical_impact.warnings)
    if not existing_rules:
        warnings.append(
            "No se genero ninguna regla detectada porque no hay evidencia documental suficiente."
        )
    return _merge_text(tuple(warnings))


def _component_list(components: tuple[AffectedComponent, ...]) -> str:
    """Renderiza una lista compacta y estable de componentes."""
    names: list[str] = []
    seen: set[str] = set()
    for component in components:
        if component.name in seen:
            continue
        names.append(component.name)
        seen.add(component.name)
    return ", ".join(names[:8])


def _merge_text(values: tuple[str, ...]) -> tuple[str, ...]:
    """Deduplica textos preservando orden."""
    merged: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _compact_whitespace(value)
        if not text or text in seen:
            continue
        merged.append(text)
        seen.add(text)
    return tuple(merged)


def _first_text(values: tuple[str, ...], fallback: str) -> str:
    """Devuelve el primer texto disponible."""
    return values[0] if values else fallback


def _review_detected_rules(
    draft: SpecDraft,
    evidence_ids: set[str],
    issues: list[ReviewIssue],
) -> None:
    """Valida que reglas detectadas sigan respaldadas por evidencia."""
    for rule in draft.existing_rules:
        missing = tuple(
            evidence_id
            for evidence_id in rule.evidence_ids
            if evidence_id not in evidence_ids
        )
        if rule.classification == SpecConclusionKind.DETECTED and missing:
            issues.append(
                ReviewIssue(
                    severity=ValidationSeverity.ERROR,
                    code="H5_REVIEW_RULE_EVIDENCE_MISSING",
                    message=(
                        f"La regla {rule.rule_id} esta marcada como detectada "
                        "pero referencia evidencia inexistente."
                    ),
                    draft_section="existing_rules",
                    related_ids=(rule.rule_id, *missing),
                )
            )


def _review_detected_components(
    draft: SpecDraft,
    evidence_ids: set[str],
    issues: list[ReviewIssue],
) -> None:
    """Valida que componentes detectados apunten a evidencia existente."""
    for component in draft.affected_components:
        missing = tuple(
            evidence_id
            for evidence_id in component.evidence_ids
            if evidence_id not in evidence_ids
        )
        if component.classification == SpecConclusionKind.DETECTED and missing:
            issues.append(
                ReviewIssue(
                    severity=ValidationSeverity.ERROR,
                    code="H5_REVIEW_COMPONENT_EVIDENCE_MISSING",
                    message=(
                        f"El componente {component.name} esta marcado como "
                        "detectado pero referencia evidencia inexistente."
                    ),
                    draft_section="affected_components",
                    related_ids=(component.component_id, *missing),
                )
            )


def _review_citations(
    draft: SpecDraft,
    evidence_ids: set[str],
    issues: list[ReviewIssue],
) -> None:
    """Busca citas H5 en textos del draft y valida que existan."""
    for section, values in _draft_text_sections(draft):
        for value in values:
            missing = tuple(
                citation
                for citation in _citation_ids(value)
                if citation not in evidence_ids
            )
            if missing:
                issues.append(
                    ReviewIssue(
                        severity=ValidationSeverity.ERROR,
                        code="H5_REVIEW_CITATION_MISSING",
                        message=(
                            f"La seccion {section} contiene citas sin evidencia."
                        ),
                        draft_section=section,
                        related_ids=missing,
                    )
                )


def _review_projected_items(draft: SpecDraft, issues: list[ReviewIssue]) -> None:
    """Detecta tareas y pruebas existentes sin referencia a requisito."""
    for section_name, values in (("tasks", draft.tasks), ("tests", draft.tests)):
        for index, value in enumerate(values, start=1):
            if "REQ-" not in value:
                issues.append(
                    ReviewIssue(
                        severity=ValidationSeverity.WARNING,
                        code="H5_REVIEW_ITEM_WITHOUT_REQUIREMENT",
                        message=(
                            f"El item {section_name} #{index} no referencia un requisito."
                        ),
                        draft_section=section_name,
                        related_ids=(f"{section_name}:{index}",),
                        degradable=True,
                    )
                )


def _review_minimum_evidence(draft: SpecDraft, issues: list[ReviewIssue]) -> None:
    """Marca vacios que pueden renderizarse como evidencia insuficiente."""
    if not draft.evidence:
        issues.append(
            ReviewIssue(
                severity=ValidationSeverity.WARNING,
                code="H5_REVIEW_INSUFFICIENT_EVIDENCE",
                message="El draft no tiene evidencia; se renderizara como parcial.",
                draft_section="evidence",
                degradable=True,
            )
        )
    if not draft.existing_rules:
        issues.append(
            ReviewIssue(
                severity=ValidationSeverity.WARNING,
                code="H5_REVIEW_RULES_TO_CONFIRM",
                message=(
                    "No hay reglas existentes detectadas; la seccion queda "
                    "como por confirmar."
                ),
                draft_section="existing_rules",
                degradable=True,
            )
        )


def _draft_text_sections(draft: SpecDraft) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Devuelve los campos textuales del draft revisables por citas."""
    rule_texts = tuple(rule.description for rule in draft.existing_rules)
    component_texts = tuple(component.reason for component in draft.affected_components)
    return (
        ("requirements", draft.requirements),
        ("design_decisions", draft.design_decisions),
        ("tasks", draft.tasks),
        ("tests", draft.tests),
        ("risks", draft.risks),
        ("assumptions", draft.assumptions),
        ("open_questions", draft.open_questions),
        ("warnings", draft.warnings),
        ("existing_rules", rule_texts),
        ("affected_components", component_texts),
    )


def _citation_ids(value: str) -> tuple[str, ...]:
    """Extrae citas H5 con formato `[F<hex>]`."""
    return tuple(re.findall(r"\[(F[0-9a-f]{12})\]", value))


def _validate_required_documents(
    documents: Mapping[str, str],
    issues: list[ValidationIssue],
) -> None:
    """Valida presencia de los cuatro documentos H5."""
    for filename in SPEC_REQUIRED_DOCUMENTS:
        if filename not in documents:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    code="H5_SPEC_DOCUMENT_MISSING",
                    message=f"Falta el documento requerido {filename}.",
                    location=filename,
                )
            )


def _validate_document_text(
    filename: str,
    content: str,
    issues: list[ValidationIssue],
) -> None:
    """Valida contenido minimo y version de plantilla."""
    if not isinstance(content, str) or not content.strip():
        issues.append(
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="H5_SPEC_DOCUMENT_EMPTY",
                message=f"El documento {filename} esta vacio.",
                location=filename,
            )
        )
        return
    if "template_version: spec.v1" not in content:
        issues.append(
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="H5_SPEC_TEMPLATE_VERSION_MISSING",
                message="Falta metadata template_version: spec.v1.",
                location=filename,
            )
        )


def _validate_required_sections(
    filename: str,
    content: str,
    issues: list[ValidationIssue],
) -> None:
    """Valida headings obligatorios de cada documento."""
    headings = set(_markdown_h2(content))
    for section in SPEC_REQUIRED_SECTIONS[filename]:
        if section not in headings:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    code="H5_SPEC_SECTION_MISSING",
                    message=f"Falta la seccion obligatoria {section}.",
                    location=f"{filename}#{section}",
                )
            )


def _validate_ids(
    documents: Mapping[str, str],
    issues: list[ValidationIssue],
) -> None:
    """Valida IDs duplicados de requisitos, tareas, pruebas y evidencia."""
    for kind, definitions in (
        ("REQ", _requirement_definitions(documents.get("requirements.md", ""))),
        ("TASK", _task_definitions(documents.get("tasks.md", ""))),
        ("TEST", _test_definitions(documents.get("test-plan.md", ""))),
    ):
        duplicated = tuple(
            item_id for item_id, count in definitions.items() if count > 1
        )
        if duplicated:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    code=f"H5_SPEC_{kind}_ID_DUPLICATED",
                    message=f"Hay IDs {kind} definidos mas de una vez.",
                    related_ids=duplicated,
                )
            )
    duplicated_evidence = _duplicated_evidence_ids(documents)
    if duplicated_evidence:
        issues.append(
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="H5_SPEC_EVIDENCE_ID_DUPLICATED",
                message="Hay IDs de evidencia definidos mas de una vez.",
                related_ids=duplicated_evidence,
            )
        )


def _validate_citations(
    documents: Mapping[str, str],
    issues: list[ValidationIssue],
) -> None:
    """Valida que las citas H5 existan y que la evidencia se use fuera del bloque."""
    evidence_ids = _evidence_ids(documents)
    all_citations: list[tuple[str, str]] = []
    external_citations: set[str] = set()
    for filename, content in documents.items():
        evidence_ranges = _section_ranges(content, "Evidencia") + _section_ranges(
            content,
            "Evidencia esperada",
        )
        for match in re.finditer(r"\[(F[0-9a-f]{12})\]", content):
            citation = match.group(1)
            all_citations.append((filename, citation))
            if not _inside_any(match.start(), evidence_ranges):
                external_citations.add(citation)

    missing = tuple(
        sorted(
            {
                citation
                for _, citation in all_citations
                if citation not in evidence_ids
            }
        )
    )
    if missing:
        issues.append(
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="H5_SPEC_CITATION_MISSING",
                message="Hay citas que no existen en bloques de evidencia.",
                related_ids=missing,
            )
        )

    unused = tuple(sorted(evidence_ids - external_citations))
    if unused:
        issues.append(
            ValidationIssue(
                severity=ValidationSeverity.WARNING,
                code="H5_SPEC_EVIDENCE_UNUSED",
                message="Hay evidencia declarada que no se cita fuera de evidencia.",
                related_ids=unused,
            )
        )


def _validate_traceability(
    documents: Mapping[str, str],
    issues: list[ValidationIssue],
) -> None:
    """Valida enlaces documentales entre REQ, TASK y TEST."""
    requirements = set(_requirement_definitions(documents.get("requirements.md", "")))
    tasks = set(_task_definitions(documents.get("tasks.md", "")))
    tests = set(_test_definitions(documents.get("test-plan.md", "")))

    if not requirements:
        issues.append(
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="H5_SPEC_REQUIREMENT_MISSING",
                message="No se encontro ningun requisito REQ-NNN.",
                location="requirements.md",
            )
        )
    task_requirements = _task_requirement_links(documents.get("tasks.md", ""))
    test_requirements = _test_requirement_links(documents.get("test-plan.md", ""))
    orphan_tasks = tuple(sorted(task for task in tasks if task not in task_requirements))
    orphan_tests = tuple(sorted(test for test in tests if test not in test_requirements))
    if orphan_tasks:
        issues.append(
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="H5_SPEC_TASK_WITHOUT_REQUIREMENT",
                message="Hay tareas sin enlace documental a requisito.",
                location="tasks.md",
                related_ids=orphan_tasks,
            )
        )
    if orphan_tests:
        issues.append(
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="H5_SPEC_TEST_WITHOUT_REQUIREMENT",
                message="Hay pruebas sin enlace documental a requisito.",
                location="test-plan.md",
                related_ids=orphan_tests,
            )
        )

    missing_req_links = tuple(
        sorted(
            {
                req_id
                for req_id in (*task_requirements.values(), *test_requirements.values())
                if req_id not in requirements
            }
        )
    )
    if missing_req_links:
        issues.append(
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="H5_SPEC_REQUIREMENT_REFERENCE_MISSING",
                message="Hay enlaces a requisitos no definidos.",
                related_ids=missing_req_links,
            )
        )


def _validate_single_acceptance_task(
    tasks_content: str,
    issues: list[ValidationIssue],
) -> None:
    """Valida que solo la ultima tarea concentre aceptacion integral."""
    task_matches = tuple(re.finditer(r"^###\s+(TASK-\d{3})\s+-\s+(.+)$", tasks_content, re.M))
    acceptance_tasks = tuple(
        match.group(1)
        for match in task_matches
        if "aceptacion integral" in _normalize_text(match.group(2))
    )
    if len(acceptance_tasks) != 1:
        issues.append(
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="H5_SPEC_ACCEPTANCE_TASK_COUNT",
                message="Debe existir una unica tarea de aceptacion integral.",
                location="tasks.md",
                related_ids=acceptance_tasks,
            )
        )
        return
    if task_matches and task_matches[-1].group(1) != acceptance_tasks[0]:
        issues.append(
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="H5_SPEC_ACCEPTANCE_TASK_NOT_LAST",
                message="La tarea de aceptacion integral debe ser la ultima.",
                location="tasks.md",
                related_ids=acceptance_tasks,
            )
        )


def _validate_detected_lines_have_evidence(
    documents: Mapping[str, str],
    issues: list[ValidationIssue],
) -> None:
    """Valida marcas `detectado` sin volver a razonar el contenido."""
    for filename, content in documents.items():
        evidence_ranges = _section_ranges(content, "Evidencia") + _section_ranges(
            content,
            "Evidencia esperada",
        )
        offset = 0
        for line_number, line in enumerate(content.splitlines(), start=1):
            start = offset
            offset += len(line) + 1
            if _inside_any(start, evidence_ranges):
                continue
            normalized = _normalize_text(line)
            if not re.search(r"\bdetectado\b", normalized):
                continue
            if not re.search(r"\[F[0-9a-f]{12}\]", line):
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        code="H5_SPEC_DETECTED_WITHOUT_EVIDENCE",
                        message="Una linea marcada como detectado no cita evidencia.",
                        location=f"{filename}:{line_number}",
                    )
                )


def _markdown_h2(content: str) -> tuple[str, ...]:
    """Extrae headings H2 en orden."""
    return tuple(
        _compact_whitespace(match.group(1))
        for match in re.finditer(r"^##\s+(.+?)\s*$", content, re.M)
    )


def _requirement_definitions(content: str) -> dict[str, int]:
    """Cuenta requisitos definidos en `Requisitos funcionales`."""
    counts: dict[str, int] = {}
    for section_start, section_end in _section_ranges(content, "Requisitos funcionales"):
        section = content[section_start:section_end]
        for requirement_id in re.findall(r"^\s*-\s+(REQ-\d{3})\b", section, re.M):
            counts[requirement_id] = counts.get(requirement_id, 0) + 1
    return counts


def _task_definitions(content: str) -> dict[str, int]:
    """Cuenta tareas definidas por headings `### TASK-NNN`."""
    counts: dict[str, int] = {}
    for task_id in re.findall(r"^###\s+(TASK-\d{3})\b", content, re.M):
        counts[task_id] = counts.get(task_id, 0) + 1
    return counts


def _test_definitions(content: str) -> dict[str, int]:
    """Cuenta pruebas definidas en matriz requisito-prueba."""
    counts: dict[str, int] = {}
    for line in content.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        if re.fullmatch(r"REQ-\d{3}", cells[0]) and re.fullmatch(r"TEST-\d{3}", cells[1]):
            counts[cells[1]] = counts.get(cells[1], 0) + 1
    return counts


def _evidence_ids(documents: Mapping[str, str]) -> set[str]:
    """Devuelve IDs de evidencia definidos en cualquier bloque de evidencia."""
    ids: set[str] = set()
    for content in documents.values():
        for start, end in _evidence_ranges(content):
            section = content[start:end]
            ids.update(re.findall(r"^\s*-\s+\[(F[0-9a-f]{12})\]", section, re.M))
    return ids


def _duplicated_evidence_ids(documents: Mapping[str, str]) -> tuple[str, ...]:
    """Detecta duplicados de evidencia dentro de un mismo documento."""
    duplicated: set[str] = set()
    for content in documents.values():
        counts: dict[str, int] = {}
        ranges = _evidence_ranges(content)
        for start, end in ranges:
            section = content[start:end]
            for evidence_id in re.findall(r"^\s*-\s+\[(F[0-9a-f]{12})\]", section, re.M):
                counts[evidence_id] = counts.get(evidence_id, 0) + 1
        duplicated.update(
            evidence_id for evidence_id, count in counts.items() if count > 1
        )
    return tuple(sorted(duplicated))


def _evidence_ranges(content: str) -> tuple[tuple[int, int], ...]:
    """Devuelve todos los rangos de evidencia reconocidos."""
    return _section_ranges(content, "Evidencia") + _section_ranges(
        content,
        "Evidencia esperada",
    )


def _section_ranges(content: str, section_name: str) -> tuple[tuple[int, int], ...]:
    """Devuelve rangos de una seccion H2 hasta el siguiente H2."""
    ranges: list[tuple[int, int]] = []
    pattern = re.compile(rf"^##\s+{re.escape(section_name)}\s*$", re.M)
    for match in pattern.finditer(content):
        next_heading = re.search(r"^##\s+", content[match.end():], re.M)
        end = match.end() + next_heading.start() if next_heading else len(content)
        ranges.append((match.start(), end))
    return tuple(ranges)


def _inside_any(position: int, ranges: tuple[tuple[int, int], ...]) -> bool:
    """Indica si una posicion cae dentro de alguno de los rangos."""
    return any(start <= position < end for start, end in ranges)


def _task_requirement_links(content: str) -> dict[str, str]:
    """Extrae enlace TASK -> REQ desde bloques de tareas."""
    links: dict[str, str] = {}
    task_blocks = tuple(re.finditer(r"^###\s+(TASK-\d{3})\s+-\s+.+$", content, re.M))
    for index, match in enumerate(task_blocks):
        start = match.end()
        end = task_blocks[index + 1].start() if index + 1 < len(task_blocks) else len(content)
        block = content[start:end]
        req_match = re.search(r"\*\*Requisito:\*\*\s*(REQ-\d{3})", block)
        if req_match:
            links[match.group(1)] = req_match.group(1)
    return links


def _test_requirement_links(content: str) -> dict[str, str]:
    """Extrae enlace TEST -> REQ desde matriz requisito-prueba."""
    links: dict[str, str] = {}
    for line in content.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        req_match = re.fullmatch(r"REQ-\d{3}", cells[0])
        test_match = re.fullmatch(r"TEST-\d{3}", cells[1])
        if req_match and test_match:
            links[test_match.group(0)] = req_match.group(0)
    return links


_ACTION_ALIASES: dict[str, str] = {
    "agrega": "agregar",
    "agregar": "agregar",
    "agregue": "agregar",
    "alta": "crear",
    "anadir": "agregar",
    "aprobar": "aprobar",
    "bloquear": "bloquear",
    "calcular": "calcular",
    "calcula": "calcular",
    "cambiar": "modificar",
    "consultar": "consultar",
    "crear": "crear",
    "eliminar": "eliminar",
    "generar": "generar",
    "guardar": "registrar",
    "listar": "consultar",
    "mostrar": "mostrar",
    "modificar": "modificar",
    "permitir": "permitir",
    "registrar": "registrar",
    "rechazar": "rechazar",
    "validar": "validar",
    "valida": "validar",
    "verificar": "validar",
}

_STOPWORDS = frozenset(
    {
        "ademas",
        "antes",
        "cada",
        "como",
        "cuando",
        "debe",
        "deben",
        "desde",
        "donde",
        "entre",
        "esta",
        "este",
        "esto",
        "para",
        "pero",
        "porque",
        "solo",
        "sobre",
        "todo",
        "tras",
        "una",
        "usar",
        "usuario",
    }
)

_ENTITY_STOPWORDS = _STOPWORDS | frozenset(
    {
        "agregar",
        "aprobar",
        "bloquear",
        "calcular",
        "consultar",
        "crear",
        "eliminar",
        "generar",
        "mostrar",
        "modificar",
        "permitir",
        "registrar",
        "rechazar",
        "validar",
    }
)


def _compact_whitespace(text: str) -> str:
    """Normaliza espacios sin alterar el contenido semantico."""
    if not isinstance(text, str):
        return ""
    return " ".join(text.split())


def _normalize_text(text: str) -> str:
    """Normaliza texto para extraccion case-insensitive y sin tildes."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return without_marks.lower()


def _important_tokens(normalized: str) -> tuple[str, ...]:
    """Extrae tokens relevantes en orden estable."""
    raw_tokens = re.findall(r"[a-z0-9_]+(?:\.[a-z0-9_]+)*", normalized)
    accepted: list[str] = []
    seen: set[str] = set()
    for token in raw_tokens:
        if len(token) < 3 and "_" not in token and "." not in token:
            continue
        if token in _STOPWORDS:
            continue
        if token not in seen:
            accepted.append(token)
            seen.add(token)
    return tuple(accepted)


def _extract_actions(tokens: tuple[str, ...]) -> tuple[str, ...]:
    """Detecta acciones funcionales conocidas."""
    actions: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        action = _ACTION_ALIASES.get(token)
        if action is not None and action not in seen:
            actions.append(action)
            seen.add(action)
    return tuple(actions)


def _extract_entities(
    original: str,
    normalized: str,
    tokens: tuple[str, ...],
) -> tuple[str, ...]:
    """Extrae entidades candidatas conservadoras."""
    entities: list[str] = []
    seen: set[str] = set()

    for quoted in re.findall(r"[\"'`]([^\"'`]+)[\"'`]", original):
        _append_entity(entities, seen, _normalize_entity(quoted))

    for token in tokens:
        if token in _ENTITY_STOPWORDS:
            continue
        if "_" in token or "." in token or any(character.isdigit() for character in token):
            _append_entity(entities, seen, token)

    for phrase in _candidate_noun_phrases(normalized):
        _append_entity(entities, seen, phrase)

    return tuple(entities)


def _candidate_noun_phrases(normalized: str) -> tuple[str, ...]:
    """Deriva frases cortas utiles como entidades funcionales."""
    phrases: list[str] = []
    patterns = (
        r"\b([a-z0-9_]+\s+de\s+[a-z0-9_]+)\b",
        r"\b(?:de|del|la|el|los|las)\s+([a-z0-9_]+(?:\s+de\s+[a-z0-9_]+)?)",
        r"\b(?:para|sobre)\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, normalized):
            raw = match.group(1)
            candidate = _normalize_entity(raw)
            parts = candidate.split("_")
            if any(part in _ENTITY_STOPWORDS for part in parts):
                continue
            if len(candidate) >= 4:
                phrases.append(candidate)
    return tuple(phrases)


def _extract_constraints(original: str) -> tuple[str, ...]:
    """Extrae restricciones explicitas de la frase del usuario."""
    return _extract_clauses(
        original,
        markers=(
            "sin ",
            "no ",
            "solo ",
            "unicamente ",
            "antes de ",
            "despues de ",
            "cuando ",
            "si ",
            "siempre que ",
            "excepto ",
        ),
    )


def _extract_assumptions(original: str) -> tuple[str, ...]:
    """Extrae supuestos declarados explicitamente."""
    return _extract_clauses(
        original,
        markers=(
            "asumiendo ",
            "suponiendo ",
            "supuesto ",
            "se asume ",
        ),
    )


def _extract_clauses(original: str, *, markers: tuple[str, ...]) -> tuple[str, ...]:
    """Devuelve clausulas que empiezan con marcadores conocidos."""
    normalized = _normalize_text(original)
    clauses: list[str] = []
    seen: set[str] = set()
    for marker in markers:
        for match in re.finditer(rf"\b{re.escape(marker)}[^.;,]+", normalized):
            clause = _compact_whitespace(match.group(0))
            if clause and clause not in seen:
                clauses.append(clause)
                seen.add(clause)
    return tuple(clauses)


def _search_terms(
    actions: tuple[str, ...],
    entities: tuple[str, ...],
    tokens: tuple[str, ...],
) -> tuple[str, ...]:
    """Construye terminos de busqueda reproducibles."""
    terms: list[str] = []
    seen: set[str] = set()
    for entity in entities:
        _append_search_term(terms, seen, entity.replace("_", " "))
    for action in actions:
        _append_search_term(terms, seen, action)
    for token in tokens:
        if token not in _ENTITY_STOPWORDS:
            _append_search_term(terms, seen, token.replace("_", " "))
    return tuple(terms[:12])


def _open_questions(
    *,
    actions: tuple[str, ...],
    entities: tuple[str, ...],
    constraints: tuple[str, ...],
    original: str,
) -> tuple[str, ...]:
    """Formula preguntas abiertas cuando el requerimiento queda incompleto."""
    questions: list[str] = []
    if not actions:
        questions.append("Que accion funcional debe especificarse?")
    if not entities:
        questions.append("Que componente, regla o entidad funcional debe analizarse?")
    if not constraints and _looks_risky_or_broad(original):
        questions.append("Que limite, condicion o criterio de aceptacion aplica?")
    return tuple(questions)


def _looks_risky_or_broad(original: str) -> bool:
    """Detecta requerimientos demasiado breves o amplios."""
    normalized = _normalize_text(original)
    return len(normalized.split()) <= 5 or any(
        word in normalized
        for word in ("mejorar", "optimizar", "cambiar", "ajustar", "revisar")
    )


def _normalize_entity(value: str) -> str:
    """Normaliza una entidad candidata a token de busqueda."""
    normalized = _normalize_text(value)
    pieces = re.findall(r"[a-z0-9_]+", normalized)
    return "_".join(piece for piece in pieces if piece not in _ENTITY_STOPWORDS)


def _append_entity(values: list[str], seen: set[str], value: str) -> None:
    """Agrega una entidad si es valida y no repetida."""
    if not value or value in seen:
        return
    if len(value) < 3 and "_" not in value and "." not in value:
        return
    values.append(value)
    seen.add(value)


def _append_search_term(values: list[str], seen: set[str], value: str) -> None:
    """Agrega un termino de busqueda normalizado y no repetido."""
    term = _compact_whitespace(value)
    if not term or term in seen:
        return
    values.append(term)
    seen.add(term)


def _evidence_query(intent: RequirementIntent) -> str:
    """Construye la consulta H3 desde la intencion ya interpretada."""
    terms = intent.search_terms or intent.entities or intent.actions
    if not terms:
        return intent.original_text
    return " ".join(terms)


def _evidence_from_context_source(source) -> EvidenceItem:
    """Mapea una fuente H3 final a evidencia H5 sin cambiar su ranking."""
    candidate = source.candidate
    metadata = candidate.source
    path = str(metadata.get("relative_path") or "fuente desconocida")
    start_line = _optional_int(metadata.get("start_line"))
    end_line = _optional_int(metadata.get("end_line"))
    line_suffix = (
        f" lineas={start_line}-{end_line}"
        if start_line is not None and end_line is not None
        else ""
    )
    source_key = f"{candidate.chunk_id}:{candidate.content_sha256}:{source.source_id}"
    return EvidenceItem(
        evidence_id=evidence_id(
            source_type=EvidenceSourceType.CHUNK,
            source_key=source_key,
        ),
        source_type=EvidenceSourceType.CHUNK,
        title=f"{source.source_id} {path}",
        citation=f"[{source.source_id}] {path}{line_suffix}",
        classification=SpecConclusionKind.DETECTED,
        file_path=path,
        chunk_id=candidate.chunk_id,
        start_line=start_line,
        end_line=end_line,
        detail=source.content,
        metadata={
            "context_source_id": source.source_id,
            "combined_score": candidate.combined_score,
            "content_truncated": source.content_truncated,
        },
    )


def _optional_int(value: object) -> int | None:
    """Convierte metadata numerica opcional a entero."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _impact_queries(intent: RequirementIntent) -> tuple[str, ...]:
    """Devuelve entidades candidatas para consultar H4."""
    if not intent.actions:
        return ()
    source = intent.entities or intent.search_terms
    technical = tuple(value for value in source if _looks_like_technical_name(value))
    if technical:
        source = technical
    queries: list[str] = []
    seen: set[str] = set()
    for value in source:
        query = _compact_whitespace(value)
        if query and query not in seen:
            queries.append(query)
            seen.add(query)
    return tuple(queries[:8])


def _looks_like_technical_name(value: str) -> bool:
    """Estima si una entidad parece nombre tecnico consultable en H4."""
    normalized = _normalize_text(value)
    if "." in normalized:
        return True
    return bool(
        re.match(
            r"^(pkg|p|fn|f|w|dw|uo|m|d|trg|vw|sp|prc|s)_",
            normalized,
        )
    )


def _resolution_warning(query: str, analysis: ImpactAnalysis) -> str:
    """Describe una resolucion H4 no concluyente."""
    status = analysis.resolution.status
    if status == "ambiguous":
        return f"H4 encontro multiples candidatos para `{query}`."
    return f"H4 no encontro simbolo activo para `{query}`."


def _component_from_symbol(
    symbol: TechnicalSymbol,
    *,
    role: AffectedComponentRole,
    classification: SpecConclusionKind,
    evidence_ids: tuple[str, ...],
    reason: str,
    unresolved_reason: str | None = None,
) -> AffectedComponent:
    """Mapea un simbolo H4 a componente afectado H5."""
    return AffectedComponent(
        component_id=symbol.symbol_id,
        name=symbol.normalized_name,
        role=role,
        technology=symbol.technology,
        classification=classification,
        evidence_ids=evidence_ids,
        component_type=symbol.symbol_type,
        reason=reason,
        unresolved_reason=unresolved_reason,
    )


def _append_edge_component_and_evidence(
    components: list[AffectedComponent],
    evidence: list[EvidenceItem],
    seen_components: set[tuple[str, AffectedComponentRole]],
    seen_evidence: set[str],
    *,
    edge: DependencyEdge,
    role: AffectedComponentRole,
) -> None:
    """Agrega el componente vecino reportado por una arista H4."""
    edge_evidence = _evidence_from_relation(edge.relation)
    _append_evidence(evidence, seen_evidence, edge_evidence)
    symbol = _neighbor_symbol(edge, role)
    if symbol is not None:
        _append_component(
            components,
            seen_components,
            _component_from_symbol(
                symbol,
                role=role,
                classification=_classification_from_relation(edge.relation),
                evidence_ids=(edge_evidence.evidence_id,),
                reason=f"relacion H4 {edge.relation.relation_type}",
            ),
        )
        return
    if edge.target_key:
        _append_component(
            components,
            seen_components,
            AffectedComponent(
                component_id=f"{edge.relation.resolution_status.value}:{edge.target_key}",
                name=edge.target_key,
                role=AffectedComponentRole.UNKNOWN,
                technology="unknown",
                classification=SpecConclusionKind.TO_CONFIRM,
                evidence_ids=(edge_evidence.evidence_id,),
                unresolved_reason=edge.relation.resolution_status.value,
            ),
        )


def _neighbor_symbol(
    edge: DependencyEdge,
    role: AffectedComponentRole,
) -> TechnicalSymbol | None:
    """Selecciona el simbolo vecino segun el rol H5 deseado."""
    if role == AffectedComponentRole.CONSUMER:
        return edge.source_symbol
    return edge.target_symbol or edge.source_symbol


def _evidence_from_symbol(symbol: TechnicalSymbol, *, prefix: str) -> EvidenceItem:
    """Crea evidencia H5 a partir de un simbolo H4 ya resuelto."""
    source_key = f"{prefix}:{symbol.symbol_id}"
    location = _symbol_location(symbol)
    return EvidenceItem(
        evidence_id=evidence_id(
            source_type=EvidenceSourceType.SYMBOL,
            source_key=source_key,
        ),
        source_type=EvidenceSourceType.SYMBOL,
        title=f"Simbolo H4 {symbol.normalized_name}",
        citation=f"[H4] simbolo {symbol.normalized_name}{location}",
        classification=SpecConclusionKind.DETECTED,
        file_path=None,
        chunk_id=symbol.chunk_id,
        symbol_id=symbol.symbol_id,
        start_line=symbol.start_line,
        end_line=symbol.end_line,
        detail=f"{symbol.symbol_type} {symbol.technology}",
        metadata={
            "technology": symbol.technology,
            "symbol_type": symbol.symbol_type,
            "confidence": symbol.confidence.value,
        },
    )


def _evidence_from_relation(relation: TechnicalRelation) -> EvidenceItem:
    """Crea evidencia H5 a partir de una relacion H4 persistida."""
    source_key = f"relation:{relation.relation_id}"
    classification = _classification_from_relation(relation)
    target = relation.target_symbol_id or relation.target_key or "destino desconocido"
    return EvidenceItem(
        evidence_id=evidence_id(
            source_type=EvidenceSourceType.RELATION,
            source_key=source_key,
        ),
        source_type=EvidenceSourceType.RELATION,
        title=f"Relacion H4 {relation.relation_type}",
        citation=(
            f"[H4] relacion {relation.relation_type} "
            f"estado={relation.resolution_status.value}"
        ),
        classification=classification,
        relation_id=relation.relation_id,
        chunk_id=relation.evidence_chunk_id,
        start_line=relation.start_line,
        end_line=relation.end_line,
        detail=f"{relation.source_symbol_id or 'origen desconocido'} -> {target}",
        metadata={
            "confidence": relation.confidence.value,
            "relation_type": relation.relation_type,
            "resolution_status": relation.resolution_status.value,
        },
    )


def _classification_from_relation(relation: TechnicalRelation) -> SpecConclusionKind:
    """Traduce clasificacion/resolucion H4 a clasificacion H5."""
    if relation.resolution_status in {
        ResolutionStatus.AMBIGUOUS,
        ResolutionStatus.UNRESOLVED,
        ResolutionStatus.DYNAMIC,
    }:
        return SpecConclusionKind.TO_CONFIRM
    if relation.classification.value == SpecConclusionKind.INFERRED.value:
        return SpecConclusionKind.INFERRED
    if relation.classification.value == SpecConclusionKind.TO_CONFIRM.value:
        return SpecConclusionKind.TO_CONFIRM
    return SpecConclusionKind.DETECTED


def _symbol_location(symbol: TechnicalSymbol) -> str:
    """Renderiza ubicacion opcional de un simbolo."""
    if symbol.start_line is not None and symbol.end_line is not None:
        return f" lineas={symbol.start_line}-{symbol.end_line}"
    if symbol.chunk_id is not None:
        return f" chunk={symbol.chunk_id}"
    return ""


def _append_component(
    components: list[AffectedComponent],
    seen: set[tuple[str, AffectedComponentRole]],
    component: AffectedComponent,
) -> None:
    """Agrega componente evitando duplicados por rol."""
    key = (component.component_id, component.role)
    if key in seen:
        return
    components.append(component)
    seen.add(key)


def _append_evidence(
    evidence: list[EvidenceItem],
    seen: set[str],
    item: EvidenceItem,
) -> None:
    """Agrega evidencia evitando IDs duplicados."""
    if item.evidence_id in seen:
        return
    evidence.append(item)
    seen.add(item.evidence_id)
