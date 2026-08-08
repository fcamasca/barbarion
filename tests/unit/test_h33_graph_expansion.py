"""Pruebas T04 de expansión BFS acotada para H3.3."""

import hashlib

from barbarion.application.rag import GraphExpansionService
from barbarion.domain.models import Confidence
from barbarion.domain.rag import (
    GraphCandidateStatus,
    GraphExpansionLimits,
    GraphSeed,
    SeedOrigin,
)
from barbarion.domain.reverse_engineering import (
    DependencyDirection,
    EvidenceClassification,
    RelationStatus,
    ResolutionStatus,
    SymbolStatus,
    TechnicalRelation,
    TechnicalSymbol,
)


def test_graph_expansion_uses_bfs_depth_and_traces_cycle_path() -> None:
    a, b, c = (_symbol("a"), _symbol("b"), _symbol("c"))
    repository = _Repository(
        (a, b, c),
        (_relation(a, b), _relation(b, c), _relation(c, a)),
    )

    traces = GraphExpansionService(repository, "legacy").expand(
        (_seed(a, score=0.9),),
        limits=_limits(depth=3),
        relation_types=frozenset({"calls"}),
    )

    assert tuple(trace.candidate_id for trace in traces) == (
        b.symbol_id,
        c.symbol_id,
        a.symbol_id,
    )
    assert tuple(trace.status for trace in traces) == (
        GraphCandidateStatus.ACCEPTED,
        GraphCandidateStatus.ACCEPTED,
        GraphCandidateStatus.CYCLE,
    )
    assert traces[1].origin.path is not None
    assert traces[1].origin.path.nodes == (a.symbol_id, b.symbol_id, c.symbol_id)
    assert traces[1].discovered_at_depth == 2
    assert traces[2].origin.relation_ids[-1] == repository.relations[-1].relation_id


def test_graph_expansion_deduplicates_across_seeds_and_respects_direction() -> None:
    a, b, c = (_symbol("a"), _symbol("b"), _symbol("c"))
    repository = _Repository(
        (a, b, c),
        (_relation(a, c), _relation(b, c)),
    )

    outgoing = GraphExpansionService(repository, "legacy").expand(
        (_seed(b, score=0.8), _seed(a, score=0.9)),
        limits=_limits(depth=1),
        relation_types=frozenset({"calls"}),
    )
    incoming = GraphExpansionService(repository, "legacy").expand(
        (_seed(c, score=0.9),),
        limits=_limits(depth=1),
        relation_types=frozenset({"calls"}),
        direction=DependencyDirection.INCOMING,
    )

    assert tuple(trace.status for trace in outgoing) == (
        GraphCandidateStatus.ACCEPTED,
        GraphCandidateStatus.DUPLICATE,
    )
    assert outgoing[0].origin.seed_ids == ("seed-a",)
    assert tuple(trace.candidate_id for trace in incoming) == (
        a.symbol_id,
        b.symbol_id,
    )


def test_graph_expansion_enforces_seed_neighbor_candidate_and_depth_limits() -> None:
    a, b, c, d = (_symbol("a"), _symbol("b"), _symbol("c"), _symbol("d"))
    repository = _Repository(
        (a, b, c, d),
        (_relation(a, b), _relation(a, c), _relation(b, d)),
    )

    neighbor_limited = GraphExpansionService(repository, "legacy").expand(
        (_seed(a, score=0.9),),
        limits=GraphExpansionLimits(1, 1, 1, 10),
        relation_types=frozenset({"calls"}),
    )
    candidate_limited = GraphExpansionService(repository, "legacy").expand(
        (_seed(a, score=0.9),),
        limits=GraphExpansionLimits(2, 1, 10, 1),
        relation_types=frozenset({"calls"}),
    )
    seed_limited = GraphExpansionService(repository, "legacy").expand(
        (_seed(a, score=0.9), _seed(b, score=0.8)),
        limits=GraphExpansionLimits(1, 1, 10, 10),
        relation_types=frozenset({"calls"}),
    )

    assert tuple(trace.status for trace in neighbor_limited) == (
        GraphCandidateStatus.ACCEPTED,
        GraphCandidateStatus.LIMIT,
    )
    assert tuple(trace.status for trace in candidate_limited) == (
        GraphCandidateStatus.ACCEPTED,
        GraphCandidateStatus.LIMIT,
    )
    assert seed_limited[-1].candidate_id == b.symbol_id
    assert seed_limited[-1].status == GraphCandidateStatus.LIMIT
    assert all(trace.discovered_at_depth <= 1 for trace in neighbor_limited)


def _limits(*, depth: int) -> GraphExpansionLimits:
    return GraphExpansionLimits(
        max_depth=depth,
        max_seeds=4,
        max_neighbors_per_seed=20,
        max_candidates=20,
    )


def _seed(symbol: TechnicalSymbol, *, score: float) -> GraphSeed:
    return GraphSeed(
        seed_id=f"seed-{symbol.normalized_name}",
        chunk_id=symbol.chunk_id or f"chunk-{symbol.normalized_name}",
        symbol_id=symbol.symbol_id,
        retrieval_score=score,
        origin=SeedOrigin.H3_CHUNK,
    )


def _symbol(name: str) -> TechnicalSymbol:
    return TechnicalSymbol(
        symbol_id=_sha(f"symbol:{name}"),
        original_name=name.upper(),
        normalized_name=name,
        symbol_type="procedure",
        technology="oracle",
        extraction_method="fixture",
        confidence=Confidence.HIGH,
        file_id=1,
        chunk_id=f"chunk-{name}",
        status=SymbolStatus.ACTIVE,
    )


def _relation(source: TechnicalSymbol, target: TechnicalSymbol) -> TechnicalRelation:
    relation_id = _sha(f"relation:{source.symbol_id}:{target.symbol_id}")
    return TechnicalRelation(
        relation_id=relation_id,
        reference_id=_sha(f"reference:{relation_id}"),
        relation_type="calls",
        classification=EvidenceClassification.DETECTED,
        resolution_status=ResolutionStatus.RESOLVED,
        confidence=Confidence.HIGH,
        evidence_file_id=1,
        source_symbol_id=source.symbol_id,
        target_symbol_id=target.symbol_id,
        target_key=target.normalized_name,
        status=RelationStatus.ACTIVE,
    )


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class _Repository:
    def __init__(
        self,
        symbols: tuple[TechnicalSymbol, ...],
        relations: tuple[TechnicalRelation, ...],
    ) -> None:
        self.symbols = {symbol.symbol_id: symbol for symbol in symbols}
        self.relations = relations

    def get_symbol(self, symbol_id: str) -> TechnicalSymbol | None:
        return self.symbols.get(symbol_id)

    def symbol_domain(self, symbol_id: str) -> str | None:
        return "legacy" if symbol_id in self.symbols else None

    def active_relations_for_symbol(
        self,
        symbol_id: str,
        *,
        direction: DependencyDirection,
    ) -> tuple[TechnicalRelation, ...]:
        relations = tuple(
            relation
            for relation in self.relations
            if relation.status == RelationStatus.ACTIVE
            and (
                (direction == DependencyDirection.OUTGOING and relation.source_symbol_id == symbol_id)
                or (direction == DependencyDirection.INCOMING and relation.target_symbol_id == symbol_id)
                or (
                    direction == DependencyDirection.BOTH
                    and symbol_id in (relation.source_symbol_id, relation.target_symbol_id)
                )
            )
        )
        return tuple(
            sorted(
                relations,
                key=lambda relation: (
                    relation.relation_type,
                    relation.resolution_status.value,
                    relation.target_key or "",
                    relation.relation_id,
                ),
            )
        )

    def relation_candidates(self, relation_id: str):
        return ()
