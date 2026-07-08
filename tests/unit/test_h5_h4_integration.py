"""Pruebas de integracion H5 con servicios H4 sin recalcular H4."""

from dataclasses import dataclass

from barbarion.application.spec_mode import (
    RequirementAnalyzer,
    TechnicalImpactCollector,
    TechnicalImpactRequest,
)
from barbarion.domain.models import Confidence
from barbarion.domain.reverse_engineering import (
    DependencyDirection,
    DependencyEdge,
    DependencyNode,
    DependencyWalk,
    EvidenceClassification,
    ImpactAnalysis,
    ObjectResolution,
    ResolutionStatus,
    TechnicalRelation,
    TechnicalSymbol,
    technical_reference_id,
    technical_relation_id,
    technical_symbol_id,
)
from barbarion.domain.spec_mode import (
    AffectedComponentRole,
    EvidenceSourceType,
    RequirementIntent,
    SpecConclusionKind,
)


def test_technical_impact_collector_consumes_h4_impact_service() -> None:
    root = _symbol("pkg_credito")
    dependency = _symbol("pkg_limite")
    consumer = _symbol("w_aprobacion", technology="powerbuilder", container_name="w")
    dependency_relation = _relation(root, dependency, relation_type="calls")
    consumer_relation = _relation(consumer, root, relation_type="calls")
    analysis = ImpactAnalysis(
        resolution=ObjectResolution(query="pkg_credito", symbol=root),
        walk=_walk(root, dependency, consumer, dependency_relation, consumer_relation),
        dependencies=(
            _edge(dependency_relation, root, dependency, DependencyDirection.OUTGOING),
        ),
        consumers=(
            _edge(consumer_relation, consumer, root, DependencyDirection.INCOMING),
        ),
        summary="Impacto H4 fixture",
    )
    impact_service = _FakeImpactService((analysis,))
    intent = RequirementAnalyzer().analyze("Validar limite de credito en pkg_credito")

    result = TechnicalImpactCollector(impact_service).collect(
        TechnicalImpactRequest(intent=intent, depth=2)
    )

    assert len(impact_service.requests) == 1
    assert impact_service.requests[0].target.query == "pkg_credito"
    assert impact_service.requests[0].depth == 2
    assert impact_service.requests[0].no_llm is True
    assert impact_service.requests[0].include_rag is False
    assert {(component.name, component.role) for component in result.components} == {
        ("pkg_credito", AffectedComponentRole.DIRECT),
        ("pkg_limite", AffectedComponentRole.DEPENDENCY),
        ("w_aprobacion", AffectedComponentRole.CONSUMER),
    }
    assert all(item.source_type in {EvidenceSourceType.SYMBOL, EvidenceSourceType.RELATION} for item in result.evidence)
    assert result.insufficient_catalog is False


def test_technical_impact_collector_preserves_h4_uncertainty() -> None:
    root = _symbol("pkg_credito")
    unresolved = _relation(
        root,
        None,
        target_key="pkg_dinamico",
        resolution_status=ResolutionStatus.DYNAMIC,
    )
    analysis = ImpactAnalysis(
        resolution=ObjectResolution(query="pkg_credito", symbol=root),
        walk=_walk(root, None, None, unresolved),
        dependencies=(
            _edge(unresolved, root, None, DependencyDirection.OUTGOING, "pkg_dinamico"),
        ),
        to_confirm=("pkg_dinamico",),
        summary="Impacto con dinamico",
    )
    intent = RequirementAnalyzer().analyze("Validar limite de credito en pkg_credito")

    result = TechnicalImpactCollector(_FakeImpactService((analysis,))).collect(
        TechnicalImpactRequest(intent=intent)
    )

    dynamic_component = next(
        component for component in result.components if component.name == "pkg_dinamico"
    )
    dynamic_evidence = next(
        item
        for item in result.evidence
        if item.source_type == EvidenceSourceType.RELATION
    )
    assert dynamic_component.classification == SpecConclusionKind.TO_CONFIRM
    assert dynamic_component.unresolved_reason in {"dynamic", "relacion H4 no resuelta o dinamica"}
    assert dynamic_evidence.classification == SpecConclusionKind.TO_CONFIRM


def test_technical_impact_collector_reports_missing_or_ambiguous_catalog() -> None:
    first = _symbol("pkg_credito", container_name="a")
    second = _symbol("pkg_credito", container_name="b")
    missing = ImpactAnalysis(
        resolution=ObjectResolution(query="pkg_sin_catalogo", status="not_found"),
        summary="Sin simbolo",
    )
    ambiguous = ImpactAnalysis(
        resolution=ObjectResolution(
            query="pkg_credito",
            candidates=(first, second),
            status="ambiguous",
        ),
        summary="Ambiguo",
    )
    intent = RequirementIntent(
        original_text="Validar componentes tecnicos",
        actions=("validar",),
        entities=("pkg_sin_catalogo", "pkg_credito"),
        search_terms=("pkg_sin_catalogo", "pkg_credito"),
    )

    result = TechnicalImpactCollector(_FakeImpactService((missing, ambiguous))).collect(
        TechnicalImpactRequest(intent=intent)
    )

    assert result.evidence == ()
    assert result.insufficient_catalog is True
    assert any("no encontro" in warning for warning in result.warnings)
    assert any("multiples candidatos" in warning for warning in result.warnings)
    assert all(
        component.classification == SpecConclusionKind.TO_CONFIRM
        for component in result.components
    )


def test_technical_impact_collector_handles_empty_entities() -> None:
    intent = RequirementAnalyzer().analyze("Mejorar el proceso")

    result = TechnicalImpactCollector(_FakeImpactService(())).collect(
        TechnicalImpactRequest(intent=intent)
    )

    assert result.components == ()
    assert result.evidence == ()
    assert result.insufficient_catalog is True
    assert result.warnings == ("No hay entidades candidatas para consultar impacto H4.",)


class _FakeImpactService:
    """Fake de ImpactService: H5 solo debe invocar `analyze`."""

    def __init__(self, analyses: tuple[ImpactAnalysis, ...]) -> None:
        self._analyses = list(analyses)
        self.requests = []

    def analyze(self, request):
        self.requests.append(request)
        if not self._analyses:
            return ImpactAnalysis(
                resolution=ObjectResolution(query=request.target.query, status="not_found"),
                summary="sin catalogo",
            )
        return self._analyses.pop(0)


def _symbol(
    normalized_name: str,
    *,
    technology: str = "oracle",
    container_name: str = "pkg",
) -> TechnicalSymbol:
    symbol_id = technical_symbol_id(
        normalized_name=normalized_name,
        symbol_type="procedure",
        technology=technology,
        container_name=container_name,
    )
    return TechnicalSymbol(
        symbol_id=symbol_id,
        original_name=normalized_name,
        normalized_name=normalized_name,
        symbol_type="procedure",
        technology=technology,
        extraction_method="fixture",
        confidence=Confidence.HIGH,
        container_name=container_name,
        chunk_id=f"chunk-{normalized_name}",
        start_line=1,
        end_line=3,
    )


def _relation(
    source: TechnicalSymbol,
    target: TechnicalSymbol | None,
    *,
    target_key: str | None = None,
    relation_type: str = "calls",
    resolution_status: ResolutionStatus = ResolutionStatus.RESOLVED,
) -> TechnicalRelation:
    raw_target = target.normalized_name if target is not None else target_key or "missing"
    reference_id = technical_reference_id(
        source_file_id=1,
        raw_text=f"{source.normalized_name}->{raw_target}",
        normalized_target=raw_target,
        reference_type=relation_type,
    )
    relation_id = technical_relation_id(
        reference_id=reference_id,
        relation_type=relation_type,
        source_symbol_id=source.symbol_id,
        target_symbol_id=target.symbol_id if target is not None else None,
        target_key=target_key,
    )
    return TechnicalRelation(
        relation_id=relation_id,
        reference_id=reference_id,
        source_symbol_id=source.symbol_id,
        target_symbol_id=target.symbol_id if target is not None else None,
        target_key=target.normalized_name if target is not None else target_key,
        relation_type=relation_type,
        classification=EvidenceClassification.DETECTED
        if resolution_status == ResolutionStatus.RESOLVED
        else EvidenceClassification.TO_CONFIRM,
        resolution_status=resolution_status,
        confidence=Confidence.MEDIUM,
        evidence_file_id=1,
        evidence_chunk_id="chunk-evidence",
        start_line=5,
        end_line=5,
    )


def _edge(
    relation: TechnicalRelation,
    source: TechnicalSymbol | None,
    target: TechnicalSymbol | None,
    direction: DependencyDirection,
    target_key: str | None = None,
) -> DependencyEdge:
    return DependencyEdge(
        relation=relation,
        depth=1,
        direction=direction,
        source_symbol=source,
        target_symbol=target,
        target_key=target_key,
    )


def _walk(
    root: TechnicalSymbol,
    dependency: TechnicalSymbol | None,
    consumer: TechnicalSymbol | None,
    *relations: TechnicalRelation,
) -> DependencyWalk:
    nodes = [DependencyNode(root, 0)]
    if dependency is not None:
        nodes.append(DependencyNode(dependency, 1))
    if consumer is not None:
        nodes.append(DependencyNode(consumer, 1))
    edges = []
    for relation in relations:
        source = root if relation.source_symbol_id == root.symbol_id else consumer
        target = dependency if relation.target_symbol_id == getattr(dependency, "symbol_id", None) else root
        if relation.target_symbol_id is None:
            target = None
        edges.append(
            DependencyEdge(
                relation=relation,
                depth=1,
                direction=DependencyDirection.OUTGOING,
                source_symbol=source,
                target_symbol=target,
                target_key=relation.target_key,
            )
        )
    return DependencyWalk(
        seed_symbol_id=root.symbol_id,
        direction=DependencyDirection.BOTH,
        max_depth=1,
        node_limit=500,
        nodes=tuple(nodes),
        edges=tuple(edges),
    )
