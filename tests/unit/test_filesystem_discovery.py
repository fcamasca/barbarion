"""Pruebas del discovery local de archivos."""

from pathlib import Path, PurePosixPath

import pytest

from barbarion.domain.models import DiscoveredFile, PipelineError
from barbarion.infrastructure.filesystem import (
    LocalFilesystemDiscovery,
    discover_files,
)


def write_file(path: Path, content: str = "contenido") -> Path:
    """Crea un archivo de fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def files_only(items: tuple[DiscoveredFile | PipelineError, ...]) -> list[DiscoveredFile]:
    """Filtra archivos descubiertos."""
    return [item for item in items if isinstance(item, DiscoveredFile)]


def errors_only(items: tuple[DiscoveredFile | PipelineError, ...]) -> list[PipelineError]:
    """Filtra errores de discovery."""
    return [item for item in items if isinstance(item, PipelineError)]


def test_discovery_returns_files_in_stable_order(tmp_path: Path) -> None:
    root = tmp_path / "root"
    write_file(root / "b" / "two.sql")
    write_file(root / "a" / "one.sql")
    write_file(root / "a" / "three.SQL")

    discovered = discover_files([root])

    files = files_only(discovered)

    assert [item.relative_path for item in files] == [
        PurePosixPath("a/one.sql"),
        PurePosixPath("a/three.SQL"),
        PurePosixPath("b/two.sql"),
    ]
    assert [item.extension for item in files] == [".sql", ".sql", ".sql"]
    assert all(item.root == root for item in files)
    assert all(item.size_bytes > 0 for item in files)
    assert all(item.mtime_ns > 0 for item in files)
    assert errors_only(discovered) == []


def test_discovery_accepts_directory_and_single_file_roots(tmp_path: Path) -> None:
    directory_root = tmp_path / "directory"
    single_file = tmp_path / "single" / "solo.sql"
    write_file(directory_root / "inside.sql")
    write_file(single_file)

    discovered = discover_files([single_file, directory_root])

    files = files_only(discovered)

    assert [(item.root, item.relative_path) for item in files] == [
        (directory_root, PurePosixPath("inside.sql")),
        (single_file.parent, PurePosixPath("solo.sql")),
    ]


def test_discovery_deduplicates_repeated_and_overlapping_roots(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    nested = root / "nested"
    write_file(root / "top.sql")
    write_file(nested / "inner.sql")

    discovered = discover_files([nested, root, root, root / "top.sql"])

    files = files_only(discovered)

    assert [item.relative_path for item in files] == [
        PurePosixPath("nested/inner.sql"),
        PurePosixPath("top.sql"),
    ]
    assert all(item.root == root for item in files)


def test_discovery_ignores_missing_roots(tmp_path: Path) -> None:
    root = tmp_path / "root"
    write_file(root / "ok.sql")

    discovered = discover_files([tmp_path / "missing", root])

    assert [item.relative_path for item in files_only(discovered)] == [
        PurePosixPath("ok.sql")
    ]
    errors = errors_only(discovered)
    assert [error.error_code for error in errors] == ["ROOT_NOT_FOUND"]


def test_local_filesystem_discovery_matches_port_shape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    write_file(root / "ok.sql")

    discovered = tuple(
        LocalFilesystemDiscovery().discover(
            [root],
            extensions=(".sql",),
            ignore_patterns=("ignored/**",),
            max_file_size_mb=1,
        )
    )

    assert [item.relative_path for item in files_only(discovered)] == [
        PurePosixPath("ok.sql")
    ]


def test_discovery_does_not_follow_file_symlinks(tmp_path: Path) -> None:
    target = write_file(tmp_path / "root" / "target.sql")
    symlink = tmp_path / "root" / "linked.sql"
    try:
        symlink.symlink_to(target)
    except OSError as error:
        pytest.skip(f"El entorno no permite crear symlinks: {error}")

    discovered = discover_files([tmp_path / "root"])

    assert [item.relative_path for item in files_only(discovered)] == [
        PurePosixPath("target.sql")
    ]


def test_discovery_does_not_descend_into_directory_symlinks(tmp_path: Path) -> None:
    target_dir = tmp_path / "target"
    write_file(target_dir / "target.sql")
    root = tmp_path / "root"
    root.mkdir()
    symlink = root / "linked-dir"
    try:
        symlink.symlink_to(target_dir, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"El entorno no permite crear symlinks: {error}")

    discovered = discover_files([root])

    assert discovered == ()


def test_discovery_filters_extensions_case_insensitively(tmp_path: Path) -> None:
    root = tmp_path / "root"
    write_file(root / "one.SQL")
    write_file(root / "two.txt")
    write_file(root / "three.md")

    discovered = discover_files([root], extensions=("sql", ".MD"))

    assert [item.relative_path for item in files_only(discovered)] == [
        PurePosixPath("one.SQL"),
        PurePosixPath("three.md"),
    ]


def test_discovery_applies_ignore_patterns_with_posix_paths(tmp_path: Path) -> None:
    root = tmp_path / "root"
    write_file(root / "keep.sql")
    write_file(root / "ignored.sql")
    write_file(root / "build" / "generated.sql")
    write_file(root / "nested" / "tmp" / "ignored.sql")

    discovered = discover_files(
        [root],
        ignore_patterns=("ignored.sql", "build/**", "nested/tmp/**"),
    )

    assert [item.relative_path for item in files_only(discovered)] == [
        PurePosixPath("keep.sql")
    ]
    assert errors_only(discovered) == []


def test_discovery_classifies_too_large_compatible_files(tmp_path: Path) -> None:
    root = tmp_path / "root"
    write_file(root / "small.sql", "ok")
    write_file(root / "large.sql", "x" * (1024 * 1024 + 1))

    discovered_with_limit = discover_files(
        [root],
        extensions=(".sql",),
        max_file_size_mb=1,
    )

    assert [item.relative_path for item in files_only(discovered_with_limit)] == [
        PurePosixPath("small.sql"),
    ]
    errors = errors_only(discovered_with_limit)
    assert [error.error_code for error in errors] == ["FILE_TOO_LARGE"]
    assert errors[0].relative_path == PurePosixPath("large.sql")


def test_discovery_reports_stat_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    write_file(root / "vanished.sql")
    original_stat = Path.stat

    def broken_stat(path: Path, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if path.name == "vanished.sql":
            raise FileNotFoundError("desaparecio")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", broken_stat)

    discovered = discover_files([root])

    errors = errors_only(discovered)
    assert [error.error_code for error in errors] == ["FILE_DISAPPEARED"]
    assert errors[0].relative_path == PurePosixPath("vanished.sql")
