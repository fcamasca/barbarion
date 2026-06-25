"""Pruebas de fingerprint SHA-256 en streaming."""

import hashlib
from pathlib import Path, PurePosixPath
from typing import BinaryIO

import pytest

from barbarion.domain.models import DiscoveredFile
from barbarion.infrastructure.fingerprint import (
    READ_BLOCK_SIZE_BYTES,
    FingerprintError,
    LocalFingerprintCalculator,
    fingerprint_file,
    sha256_file,
)


def write_bytes(path: Path, content: bytes) -> Path:
    """Crea un archivo binario de prueba."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def discovered_for(path: Path, root: Path | None = None) -> DiscoveredFile:
    """Construye metadata descubierta para un archivo real."""
    effective_root = path.parent if root is None else root
    stat_result = path.stat()
    return DiscoveredFile(
        root=effective_root,
        relative_path=PurePosixPath(path.relative_to(effective_root).as_posix()),
        runtime_path=path,
        extension=path.suffix,
        size_bytes=stat_result.st_size,
        mtime_ns=stat_result.st_mtime_ns,
    )


def test_sha256_known_vector(tmp_path: Path) -> None:
    path = write_bytes(tmp_path / "vector.txt", b"abc")

    fingerprint = fingerprint_file(discovered_for(path))

    assert fingerprint.sha256 == (
        "ba7816bf8f01cfea414140de5dae2223"
        "b00361a396177a9cb410ff61f20015ad"
    )
    assert fingerprint.size_bytes == 3
    assert fingerprint.version == 1


def test_sha256_empty_file(tmp_path: Path) -> None:
    path = write_bytes(tmp_path / "empty.bin", b"")

    assert sha256_file(path) == hashlib.sha256(b"").hexdigest()


def test_large_file_is_read_in_one_mebibyte_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"a" * (READ_BLOCK_SIZE_BYTES + 123)
    path = write_bytes(tmp_path / "large.bin", payload)
    original_open = Path.open
    read_sizes: list[int] = []

    class RecordingReader:
        def __init__(self, wrapped: BinaryIO) -> None:
            self.wrapped = wrapped

        def __enter__(self) -> "RecordingReader":
            self.wrapped.__enter__()
            return self

        def __exit__(self, *args: object) -> None:
            self.wrapped.__exit__(*args)

        def read(self, size: int = -1) -> bytes:
            read_sizes.append(size)
            return self.wrapped.read(size)

    def recording_open(self: Path, *args: object, **kwargs: object) -> RecordingReader:
        return RecordingReader(original_open(self, *args, **kwargs))

    monkeypatch.setattr(Path, "open", recording_open)

    fingerprint = LocalFingerprintCalculator().fingerprint(discovered_for(path))

    assert fingerprint.sha256 == hashlib.sha256(payload).hexdigest()
    assert read_sizes == [
        READ_BLOCK_SIZE_BYTES,
        READ_BLOCK_SIZE_BYTES,
        READ_BLOCK_SIZE_BYTES,
    ]


def test_missing_file_is_reported(tmp_path: Path) -> None:
    path = write_bytes(tmp_path / "gone.sql", b"select 1;")
    discovered = discovered_for(path)
    path.unlink()

    with pytest.raises(FingerprintError, match="FILE_DISAPPEARED"):
        fingerprint_file(discovered)


def test_changed_file_is_reported(tmp_path: Path) -> None:
    path = write_bytes(tmp_path / "changed.sql", b"select 1;")
    discovered = discovered_for(path)
    path.write_bytes(b"select 2; -- changed")

    with pytest.raises(FingerprintError, match="FILE_CHANGED_DURING_READ"):
        fingerprint_file(discovered)

