"""Pruebas de decision incremental pura."""

from pathlib import Path, PurePosixPath

import pytest

from barbarion.domain.ingestion import (
    IncrementalAction,
    PersistedFileState,
    decide_incremental,
)
from barbarion.domain.models import (
    DiscoveredFile,
    FileFingerprint,
    FileStatus,
    IngestionMode,
)


CURRENT_SIGNATURE = "sig-v1"
OLD_SHA = "a" * 64
NEW_SHA = "b" * 64


def discovered(
    tmp_path: Path,
    *,
    size_bytes: int = 10,
    mtime_ns: int = 100,
) -> DiscoveredFile:
    """Construye un archivo visto por discovery."""
    return DiscoveredFile(
        root=tmp_path,
        relative_path=PurePosixPath("pkg/body.sql"),
        runtime_path=tmp_path / "pkg" / "body.sql",
        extension=".sql",
        size_bytes=size_bytes,
        mtime_ns=mtime_ns,
    )


def persisted(
    *,
    size_bytes: int = 10,
    mtime_ns: int = 100,
    sha256: str | None = OLD_SHA,
    status: FileStatus = FileStatus.PROCESSED,
    processing_signature: str | None = CURRENT_SIGNATURE,
) -> PersistedFileState:
    """Construye estado persistido minimo."""
    return PersistedFileState(
        size_bytes=size_bytes,
        mtime_ns=mtime_ns,
        sha256=sha256,
        status=status,
        processing_signature=processing_signature,
    )


def fingerprint(
    *,
    size_bytes: int = 12,
    mtime_ns: int = 200,
    sha256: str = OLD_SHA,
) -> FileFingerprint:
    """Construye fingerprint calculado."""
    return FileFingerprint(size_bytes=size_bytes, mtime_ns=mtime_ns, sha256=sha256)


def test_new_file_is_processed(tmp_path: Path) -> None:
    decision = decide_incremental(discovered(tmp_path), CURRENT_SIGNATURE)

    assert decision.action == IncrementalAction.PROCESS
    assert decision.reason == "new"
    assert decision.requires_hash is True
    assert decision.requires_parser is True


def test_unchanged_fast_path_avoids_hash_and_parser(tmp_path: Path) -> None:
    decision = decide_incremental(
        discovered(tmp_path),
        CURRENT_SIGNATURE,
        persisted=persisted(),
    )

    assert decision.action == IncrementalAction.UNCHANGED
    assert decision.reason == "metadata_unchanged"
    assert decision.requires_hash is False
    assert decision.requires_parser is False


def test_metadata_change_requires_hash_before_parser(tmp_path: Path) -> None:
    decision = decide_incremental(
        discovered(tmp_path, size_bytes=12, mtime_ns=200),
        CURRENT_SIGNATURE,
        persisted=persisted(),
    )

    assert decision.action == IncrementalAction.HASH_REQUIRED
    assert decision.reason == "metadata_changed"
    assert decision.requires_hash is True
    assert decision.requires_parser is False


def test_same_sha_touches_metadata_without_parser(tmp_path: Path) -> None:
    decision = decide_incremental(
        discovered(tmp_path, size_bytes=12, mtime_ns=200),
        CURRENT_SIGNATURE,
        persisted=persisted(),
        fingerprint=fingerprint(sha256=OLD_SHA),
    )

    assert decision.action == IncrementalAction.TOUCH
    assert decision.reason == "content_unchanged"
    assert decision.requires_hash is True
    assert decision.requires_parser is False


def test_different_sha_processes_content(tmp_path: Path) -> None:
    decision = decide_incremental(
        discovered(tmp_path, size_bytes=12, mtime_ns=200),
        CURRENT_SIGNATURE,
        persisted=persisted(),
        fingerprint=fingerprint(sha256=NEW_SHA),
    )

    assert decision.action == IncrementalAction.PROCESS
    assert decision.reason == "content_changed"
    assert decision.requires_parser is True


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (persisted(status=FileStatus.ERROR), "previous_error"),
        (
            persisted(processing_signature="sig-v0"),
            "processing_signature_changed",
        ),
        (persisted(status=FileStatus.SKIPPED), "status_skipped"),
    ],
)
def test_states_that_require_retry_are_processed(
    state: PersistedFileState,
    reason: str,
    tmp_path: Path,
) -> None:
    decision = decide_incremental(
        discovered(tmp_path),
        CURRENT_SIGNATURE,
        persisted=state,
    )

    assert decision.action == IncrementalAction.PROCESS
    assert decision.reason == reason
    assert decision.requires_hash is True
    assert decision.requires_parser is True


def test_full_mode_ignores_fast_path(tmp_path: Path) -> None:
    decision = decide_incremental(
        discovered(tmp_path),
        CURRENT_SIGNATURE,
        mode=IngestionMode.FULL,
        persisted=persisted(),
    )

    assert decision.action == IncrementalAction.PROCESS
    assert decision.reason == "full"
    assert decision.requires_hash is True
    assert decision.requires_parser is True

