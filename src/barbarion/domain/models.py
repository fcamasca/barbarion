"""Value objects y estados puros para el pipeline de ingesta."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any


SHA256_HEX_LENGTH = 64


class Confidence(StrEnum):
    """Nivel de confianza de una unidad logica."""

    # Extensible para reverse engineering: futuros niveles podran separar deteccion exacta,
    # heuristica o inferida sin cambiar el contrato base de ingesta.
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IngestionRunStatus(StrEnum):
    """Estado persistible de una ejecucion de ingesta."""

    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class IngestionMode(StrEnum):
    """Modo operativo de una ejecucion."""

    INCREMENTAL = "incremental"
    FULL = "full"


class FileStatus(StrEnum):
    """Estado vigente de un archivo dentro del inventario."""

    PENDING = "pending"
    PROCESSED = "processed"
    SKIPPED = "skipped"
    ERROR = "error"
    DELETED = "deleted"


class ErrorStage(StrEnum):
    """Etapa donde se produjo un error tipado."""

    DISCOVERY = "discovery"
    FINGERPRINT = "fingerprint"
    EXTRACTION = "extraction"
    NORMALIZATION = "normalization"
    CHUNKING = "chunking"
    PERSISTENCE = "persistence"
    RECONCILIATION = "reconciliation"


@dataclass(frozen=True, slots=True)
class DiscoveredFile:
    """Archivo candidato descubierto por el filesystem autorizado."""

    root: Path
    relative_path: PurePosixPath
    runtime_path: Path
    extension: str
    size_bytes: int
    mtime_ns: int

    def __post_init__(self) -> None:
        _require_non_negative(self.size_bytes, "size_bytes")
        _require_non_negative(self.mtime_ns, "mtime_ns")
        _require_relative_posix_path(self.relative_path, "relative_path")
        object.__setattr__(
            self,
            "extension",
            _normalize_extension(self.extension, "extension"),
        )


@dataclass(frozen=True, slots=True)
class FileFingerprint:
    """Firma de lectura de un archivo fuente."""

    size_bytes: int
    mtime_ns: int
    sha256: str | None
    version: int = 1

    def __post_init__(self) -> None:
        _require_non_negative(self.size_bytes, "size_bytes")
        _require_non_negative(self.mtime_ns, "mtime_ns")
        _require_positive(self.version, "version")
        if self.sha256 is not None:
            _require_sha256(self.sha256, "sha256")


@dataclass(frozen=True, slots=True)
class SourceFile:
    """Entrada minima que un parser necesita conocer."""

    discovered: DiscoveredFile
    fingerprint: FileFingerprint | None = None


@dataclass(frozen=True, slots=True)
class ExtractionContext:
    """Limites y politica de lectura para parsers."""

    encodings: tuple[str, ...]
    max_extracted_chars: int
    max_pdf_pages: int

    def __post_init__(self) -> None:
        if not self.encodings:
            raise ValueError("encodings debe contener al menos un valor.")
        _require_positive(self.max_extracted_chars, "max_extracted_chars")
        _require_positive(self.max_pdf_pages, "max_pdf_pages")


@dataclass(frozen=True, slots=True)
class LogicalUnit:
    """Unidad logica extraida para normalizacion y chunking."""

    unit_type: str
    name: str | None
    confidence: Confidence
    start_line: int | None = None
    end_line: int | None = None
    start_char: int | None = None
    end_char: int | None = None
    page_start: int | None = None
    page_end: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.unit_type, "unit_type")
        _validate_optional_range(self.start_line, self.end_line, "line")
        _validate_optional_range(self.start_char, self.end_char, "char")
        _validate_optional_range(self.page_start, self.page_end, "page")
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Resultado puro de un parser."""

    text: str
    title: str | None
    encoding: str | None
    units: tuple[LogicalUnit, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise ValueError("text debe ser una cadena.")
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))
        object.__setattr__(self, "warnings", tuple(self.warnings))


@dataclass(frozen=True, slots=True)
class NormalizedDocument:
    """Documento normalizado y trazable antes del chunking."""

    text: str
    units: tuple[LogicalUnit, ...]
    source_sha256: str
    content_sha256: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_sha256(self.source_sha256, "source_sha256")
        _require_sha256(self.content_sha256, "content_sha256")
        object.__setattr__(self, "units", tuple(self.units))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class ChunkCandidate:
    """Fragmento candidato para persistencia e indexacion posterior."""

    ordinal: int
    chunk_type: str
    content: str
    content_sha256: str
    chunk_id: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    start_char: int | None = None
    end_char: int | None = None
    page_start: int | None = None
    page_end: int | None = None
    object_type: str | None = None
    object_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_negative(self.ordinal, "ordinal")
        if self.chunk_id is not None:
            _require_sha256(self.chunk_id, "chunk_id")
        _require_non_empty(self.chunk_type, "chunk_type")
        _require_non_empty(self.content, "content")
        _require_sha256(self.content_sha256, "content_sha256")
        _validate_optional_range(self.start_line, self.end_line, "line")
        _validate_optional_range(self.start_char, self.end_char, "char")
        _validate_optional_range(self.page_start, self.page_end, "page")
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class IngestionMetrics:
    """Contadores acumulados por una ejecucion."""

    discovered_files: int = 0
    processed_files: int = 0
    unchanged_files: int = 0
    skipped_files: int = 0
    deleted_files: int = 0
    error_count: int = 0
    source_bytes: int = 0
    processed_bytes: int = 0
    chunk_count: int = 0
    duration_ms: int | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "discovered_files",
            "processed_files",
            "unchanged_files",
            "skipped_files",
            "deleted_files",
            "error_count",
            "source_bytes",
            "processed_bytes",
            "chunk_count",
        ):
            _require_non_negative(getattr(self, field_name), field_name)
        if self.duration_ms is not None:
            _require_non_negative(self.duration_ms, "duration_ms")


@dataclass(frozen=True, slots=True)
class PipelineError:
    """Error tipado y seguro para logs o persistencia."""

    stage: ErrorStage
    error_code: str
    message: str
    recoverable: bool
    relative_path: PurePosixPath | None = None
    exception_type: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.error_code, "error_code")
        _require_non_empty(self.message, "message")
        if self.relative_path is not None:
            _require_relative_posix_path(self.relative_path, "relative_path")
        object.__setattr__(self, "details", _freeze_mapping(self.details))


@dataclass(frozen=True, slots=True)
class IngestionOutcome:
    """Resultado agregado de una ejecucion o etapa."""

    status: IngestionRunStatus
    metrics: IngestionMetrics
    error: PipelineError | None = None

    def __post_init__(self) -> None:
        if self.status in {
            IngestionRunStatus.FAILED,
            IngestionRunStatus.INTERRUPTED,
        } and self.error is None:
            raise ValueError("Los estados fallidos requieren un error tipado.")


def _normalize_extension(value: str, key: str) -> str:
    _require_non_empty(value, key)
    extension = value.lower()
    if not extension.startswith("."):
        extension = f".{extension}"
    if extension == "." or "/" in extension or "\\" in extension:
        raise ValueError(f"{key} contiene una extension no valida.")
    return extension


def _require_non_empty(value: str, key: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} debe ser una cadena no vacia.")


def _require_non_negative(value: int, key: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} debe ser un entero mayor o igual que 0.")


def _require_positive(value: int, key: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{key} debe ser un entero mayor que 0.")


def _require_sha256(value: str, key: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != SHA256_HEX_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{key} debe ser un SHA-256 hexadecimal en minusculas.")


def _require_relative_posix_path(value: PurePosixPath, key: str) -> None:
    if value.is_absolute() or ".." in value.parts:
        raise ValueError(f"{key} debe ser una ruta relativa segura.")


def _validate_optional_range(
    start: int | None,
    end: int | None,
    label: str,
) -> None:
    if start is None and end is None:
        return
    if start is None or end is None:
        raise ValueError(f"El rango {label} debe tener inicio y fin.")
    _require_positive(start, f"start_{label}")
    _require_positive(end, f"end_{label}")
    if end < start:
        raise ValueError(f"El rango {label} debe terminar despues del inicio.")


def _freeze_mapping(values: dict[str, Any]) -> MappingProxyType[str, Any]:
    return MappingProxyType(dict(values))
