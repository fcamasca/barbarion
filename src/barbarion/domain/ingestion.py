"""Reglas puras de ingesta compartidas por el pipeline."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any

from barbarion.config import IngestionSettings, Settings
from barbarion.domain.models import (
    ChunkCandidate,
    Confidence,
    DiscoveredFile,
    ExtractionResult,
    FileFingerprint,
    FileStatus,
    IngestionMode,
    LogicalUnit,
    NormalizedDocument,
)


NORMALIZER_VERSION = "1"
CHUNKER_VERSION = "1"
CHUNK_ID_SCHEMA = "barbarion.chunk-id.v1"


@dataclass(frozen=True, slots=True)
class ProcessingVersions:
    """Versiones que participan en una firma de procesamiento."""

    parser_versions: Mapping[str, str]
    normalizer_version: str = "1"
    chunker_version: str = "1"

    def __post_init__(self) -> None:
        if not self.parser_versions:
            raise ValueError("parser_versions debe contener al menos un parser.")
        _require_non_empty(self.normalizer_version, "normalizer_version")
        _require_non_empty(self.chunker_version, "chunker_version")
        for parser_id, parser_version in self.parser_versions.items():
            _require_non_empty(parser_id, "parser_id")
            _require_non_empty(parser_version, "parser_version")


class IncrementalAction(StrEnum):
    """Accion que el pipeline debe tomar para un archivo visto."""

    PROCESS = "process"
    UNCHANGED = "unchanged"
    TOUCH = "touch"
    HASH_REQUIRED = "hash_required"


@dataclass(frozen=True, slots=True)
class PersistedFileState:
    """Estado minimo persistido necesario para decidir reingesta."""

    size_bytes: int
    mtime_ns: int
    sha256: str | None
    status: FileStatus
    processing_signature: str | None


@dataclass(frozen=True, slots=True)
class IncrementalDecision:
    """Resultado verificable de la decision incremental."""

    action: IncrementalAction
    reason: str
    requires_hash: bool
    requires_parser: bool


def decide_incremental(
    discovered_file: DiscoveredFile,
    current_processing_signature: str,
    *,
    mode: IngestionMode = IngestionMode.INCREMENTAL,
    persisted: PersistedFileState | None = None,
    fingerprint: FileFingerprint | None = None,
) -> IncrementalDecision:
    """Decide si un archivo debe procesarse, tocarse o ignorarse."""
    _require_non_empty(current_processing_signature, "current_processing_signature")

    if mode == IngestionMode.FULL:
        return _process("full")
    if persisted is None:
        return _process("new")
    if persisted.status == FileStatus.ERROR:
        return _process("previous_error")
    if persisted.status != FileStatus.PROCESSED:
        return _process(f"status_{persisted.status.value}")
    if persisted.processing_signature != current_processing_signature:
        return _process("processing_signature_changed")
    if (
        persisted.size_bytes == discovered_file.size_bytes
        and persisted.mtime_ns == discovered_file.mtime_ns
    ):
        return IncrementalDecision(
            action=IncrementalAction.UNCHANGED,
            reason="metadata_unchanged",
            requires_hash=False,
            requires_parser=False,
        )
    if fingerprint is None:
        return IncrementalDecision(
            action=IncrementalAction.HASH_REQUIRED,
            reason="metadata_changed",
            requires_hash=True,
            requires_parser=False,
        )
    if fingerprint.sha256 == persisted.sha256:
        return IncrementalDecision(
            action=IncrementalAction.TOUCH,
            reason="content_unchanged",
            requires_hash=True,
            requires_parser=False,
        )
    return _process("content_changed")


def processing_signature(
    settings: Settings,
    versions: ProcessingVersions,
) -> str:
    """Devuelve SHA-256 de la configuracion transformativa canonica."""
    canonical = canonical_processing_config(settings.ingestion, versions)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalize_extraction(
    extraction: ExtractionResult,
    *,
    source_sha256: str,
) -> NormalizedDocument:
    """Normaliza texto sin alterar contenido tecnico interno."""

    _require_sha256(source_sha256, "source_sha256")
    normalized_text, offsets = _normalize_text_and_offsets(extraction.text)
    normalized_units = tuple(_normalize_unit(unit, offsets) for unit in extraction.units)
    content_sha256 = _sha256_text(normalized_text)
    metadata = {
        "normalizer_version": NORMALIZER_VERSION,
        "title": extraction.title,
        "encoding": extraction.encoding,
        "source_metadata": _plain_mapping(extraction.metadata),
        "warnings": tuple(extraction.warnings),
    }
    return NormalizedDocument(
        text=normalized_text,
        units=normalized_units,
        source_sha256=source_sha256,
        content_sha256=content_sha256,
        metadata=metadata,
    )


def chunk_document(
    document: NormalizedDocument,
    *,
    file_identity: str | PurePosixPath,
    processing_signature: str,
    chunk_size: int,
    chunk_overlap: int,
    chunker_version: str = CHUNKER_VERSION,
) -> tuple[ChunkCandidate, ...]:
    """Crea chunks trazables y deterministas desde un documento normalizado."""

    _require_non_empty(str(file_identity), "file_identity")
    _require_non_empty(processing_signature, "processing_signature")
    _require_non_empty(chunker_version, "chunker_version")
    _require_positive(chunk_size, "chunk_size")
    _require_non_negative(chunk_overlap, "chunk_overlap")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap debe ser menor que chunk_size.")
    if not document.text:
        raise ValueError("El documento normalizado no puede estar vacio.")

    spans = _unit_spans(document)
    chunks: list[ChunkCandidate] = []
    pending_group: list[_Span] = []

    def flush_group() -> None:
        if not pending_group:
            return
        chunks.append(
            _make_chunk(
                ordinal=len(chunks),
                spans=tuple(pending_group),
                document=document,
                file_identity=str(file_identity),
                processing_signature=processing_signature,
                chunker_version=chunker_version,
            )
        )
        pending_group.clear()

    for span in spans:
        if len(span.content) > chunk_size:
            flush_group()
            for split_span in _split_span(span, chunk_size=chunk_size, overlap=chunk_overlap):
                chunks.append(
                    _make_chunk(
                        ordinal=len(chunks),
                        spans=(split_span,),
                        document=document,
                        file_identity=str(file_identity),
                        processing_signature=processing_signature,
                        chunker_version=chunker_version,
                    )
                )
            continue
        candidate_group = (*pending_group, span)
        if (
            pending_group
            and _compatible_group(pending_group[-1], span)
            and _group_content_length(candidate_group) <= chunk_size
        ):
            pending_group.append(span)
            continue
        flush_group()
        pending_group.append(span)
    flush_group()

    if not chunks:
        raise ValueError("No se generaron chunks para el documento.")
    return tuple(chunks)


def canonical_processing_config(
    ingestion: IngestionSettings,
    versions: ProcessingVersions,
) -> str:
    """Serializa solo valores que cambian el procesamiento de contenido."""
    payload = {
        "schema": "barbarion.processing-signature.v1",
        "versions": {
            "parsers": dict(sorted(versions.parser_versions.items())),
            "normalizer": versions.normalizer_version,
            "chunker": versions.chunker_version,
        },
        "ingestion": {
            "extensions": sorted(ingestion.extensions),
            "chunk_size": ingestion.chunk_size,
            "chunk_overlap": ingestion.chunk_overlap,
            "max_file_size_mb": ingestion.max_file_size_mb,
            "max_extracted_chars": ingestion.max_extracted_chars,
            "max_pdf_pages": ingestion.max_pdf_pages,
            "encodings": list(ingestion.encodings),
        },
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def canonical_chunk_metadata(metadata: Mapping[str, Any]) -> str:
    """Serializa metadata de chunk de forma canonica."""

    return json.dumps(
        _jsonable(metadata),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def chunk_id_for(
    *,
    file_identity: str,
    source_sha256: str,
    processing_signature: str,
    locator: Mapping[str, Any],
    content_sha256: str,
) -> str:
    """Calcula identidad determinista para sincronizacion posterior."""

    _require_non_empty(file_identity, "file_identity")
    _require_sha256(source_sha256, "source_sha256")
    _require_non_empty(processing_signature, "processing_signature")
    _require_sha256(content_sha256, "content_sha256")
    payload = {
        "schema": CHUNK_ID_SCHEMA,
        "file_identity": file_identity,
        "source_sha256": source_sha256,
        "processing_signature": processing_signature,
        "locator": _jsonable(locator),
        "content_sha256": content_sha256,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _process(reason: str) -> IncrementalDecision:
    return IncrementalDecision(
        action=IncrementalAction.PROCESS,
        reason=reason,
        requires_hash=True,
        requires_parser=True,
    )


@dataclass(frozen=True, slots=True)
class _Offsets:
    old_to_new: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _Span:
    unit: LogicalUnit | None
    content: str
    start_char: int
    end_char: int
    start_line: int | None = None
    end_line: int | None = None
    page_start: int | None = None
    page_end: int | None = None


def _normalize_text_and_offsets(text: str) -> tuple[str, _Offsets]:
    raw_text = text[1:] if text.startswith("\ufeff") else text
    old_to_new: list[int] = [0] * (len(text) + 1)
    normalized: list[str] = []
    source_index = 0
    if text.startswith("\ufeff"):
        old_to_new[0] = 0
        old_to_new[1] = 0
        source_index = 1
    new_index = 0
    index = 0
    while index < len(raw_text):
        original_index = source_index + index
        character = raw_text[index]
        old_to_new[original_index] = new_index
        if character == "\r":
            normalized.append("\n")
            new_index += 1
            if index + 1 < len(raw_text) and raw_text[index + 1] == "\n":
                old_to_new[original_index + 1] = new_index - 1
                index += 2
                continue
            index += 1
            continue
        normalized.append(character)
        new_index += 1
        index += 1
    old_to_new[len(text)] = new_index
    return "".join(normalized), _Offsets(old_to_new=tuple(old_to_new))


def _normalize_unit(unit: LogicalUnit, offsets: _Offsets) -> LogicalUnit:
    start_char = _map_position(unit.start_char, offsets)
    end_char = _map_position(unit.end_char, offsets)
    if start_char is not None and end_char is not None and end_char < start_char:
        end_char = start_char
    return LogicalUnit(
        unit_type=unit.unit_type,
        name=unit.name,
        confidence=unit.confidence,
        start_line=unit.start_line,
        end_line=unit.end_line,
        start_char=start_char,
        end_char=end_char,
        page_start=unit.page_start,
        page_end=unit.page_end,
        metadata=dict(unit.metadata),
    )


def _map_position(value: int | None, offsets: _Offsets) -> int | None:
    if value is None:
        return None
    index = max(0, min(value - 1, len(offsets.old_to_new) - 1))
    return offsets.old_to_new[index] + 1


def _unit_spans(document: NormalizedDocument) -> tuple[_Span, ...]:
    if not document.units:
        return tuple(_paragraph_spans(document.text))
    line_offsets = _line_offsets(document.text)
    spans: list[_Span] = []
    for unit in document.units:
        start, end = _unit_char_range(unit, text=document.text, line_offsets=line_offsets)
        content = document.text[start - 1 : end].strip()
        if not content:
            continue
        spans.append(
            _Span(
                unit=unit,
                content=content,
                start_char=start,
                end_char=end,
                start_line=unit.start_line,
                end_line=unit.end_line,
                page_start=unit.page_start,
                page_end=unit.page_end,
            )
        )
    if spans:
        return tuple(spans)
    return tuple(_paragraph_spans(document.text))


def _paragraph_spans(text: str) -> tuple[_Span, ...]:
    spans: list[_Span] = []
    start = 0
    for paragraph in text.split("\n\n"):
        paragraph_start = text.find(paragraph, start)
        paragraph_end = paragraph_start + len(paragraph)
        stripped = paragraph.strip()
        if stripped:
            leading = len(paragraph) - len(paragraph.lstrip())
            trailing = len(paragraph.rstrip())
            spans.append(
                _Span(
                    unit=None,
                    content=stripped,
                    start_char=paragraph_start + leading + 1,
                    end_char=paragraph_start + trailing,
                )
            )
        start = paragraph_end + 2
    return tuple(spans)


def _unit_char_range(
    unit: LogicalUnit,
    *,
    text: str,
    line_offsets: tuple[int, ...],
) -> tuple[int, int]:
    if unit.start_char is not None and unit.end_char is not None:
        start = max(1, unit.start_char)
        end = min(len(text), unit.end_char)
        return start, max(start, end)
    if unit.start_line is not None and unit.end_line is not None:
        start_line = min(unit.start_line, len(line_offsets))
        end_line = min(unit.end_line, len(line_offsets))
        start = line_offsets[start_line - 1] + 1
        if end_line >= len(line_offsets):
            end = len(text)
        else:
            end = max(start, line_offsets[end_line] - 1)
        return start, end
    return 1, len(text)


def _line_offsets(text: str) -> tuple[int, ...]:
    offsets = [0]
    for index, character in enumerate(text):
        if character == "\n":
            offsets.append(index + 1)
    return tuple(offsets)


def _split_span(span: _Span, *, chunk_size: int, overlap: int) -> tuple[_Span, ...]:
    pieces = _split_text(span.content, chunk_size=chunk_size, overlap=overlap)
    result: list[_Span] = []
    cursor = 0
    for piece in pieces:
        local_start = span.content.find(piece, max(0, cursor - overlap))
        if local_start < 0:
            local_start = cursor
        local_end = local_start + len(piece)
        result.append(
            _Span(
                unit=span.unit,
                content=piece,
                start_char=span.start_char + local_start,
                end_char=span.start_char + local_end - 1,
                start_line=span.start_line,
                end_line=span.end_line,
                page_start=span.page_start,
                page_end=span.page_end,
            )
        )
        cursor = local_end
    return tuple(result)


def _split_text(text: str, *, chunk_size: int, overlap: int) -> tuple[str, ...]:
    if len(text) <= chunk_size:
        return (text,)
    chunks: list[str] = []
    start = 0
    while start < len(text):
        hard_end = min(len(text), start + chunk_size)
        end = _best_break(text, start=start, hard_end=hard_end)
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return tuple(chunks)


def _best_break(text: str, *, start: int, hard_end: int) -> int:
    if hard_end >= len(text) or text[hard_end] in "\n ":
        return hard_end
    window = text[start:hard_end]
    for marker in ("\n\n", "\n", " "):
        position = window.rfind(marker)
        if position > 0:
            return start + position + len(marker)
    return hard_end


def _compatible_group(left: _Span, right: _Span) -> bool:
    return _parent_key(left.unit) == _parent_key(right.unit)


def _parent_key(unit: LogicalUnit | None) -> tuple[Any, ...]:
    if unit is None:
        return ("document",)
    metadata = unit.metadata
    return (
        metadata.get("parent_type", unit.unit_type),
        metadata.get("parent_name", unit.name),
        tuple(metadata.get("breadcrumb", ())),
    )


def _group_content_length(spans: tuple[_Span, ...]) -> int:
    return sum(len(span.content) for span in spans) + max(0, len(spans) - 1) * 2


def _make_chunk(
    *,
    ordinal: int,
    spans: tuple[_Span, ...],
    document: NormalizedDocument,
    file_identity: str,
    processing_signature: str,
    chunker_version: str,
) -> ChunkCandidate:
    content = "\n\n".join(span.content for span in spans).strip()
    if not content:
        raise ValueError("Un chunk no puede tener contenido vacio.")
    confidence = _minimum_confidence(spans)
    locator = _locator(spans)
    metadata = {
        "schema": "barbarion.chunk-metadata.v1",
        "chunker_version": chunker_version,
        "logical_unit_confidence": confidence.value,
        "heuristic": confidence != Confidence.HIGH,
        **locator,
    }
    content_sha256 = _sha256_text(content)
    chunk_id = chunk_id_for(
        file_identity=file_identity,
        source_sha256=document.source_sha256,
        processing_signature=processing_signature,
        locator=locator,
        content_sha256=content_sha256,
    )
    object_type = metadata.get("object_type")
    object_name = metadata.get("object_name")
    return ChunkCandidate(
        ordinal=ordinal,
        chunk_id=chunk_id,
        chunk_type=_chunk_type(spans),
        content=content,
        content_sha256=content_sha256,
        start_line=metadata.get("start_line"),
        end_line=metadata.get("end_line"),
        start_char=metadata.get("start_char"),
        end_char=metadata.get("end_char"),
        page_start=metadata.get("page_start"),
        page_end=metadata.get("page_end"),
        object_type=object_type if isinstance(object_type, str) else None,
        object_name=object_name if isinstance(object_name, str) else None,
        metadata=metadata,
    )


def _minimum_confidence(spans: tuple[_Span, ...]) -> Confidence:
    order = {Confidence.LOW: 0, Confidence.MEDIUM: 1, Confidence.HIGH: 2}
    confidences = [
        span.unit.confidence if span.unit is not None else Confidence.LOW
        for span in spans
    ]
    return min(confidences, key=lambda confidence: order[confidence])


def _locator(spans: tuple[_Span, ...]) -> dict[str, Any]:
    start_char = min(span.start_char for span in spans)
    end_char = max(span.end_char for span in spans)
    metadata: dict[str, Any] = {
        "start_char": start_char,
        "end_char": end_char,
    }
    line_starts = [span.start_line for span in spans if span.start_line is not None]
    line_ends = [span.end_line for span in spans if span.end_line is not None]
    if line_starts and line_ends:
        metadata["start_line"] = min(line_starts)
        metadata["end_line"] = max(line_ends)
    page_starts = [span.page_start for span in spans if span.page_start is not None]
    page_ends = [span.page_end for span in spans if span.page_end is not None]
    if page_starts and page_ends:
        metadata["page_start"] = min(page_starts)
        metadata["page_end"] = max(page_ends)
    units = [span.unit for span in spans if span.unit is not None]
    if units:
        first = units[0]
        if first.name is not None:
            metadata["object_name"] = first.metadata.get("object_name", first.name)
        metadata["object_type"] = first.metadata.get("object_type", first.unit_type)
        breadcrumb = first.metadata.get("breadcrumb")
        if breadcrumb is not None:
            metadata["breadcrumb"] = tuple(breadcrumb)
        metadata["logical_units"] = tuple(
            {
                "type": unit.unit_type,
                "name": unit.name,
                "confidence": unit.confidence.value,
            }
            for unit in units
        )
    return metadata


def _chunk_type(spans: tuple[_Span, ...]) -> str:
    if len(spans) == 1 and spans[0].unit is not None:
        return spans[0].unit.unit_type
    if all(span.unit is None for span in spans):
        return "text"
    return "group"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _plain_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    return dict(values) if isinstance(values, MappingProxyType) else dict(values)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _jsonable(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    return value


def _require_non_empty(value: str, key: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} debe ser una cadena no vacia.")


def _require_non_negative(value: int, key: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} debe ser un entero mayor o igual que 0.")


def _require_positive(value: int, key: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{key} debe ser un entero mayor que 0.")


def _require_sha256(value: str, key: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{key} debe ser un SHA-256 hexadecimal en minusculas.")
