"""Discovery local y determinista de archivos autorizados."""

from __future__ import annotations

import os
from dataclasses import dataclass
from fnmatch import fnmatchcase
from collections.abc import Iterable, Sequence
from pathlib import Path, PurePosixPath

from barbarion.domain.models import DiscoveredFile, ErrorStage, PipelineError


DiscoveryItem = DiscoveredFile | PipelineError


@dataclass(frozen=True, slots=True)
class _DiscoveryOptions:
    """Opciones normalizadas para recorrer el filesystem."""

    extensions: frozenset[str]
    ignore_patterns: tuple[str, ...]
    max_file_size_bytes: int | None


class LocalFilesystemDiscovery:
    """Adaptador basico de discovery sobre el filesystem local."""

    def discover(
        self,
        roots: Sequence[Path],
        extensions: Sequence[str] = (),
        ignore_patterns: Sequence[str] = (),
        max_file_size_mb: int = 0,
    ) -> Iterable[DiscoveryItem]:
        """Recorre roots en orden estable sin seguir symlinks."""
        return discover_files(
            roots,
            extensions=extensions,
            ignore_patterns=ignore_patterns,
            max_file_size_mb=max_file_size_mb,
        )


def discover_files(
    roots: Sequence[Path],
    *,
    extensions: Sequence[str] = (),
    ignore_patterns: Sequence[str] = (),
    max_file_size_mb: int = 0,
) -> tuple[DiscoveryItem, ...]:
    """Devuelve archivos regulares descubiertos desde roots normalizadas."""
    options = _build_options(extensions, ignore_patterns, max_file_size_mb)
    normalized_roots, root_errors = _normalize_roots(roots)
    discovered: list[DiscoveryItem] = list(root_errors)
    seen_files: set[Path] = set()

    for root in normalized_roots:
        for item in _iter_regular_files(root, options):
            if isinstance(item, PipelineError):
                discovered.append(item)
                continue
            file_path = item
            resolved_file = file_path.resolve(strict=False)
            if resolved_file in seen_files:
                continue
            seen_files.add(resolved_file)
            base_root = root.parent if root.is_file() else root
            relative_path = _relative_posix_path(file_path, base_root)
            try:
                stat_result = file_path.stat()
            except OSError as error:
                error_code = (
                    "FILE_DISAPPEARED"
                    if isinstance(error, FileNotFoundError)
                    else "FILE_STAT_FAILED"
                )
                discovered.append(
                    _pipeline_error(
                        error_code,
                        f"No se pudo leer metadata de '{relative_path.as_posix()}'.",
                        relative_path,
                        error,
                    )
                )
                continue
            discovered.append(
                _classify_file(root, file_path, stat_result, relative_path, options)
            )

    return tuple(
        sorted(
            discovered,
            key=_sort_key,
        )
    )


def _normalize_roots(
    roots: Sequence[Path],
) -> tuple[tuple[Path, ...], tuple[PipelineError, ...]]:
    """Normaliza, ordena y deduplica roots repetidas o solapadas."""
    raw_roots = sorted(
        {Path(root).expanduser().resolve(strict=False) for root in roots},
        key=lambda path: str(path).casefold(),
    )

    selected: list[Path] = []
    errors: list[PipelineError] = []
    for candidate in raw_roots:
        if candidate.is_symlink():
            continue
        if not candidate.exists():
            errors.append(
                _pipeline_error(
                    "ROOT_NOT_FOUND",
                    f"La root de ingesta no existe: '{candidate}'.",
                    PurePosixPath(candidate.name),
                )
            )
            continue
        if not candidate.is_file() and not candidate.is_dir():
            errors.append(
                _pipeline_error(
                    "ROOT_UNSUPPORTED",
                    f"La root de ingesta no es archivo ni directorio: '{candidate}'.",
                    PurePosixPath(candidate.name),
                )
            )
            continue
        if any(_is_same_or_inside(candidate, parent) for parent in selected):
            continue
        selected.append(candidate)
    return tuple(selected), tuple(errors)


def _iter_regular_files(
    root: Path,
    options: _DiscoveryOptions,
) -> Iterable[Path | PipelineError]:
    """Itera archivos regulares bajo una root sin descender en symlinks."""
    base_root = root.parent if root.is_file() else root
    if root.is_file() and not root.is_symlink():
        relative_path = _relative_posix_path(root, base_root)
        if _is_candidate_file(relative_path, root, options):
            yield root
        return
    if not root.is_dir() or root.is_symlink():
        return

    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            entries = sorted(
                os.scandir(directory),
                key=lambda entry: entry.name.casefold(),
            )
        except OSError as error:
            relative_path = _relative_posix_path(directory, base_root)
            yield _pipeline_error(
                "DIRECTORY_READ_FAILED",
                f"No se pudo leer el directorio '{relative_path.as_posix()}'.",
                relative_path,
                error,
            )
            continue
        child_directories: list[Path] = []
        for entry in entries:
            path = Path(entry.path)
            relative_path = _relative_posix_path(path, base_root)
            if entry.is_symlink():
                continue
            if _is_ignored(relative_path, options.ignore_patterns):
                continue
            if entry.is_file(follow_symlinks=False):
                if _extension_matches(path, options.extensions):
                    yield path
            elif entry.is_dir(follow_symlinks=False):
                child_directories.append(path)
        stack.extend(reversed(child_directories))


def _classify_file(
    root: Path,
    file_path: Path,
    stat_result: os.stat_result,
    relative_path: PurePosixPath,
    options: _DiscoveryOptions,
) -> DiscoveryItem:
    if (
        options.max_file_size_bytes is not None
        and stat_result.st_size > options.max_file_size_bytes
    ):
        return _pipeline_error(
            "FILE_TOO_LARGE",
            (
                f"El archivo '{relative_path.as_posix()}' excede el limite "
                "configurado."
            ),
            relative_path,
        )
    return _build_discovered_file(root, file_path, stat_result)


def _is_candidate_file(
    relative_path: PurePosixPath,
    path: Path,
    options: _DiscoveryOptions,
) -> bool:
    return (
        not _is_ignored(relative_path, options.ignore_patterns)
        and _extension_matches(path, options.extensions)
    )


def _build_options(
    extensions: Sequence[str],
    ignore_patterns: Sequence[str],
    max_file_size_mb: int,
) -> _DiscoveryOptions:
    normalized_extensions = frozenset(
        _normalize_extension(extension) for extension in extensions
    )
    max_file_size_bytes = (
        max_file_size_mb * 1024 * 1024 if max_file_size_mb > 0 else None
    )
    return _DiscoveryOptions(
        extensions=normalized_extensions,
        ignore_patterns=tuple(ignore_patterns),
        max_file_size_bytes=max_file_size_bytes,
    )


def _normalize_extension(extension: str) -> str:
    normalized = extension.strip().lower()
    if normalized and not normalized.startswith("."):
        normalized = f".{normalized}"
    return normalized


def _extension_matches(path: Path, extensions: frozenset[str]) -> bool:
    return not extensions or path.suffix.lower() in extensions


def _is_ignored(relative_path: PurePosixPath, ignore_patterns: tuple[str, ...]) -> bool:
    path = relative_path.as_posix()
    return any(fnmatchcase(path, pattern) for pattern in ignore_patterns)


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


def _sort_key(item: DiscoveryItem) -> tuple[str, str, str]:
    if isinstance(item, DiscoveredFile):
        return (
            str(item.root).casefold(),
            item.relative_path.as_posix().casefold(),
            "0-file",
        )
    relative_path = (
        item.relative_path.as_posix().casefold()
        if item.relative_path is not None
        else ""
    )
    return ("", relative_path, f"1-{item.error_code}")


def _pipeline_error(
    error_code: str,
    message: str,
    relative_path: PurePosixPath | None,
    exception: OSError | None = None,
) -> PipelineError:
    return PipelineError(
        stage=ErrorStage.DISCOVERY,
        error_code=error_code,
        message=message,
        recoverable=True,
        relative_path=relative_path,
        exception_type=type(exception).__name__ if exception is not None else None,
    )


def _is_same_or_inside(candidate: Path, parent: Path) -> bool:
    if candidate == parent:
        return True
    try:
        candidate.relative_to(parent)
    except ValueError:
        return False
    return True
