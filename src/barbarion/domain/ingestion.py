"""Reglas puras de ingesta compartidas por el pipeline."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

from barbarion.config import IngestionSettings, Settings


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


def _require_non_empty(value: str, key: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} debe ser una cadena no vacia.")

