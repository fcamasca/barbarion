from __future__ import annotations

import hashlib
import json

import pytest

from barbarion.domain.ingestion import (
    canonical_chunk_metadata,
    chunk_document,
    chunk_id_for,
    normalize_extraction,
)
from barbarion.domain.models import (
    Confidence,
    ExtractionResult,
    LogicalUnit,
    NormalizedDocument,
)


SOURCE_SHA = "a" * 64
OTHER_SHA = "b" * 64
PROCESSING_SIGNATURE = "processing-signature"


def extraction(text: str, units: tuple[LogicalUnit, ...] = ()) -> ExtractionResult:
    return ExtractionResult(
        text=text,
        title="fixture",
        encoding="utf-8",
        units=units,
        metadata={"parser": "test"},
        warnings=("WARN",),
    )


def test_normalization_removes_bom_and_normalizes_line_endings_only() -> None:
    source = "\ufeffLinea 1\r\n\tSELECT * FROM dual; -- Comentario\rUltima Ñ"

    document = normalize_extraction(extraction(source), source_sha256=SOURCE_SHA)

    assert document.text == "Linea 1\n\tSELECT * FROM dual; -- Comentario\nUltima Ñ"
    assert "\tSELECT" in document.text
    assert "-- Comentario" in document.text
    assert document.content_sha256 == hashlib.sha256(
        document.text.encode("utf-8")
    ).hexdigest()
    assert document.metadata["normalizer_version"] == "1"
    assert document.metadata["warnings"] == ("WARN",)


def test_normalization_adjusts_character_offsets_after_bom_and_crlf() -> None:
    unit = LogicalUnit(
        unit_type="section",
        name="demo",
        confidence=Confidence.HIGH,
        start_char=8,
        end_char=12,
    )

    document = normalize_extraction(
        extraction("\ufeffUno\r\nDos", (unit,)),
        source_sha256=SOURCE_SHA,
    )

    assert document.text == "Uno\nDos"
    assert document.units[0].start_char == 6
    assert document.units[0].end_char == 8


def test_chunking_uses_logical_units_and_propagates_traceability() -> None:
    units = (
        LogicalUnit(
            unit_type="procedure",
            name="pkg.proc_a",
            confidence=Confidence.HIGH,
            start_line=1,
            end_line=2,
            metadata={
                "object_type": "procedure",
                "object_name": "pkg.proc_a",
                "breadcrumb": ("pkg", "proc_a"),
            },
        ),
        LogicalUnit(
            unit_type="procedure",
            name="pkg.proc_b",
            confidence=Confidence.MEDIUM,
            start_line=4,
            end_line=5,
            metadata={
                "parent_type": "package_body",
                "parent_name": "pkg",
                "object_type": "procedure",
                "object_name": "pkg.proc_b",
                "breadcrumb": ("pkg", "proc_b"),
            },
        ),
    )
    document = normalize_extraction(
        extraction("PROCEDURE a\nEND;\n\nPROCEDURE b\nEND;", units),
        source_sha256=SOURCE_SHA,
    )

    chunks = chunk_document(
        document,
        file_identity="src/pkg.pkb",
        processing_signature=PROCESSING_SIGNATURE,
        chunk_size=100,
        chunk_overlap=0,
    )

    assert [chunk.ordinal for chunk in chunks] == [0, 1]
    assert all(chunk.chunk_id is not None for chunk in chunks)
    assert chunks[0].chunk_type == "procedure"
    assert chunks[0].object_name == "pkg.proc_a"
    assert chunks[0].metadata["logical_unit_confidence"] == "high"
    assert chunks[1].metadata["logical_unit_confidence"] == "medium"
    assert chunks[1].metadata["heuristic"] is True


def test_chunking_groups_small_compatible_units() -> None:
    units = (
        LogicalUnit(
            unit_type="event",
            name="open",
            confidence=Confidence.HIGH,
            start_line=1,
            end_line=1,
            metadata={"parent_type": "window", "parent_name": "w_main"},
        ),
        LogicalUnit(
            unit_type="event",
            name="close",
            confidence=Confidence.LOW,
            start_line=2,
            end_line=2,
            metadata={"parent_type": "window", "parent_name": "w_main"},
        ),
    )
    document = normalize_extraction(extraction("open\nclose", units), source_sha256=SOURCE_SHA)

    chunks = chunk_document(
        document,
        file_identity="pb/w_main.srw",
        processing_signature=PROCESSING_SIGNATURE,
        chunk_size=20,
        chunk_overlap=0,
    )

    assert len(chunks) == 1
    assert chunks[0].chunk_type == "group"
    assert chunks[0].content == "open\n\nclose"
    assert chunks[0].metadata["logical_unit_confidence"] == "low"


def test_chunking_splits_large_units_by_lines_and_overlap() -> None:
    unit = LogicalUnit(
        unit_type="file",
        name="large.txt",
        confidence=Confidence.LOW,
        start_line=1,
        end_line=4,
    )
    document = normalize_extraction(
        extraction("aaaa\nbbbb\ncccc\ndddd", (unit,)),
        source_sha256=SOURCE_SHA,
    )

    chunks = chunk_document(
        document,
        file_identity="large.txt",
        processing_signature=PROCESSING_SIGNATURE,
        chunk_size=9,
        chunk_overlap=2,
    )

    assert len(chunks) >= 2
    assert all(len(chunk.content) <= 9 for chunk in chunks)
    assert chunks[0].content == "aaaa\nbbbb"
    assert chunks[1].content.startswith("bb")


def test_chunking_uses_paragraphs_when_document_has_no_units() -> None:
    document = NormalizedDocument(
        text="primer parrafo\n\nsegundo parrafo",
        units=(),
        source_sha256=SOURCE_SHA,
        content_sha256=hashlib.sha256(b"primer parrafo\n\nsegundo parrafo").hexdigest(),
    )

    chunks = chunk_document(
        document,
        file_identity="notes.txt",
        processing_signature=PROCESSING_SIGNATURE,
        chunk_size=100,
        chunk_overlap=0,
    )

    assert len(chunks) == 1
    assert chunks[0].chunk_type == "text"
    assert chunks[0].metadata["logical_unit_confidence"] == "low"


def test_chunking_preserves_page_locators() -> None:
    unit = LogicalUnit(
        unit_type="page",
        name="pagina 2",
        confidence=Confidence.HIGH,
        start_char=1,
        end_char=11,
        page_start=2,
        page_end=2,
        metadata={"breadcrumb": ("pagina 2",)},
    )
    document = NormalizedDocument(
        text="texto pagina",
        units=(unit,),
        source_sha256=SOURCE_SHA,
        content_sha256=hashlib.sha256(b"texto pagina").hexdigest(),
    )

    chunks = chunk_document(
        document,
        file_identity="manual.pdf",
        processing_signature=PROCESSING_SIGNATURE,
        chunk_size=100,
        chunk_overlap=0,
    )

    assert chunks[0].page_start == 2
    assert chunks[0].page_end == 2
    assert chunks[0].metadata["breadcrumb"] == ("pagina 2",)


def test_chunking_rejects_empty_document() -> None:
    document = NormalizedDocument(
        text="",
        units=(),
        source_sha256=SOURCE_SHA,
        content_sha256=hashlib.sha256(b"").hexdigest(),
    )

    with pytest.raises(ValueError, match="vacio"):
        chunk_document(
            document,
            file_identity="empty.txt",
            processing_signature=PROCESSING_SIGNATURE,
            chunk_size=10,
            chunk_overlap=0,
        )


def test_chunk_metadata_and_ids_are_canonical_and_deterministic() -> None:
    locator = {"end_line": 2, "start_line": 1, "breadcrumb": ("pkg", "proc")}

    first_metadata = canonical_chunk_metadata(locator)
    second_metadata = canonical_chunk_metadata(
        {"breadcrumb": ["pkg", "proc"], "start_line": 1, "end_line": 2}
    )
    first_id = chunk_id_for(
        file_identity="pkg.pkb",
        source_sha256=SOURCE_SHA,
        processing_signature=PROCESSING_SIGNATURE,
        locator=locator,
        content_sha256=OTHER_SHA,
    )
    second_id = chunk_id_for(
        file_identity="pkg.pkb",
        source_sha256=SOURCE_SHA,
        processing_signature=PROCESSING_SIGNATURE,
        locator={"start_line": 1, "breadcrumb": ["pkg", "proc"], "end_line": 2},
        content_sha256=OTHER_SHA,
    )

    assert json.loads(first_metadata) == json.loads(second_metadata)
    assert first_id == second_id
    assert chunk_id_for(
        file_identity="pkg.pkb",
        source_sha256=SOURCE_SHA,
        processing_signature="other",
        locator=locator,
        content_sha256=OTHER_SHA,
    ) != first_id
