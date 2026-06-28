"""Pruebas de inicialización y validación de directorios."""

import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

from barbarion.bootstrap import (
    SOURCE_SUBDIRECTORIES,
    DirectoryResult,
    initialize_directories,
)
from barbarion.config import Settings, load_settings


def default_settings(tmp_path: Path) -> Settings:
    """Construye una configuración predeterminada dentro de `tmp_path`."""
    return load_settings(environ={}, cwd=tmp_path)


def results_by_path(
    results: tuple[DirectoryResult, ...],
) -> dict[Path, DirectoryResult]:
    """Indexa resultados para simplificar aserciones."""
    return {result.path: result for result in results}


def test_initialize_directories_creates_unique_configured_paths(
    tmp_path: Path,
) -> None:
    settings = default_settings(tmp_path)

    results = initialize_directories(settings)

    assert len(results) == 8
    assert all(result.success for result in results)
    assert settings.data_dir.is_dir()
    assert settings.output_dir.is_dir()
    assert settings.logs_dir.is_dir()
    source_root = settings.ingestion.paths[0]
    assert source_root.is_dir()
    for name in SOURCE_SUBDIRECTORIES:
        assert (source_root / name).is_dir()
    indexed = results_by_path(results)
    assert indexed[settings.data_dir].roles == ("data", "database")
    assert indexed[settings.output_dir].roles == ("output",)
    assert indexed[settings.logs_dir].roles == ("logs",)
    assert indexed[source_root].roles == ("sources",)
    assert list(settings.data_dir.iterdir()) == []
    assert list(settings.output_dir.iterdir()) == []
    assert list(settings.logs_dir.iterdir()) == []


def test_initialization_is_idempotent_and_preserves_content(tmp_path: Path) -> None:
    settings = default_settings(tmp_path)
    first_results = initialize_directories(settings)
    sentinel = settings.data_dir / "sentinel.txt"
    sentinel.write_text("preservar", encoding="utf-8")
    source_file = settings.ingestion.paths[0] / "docs" / "note.md"
    source_file.write_text("contenido", encoding="utf-8")

    second_results = initialize_directories(settings)

    assert all(result.success for result in first_results)
    assert all(result.success for result in second_results)
    assert sentinel.read_text(encoding="utf-8") == "preservar"
    assert source_file.read_text(encoding="utf-8") == "contenido"


def test_file_in_place_of_directory_returns_failure(tmp_path: Path) -> None:
    settings = default_settings(tmp_path)
    settings.data_dir.write_text("bloqueo", encoding="utf-8")

    results = initialize_directories(settings)

    blocked = results_by_path(results)[settings.data_dir]
    assert blocked.success is False
    assert blocked.roles == ("data", "database")
    assert str(settings.data_dir) in blocked.detail
    assert "no es un directorio" in blocked.detail
    assert results_by_path(results)[settings.output_dir].success is True
    assert results_by_path(results)[settings.ingestion.paths[0]].success is True


def test_duplicate_paths_are_checked_once(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    settings = replace(
        default_settings(tmp_path),
        data_dir=shared,
        output_dir=shared,
        logs_dir=shared,
        database_path=shared / "barbarion.db",
    )

    results = initialize_directories(settings)

    indexed = results_by_path(results)
    assert indexed[shared] == DirectoryResult(
        roles=("data", "output", "logs", "database"),
        path=shared,
        success=True,
        detail=f"Directorio disponible: '{shared}'.",
    )
    for name in SOURCE_SUBDIRECTORIES:
        assert (tmp_path / "sources" / name).is_dir()


def test_permission_error_is_returned_without_raising(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = default_settings(tmp_path)

    def deny_mkdir(*args: object, **kwargs: object) -> None:
        """Simula un sistema de archivos que rechaza la creación."""
        del args, kwargs
        raise PermissionError("permiso denegado")

    monkeypatch.setattr(Path, "mkdir", deny_mkdir)

    results = initialize_directories(settings)

    assert all(result.success is False for result in results)
    assert all("permiso denegado" in result.detail for result in results)


def test_write_probe_error_is_returned_and_leaves_no_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = default_settings(tmp_path)

    def deny_temporary_file(*args: object, **kwargs: object) -> object:
        """Simula un directorio existente pero no escribible."""
        del args, kwargs
        raise PermissionError("escritura denegada")

    monkeypatch.setattr(tempfile, "TemporaryFile", deny_temporary_file)

    results = initialize_directories(settings)

    assert all(result.success is False for result in results)
    assert all("escritura denegada" in result.detail for result in results)
    assert not any(path.is_file() for path in settings.ingestion.paths[0].rglob("*"))


def test_initialize_directories_completes_custom_source_subdirectories(
    tmp_path: Path,
) -> None:
    custom_sources = tmp_path / "custom-inputs"
    custom_sources.mkdir()
    existing = custom_sources / "keep.txt"
    existing.write_text("no tocar", encoding="utf-8")
    settings = replace(
        default_settings(tmp_path),
        ingestion=replace(
            default_settings(tmp_path).ingestion,
            paths=(custom_sources,),
        ),
    )

    results = initialize_directories(settings)

    assert all(result.success for result in results)
    assert existing.read_text(encoding="utf-8") == "no tocar"
    for name in SOURCE_SUBDIRECTORIES:
        assert (custom_sources / name).is_dir()
