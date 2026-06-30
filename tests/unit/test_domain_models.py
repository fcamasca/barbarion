"""Pruebas de contratos puros del dominio de ingesta."""

from pathlib import Path, PurePosixPath
from types import MappingProxyType

import pytest

from barbarion.domain.models import (
    ChunkCandidate,
    Confidence,
    DiscoveredFile,
    ErrorStage,
    ExtractionContext,
    ExtractionResult,
    FileFingerprint,
    IngestionMetrics,
    IngestionOutcome,
    IngestionRunStatus,
    LogicalUnit,
    NormalizedDocument,
    PipelineError,
    SourceFile,
)
from barbarion.domain.reverse_engineering import (
    EvidenceClassification,
    TechnicalReference,
    TechnicalRelation,
    ResolutionStatus,
    TechnicalSymbol,
    technical_reference_id,
    technical_relation_id,
    technical_symbol_id,
    normalize_symbol_name,
)


VALID_SHA = "a" * 64
OTHER_SHA = "b" * 64


def discovered_file(tmp_path: Path) -> DiscoveredFile:
    """Construye un archivo descubierto valido."""
    return DiscoveredFile(
        root=tmp_path,
        relative_path=PurePosixPath("pkg/body.sql"),
        runtime_path=tmp_path / "pkg" / "body.sql",
        extension="SQL",
        size_bytes=128,
        mtime_ns=12345,
    )


def test_discovered_file_normalizes_extension(tmp_path: Path) -> None:
    file = discovered_file(tmp_path)

    assert file.extension == ".sql"
    assert file.relative_path == PurePosixPath("pkg/body.sql")


def test_discovered_file_rejects_unsafe_relative_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="relativa segura"):
        DiscoveredFile(
            root=tmp_path,
            relative_path=PurePosixPath("../secret.sql"),
            runtime_path=tmp_path / "secret.sql",
            extension=".sql",
            size_bytes=1,
            mtime_ns=1,
        )


def test_fingerprint_accepts_optional_sha256() -> None:
    fingerprint = FileFingerprint(
        size_bytes=10,
        mtime_ns=20,
        sha256=None,
    )

    assert fingerprint.version == 1
    assert fingerprint.sha256 is None


def test_fingerprint_rejects_invalid_sha256() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        FileFingerprint(size_bytes=10, mtime_ns=20, sha256="ABC")


def test_extraction_contract_keeps_units_and_freezes_metadata() -> None:
    unit = LogicalUnit(
        unit_type="package",
        name="pkg_demo",
        confidence=Confidence.HIGH,
        start_line=1,
        end_line=12,
        metadata={"parser": "oracle"},
    )
    result = ExtractionResult(
        text="create package pkg_demo as end;",
        title="pkg_demo",
        encoding="utf-8",
        units=(unit,),
        metadata={"source": "fixture"},
        warnings=("LOW_CONFIDENCE_ENCODING",),
    )

    assert unit.confidence == Confidence.HIGH
    assert isinstance(unit.metadata, MappingProxyType)
    assert result.units == (unit,)
    assert result.warnings == ("LOW_CONFIDENCE_ENCODING",)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"start_line": 3}, "inicio y fin"),
        ({"start_line": 5, "end_line": 4}, "terminar despues"),
        ({"page_start": 0, "page_end": 1}, "mayor que 0"),
    ],
)
def test_logical_unit_rejects_invalid_ranges(
    kwargs: dict[str, int],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        LogicalUnit(
            unit_type="file",
            name=None,
            confidence=Confidence.LOW,
            **kwargs,
        )


def test_normalized_document_and_chunk_candidate_validate_hashes() -> None:
    unit = LogicalUnit("file", None, Confidence.LOW, start_line=1, end_line=1)
    document = NormalizedDocument(
        text="select 1;",
        units=(unit,),
        source_sha256=VALID_SHA,
        content_sha256=OTHER_SHA,
    )
    chunk = ChunkCandidate(
        ordinal=0,
        chunk_id=None,
        chunk_type="file",
        content=document.text,
        content_sha256=OTHER_SHA,
        start_line=1,
        end_line=1,
        metadata={"logical_unit_confidence": Confidence.LOW.value},
    )

    assert document.units == (unit,)
    assert chunk.ordinal == 0
    assert chunk.metadata["logical_unit_confidence"] == "low"


def test_chunk_candidate_requires_content() -> None:
    with pytest.raises(ValueError, match="content"):
        ChunkCandidate(
            ordinal=0,
            chunk_id=None,
            chunk_type="file",
            content="",
            content_sha256=VALID_SHA,
        )


def test_pipeline_error_and_outcome_are_typed(tmp_path: Path) -> None:
    error = PipelineError(
        stage=ErrorStage.EXTRACTION,
        error_code="TEXT_DECODE_FAILED",
        message="No se pudo decodificar el archivo.",
        recoverable=True,
        relative_path=PurePosixPath("pkg/body.sql"),
        details={"encoding": "cp1252"},
    )
    metrics = IngestionMetrics(discovered_files=1, error_count=1)
    outcome = IngestionOutcome(
        status=IngestionRunStatus.FAILED,
        metrics=metrics,
        error=error,
    )
    source = SourceFile(
        discovered=discovered_file(tmp_path),
        fingerprint=FileFingerprint(128, 12345, VALID_SHA),
    )

    assert outcome.error == error
    assert source.fingerprint is not None
    assert isinstance(error.details, MappingProxyType)


def test_failed_outcome_requires_typed_error() -> None:
    with pytest.raises(ValueError, match="requieren un error"):
        IngestionOutcome(
            status=IngestionRunStatus.FAILED,
            metrics=IngestionMetrics(),
        )


def test_h4_normalizes_symbol_names_for_cross_file_resolution() -> None:
    assert normalize_symbol_name(' "PKG_CLIENTE" . Procesar ') == "pkg_cliente.procesar"


def test_technical_symbol_ids_are_deterministic_and_logical() -> None:
    first = technical_symbol_id(
        normalized_name="PKG_CLIENTE.PROCESAR",
        symbol_type="Procedure",
        technology="Oracle",
        container_name="PKG_CLIENTE",
    )
    second = technical_symbol_id(
        normalized_name="pkg_cliente.procesar",
        symbol_type="procedure",
        technology="oracle",
        container_name="pkg_cliente",
    )
    other_container = technical_symbol_id(
        normalized_name="pkg_cliente.procesar",
        symbol_type="procedure",
        technology="oracle",
        container_name="pkg_otro",
    )

    assert first == second
    assert first != other_container


def test_h4_models_validate_ranges_and_freeze_metadata() -> None:
    symbol_id = technical_symbol_id(
        normalized_name="pkg_cliente.procesar",
        symbol_type="procedure",
        technology="oracle",
        container_name="pkg_cliente",
    )
    symbol = TechnicalSymbol(
        symbol_id=symbol_id,
        original_name="PKG_CLIENTE.PROCESAR",
        normalized_name="pkg_cliente.procesar",
        symbol_type="procedure",
        technology="oracle",
        extraction_method="parser",
        confidence=Confidence.HIGH,
        file_id=10,
        document_id=20,
        chunk_id="chunk-1",
        container_name="pkg_cliente",
        start_line=3,
        end_line=8,
        metadata={"owner": "fixture"},
    )

    assert isinstance(symbol.metadata, MappingProxyType)
    assert symbol.metadata["owner"] == "fixture"
    with pytest.raises(ValueError, match="terminar despues"):
        TechnicalSymbol(
            symbol_id=symbol_id,
            original_name="PKG_CLIENTE.PROCESAR",
            normalized_name="pkg_cliente.procesar",
            symbol_type="procedure",
            technology="oracle",
            extraction_method="parser",
            confidence=Confidence.HIGH,
            start_line=8,
            end_line=3,
        )


def test_h4_reference_and_relation_ids_are_deterministic() -> None:
    target_id = technical_symbol_id(
        normalized_name="pkg_cliente.procesar",
        symbol_type="procedure",
        technology="oracle",
    )
    reference_id = technical_reference_id(
        source_file_id=10,
        raw_text="PKG_CLIENTE.PROCESAR",
        normalized_target="PKG_CLIENTE.PROCESAR",
        reference_type="calls",
        start_line=12,
        end_line=12,
    )
    relation_id = technical_relation_id(
        reference_id=reference_id,
        relation_type="calls",
        target_symbol_id=target_id,
    )
    repeated = technical_relation_id(
        reference_id=reference_id,
        relation_type="CALLS",
        target_symbol_id=target_id,
    )

    reference = TechnicalReference(
        reference_id=reference_id,
        source_file_id=10,
        raw_text="PKG_CLIENTE.PROCESAR",
        normalized_target="pkg_cliente.procesar",
        reference_type="calls",
        technology="oracle",
        detection_method="parser",
        confidence=Confidence.MEDIUM,
        resolution_status=ResolutionStatus.UNRESOLVED,
        start_line=12,
        end_line=12,
    )

    assert relation_id == repeated
    assert reference.normalized_target == "pkg_cliente.procesar"


def test_h4_dynamic_relations_require_to_confirm_classification() -> None:
    reference_id = technical_reference_id(
        source_file_id=10,
        raw_text="execute immediate v_sql",
        normalized_target="dynamic.sql",
        reference_type="dynamic_call",
    )
    relation_id = technical_relation_id(
        reference_id=reference_id,
        relation_type="dynamic_call",
        target_key="dynamic.sql",
    )

    relation = TechnicalRelation(
        relation_id=relation_id,
        reference_id=reference_id,
        relation_type="dynamic_call",
        classification=EvidenceClassification.TO_CONFIRM,
        resolution_status=ResolutionStatus.DYNAMIC,
        confidence=Confidence.LOW,
        evidence_file_id=10,
    )

    assert relation.resolution_status == ResolutionStatus.DYNAMIC
    with pytest.raises(ValueError, match="por_confirmar"):
        TechnicalRelation(
            relation_id=relation_id,
            reference_id=reference_id,
            relation_type="dynamic_call",
            classification=EvidenceClassification.DETECTED,
            resolution_status=ResolutionStatus.DYNAMIC,
            confidence=Confidence.LOW,
            evidence_file_id=10,
        )
