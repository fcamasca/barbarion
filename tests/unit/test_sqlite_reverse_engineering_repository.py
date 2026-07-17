"""Pruebas del repositorio SQLite H4 Reverse Engineering."""

import sqlite3
from dataclasses import replace
from pathlib import Path

from barbarion.application.reverse_engineering import AnalyzeService
from barbarion.config import (
    DataDrivenConfiguration,
    DataDrivenReferenceColumn,
    DataDrivenSettings,
    load_settings,
)
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


def test_h4_analyze_persists_data_driven_symbols_idempotently(
    tmp_path: Path,
) -> None:
    path = tmp_path / "barbarion.db"
    initialize_database(path)
    _seed_configuration_chunk(path)
    repository = SQLiteReverseEngineeringRepository(path)
    settings = replace(
        load_settings(environ={}, cwd=tmp_path),
        data_driven=DataDrivenSettings(
            enabled=True,
            file_patterns=("*.sql",),
            max_statements_per_file=100,
            max_literal_chars=1000,
            token_patterns=(),
            configurations=(_configuration(),),
        ),
    )
    service = AnalyzeService(settings=settings, repository=repository)

    first = service.run()
    second = service.run()

    assert first.symbols_detected == second.symbols_detected == 5
    assert first.references_detected == second.references_detected == 1
    assert first.relations_resolved == second.relations_resolved == 1
    symbols = repository.active_symbols()
    assert len(symbols) == 5
    by_type = {
        (symbol.symbol_type, symbol.original_name): symbol
        for symbol in symbols
    }
    entity = by_type[("configuration_entity", "pricing_rules")]
    record = by_type[("configuration_record", "Base Rule")]
    formula = by_type[("configuration_formula", "{A}+{B}")]
    mapping = by_type[("configuration_mapping", "CustomerMap")]
    assert record.parent_symbol_id == entity.symbol_id
    assert formula.parent_symbol_id == record.symbol_id
    assert mapping.parent_symbol_id == record.symbol_id
    assert record.file_id == 1
    assert record.document_id == 1
    assert record.chunk_id == "cfg-chunk-1"
    assert record.start_line == 20
    assert record.metadata["configuration_name"] == "pricing_rules"
    assert record.metadata["identity"] == {"rule_id": "'R1'"}
    assert record.metadata["artifact_kind"] == "configuration"
    assert record.metadata["relative_path"] == "cfg/pricing.sql"

    with sqlite3.connect(path) as connection:
        symbol_count = connection.execute(
            "SELECT COUNT(*) FROM symbols"
        ).fetchone()[0]
        reference_count = connection.execute(
            "SELECT COUNT(*) FROM symbol_references"
        ).fetchone()[0]
        relation_count = connection.execute(
            "SELECT COUNT(*) FROM relations"
        ).fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert symbol_count == 5
    assert reference_count == 1
    assert relation_count == 1
    assert "symbols" in tables
    assert "relations" in tables
    assert "symbol_references" in tables
    assert not any(table.startswith("data_driven") for table in tables)


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


def _configuration() -> DataDrivenConfiguration:
    return DataDrivenConfiguration(
        name="pricing_rules",
        symbol_type="configuration_record",
        tables=("APP_CFG.PRICING_RULES",),
        identity_columns=("RULE_ID",),
        file_patterns=(),
        default_column_order=(),
        name_columns=("RULE_NAME",),
        description_columns=(),
        rule_columns=(),
        formula_columns=("FORMULA",),
        variable_columns=(),
        parameter_columns=(),
        mapping_columns=("MAPPING_NAME",),
        reference_columns=(
            DataDrivenReferenceColumn(
                column="NEXT_RULE_ID",
                target_configuration="pricing_rules",
            ),
        ),
        parent_columns=(),
        sequence_columns=(),
        status_columns=(),
        effective_from_columns=(),
        effective_to_columns=(),
        metadata_columns=(),
    )


def _seed_configuration_chunk(path: Path) -> None:
    statement = (
        "INSERT INTO APP_CFG.PRICING_RULES (\n"
        "    RULE_ID, RULE_NAME,\n"
        "    FORMULA, MAPPING_NAME\n"
        ")\n"
        "VALUES ('R1', 'Base Rule', '{A}+{B}', 'CustomerMap');"
    )
    linked_statement = (
        "INSERT INTO APP_CFG.PRICING_RULES "
        "(RULE_ID, RULE_NAME, NEXT_RULE_ID) "
        "VALUES ('R2', 'Linked Rule', 'R1');"
    )
    document_text = ("\n" * 19) + statement + "\n" + linked_statement
    first_chunk = "\n".join(statement.splitlines()[:3])
    second_chunk = "\n".join((*statement.splitlines()[2:], linked_statement))
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO ingestion_runs(
                id, domain, mode, status, roots_json, config_sha256, started_at
            )
            VALUES (1, 'default', 'incremental', 'completed', '[]', ?, ?)
            """,
            ("f" * 64, "2026-01-01T00:00:00+00:00"),
        )
        connection.execute(
            """
            INSERT INTO files(
                id, domain, source_root, relative_path, extension, artifact_kind,
                media_type, size_bytes, modified_at_ns, sha256, status,
                first_seen_run_id, last_seen_run_id, created_at, updated_at
            )
            VALUES (
                1, 'default', 'root', 'cfg/pricing.sql', '.sql',
                'configuration', 'text/plain', 128, 1, ?, 'processed',
                1, 1, ?, ?
            )
            """,
            (
                "a" * 64,
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO documents(
                id, file_id, source_sha256, parser_id, parser_version,
                normalizer_version, normalized_text, content_sha256,
                metadata_json, warnings_json, extracted_at
            )
            VALUES (1, 1, ?, 'data_driven_dml', '1', '1', ?, ?, '{}', '[]', ?)
            """,
            (
                "a" * 64,
                document_text,
                "b" * 64,
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO chunks(
                id, document_id, ordinal, chunk_type, content, content_sha256,
                start_line, end_line, object_type, object_name, metadata_json,
                chunker_version, created_at
            )
            VALUES
                (
                    'cfg-chunk-1', 1, 0, 'file', ?, ?, 20, 22, NULL, NULL,
                    '{"artifact_kind":"configuration"}', '1', ?
                ),
                (
                    'cfg-chunk-2', 1, 1, 'file', ?, ?, 22, 25, NULL, NULL,
                    '{"artifact_kind":"configuration"}', '1', ?
                )
            """,
            (
                first_chunk,
                "c" * 64,
                "2026-01-01T00:00:00+00:00",
                second_chunk,
                "d" * 64,
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.commit()
