"""Pruebas de firma de procesamiento canónica."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from barbarion.config import IngestionSettings, Settings, load_settings
from barbarion.domain.ingestion import (
    ProcessingVersions,
    canonical_processing_config,
    processing_signature,
)


def versions(**overrides: str) -> ProcessingVersions:
    """Construye versiones de prueba."""
    parser_versions = {
        "oracle": overrides.pop("oracle", "1"),
        "text": overrides.pop("text", "1"),
    }
    return ProcessingVersions(
        parser_versions=parser_versions,
        normalizer_version=overrides.pop("normalizer", "1"),
        chunker_version=overrides.pop("chunker", "1"),
    )


def test_canonical_processing_config_is_stable(tmp_path: Path) -> None:
    settings = load_settings(environ={}, cwd=tmp_path)
    unordered_versions = ProcessingVersions(
        parser_versions={"text": "1", "oracle": "1"},
        normalizer_version="1",
        chunker_version="1",
    )
    ordered_versions = ProcessingVersions(
        parser_versions={"oracle": "1", "text": "1"},
        normalizer_version="1",
        chunker_version="1",
    )

    first = canonical_processing_config(settings.ingestion, unordered_versions)
    second = canonical_processing_config(settings.ingestion, ordered_versions)

    assert first == second
    assert json.loads(first) == json.loads(second)
    assert processing_signature(settings, unordered_versions) == processing_signature(
        settings,
        ordered_versions,
    )


@pytest.mark.parametrize(
    "changed",
    [
        {"chunk_size": 8000},
        {"chunk_overlap": 100},
        {"max_file_size_mb": 100},
        {"max_extracted_chars": 10_000_000},
        {"max_pdf_pages": 25},
        {"encodings": ("utf-8",)},
        {"extensions": (".sql", ".md")},
    ],
)
def test_transformative_ingestion_config_changes_signature(
    changed: dict[str, object],
    tmp_path: Path,
) -> None:
    settings = load_settings(environ={}, cwd=tmp_path)
    changed_ingestion = replace(settings.ingestion, **changed)
    changed_settings = replace(settings, ingestion=changed_ingestion)

    assert processing_signature(settings, versions()) != processing_signature(
        changed_settings,
        versions(),
    )


@pytest.mark.parametrize(
    "changed_versions",
    [
        {"oracle": "2"},
        {"normalizer": "2"},
        {"chunker": "2"},
    ],
)
def test_version_changes_signature(
    changed_versions: dict[str, str],
    tmp_path: Path,
) -> None:
    settings = load_settings(environ={}, cwd=tmp_path)

    assert processing_signature(settings, versions()) != processing_signature(
        settings,
        versions(**changed_versions),
    )


def test_non_transformative_config_does_not_change_signature(tmp_path: Path) -> None:
    settings = load_settings(environ={}, cwd=tmp_path)
    changed_ingestion = replace(
        settings.ingestion,
        paths=(tmp_path / "other-source",),
        ignore_patterns=("ignored/**",),
    )
    changed_settings = replace(
        settings,
        domain="other-domain",
        data_dir=tmp_path / "other-data",
        output_dir=tmp_path / "other-output",
        logs_dir=tmp_path / "other-logs",
        database_path=tmp_path / "other-data" / "other.db",
        log_level="DEBUG",
        ollama_url="http://localhost:11434",
        ollama_timeout_seconds=9.0,
        ingestion=changed_ingestion,
        config_source=tmp_path / "other.toml",
    )

    assert processing_signature(settings, versions()) == processing_signature(
        changed_settings,
        versions(),
    )


def test_canonical_payload_excludes_paths_ignores_and_logging(
    tmp_path: Path,
) -> None:
    settings = load_settings(environ={}, cwd=tmp_path)
    payload = json.loads(canonical_processing_config(settings.ingestion, versions()))
    serialized = canonical_processing_config(settings.ingestion, versions())

    assert "paths" not in payload["ingestion"]
    assert "ignore_patterns" not in payload["ingestion"]
    assert "log_level" not in serialized
    assert "logs_dir" not in serialized


@pytest.mark.parametrize(
    "invalid_versions",
    [
        ProcessingVersions,
    ],
)
def test_processing_versions_require_parser_versions(
    invalid_versions: type[ProcessingVersions],
) -> None:
    with pytest.raises(ValueError, match="parser_versions"):
        invalid_versions(parser_versions={})

