"""Fingerprint SHA-256 de archivos fuente."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

from barbarion.domain.models import DiscoveredFile, FileFingerprint

READ_BLOCK_SIZE_BYTES = 1024 * 1024


class FingerprintError(RuntimeError):
    """Error recuperable al calcular fingerprint de un archivo."""


class LocalFingerprintCalculator:
    """Calcula fingerprints sobre archivos locales."""

    def fingerprint(self, discovered_file: DiscoveredFile) -> FileFingerprint:
        """Calcula SHA-256 y valida metadata final."""
        return fingerprint_file(discovered_file)


def fingerprint_file(discovered_file: DiscoveredFile) -> FileFingerprint:
    """Calcula el fingerprint de un archivo leyendo bytes en streaming."""
    digest = hashlib.sha256()
    path = discovered_file.runtime_path
    try:
        with path.open("rb") as file:
            while chunk := file.read(READ_BLOCK_SIZE_BYTES):
                digest.update(chunk)
        stat_result = path.stat()
    except FileNotFoundError as error:
        raise FingerprintError(
            f"FILE_DISAPPEARED: el archivo desaparecio durante la lectura: "
            f"'{path}'."
        ) from error
    except OSError as error:
        raise FingerprintError(
            f"FILE_READ_FAILED: no se pudo leer el archivo: '{path}'."
        ) from error

    if (
        stat_result.st_size != discovered_file.size_bytes
        or stat_result.st_mtime_ns != discovered_file.mtime_ns
    ):
        raise FingerprintError(
            "FILE_CHANGED_DURING_READ: el archivo cambio mientras se calculaba "
            f"su fingerprint: '{path}'."
        )

    return FileFingerprint(
        size_bytes=stat_result.st_size,
        mtime_ns=stat_result.st_mtime_ns,
        sha256=digest.hexdigest(),
    )


def sha256_file(path: Path) -> str:
    """Devuelve solo el SHA-256 hexadecimal de un archivo."""
    stat_result = path.stat()
    discovered_file = DiscoveredFile(
        root=path.parent,
        relative_path=PurePosixPath(path.name),
        runtime_path=path,
        extension=path.suffix,
        size_bytes=stat_result.st_size,
        mtime_ns=stat_result.st_mtime_ns,
    )
    return fingerprint_file(discovered_file).sha256 or ""
