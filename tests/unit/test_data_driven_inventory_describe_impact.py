"""Pruebas de visibilidad H4 para conocimiento Data-Driven."""

from dataclasses import replace

from pathlib import Path

from barbarion import cli
from barbarion.application.reverse_engineering import (
    DependencyWalkService,
    DescribeRequest,
    DescribeService,
    ImpactRequest,
    ImpactService,
    InventoryRequest,
    InventoryService,
    ObjectRequest,
)
from barbarion.database import initialize_database
from barbarion.domain.models import Confidence
from barbarion.domain.reverse_engineering import (
    AnalysisRunMode,
    DependencyDirection,
    EvidenceClassification,
    InventoryFilters,
    InventoryItem,
    InventorySummary,
    RelationCandidate,
    ResolutionStatus,
    TechnicalRelation,
    TechnicalSymbol,
    technical_reference_id,
    technical_relation_id,
    technical_symbol_id,
)
from barbarion.infrastructure.markdown import (
    render_component_markdown,
    render_impact_markdown,
)
from barbarion.infrastructure.sqlite import SQLiteReverseEngineeringRepository


def test_cli_accepts_configuration_technology_filters() -> None:
    """Verifica el contrato argparse para filtros Data-Driven."""
    parser = cli.build_parser()

    inventory = parser.parse_args(
        ["inventory", "--technology", "configuration"]
    )
    impact = parser.parse_args(
        ["impact", "pricing_rules.r1", "--technology", "configuration"]
    )

    assert inventory.technology == "configuration"
    assert impact.technology == "configuration"


def test_inventory_technology_configuration_filters_sqlite(
    tmp_path: Path,
) -> None:
    """Verifica filtro real de inventario por tecnologia `configuration`.

    Args:
        tmp_path: Directorio temporal para crear una base SQLite aislada.
    """
    db_path = tmp_path / "barbarion.db"
    initialize_database(db_path)
    repository = SQLiteReverseEngineeringRepository(db_path)
    run_id = repository.begin_analysis_run(
        mode=AnalysisRunMode.INCREMENTAL,
        scope={"stage": "fixture"},
    )
    configuration = replace(
        _configuration_symbol("pricing_rules.r1"),
        file_id=None,
        document_id=None,
        chunk_id=None,
    )
    oracle = replace(
        _technical_symbol("tax_rate", symbol_type="function", technology="oracle"),
        file_id=None,
        document_id=None,
        chunk_id=None,
    )
    repository.upsert_symbol(run_id=run_id, symbol=configuration)
    repository.upsert_symbol(run_id=run_id, symbol=oracle)

    inventory = InventoryService(repository).inventory(
        InventoryRequest(filters=InventoryFilters(technology="configuration"))
    )

    assert inventory.summary.symbols == 1
    assert tuple(item.symbol.technology for item in inventory.items) == ("configuration",)
    assert inventory.items[0].symbol.normalized_name == "pricing_rules.r1"


def test_inventory_exposes_configuration_filter_and_metadata() -> None:
    """Verifica inventario text/json para tecnologia `configuration`."""
    symbol = _configuration_symbol("pricing_rules.r1")
    item = InventoryItem(
        symbol=symbol,
        relative_path="config/pricing/rules.sql",
        outgoing_relations=1,
        incoming_relations=0,
        reference_count=2,
    )
    repository = _FakeRepository(
        symbols=(symbol,),
        relations=(),
        inventory_items=(item,),
        inventory_summary=InventorySummary(files=1, symbols=1, references=2, relations=1),
    )
    inventory = InventoryService(repository).inventory(
        InventoryRequest(filters=InventoryFilters(technology="configuration"))
    )

    text = cli._render_inventory(inventory, "text")
    payload = cli._inventory_json(inventory)

    assert repository.last_filters == InventoryFilters(technology="configuration")
    assert "tecnologia=configuration" in text
    assert "configuracion=pricing_rules" in text
    assert payload["items"][0]["configuration"]["configuration_name"] == "pricing_rules"
    assert payload["items"][0]["configuration"]["display_values"] == ["Base Rule"]


def test_describe_configuration_record_uses_data_driven_summary() -> None:
    """Comprueba describe con responsabilidades propias de configuracion."""
    record = _configuration_symbol("pricing_rules.r1")
    formula = _configuration_symbol(
        "pricing_rules.r1.configuration_formula.formula",
        symbol_type="configuration_formula",
    )
    repository = _FakeRepository(
        symbols=(record, formula),
        relations=(_relation(record, formula, relation_type="uses"),),
    )
    service = DescribeService(
        repository=repository,
        dependency_walk_service=DependencyWalkService(repository),
    )

    result = service.describe(
        DescribeRequest(target=ObjectRequest(query="pricing_rules.r1"), no_llm=True)
    )
    json_payload = cli._description_json(result)

    assert result.resolution.symbol == record
    assert "registro Data-Driven" in result.summary
    assert any("proviene de la tabla APP_CFG.PRICING_RULES" in item for item in result.responsibilities)
    assert json_payload["resolution"]["symbol"]["configuration"]["record_id"] == "R1"


def test_describe_configuration_entity_record_and_derived_symbols() -> None:
    """Comprueba busqueda de entidad, registro y simbolo derivado Data-Driven."""
    entity = _configuration_symbol("pricing_rules", symbol_type="configuration_entity")
    record = _configuration_symbol("pricing_rules.r1")
    formula = _configuration_symbol(
        "pricing_rules.r1.configuration_formula.formula",
        symbol_type="configuration_formula",
        display_values=("A" * 120,),
    )
    repository = _FakeRepository(
        symbols=(entity, record, formula),
        relations=(
            _relation(entity, record, relation_type="parent_of"),
            _relation(record, formula, relation_type="uses"),
        ),
    )
    service = DescribeService(
        repository=repository,
        dependency_walk_service=DependencyWalkService(repository),
    )

    entity_description = service.describe(
        DescribeRequest(target=ObjectRequest(query="pricing_rules"), no_llm=True)
    )
    record_description = service.describe(
        DescribeRequest(target=ObjectRequest(query="pricing_rules.r1"), no_llm=True)
    )
    formula_description = service.describe(
        DescribeRequest(
            target=ObjectRequest(
                query="pricing_rules.r1.configuration_formula.formula"
            ),
            no_llm=True,
        )
    )
    markdown = render_component_markdown(formula_description)
    json_payload = cli._description_json(formula_description)

    assert "entidad Data-Driven" in entity_description.summary
    assert "registro Data-Driven" in record_description.summary
    assert "configuration_formula Data-Driven" in formula_description.summary
    assert "... (truncado)" in markdown
    assert json_payload["resolution"]["symbol"]["configuration"]["display_values"] == [
        "A" * 120
    ]


def test_impact_configuration_record_reports_cross_technology() -> None:
    """Valida impacto cruzado entre configuracion y funcion tecnica."""
    record = _configuration_symbol("pricing_rules.r1")
    function = _technical_symbol("tax_rate", symbol_type="function", technology="oracle")
    repository = _FakeRepository(
        symbols=(record, function),
        relations=(_relation(record, function, relation_type="calls"),),
    )
    service = ImpactService(
        repository=repository,
        dependency_walk_service=DependencyWalkService(repository),
    )

    result = service.analyze(
        ImpactRequest(
            target=ObjectRequest(query="pricing_rules.r1"),
            direction=DependencyDirection.OUTGOING,
            depth=1,
        )
    )
    text = cli._render_impact(result, "text")

    assert "Impacto Data-Driven" in result.summary
    assert len(result.cross_technology) == 1
    assert "cruces_tecnologia = 1" in text


def test_impact_data_driven_formats_cross_relations_and_statuses() -> None:
    """Valida impact Data-Driven en text, json y markdown con estados mixtos."""
    record = _configuration_symbol("pricing_rules.r1")
    next_record = _configuration_symbol("pricing_rules.r2")
    oracle = _technical_symbol("tax_rate", symbol_type="function", technology="oracle")
    powerbuilder = _technical_symbol(
        "calculate_amount",
        symbol_type="function_object",
        technology="powerbuilder",
    )
    consumer = _configuration_symbol("pricing_rules.consumer")
    relations = (
        _relation(record, next_record, relation_type="precedes"),
        _relation(record, oracle, relation_type="calls"),
        _relation(record, powerbuilder, relation_type="calls"),
        _relation(consumer, record, relation_type="references"),
        _relation(
            record,
            None,
            relation_type="calls",
            target_key="ambiguous_rate",
            resolution_status=ResolutionStatus.AMBIGUOUS,
        ),
        _relation(
            record,
            None,
            relation_type="calls",
            target_key="missing_rate",
            resolution_status=ResolutionStatus.UNRESOLVED,
        ),
        _relation(
            record,
            None,
            relation_type="calls",
            target_key="dynamic.rate",
            resolution_status=ResolutionStatus.DYNAMIC,
        ),
        _relation(
            record,
            None,
            relation_type="calls",
            target_key="external.rate",
            resolution_status=ResolutionStatus.EXTERNAL,
        ),
    )
    repository = _FakeRepository(
        symbols=(record, next_record, oracle, powerbuilder, consumer),
        relations=relations,
    )
    service = ImpactService(
        repository=repository,
        dependency_walk_service=DependencyWalkService(repository),
    )

    result = service.analyze(
        ImpactRequest(
            target=ObjectRequest(query="pricing_rules.r1"),
            direction=DependencyDirection.BOTH,
            depth=1,
        )
    )
    text = cli._render_impact(result, "text")
    json_payload = cli._impact_json(result)
    markdown = render_impact_markdown(result)

    assert len(result.consumers) == 1
    assert len(result.dependencies) == 7
    assert len(result.cross_technology) == 2
    for status in ("ambiguous", "unresolved", "dynamic", "external"):
        assert f"estado={status}" in text
        assert f"estado={status}" in markdown
    assert "pricing_rules.r1 -> pricing_rules.r2 tipo=precedes estado=resolved" in text
    assert "pricing_rules.consumer -> pricing_rules.r1" in text
    assert {edge["resolution_status"] for edge in json_payload["walk"]["edges"]} >= {
        "resolved",
        "ambiguous",
        "unresolved",
        "dynamic",
        "external",
    }
    assert json_payload["walk"]["edges"][0]["source_symbol"]["configuration"]


class _FakeRepository:
    """Repositorio en memoria para servicios de inventario, describe e impacto."""

    def __init__(
        self,
        *,
        symbols: tuple[TechnicalSymbol, ...],
        relations: tuple[TechnicalRelation, ...],
        inventory_items: tuple[InventoryItem, ...] = (),
        inventory_summary: InventorySummary | None = None,
        candidates: dict[str, tuple[RelationCandidate, ...]] | None = None,
    ) -> None:
        self._symbols = {symbol.symbol_id: symbol for symbol in symbols}
        self._relations = relations
        self._inventory_items = inventory_items
        self._inventory_summary = inventory_summary or InventorySummary()
        self._candidates = candidates or {}
        self.last_filters: InventoryFilters | None = None

    def inventory_summary(self, filters: InventoryFilters) -> InventorySummary:
        """Devuelve resumen fixture conservando filtros recibidos."""
        self.last_filters = filters
        return self._inventory_summary

    def inventory_items(self, filters: InventoryFilters) -> tuple[InventoryItem, ...]:
        """Devuelve items fixture conservando filtros recibidos."""
        self.last_filters = filters
        return self._inventory_items

    def get_symbol(self, symbol_id: str) -> TechnicalSymbol | None:
        """Devuelve un simbolo fixture por ID."""
        return self._symbols.get(symbol_id)

    def active_symbols(self) -> tuple[TechnicalSymbol, ...]:
        """Devuelve simbolos fixture en orden estable."""
        return tuple(sorted(self._symbols.values(), key=lambda item: item.symbol_id))

    def active_relations_for_symbol(
        self,
        symbol_id: str,
        *,
        direction: DependencyDirection,
    ) -> tuple[TechnicalRelation, ...]:
        """Devuelve relaciones adyacentes segun direccion solicitada."""
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

    def relation_candidates(self, relation_id: str) -> tuple[RelationCandidate, ...]:
        """Devuelve candidatos ambiguos asociados a una relacion fixture."""
        return self._candidates.get(relation_id, ())


def _configuration_symbol(
    normalized_name: str,
    *,
    symbol_type: str = "configuration_record",
    display_values: tuple[str, ...] = ("Base Rule",),
) -> TechnicalSymbol:
    """Crea un simbolo Data-Driven con metadata representativa."""
    return _technical_symbol(
        normalized_name,
        symbol_type=symbol_type,
        technology="configuration",
        container_name="pricing_rules",
        metadata={
            "configuration_name": "pricing_rules",
            "record_id": "R1",
            "table": "APP_CFG.PRICING_RULES",
            "operation": "insert",
            "identity_values": ("R1",),
            "display_values": display_values,
            "declared_columns": ("RULE_ID", "RULE_NAME", "FORMULA"),
        },
    )


def _technical_symbol(
    normalized_name: str,
    *,
    symbol_type: str,
    technology: str,
    container_name: str | None = None,
    metadata: dict[str, object] | None = None,
) -> TechnicalSymbol:
    """Crea un simbolo fixture con identidad determinista."""
    return TechnicalSymbol(
        symbol_id=technical_symbol_id(
            normalized_name=normalized_name,
            symbol_type=symbol_type,
            technology=technology,
            container_name=container_name,
        ),
        original_name=normalized_name,
        normalized_name=normalized_name,
        symbol_type=symbol_type,
        technology=technology,
        extraction_method="fixture",
        confidence=Confidence.HIGH,
        file_id=1,
        document_id=1,
        chunk_id=f"chunk-{normalized_name}",
        container_name=container_name,
        start_line=1,
        end_line=3,
        metadata=metadata or {},
    )


def _relation(
    source: TechnicalSymbol,
    target: TechnicalSymbol | None,
    *,
    relation_type: str,
    target_key: str | None = None,
    resolution_status: ResolutionStatus = ResolutionStatus.RESOLVED,
) -> TechnicalRelation:
    """Crea una relacion fixture entre dos simbolos o un destino no resuelto."""
    normalized_target = target.normalized_name if target is not None else target_key
    assert normalized_target is not None
    reference_id = technical_reference_id(
        source_file_id=1,
        raw_text=f"{source.normalized_name}->{normalized_target}",
        normalized_target=normalized_target,
        reference_type=relation_type,
        start_line=1,
        end_line=1,
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
        classification=(
            EvidenceClassification.DETECTED
            if resolution_status == ResolutionStatus.RESOLVED
            else EvidenceClassification.TO_CONFIRM
        ),
        resolution_status=resolution_status,
        confidence=Confidence.HIGH,
        evidence_file_id=1,
        evidence_chunk_id=source.chunk_id,
    )
