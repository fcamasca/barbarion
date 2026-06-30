"""Pruebas del repositorio SQLite H4 Reverse Engineering."""

from pathlib import Path

from barbarion.database import initialize_database
from barbarion.domain.models import Confidence
from barbarion.domain.reverse_engineering import (
    AnalysisRunMode,
    AnalysisRunStatus,
    EvidenceClassification,
    DependencyDirection,
    TechnicalReference,
    TechnicalRelation,
    ResolutionStatus,
    TechnicalSymbol,
    technical_reference_id,
    technical_relation_id,
    technical_symbol_id,
)
from barbarion.infrastructure.sqlite import SQLiteReverseEngineeringRepository
from tests.unit.test_rag_index_service import seed_chunks


def test_h4_repository_inserts_and_reads_run_symbols_references_and_relations(
    tmp_path: Path,
) -> None:
    path = tmp_path / "barbarion.db"
    initialize_database(path)
    seed_chunks(path)
    repository = SQLiteReverseEngineeringRepository(path)

    run_id = repository.begin_analysis_run(
        mode=AnalysisRunMode.INCREMENTAL,
        scope={"path_prefix": "pkg/"},
    )
    symbol_id = technical_symbol_id(
        normalized_name="pkg_demo.demo",
        symbol_type="procedure",
        technology="oracle",
        container_name="pkg_demo",
    )
    symbol = TechnicalSymbol(
        symbol_id=symbol_id,
        original_name="PKG_DEMO.DEMO",
        normalized_name="pkg_demo.demo",
        symbol_type="procedure",
        technology="oracle",
        extraction_method="parser",
        confidence=Confidence.HIGH,
        file_id=1,
        document_id=1,
        chunk_id="chunk-1",
        container_name="pkg_demo",
        start_line=1,
        end_line=4,
        metadata={"source": "fixture"},
    )
    reference_id = technical_reference_id(
        source_file_id=1,
        raw_text="PKG_DEMO.DEMO",
        normalized_target="pkg_demo.demo",
        reference_type="calls",
        start_line=6,
        end_line=6,
    )
    reference = TechnicalReference(
        reference_id=reference_id,
        source_file_id=1,
        source_chunk_id="chunk-2",
        raw_text="PKG_DEMO.DEMO",
        normalized_target="pkg_demo.demo",
        reference_type="calls",
        technology="oracle",
        detection_method="parser",
        confidence=Confidence.MEDIUM,
        resolution_status=ResolutionStatus.RESOLVED,
        start_line=6,
        end_line=6,
    )
    relation_id = technical_relation_id(
        reference_id=reference_id,
        relation_type="calls",
        target_symbol_id=symbol_id,
    )
    relation = TechnicalRelation(
        relation_id=relation_id,
        reference_id=reference_id,
        target_symbol_id=symbol_id,
        target_key="pkg_demo.demo",
        relation_type="calls",
        classification=EvidenceClassification.DETECTED,
        resolution_status=ResolutionStatus.RESOLVED,
        confidence=Confidence.MEDIUM,
        evidence_file_id=1,
        evidence_chunk_id="chunk-2",
        start_line=6,
        end_line=6,
    )

    repository.upsert_symbol(run_id=run_id, symbol=symbol)
    repository.upsert_reference(run_id=run_id, reference=reference)
    repository.upsert_relation(run_id=run_id, relation=relation)
    repository.finish_analysis_run(
        run_id=run_id,
        status=AnalysisRunStatus.COMPLETED,
        symbols_detected=1,
        references_detected=1,
        relations_resolved=1,
        duration_ms=25,
    )

    run = repository.analysis_run(run_id)
    assert run is not None
    assert run.status == AnalysisRunStatus.COMPLETED
    assert run.scope["path_prefix"] == "pkg/"
    assert run.symbols_detected == 1
    assert repository.get_symbol(symbol_id) == symbol
    assert repository.get_reference(reference_id) == reference
    assert repository.get_relation(relation_id) == relation
    assert repository.active_relations_for_symbol(
        symbol_id,
        direction=DependencyDirection.INCOMING,
    ) == (relation,)
    assert repository.active_relations_for_symbol(
        symbol_id,
        direction=DependencyDirection.OUTGOING,
    ) == ()


def test_h4_repository_active_references_ignore_orphan_chunks(
    tmp_path: Path,
) -> None:
    path = tmp_path / "barbarion.db"
    initialize_database(path)
    seed_chunks(path)
    repository = SQLiteReverseEngineeringRepository(path)
    run_id = repository.begin_analysis_run(
        mode=AnalysisRunMode.FULL,
        scope={"path_prefix": "pkg/"},
    )
    active_reference = _reference(
        source_chunk_id="chunk-2",
        raw_text="active_call();",
        normalized_target="active_call",
        start_line=6,
    )
    orphan_reference = _reference(
        source_chunk_id="chunk-1",
        raw_text="orphan_call();",
        normalized_target="orphan_call",
        start_line=9,
    )

    repository.upsert_reference(run_id=run_id, reference=active_reference)
    repository.upsert_reference(run_id=run_id, reference=orphan_reference)
    with repository._connect() as connection:
        connection.execute("DELETE FROM chunks WHERE id = 'chunk-1'")
        connection.commit()

    stored_orphan = repository.get_reference(orphan_reference.reference_id)
    assert stored_orphan is not None
    assert stored_orphan.source_chunk_id is None
    assert repository.active_references() == (active_reference,)


def _reference(
    *,
    source_chunk_id: str,
    raw_text: str,
    normalized_target: str,
    start_line: int,
) -> TechnicalReference:
    reference_id = technical_reference_id(
        source_file_id=1,
        raw_text=raw_text,
        normalized_target=normalized_target,
        reference_type="calls",
        start_line=start_line,
        end_line=start_line,
    )
    return TechnicalReference(
        reference_id=reference_id,
        source_file_id=1,
        source_chunk_id=source_chunk_id,
        raw_text=raw_text,
        normalized_target=normalized_target,
        reference_type="calls",
        technology="oracle",
        detection_method="parser",
        confidence=Confidence.MEDIUM,
        resolution_status=ResolutionStatus.UNRESOLVED,
        start_line=start_line,
        end_line=start_line,
    )
