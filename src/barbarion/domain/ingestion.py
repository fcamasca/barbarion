"""Reglas puras de ingesta compartidas por el pipeline."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from barbarion.config import IngestionSettings, Settings
from barbarion.domain.models import (
    DiscoveredFile,
    FileFingerprint,
    FileStatus,
    IngestionMode,
)


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


def _process(reason: str) -> IncrementalDecision:
    return IncrementalDecision(
        action=IncrementalAction.PROCESS,
        reason=reason,
        requires_hash=True,
        requires_parser=True,
    )


def _require_non_empty(value: str, key: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} debe ser una cadena no vacia.")
