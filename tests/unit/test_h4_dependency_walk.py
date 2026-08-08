"""Pruebas H4-T06 para navegacion de dependencias."""

from barbarion.application.reverse_engineering import (
    DependencyWalkService,
    query_graph_relations,
)
from barbarion.domain.models import Confidence
from barbarion.domain.reverse_engineering import (
    EvidenceClassification,
    DependencyDirection,
    DependencyFilters,
    TechnicalReference,
    TechnicalRelation,
    RelationCandidate,
    ResolutionStatus,
    TechnicalSymbol,
    technical_reference_id,
    technical_relation_id,
    technical_symbol_id,
)


def test_dependency_walk_uses_bfs_depth_and_marks_cycles() -> None:
    root = _symbol("pkg.root")
    worker = _symbol("pkg.worker")
    leaf = _symbol("pkg.leaf")
    repository = _FakeRepository(
        symbols=(root, worker, leaf),
        relations=(
            _relation(root, worker),
            _relation(worker, leaf),
            _relation(leaf, root),
        ),
    )

    walk = DependencyWalkService(repository).walk(
        root.symbol_id,
        direction=DependencyDirection.OUTGOING,
        max_depth=3,
    )

    assert tuple(node.symbol.symbol_id for node in walk.nodes) == (
        root.symbol_id,
        worker.symbol_id,
        leaf.symbol_id,
    )
    assert tuple(node.depth for node in walk.nodes) == (0, 1, 2)
    assert len(walk.edges) == 3
    assert walk.edges[-1].is_cycle is True
    assert walk.cycles == ((root.symbol_id, worker.symbol_id, leaf.symbol_id, root.symbol_id),)


def test_query_graph_relations_filters_direction_type_resolution_and_confidence() -> None:
    root = _symbol("pkg.root")
    target = _symbol("pkg.target")
    incoming = _symbol("pkg.incoming")
    repository = _FakeRepository(
        symbols=(root, target, incoming),
        relations=(
            _relation(root, target, relation_type="calls", confidence=Confidence.HIGH),
            _relation(root, target, relation_type="uses", confidence=Confidence.LOW),
            _relation(incoming, root, relation_type="opens", confidence=Confidence.HIGH),
            _relation(
                root,
                target,
                relation_type="references",
                confidence=Confidence.HIGH,
                resolution_status=ResolutionStatus.AMBIGUOUS,
            ),
        ),
    )

    outgoing = query_graph_relations(
        repository,
        root.symbol_id,
        direction=DependencyDirection.OUTGOING,
        relation_types=frozenset({"calls", "uses", "references"}),
        min_confidence=Confidence.MEDIUM,
    )
    incoming_result = query_graph_relations(
        repository,
        root.symbol_id,
        direction=DependencyDirection.INCOMING,
        relation_types=frozenset({"opens"}),
    )

    assert tuple(relation.relation_type for relation in outgoing) == ("calls",)
    assert tuple(relation.relation_type for relation in incoming_result) == ("opens",)


def test_query_graph_relations_handles_dynamic_external_and_domain() -> None:
    root = _symbol("pkg.root")
    local = _symbol("pkg.local")
    foreign = _symbol("pkg.foreign")
    repository = _FakeRepository(
        symbols=(root, local, foreign),
        relations=(
            _relation(root, local, relation_type="uses"),
            _relation(
                root,
                local,
                relation_type="uses",
                resolution_status=ResolutionStatus.DYNAMIC,
            ),
            _relation(
                root,
                local,
                relation_type="uses",
                resolution_status=ResolutionStatus.EXTERNAL,
            ),
            _relation(root, foreign, relation_type="calls"),
        ),
        domains={
            root.symbol_id: "legacy",
            local.symbol_id: "legacy",
            foreign.symbol_id: "other",
        },
    )

    resolved = query_graph_relations(
        repository,
        root.symbol_id,
        direction=DependencyDirection.OUTGOING,
        relation_types=frozenset({"calls", "uses"}),
        domain="legacy",
    )
    dynamic = query_graph_relations(
        repository,
        root.symbol_id,
        resolution_status=ResolutionStatus.DYNAMIC,
        domain="legacy",
    )
    external = query_graph_relations(
        repository,
        root.symbol_id,
        resolution_status=ResolutionStatus.EXTERNAL,
        domain="legacy",
    )
    wrong_domain = query_graph_relations(
        repository,
        root.symbol_id,
        domain="other",
    )

    assert tuple(relation.relation_type for relation in resolved) == ("uses",)
    assert len(dynamic) == 1
    assert dynamic[0].resolution_status == ResolutionStatus.DYNAMIC
    assert len(external) == 1
    assert external[0].resolution_status == ResolutionStatus.EXTERNAL
    assert wrong_domain == ()


def test_dependency_walk_respects_direction_and_depth_zero() -> None:
    root = _symbol("pkg.root")
    caller = _symbol("pkg.caller")
    dependency = _symbol("pkg.dependency")
    repository = _FakeRepository(
        symbols=(root, caller, dependency),
        relations=(
            _relation(caller, root),
            _relation(root, dependency),
        ),
    )

    incoming = DependencyWalkService(repository).walk(
        root.symbol_id,
        direction=DependencyDirection.INCOMING,
        max_depth=1,
    )
    depth_zero = DependencyWalkService(repository).walk(
        root.symbol_id,
        direction=DependencyDirection.BOTH,
        max_depth=0,
    )

    assert tuple(node.symbol.symbol_id for node in incoming.nodes) == (
        root.symbol_id,
        caller.symbol_id,
    )
    assert all(edge.direction == DependencyDirection.INCOMING for edge in incoming.edges)
    assert tuple(node.symbol.symbol_id for node in depth_zero.nodes) == (root.symbol_id,)
    assert depth_zero.edges == ()


def test_dependency_walk_keeps_ambiguous_and_unresolved_edges_as_leaves() -> None:
    root = _symbol("pkg.root")
    candidate_a = _symbol("pkg.option_a")
    candidate_b = _symbol("pkg.option_b")
    ambiguous = _relation(
        root,
        None,
        target_key="pkg.option",
        resolution_status=ResolutionStatus.AMBIGUOUS,
    )
    unresolved = _relation(
        root,
        None,
        target_key="pkg.missing",
        resolution_status=ResolutionStatus.UNRESOLVED,
    )
    repository = _FakeRepository(
        symbols=(root, candidate_a, candidate_b),
        relations=(ambiguous, unresolved),
        candidates={
            ambiguous.relation_id: (
                _candidate(ambiguous, candidate_a, rank=1),
                _candidate(ambiguous, candidate_b, rank=2),
            ),
        },
    )

    walk = DependencyWalkService(repository).walk(root.symbol_id, max_depth=2)
    ambiguous_edge = next(
        edge
        for edge in walk.edges
        if edge.relation.resolution_status == ResolutionStatus.AMBIGUOUS
    )

    assert tuple(node.symbol.symbol_id for node in walk.nodes) == (root.symbol_id,)
    assert tuple(edge.target_key for edge in walk.edges) == ("pkg.missing", "pkg.option")
    assert ambiguous_edge.candidate_symbol_ids == (
        candidate_a.symbol_id,
        candidate_b.symbol_id,
    )


def test_dependency_walk_applies_filters_and_node_limit() -> None:
    root = _symbol("pkg.root")
    high = _symbol("pkg.high")
    low = _symbol("pkg.low")
    repository = _FakeRepository(
        symbols=(root, high, low),
        relations=(
            _relation(root, high, confidence=Confidence.HIGH, relation_type="calls"),
            _relation(root, low, confidence=Confidence.LOW, relation_type="uses"),
        ),
    )

    filtered = DependencyWalkService(repository).walk(
        root.symbol_id,
        max_depth=1,
        filters=DependencyFilters(
            relation_type="calls",
            min_confidence=Confidence.MEDIUM,
        ),
    )
    limited = DependencyWalkService(repository).walk(
        root.symbol_id,
        max_depth=1,
        node_limit=1,
    )

    assert tuple(edge.relation.relation_type for edge in filtered.edges) == ("calls",)
    assert tuple(node.symbol.symbol_id for node in filtered.nodes) == (
        root.symbol_id,
        high.symbol_id,
    )
    assert limited.limit_reached is True
    assert tuple(node.symbol.symbol_id for node in limited.nodes) == (root.symbol_id,)


def test_dependency_walk_rejects_invalid_seed_and_limits() -> None:
    root = _symbol("pkg.root")
    service = DependencyWalkService(_FakeRepository(symbols=(root,), relations=()))

    for kwargs in ({"max_depth": 6}, {"max_depth": -1}, {"node_limit": 0}):
        try:
            service.walk(root.symbol_id, **kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError("Se esperaba ValueError para limites invalidos.")

    try:
        service.walk("0" * 64)
    except ValueError:
        pass
    else:
        raise AssertionError("Se esperaba ValueError para una semilla inexistente.")


class _FakeRepository:
    """Repositorio minimo para probar BFS sin SQLite."""

    def __init__(
        self,
        *,
        symbols: tuple[TechnicalSymbol, ...],
        relations: tuple[TechnicalRelation, ...],
        candidates: dict[str, tuple[RelationCandidate, ...]] | None = None,
        domains: dict[str, str] | None = None,
    ) -> None:
        self._symbols = {symbol.symbol_id: symbol for symbol in symbols}
        self._relations = relations
        self._candidates = candidates or {}
        self._domains = domains or {
            symbol.symbol_id: "default" for symbol in symbols
        }

    def get_symbol(self, symbol_id: str) -> TechnicalSymbol | None:
        """Devuelve un simbolo fixture por ID."""
        return self._symbols.get(symbol_id)

    def symbol_domain(self, symbol_id: str) -> str | None:
        """Devuelve el dominio fixture del simbolo."""
        return self._domains.get(symbol_id)

    def active_relations_for_symbol(
        self,
        symbol_id: str,
        *,
        direction: DependencyDirection,
    ) -> tuple[TechnicalRelation, ...]:
        """Devuelve relaciones activas adyacentes respetando direccion."""
        if direction == DependencyDirection.OUTGOING:
            return tuple(
                relation
                for relation in self._relations
                if relation.source_symbol_id == symbol_id
            )
        if direction == DependencyDirection.INCOMING:
            return tuple(
                relation
                for relation in self._relations
                if relation.target_symbol_id == symbol_id
            )
        return tuple(
            relation
            for relation in self._relations
            if relation.source_symbol_id == symbol_id or relation.target_symbol_id == symbol_id
        )

    def relation_candidates(
        self,
        relation_id: str,
    ) -> tuple[RelationCandidate, ...]:
        """Devuelve candidatos ambiguos asociados a una relacion fixture."""
        return self._candidates.get(relation_id, ())


def _symbol(normalized_name: str, *, technology: str = "oracle") -> TechnicalSymbol:
    symbol_id = technical_symbol_id(
        normalized_name=normalized_name,
        symbol_type="procedure",
        technology=technology,
        container_name="pkg",
    )
    return TechnicalSymbol(
        symbol_id=symbol_id,
        original_name=normalized_name,
        normalized_name=normalized_name,
        symbol_type="procedure",
        technology=technology,
        extraction_method="fixture",
        confidence=Confidence.HIGH,
        container_name="pkg",
    )


def _relation(
    source: TechnicalSymbol,
    target: TechnicalSymbol | None,
    *,
    target_key: str | None = None,
    resolution_status: ResolutionStatus = ResolutionStatus.RESOLVED,
    confidence: Confidence = Confidence.MEDIUM,
    relation_type: str = "calls",
) -> TechnicalRelation:
    raw_target = target.normalized_name if target is not None else target_key or "missing"
    reference = _reference(source, raw_target, relation_type=relation_type)
    relation_id = technical_relation_id(
        reference_id=reference.reference_id,
        relation_type=relation_type,
        source_symbol_id=source.symbol_id,
        target_symbol_id=target.symbol_id if target is not None else None,
        target_key=target_key,
    )
    return TechnicalRelation(
        relation_id=relation_id,
        reference_id=reference.reference_id,
        source_symbol_id=source.symbol_id,
        target_symbol_id=target.symbol_id if target is not None else None,
        target_key=target.normalized_name if target is not None else target_key,
        relation_type=relation_type,
        classification=EvidenceClassification.DETECTED
        if resolution_status == ResolutionStatus.RESOLVED
        else EvidenceClassification.TO_CONFIRM,
        resolution_status=resolution_status,
        confidence=confidence,
        evidence_file_id=1,
    )


def _reference(
    source: TechnicalSymbol,
    target: str,
    *,
    relation_type: str,
) -> TechnicalReference:
    reference_id = technical_reference_id(
        source_file_id=1,
        raw_text=f"{source.normalized_name}->{target}",
        normalized_target=target,
        reference_type=relation_type,
        start_line=1,
        end_line=1,
    )
    return TechnicalReference(
        reference_id=reference_id,
        source_file_id=1,
        source_symbol_id=source.symbol_id,
        raw_text=target,
        normalized_target=target,
        reference_type=relation_type,
        technology=source.technology,
        detection_method="fixture",
        confidence=Confidence.MEDIUM,
        resolution_status=ResolutionStatus.RESOLVED,
        start_line=1,
        end_line=1,
    )


def _candidate(
    relation: TechnicalRelation,
    symbol: TechnicalSymbol,
    *,
    rank: int,
) -> RelationCandidate:
    return RelationCandidate(
        relation_id=relation.relation_id,
        candidate_symbol_id=symbol.symbol_id,
        rank=rank,
        reason="fixture",
    )
