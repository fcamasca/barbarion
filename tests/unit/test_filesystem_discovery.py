"""Pruebas del discovery local de archivos."""

from pathlib import Path, PurePosixPath

import pytest

from barbarion.infrastructure.filesystem import (
    LocalFilesystemDiscovery,
    discover_files,
)


def write_file(path: Path, content: str = "contenido") -> Path:
    """Crea un archivo de fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_discovery_returns_files_in_stable_order(tmp_path: Path) -> None:
    root = tmp_path / "root"
    write_file(root / "b" / "two.sql")
    write_file(root / "a" / "one.sql")
    write_file(root / "a" / "three.SQL")

    discovered = discover_files([root])

    assert [item.relative_path for item in discovered] == [
        PurePosixPath("a/one.sql"),
        PurePosixPath("a/three.SQL"),
        PurePosixPath("b/two.sql"),
    ]
    assert [item.extension for item in discovered] == [".sql", ".sql", ".sql"]
    assert all(item.root == root for item in discovered)
    assert all(item.size_bytes > 0 for item in discovered)
    assert all(item.mtime_ns > 0 for item in discovered)


def test_discovery_accepts_directory_and_single_file_roots(tmp_path: Path) -> None:
    directory_root = tmp_path / "directory"
    single_file = tmp_path / "single" / "solo.sql"
    write_file(directory_root / "inside.sql")
    write_file(single_file)

    discovered = discover_files([single_file, directory_root])

    assert [(item.root, item.relative_path) for item in discovered] == [
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

    assert [item.relative_path for item in discovered] == [
        PurePosixPath("nested/inner.sql"),
        PurePosixPath("top.sql"),
    ]
    assert all(item.root == root for item in discovered)


def test_discovery_ignores_missing_roots(tmp_path: Path) -> None:
    root = tmp_path / "root"
    write_file(root / "ok.sql")

    discovered = discover_files([tmp_path / "missing", root])

    assert [item.relative_path for item in discovered] == [PurePosixPath("ok.sql")]


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

    assert [item.relative_path for item in discovered] == [PurePosixPath("ok.sql")]


def test_discovery_does_not_follow_file_symlinks(tmp_path: Path) -> None:
    target = write_file(tmp_path / "root" / "target.sql")
    symlink = tmp_path / "root" / "linked.sql"
    try:
        symlink.symlink_to(target)
    except OSError as error:
        pytest.skip(f"El entorno no permite crear symlinks: {error}")

    discovered = discover_files([tmp_path / "root"])

    assert [item.relative_path for item in discovered] == [
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

