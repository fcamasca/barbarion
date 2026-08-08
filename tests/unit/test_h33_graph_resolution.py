"""Pruebas T05 de resolución citable y fusión graph-aware."""

import hashlib
from dataclasses import replace

from barbarion.application.rag import (
    GraphEvidenceResolver,
    _prepare_graph_aware_families,
)
from barbarion.domain.models import Confidence
from barbarion.domain.rag import (
    CandidateOrigin,
    CandidateOriginKind,
    GraphCandidateStatus,
    GraphCandidateTrace,
    GraphPath,
    GraphSeed,
    RetrievalCandidate,
    SeedOrigin,
    SymbolMetadata,
)
from barbarion.domain.reverse_engineering import (
    DependencyDirection,
    EvidenceClassification,
    ResolutionStatus,
    SymbolStatus,
    TechnicalReference,
    TechnicalRelation,
    TechnicalSymbol,
)


def test_graph_resolver_prefers_active_symbol_chunk_and_keeps_all_origins() -> None:
    target = _symbol("target", chunk_id="chunk-target")
    repository = _ReverseRepository((target,), (), ())
    rag = _RagRepository({"chunk-target": "procedure target is begin null; end;"})
    traces = (
        _trace(target, seed_id="seed-a", relation_id=_sha("r-a")),
        _trace(
            target,
            seed_id="seed-b",
            relation_id=_sha("r-b"),
            status=GraphCandidateStatus.DUPLICATE,
        ),
    )

    candidates = GraphEvidenceResolver(repository, rag, "legacy").resolve(
        traces,
        seeds=(_seed("seed-a", 0.9), _seed("seed-b", 0.8)),
    )

    assert len(candidates) == 1
    assert candidates[0].chunk_id == "chunk-target"
    assert candidates[0].source["relation_evidence_fallback"] is False
    assert len(candidates[0].source["graph_origins"]) == 2


def test_graph_resolver_accepts_only_valid_relation_evidence_fallback() -> None:
    caller = _symbol("caller", chunk_id="chunk-evidence")
    target = _symbol("pkg.target", chunk_id=None)
    relation, reference = _relation_and_reference(caller, target, "chunk-evidence")
    trace = _trace(target, seed_id="seed-a", relation_id=relation.relation_id)
    repository = _ReverseRepository(
        (caller, target),
        (relation,),
        (reference,),
    )
    valid_rag = _RagRepository(
        {"chunk-evidence": "begin PKG.TARGET(); end;"}
    )
    invalid_rag = _RagRepository(
        {"chunk-evidence": "begin unrelated_call(); end;"}
    )

    valid = GraphEvidenceResolver(repository, valid_rag, "legacy").resolve(
        (trace,), seeds=(_seed("seed-a", 0.9),)
    )
    invalid = GraphEvidenceResolver(repository, invalid_rag, "legacy").resolve(
        (trace,), seeds=(_seed("seed-a", 0.9),)
    )

    assert len(valid) == 1
    assert valid[0].chunk_id == "chunk-evidence"
    assert valid[0].source["relation_evidence_fallback"] is True
    assert invalid == ()


def test_graph_fusion_deduplicates_chunk_without_losing_origins() -> None:
    structured = _candidate(
        "chunk-shared",
        evidence_kind="structured_symbol",
    )
    graph = _candidate(
        "chunk-shared",
        evidence_kind="graph_expansion",
        graph_origins=(
            {"seed_ids": ("seed-a",), "relation_ids": ("r-a",)},
            {"seed_ids": ("seed-b",), "relation_ids": ("r-b",)},
        ),
    )
    direct = _candidate("chunk-shared", evidence_kind=None)

    structural, chunks = _prepare_graph_aware_families(
        (structured,), (graph,), (direct,)
    )

    assert len(structural) == 1
    assert chunks == ()
    assert len(structural[0].source["graph_origins"]) == 2
    assert structural[0].source["candidate_origin_kinds"] == (
        "structured_symbol",
        "graph_expansion",
        "h3_chunk",
    )


def _trace(
    symbol: TechnicalSymbol,
    *,
    seed_id: str,
    relation_id: str,
    status: GraphCandidateStatus = GraphCandidateStatus.ACCEPTED,
) -> GraphCandidateTrace:
    root_id = _sha(f"root:{seed_id}")
    path = GraphPath(
        nodes=(root_id, symbol.symbol_id),
        relations=(relation_id,),
        direction=DependencyDirection.OUTGOING,
        depth=1,
    )
    return GraphCandidateTrace(
        candidate_id=symbol.symbol_id,
        origin=CandidateOrigin(
            kind=CandidateOriginKind.GRAPH_EXPANSION,
            seed_ids=(seed_id,),
            relation_ids=(relation_id,),
            path=path,
        ),
        discovered_at_depth=1,
        dedupe_key=symbol.symbol_id,
        status=status,
    )


def _seed(seed_id: str, score: float) -> GraphSeed:
    return GraphSeed(
        seed_id=seed_id,
        chunk_id=f"chunk-{seed_id}",
        symbol_id=_sha(f"root:{seed_id}"),
        retrieval_score=score,
        origin=SeedOrigin.H3_CHUNK,
    )


def _symbol(name: str, *, chunk_id: str | None) -> TechnicalSymbol:
    return TechnicalSymbol(
        symbol_id=_sha(f"symbol:{name}"),
        original_name=name.upper(),
        normalized_name=name,
        symbol_type="procedure",
        technology="oracle",
        extraction_method="fixture",
        confidence=Confidence.HIGH,
        file_id=1,
        chunk_id=chunk_id,
        status=SymbolStatus.ACTIVE,
    )


def _relation_and_reference(
    caller: TechnicalSymbol,
    target: TechnicalSymbol,
    chunk_id: str,
) -> tuple[TechnicalRelation, TechnicalReference]:
    reference_id = _sha("reference:fallback")
    relation = TechnicalRelation(
        relation_id=_sha("relation:fallback"),
        reference_id=reference_id,
        relation_type="calls",
        classification=EvidenceClassification.DETECTED,
        resolution_status=ResolutionStatus.RESOLVED,
        confidence=Confidence.HIGH,
        evidence_file_id=1,
        source_symbol_id=caller.symbol_id,
        target_symbol_id=target.symbol_id,
        target_key=target.normalized_name,
        evidence_chunk_id=chunk_id,
    )
    reference = TechnicalReference(
        reference_id=reference_id,
        source_file_id=1,
        source_chunk_id=chunk_id,
        source_symbol_id=caller.symbol_id,
        raw_text="PKG.TARGET()",
        normalized_target="pkg.target",
        reference_type="call",
        technology="oracle",
        detection_method="fixture",
        confidence=Confidence.HIGH,
        resolution_status=ResolutionStatus.RESOLVED,
    )
    return relation, reference


def _candidate(
    chunk_id: str,
    *,
    evidence_kind: str | None,
    graph_origins=(),
) -> RetrievalCandidate:
    source = {"content": "select 1"}
    if evidence_kind is not None:
        source["evidence_kind"] = evidence_kind
    if graph_origins:
        source["graph_origins"] = graph_origins
    return RetrievalCandidate(
        chunk_id=chunk_id,
        content_sha256=_sha(chunk_id),
        combined_score=0.8,
        metadata=SymbolMetadata(symbol_name="pkg.target"),
        source=source,
    )


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class _ReverseRepository:
    def __init__(self, symbols, relations, references) -> None:
        self.symbols = {symbol.symbol_id: symbol for symbol in symbols}
        self.relations = {relation.relation_id: relation for relation in relations}
        self.references = {
            reference.reference_id: reference for reference in references
        }

    def get_symbol(self, symbol_id):
        return self.symbols.get(symbol_id)

    def get_relation(self, relation_id):
        return self.relations.get(relation_id)

    def get_reference(self, reference_id):
        return self.references.get(reference_id)


class _RagRepository:
    def __init__(self, chunks: dict[str, str]) -> None:
        self.chunks = chunks

    def active_chunk_exists(self, chunk_id: str, *, domain: str) -> bool:
        return domain == "legacy" and chunk_id in self.chunks

    def enrich_candidates(self, candidates, *, include_snippets):
        return tuple(
            replace(
                candidate,
                content_sha256=_sha(candidate.chunk_id),
                source={
                    "content": self.chunks[candidate.chunk_id],
                    "snippet": self.chunks[candidate.chunk_id],
                    **dict(candidate.source),
                },
            )
            for candidate in candidates
        )
