"""Pruebas H4-T07 para servicios describe e impact."""

from dataclasses import dataclass

from barbarion.application.rag import ContextBuilder
from barbarion.application.reverse_engineering import (
    DependencyWalkService,
    DescribeRequest,
    DescribeService,
    ObjectRequest,
    ImpactRequest,
    ImpactService,
)
from barbarion.domain.rag import RetrievalCandidate
from barbarion.domain.models import Confidence
from barbarion.domain.reverse_engineering import (
    EvidenceClassification,
    DependencyDirection,
    TechnicalReference,
    TechnicalRelation,
    RelationCandidate,
    ResolutionStatus,
    TechnicalSymbol,
    technical_reference_id,
    technical_relation_id,
    technical_symbol_id,
)


def test_describe_resolves_unique_object_without_llm() -> None:
    root = _symbol("pkg.root")
    dependency = _symbol("pkg.dependency")
    consumer = _symbol("pkg.consumer")
    repository = _FakeRepository(
        symbols=(root, dependency, consumer),
        relations=(
            _relation(root, dependency),
            _relation(consumer, root),
        ),
    )
    service = DescribeService(
        repository=repository,
        dependency_walk_service=DependencyWalkService(repository),
    )

    result = service.describe(
        DescribeRequest(target=ObjectRequest(query="pkg.root"), no_llm=True)
    )

    assert result.resolution.symbol == root
    assert result.no_llm is True
    assert "Dependencias salientes: 1" in result.summary
    assert "Consumidores: 1" in result.summary
    assert len(result.evidence) == 2
    assert result.to_confirm == ()


def test_describe_reports_missing_and_ambiguous_without_auto_selection() -> None:
    first = _symbol("pkg.duplicado", container_name="pkg_a")
    second = _symbol("pkg.duplicado", container_name="pkg_b")
    repository = _FakeRepository(symbols=(first, second), relations=())
    service = DescribeService(
        repository=repository,
        dependency_walk_service=DependencyWalkService(repository),
    )

    missing = service.describe(
        DescribeRequest(target=ObjectRequest(query="pkg.missing"))
    )
    ambiguous = service.describe(
        DescribeRequest(target=ObjectRequest(query="pkg.duplicado"))
    )

    assert missing.resolution.status == "not_found"
    assert missing.outgoing is None
    assert ambiguous.resolution.status == "ambiguous"
    assert {
        symbol.symbol_id for symbol in ambiguous.resolution.candidates
    } == {first.symbol_id, second.symbol_id}
    assert ambiguous.outgoing is None


def test_describe_uses_fake_llm_after_deterministic_walk() -> None:
    root = _symbol("pkg.root")
    dependency = _symbol("pkg.dependency")
    repository = _FakeRepository(
        symbols=(root, dependency),
        relations=(_relation(root, dependency),),
    )
    llm = _FakeLlm("Sintesis LLM controlada.")
    service = DescribeService(
        repository=repository,
        dependency_walk_service=DependencyWalkService(repository),
        llm_provider=llm,
    )

    result = service.describe(
        DescribeRequest(target=ObjectRequest(query="pkg.root"), no_llm=False)
    )

    assert result.no_llm is False
    assert result.summary == "Sintesis LLM controlada."
    assert "pkg.root" in llm.prompt
    assert result.outgoing is not None
    assert len(result.outgoing.nodes) == 2


def test_impact_consumes_dependency_walk_and_keeps_rag_out_of_selection() -> None:
    root = _symbol("pkg.root")
    dependency = _symbol("pkg.dependency", technology="oracle")
    consumer = _symbol("w_root", technology="powerbuilder", container_name="w")
    repository = _FakeRepository(
        symbols=(root, dependency, consumer),
        relations=(
            _relation(root, dependency),
            _relation(consumer, root),
        ),
    )
    service = ImpactService(
        repository=repository,
        dependency_walk_service=DependencyWalkService(repository),
        search_service=_FakeSearchService(),
        context_builder=_FakeContextBuilder(),
    )

    result = service.analyze(
        ImpactRequest(
            target=ObjectRequest(query="pkg.root"),
            direction=DependencyDirection.BOTH,
            depth=1,
            include_rag=True,
        )
    )

    assert result.resolution.symbol == root
    assert result.walk is not None
    assert tuple(node.symbol.symbol_id for node in result.walk.nodes) == (
        root.symbol_id,
        dependency.symbol_id,
        consumer.symbol_id,
    )
    assert result.rag_sources == ("F1:semantic-only-chunk",)
    assert len(result.consumers) == 1
    assert len(result.dependencies) == 1
    assert len(result.cross_technology) == 1


def test_h4_impact_accepts_optimized_context_without_changing_graph_selection() -> None:
    root = _symbol("pkg.root")
    dependency = _symbol("pkg.dependency")
    repository = _FakeRepository(
        symbols=(root, dependency),
        relations=(_relation(root, dependency),),
    )
    candidates = (
        RetrievalCandidate(
            chunk_id="low-document-first",
            content_sha256="a" * 64,
            combined_score=0.2,
            source={
                "document_id": 1,
                "ordinal": 0,
                "relative_path": "synthetic/low.sql",
                "content": "evidencia complementaria baja",
            },
        ),
        RetrievalCandidate(
            chunk_id="high-relevance",
            content_sha256="b" * 64,
            combined_score=0.9,
            source={
                "document_id": 2,
                "ordinal": 0,
                "relative_path": "synthetic/high.sql",
                "content": "evidencia complementaria relevante",
            },
        ),
    )

    class Search:
        def search(self, request):  # noqa: ANN001, ANN201
            del request
            return _FakeSearchResponse(candidates=candidates)

    service = ImpactService(
        repository=repository,
        dependency_walk_service=DependencyWalkService(repository),
        search_service=Search(),
        context_builder=ContextBuilder(
            token_budget=500,
            max_chunk_tokens=100,
            dedupe_min_hash_prefix=16,
            selection_policy="optimized_v1",
        ),
    )

    result = service.analyze(
        ImpactRequest(
            target=ObjectRequest(query="pkg.root"),
            include_rag=True,
        )
    )

    assert result.walk is not None
    assert tuple(node.symbol.symbol_id for node in result.walk.nodes) == (
        root.symbol_id,
        dependency.symbol_id,
    )
    assert result.rag_sources == (
        "F1:low-document-first",
        "F2:high-relevance",
    )


def test_impact_reports_cycles_and_unresolved_edges_as_risks() -> None:
    root = _symbol("pkg.root")
    dependency = _symbol("pkg.dependency")
    unresolved = _relation(
        root,
        None,
        target_key="pkg.missing",
        resolution_status=ResolutionStatus.UNRESOLVED,
    )
    repository = _FakeRepository(
        symbols=(root, dependency),
        relations=(
            _relation(root, dependency),
            _relation(dependency, root),
            unresolved,
        ),
    )
    service = ImpactService(
        repository=repository,
        dependency_walk_service=DependencyWalkService(repository),
    )

    result = service.analyze(
        ImpactRequest(target=ObjectRequest(query="pkg.root"), depth=2)
    )

    assert result.walk is not None
    assert result.walk.cycles
    assert "pkg.missing" in result.to_confirm
    assert "hay ciclos de dependencia" in result.risks
    assert "hay relaciones por confirmar" in result.risks


class _FakeRepository:
    """Repositorio minimo para servicios H4 sin SQLite."""

    def __init__(
        self,
        *,
        symbols: tuple[TechnicalSymbol, ...],
        relations: tuple[TechnicalRelation, ...],
        candidates: dict[str, tuple[RelationCandidate, ...]] | None = None,
    ) -> None:
        self._symbols = {symbol.symbol_id: symbol for symbol in symbols}
        self._relations = relations
        self._candidates = candidates or {}

    def get_symbol(self, symbol_id: str) -> TechnicalSymbol | None:
        """Devuelve un simbolo fixture por ID."""
        return self._symbols.get(symbol_id)

    def active_symbols(self) -> tuple[TechnicalSymbol, ...]:
        """Devuelve simbolos activos ordenados."""
        return tuple(
            sorted(
                self._symbols.values(),
                key=lambda symbol: (
                    symbol.technology,
                    symbol.container_name or "",
                    symbol.normalized_name,
                    symbol.symbol_id,
                ),
            )
        )

    def active_relations_for_symbol(
        self,
        symbol_id: str,
        *,
        direction: DependencyDirection,
    ) -> tuple[TechnicalRelation, ...]:
        """Devuelve relaciones adyacentes segun direccion calculada."""
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


class _FakeLlm:
    """LLM fake que conserva el prompt recibido."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.prompt = ""

    def generate(self, *, prompt: str, timeout_seconds: float) -> str:
        """Devuelve una respuesta determinista sin usar red."""
        del timeout_seconds
        self.prompt = prompt
        return self.response


class _FakeSearchService:
    """Search fake que simula evidencia RAG no determinante."""

    def search(self, request):
        """Devuelve un candidato que no debe modificar el impacto."""
        del request
        return _FakeSearchResponse(candidates=(_FakeCandidate("semantic-only-chunk"),))


class _FakeContextBuilder:
    """Context builder fake que expone fuentes trazables."""

    def build(self, candidates):
        """Convierte candidatos fake en fuentes fake."""
        return _FakeContext(
            sources=tuple(
                _FakeSource(source_id=f"F{index}", candidate=candidate)
                for index, candidate in enumerate(candidates, start=1)
            )
        )


@dataclass(frozen=True, slots=True)
class _FakeSearchResponse:
    candidates: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class _FakeContext:
    sources: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class _FakeSource:
    source_id: str
    candidate: object


@dataclass(frozen=True, slots=True)
class _FakeCandidate:
    chunk_id: str


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
    )


def _relation(
    source: TechnicalSymbol,
    target: TechnicalSymbol | None,
    *,
    target_key: str | None = None,
    resolution_status: ResolutionStatus = ResolutionStatus.RESOLVED,
) -> TechnicalRelation:
    raw_target = target.normalized_name if target is not None else target_key or "missing"
    reference = _reference(source, raw_target)
    relation_id = technical_relation_id(
        reference_id=reference.reference_id,
        relation_type="calls",
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
        relation_type="calls",
        classification=EvidenceClassification.DETECTED
        if resolution_status == ResolutionStatus.RESOLVED
        else EvidenceClassification.TO_CONFIRM,
        resolution_status=resolution_status,
        confidence=Confidence.MEDIUM,
        evidence_file_id=1,
    )


def _reference(source: TechnicalSymbol, target: str) -> TechnicalReference:
    reference_id = technical_reference_id(
        source_file_id=1,
        raw_text=f"{source.normalized_name}->{target}",
        normalized_target=target,
        reference_type="call",
        start_line=1,
        end_line=1,
    )
    return TechnicalReference(
        reference_id=reference_id,
        source_file_id=1,
        source_symbol_id=source.symbol_id,
        raw_text=target,
        normalized_target=target,
        reference_type="call",
        technology=source.technology,
        detection_method="fixture",
        confidence=Confidence.MEDIUM,
        resolution_status=ResolutionStatus.RESOLVED,
        start_line=1,
        end_line=1,
    )
