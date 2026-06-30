"""Integracion H4-T04 de resolucion y persistencia SQLite."""

from pathlib import Path

from barbarion.application.reverse_engineering import RelationResolutionService
from barbarion.config import load_settings
from barbarion.database import initialize_database
from barbarion.domain.models import Confidence
from barbarion.domain.reverse_engineering import (
    H4AnalysisRunMode,
    H4ResolutionStatus,
    H4Symbol,
    H4Reference,
    h4_reference_id,
    h4_symbol_id,
)
from barbarion.infrastructure.sqlite import SQLiteReverseEngineeringRepository
from tests.unit.test_rag_index_service import seed_chunks


def test_h4_relation_resolution_persists_relations_and_candidates(
    tmp_path: Path,
) -> None:
    path = tmp_path / "barbarion.db"
    initialize_database(path)
    seed_chunks(path)
    repository = SQLiteReverseEngineeringRepository(path)
    seed_run_id = repository.begin_analysis_run(
        mode=H4AnalysisRunMode.INCREMENTAL,
        scope={"stage": "fixture"},
    )
    source = _symbol("actual", "procedure", container_name="pkg_cliente")
    target = _symbol("procesar", "procedure", container_name="pkg_cliente")
    ambiguous_a = _symbol("duplicado", "procedure", container_name="pkg_a")
    ambiguous_b = _symbol("duplicado", "procedure", container_name="pkg_b")
    table = _symbol("ordenes", "table")
    for symbol in (source, target, ambiguous_a, ambiguous_b, table):
        repository.upsert_symbol(run_id=seed_run_id, symbol=symbol)
    references = (
        _reference(
            "PKG_CLIENTE.PROCESAR",
            normalized_target="pkg_cliente.procesar",
            reference_type="call",
            source_symbol_id=source.symbol_id,
        ),
        _reference(
            "DUPLICADO",
            normalized_target="duplicado",
            reference_type="call",
        ),
        _reference(
            "FROM ORDENES",
            normalized_target="ordenes",
            reference_type="table",
        ),
        _reference(
            "execute immediate v_sql",
            normalized_target="dynamic.sql",
            reference_type="dynamic_sql",
            resolution_status=H4ResolutionStatus.DYNAMIC,
        ),
        _reference(
            "remote_pkg.process@erp_link",
            normalized_target="remote_pkg.process",
            reference_type="call",
            metadata={"scope": "external"},
        ),
        _reference(
            "NO_EXISTE",
            normalized_target="no_existe",
            reference_type="call",
        ),
    )
    for reference in references:
        repository.upsert_reference(run_id=seed_run_id, reference=reference)

    summary = RelationResolutionService(
        settings=load_settings(environ={}, cwd=tmp_path),
        repository=repository,
    ).run()

    assert summary.references_seen == 6
    assert summary.relations_resolved == 2
    assert summary.relations_ambiguous == 1
    assert summary.relations_dynamic == 1
    assert summary.relations_external == 1
    assert summary.unresolved_without_relation == 1
    relations = _relations_by_reference(repository, references)
    assert relations[references[0].reference_id].target_symbol_id == target.symbol_id
    assert relations[references[0].reference_id].resolution_status == H4ResolutionStatus.RESOLVED
    assert relations[references[1].reference_id].resolution_status == H4ResolutionStatus.AMBIGUOUS
    assert relations[references[2].reference_id].target_symbol_id == table.symbol_id
    assert relations[references[3].reference_id].resolution_status == H4ResolutionStatus.DYNAMIC
    assert relations[references[4].reference_id].resolution_status == H4ResolutionStatus.EXTERNAL
    assert references[5].reference_id not in relations
    candidates = repository.relation_candidates(
        relations[references[1].reference_id].relation_id
    )
    assert tuple(candidate.candidate_symbol_id for candidate in candidates) == (
        ambiguous_a.symbol_id,
        ambiguous_b.symbol_id,
    )


def _relations_by_reference(
    repository: SQLiteReverseEngineeringRepository,
    references: tuple[H4Reference, ...],
) -> dict[str, object]:
    relations = {}
    for reference in references:
        persisted = repository.relations_for_reference(reference.reference_id)
        if persisted:
            assert len(persisted) == 1
            relations[reference.reference_id] = persisted[0]
    return relations


def _symbol(
    normalized_name: str,
    symbol_type: str,
    *,
    container_name: str | None = None,
) -> H4Symbol:
    symbol_id = h4_symbol_id(
        normalized_name=normalized_name,
        symbol_type=symbol_type,
        technology="oracle",
        container_name=container_name,
    )
    return H4Symbol(
        symbol_id=symbol_id,
        original_name=normalized_name,
        normalized_name=normalized_name,
        symbol_type=symbol_type,
        technology="oracle",
        extraction_method="fixture",
        confidence=Confidence.HIGH,
        file_id=1,
        document_id=1,
        chunk_id="chunk-1",
        container_name=container_name,
    )


def _reference(
    raw_text: str,
    *,
    normalized_target: str,
    reference_type: str,
    source_symbol_id: str | None = None,
    resolution_status: H4ResolutionStatus = H4ResolutionStatus.UNRESOLVED,
    metadata: dict[str, object] | None = None,
) -> H4Reference:
    reference_id = h4_reference_id(
        source_file_id=1,
        raw_text=raw_text,
        normalized_target=normalized_target,
        reference_type=reference_type,
        start_line=1,
        end_line=1,
    )
    return H4Reference(
        reference_id=reference_id,
        source_file_id=1,
        source_symbol_id=source_symbol_id,
        source_chunk_id="chunk-1",
        raw_text=raw_text,
        normalized_target=normalized_target,
        reference_type=reference_type,
        technology="oracle",
        detection_method="fixture",
        confidence=Confidence.MEDIUM,
        resolution_status=resolution_status,
        start_line=1,
        end_line=1,
        metadata=metadata or {},
    )
