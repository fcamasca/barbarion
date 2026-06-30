"""Pruebas H4-T06 para navegacion de dependencias."""

from barbarion.application.reverse_engineering import DependencyWalkService
from barbarion.domain.models import Confidence
from barbarion.domain.reverse_engineering import (
    H4Classification,
    H4DependencyDirection,
    H4DependencyFilters,
    H4Reference,
    H4Relation,
    H4RelationCandidate,
    H4ResolutionStatus,
    H4Symbol,
    h4_reference_id,
    h4_relation_id,
    h4_symbol_id,
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
        direction=H4DependencyDirection.OUTGOING,
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
        direction=H4DependencyDirection.INCOMING,
        max_depth=1,
    )
    depth_zero = DependencyWalkService(repository).walk(
        root.symbol_id,
        direction=H4DependencyDirection.BOTH,
        max_depth=0,
    )

    assert tuple(node.symbol.symbol_id for node in incoming.nodes) == (
        root.symbol_id,
        caller.symbol_id,
    )
    assert all(edge.direction == H4DependencyDirection.INCOMING for edge in incoming.edges)
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
        resolution_status=H4ResolutionStatus.AMBIGUOUS,
    )
    unresolved = _relation(
        root,
        None,
        target_key="pkg.missing",
        resolution_status=H4ResolutionStatus.UNRESOLVED,
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
        if edge.relation.resolution_status == H4ResolutionStatus.AMBIGUOUS
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
        filters=H4DependencyFilters(
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
        symbols: tuple[H4Symbol, ...],
        relations: tuple[H4Relation, ...],
        candidates: dict[str, tuple[H4RelationCandidate, ...]] | None = None,
    ) -> None:
        self._symbols = {symbol.symbol_id: symbol for symbol in symbols}
        self._relations = relations
        self._candidates = candidates or {}

    def get_symbol(self, symbol_id: str) -> H4Symbol | None:
        """Devuelve un simbolo fixture por ID."""
        return self._symbols.get(symbol_id)

    def active_relations_for_symbol(
        self,
        symbol_id: str,
        *,
        direction: H4DependencyDirection,
    ) -> tuple[H4Relation, ...]:
        """Devuelve relaciones activas adyacentes respetando direccion."""
        if direction == H4DependencyDirection.OUTGOING:
            return tuple(
                relation
                for relation in self._relations
                if relation.source_symbol_id == symbol_id
            )
        if direction == H4DependencyDirection.INCOMING:
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
    ) -> tuple[H4RelationCandidate, ...]:
        """Devuelve candidatos ambiguos asociados a una relacion fixture."""
        return self._candidates.get(relation_id, ())


def _symbol(normalized_name: str, *, technology: str = "oracle") -> H4Symbol:
    symbol_id = h4_symbol_id(
        normalized_name=normalized_name,
        symbol_type="procedure",
        technology=technology,
        container_name="pkg",
    )
    return H4Symbol(
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
    source: H4Symbol,
    target: H4Symbol | None,
    *,
    target_key: str | None = None,
    resolution_status: H4ResolutionStatus = H4ResolutionStatus.RESOLVED,
    confidence: Confidence = Confidence.MEDIUM,
    relation_type: str = "calls",
) -> H4Relation:
    raw_target = target.normalized_name if target is not None else target_key or "missing"
    reference = _reference(source, raw_target, relation_type=relation_type)
    relation_id = h4_relation_id(
        reference_id=reference.reference_id,
        relation_type=relation_type,
        source_symbol_id=source.symbol_id,
        target_symbol_id=target.symbol_id if target is not None else None,
        target_key=target_key,
    )
    return H4Relation(
        relation_id=relation_id,
        reference_id=reference.reference_id,
        source_symbol_id=source.symbol_id,
        target_symbol_id=target.symbol_id if target is not None else None,
        target_key=target.normalized_name if target is not None else target_key,
        relation_type=relation_type,
        classification=H4Classification.DETECTED
        if resolution_status == H4ResolutionStatus.RESOLVED
        else H4Classification.TO_CONFIRM,
        resolution_status=resolution_status,
        confidence=confidence,
        evidence_file_id=1,
    )


def _reference(
    source: H4Symbol,
    target: str,
    *,
    relation_type: str,
) -> H4Reference:
    reference_id = h4_reference_id(
        source_file_id=1,
        raw_text=f"{source.normalized_name}->{target}",
        normalized_target=target,
        reference_type=relation_type,
        start_line=1,
        end_line=1,
    )
    return H4Reference(
        reference_id=reference_id,
        source_file_id=1,
        source_symbol_id=source.symbol_id,
        raw_text=target,
        normalized_target=target,
        reference_type=relation_type,
        technology=source.technology,
        detection_method="fixture",
        confidence=Confidence.MEDIUM,
        resolution_status=H4ResolutionStatus.RESOLVED,
        start_line=1,
        end_line=1,
    )


def _candidate(
    relation: H4Relation,
    symbol: H4Symbol,
    *,
    rank: int,
) -> H4RelationCandidate:
    return H4RelationCandidate(
        relation_id=relation.relation_id,
        candidate_symbol_id=symbol.symbol_id,
        rank=rank,
        reason="fixture",
    )
