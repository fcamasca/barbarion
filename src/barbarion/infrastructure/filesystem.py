"""Discovery local y determinista de archivos autorizados."""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from pathlib import Path, PurePosixPath

from barbarion.domain.models import DiscoveredFile


class LocalFilesystemDiscovery:
    """Adaptador basico de discovery sobre el filesystem local."""

    def discover(
        self,
        roots: Sequence[Path],
        extensions: Sequence[str] = (),
        ignore_patterns: Sequence[str] = (),
        max_file_size_mb: int = 0,
    ) -> Iterable[DiscoveredFile]:
        """Recorre roots en orden estable sin seguir symlinks."""
        del extensions, ignore_patterns, max_file_size_mb
        return discover_files(roots)


def discover_files(roots: Sequence[Path]) -> tuple[DiscoveredFile, ...]:
    """Devuelve archivos regulares descubiertos desde roots normalizadas."""
    normalized_roots = _normalize_roots(roots)
    discovered: list[DiscoveredFile] = []
    seen_files: set[Path] = set()

    for root in normalized_roots:
        for file_path in _iter_regular_files(root):
            resolved_file = file_path.resolve(strict=False)
            if resolved_file in seen_files:
                continue
            seen_files.add(resolved_file)
            stat_result = file_path.stat()
            discovered.append(_build_discovered_file(root, file_path, stat_result))

    return tuple(
        sorted(
            discovered,
            key=lambda item: (
                str(item.root).casefold(),
                item.relative_path.as_posix().casefold(),
            ),
        )
    )


def _normalize_roots(roots: Sequence[Path]) -> tuple[Path, ...]:
    """Normaliza, ordena y deduplica roots repetidas o solapadas."""
    candidates = tuple(
        sorted(
            {
                Path(root).expanduser().resolve(strict=False)
                for root in roots
            },
            key=lambda path: str(path).casefold(),
        )
    )

    selected: list[Path] = []
    for candidate in candidates:
        if candidate.is_symlink() or not candidate.exists():
            continue
        if any(_is_same_or_inside(candidate, parent) for parent in selected):
            continue
        selected.append(candidate)
    return tuple(selected)


def _iter_regular_files(root: Path) -> Iterable[Path]:
    """Itera archivos regulares bajo una root sin descender en symlinks."""
    if root.is_file() and not root.is_symlink():
        yield root
        return
    if not root.is_dir() or root.is_symlink():
        return

    stack = [root]
    while stack:
        directory = stack.pop()
        entries = sorted(
            os.scandir(directory),
            key=lambda entry: entry.name.casefold(),
        )
        child_directories: list[Path] = []
        for entry in entries:
            path = Path(entry.path)
            if entry.is_symlink():
                continue
            if entry.is_file(follow_symlinks=False):
                yield path
            elif entry.is_dir(follow_symlinks=False):
                child_directories.append(path)
        stack.extend(reversed(child_directories))


def _build_discovered_file(
    root: Path,
    file_path: Path,
    stat_result: os.stat_result,
) -> DiscoveredFile:
    """Construye el value object con rutas relativas POSIX."""
    base_root = root.parent if root.is_file() else root
    relative_path = _relative_posix_path(file_path, base_root)
    return DiscoveredFile(
        root=base_root.resolve(strict=False),
        relative_path=relative_path,
        runtime_path=file_path.resolve(strict=False),
        extension=file_path.suffix,
        size_bytes=stat_result.st_size,
        mtime_ns=stat_result.st_mtime_ns,
    )


def _relative_posix_path(file_path: Path, root: Path) -> PurePosixPath:
    relative = file_path.resolve(strict=False).relative_to(root.resolve(strict=False))
    return PurePosixPath(relative.as_posix())


def _is_same_or_inside(candidate: Path, parent: Path) -> bool:
    if candidate == parent:
        return True
    try:
        candidate.relative_to(parent)
    except ValueError:
        return False
    return True

