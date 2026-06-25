"""Decodificacion textual determinista para parsers locales."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from barbarion.domain.models import ErrorStage, PipelineError, SourceFile


LOW_CONFIDENCE_ENCODING = "LOW_CONFIDENCE_ENCODING"
TEXT_DECODE_FAILED = "TEXT_DECODE_FAILED"
EXTRACTION_LIMIT_EXCEEDED = "EXTRACTION_LIMIT_EXCEEDED"
DOCUMENT_CORRUPT = "DOCUMENT_CORRUPT"


@dataclass(frozen=True, slots=True)
class DecodedText:
    """Texto decodificado junto con evidencia de la politica aplicada."""

    text: str
    encoding: str
    warnings: tuple[str, ...] = ()


class TextExtractionError(Exception):
    """Error tipado de lectura textual recuperable."""

    def __init__(
        self,
        *,
        error_code: str,
        message: str,
        relative_path: PurePosixPath,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(f"{error_code}: {message}")
        self.error_code = error_code
        self.message = message
        self.relative_path = relative_path
        self.details = {} if details is None else dict(details)

    def to_pipeline_error(self) -> PipelineError:
        """Convierte el fallo a un error seguro para persistencia o logs."""

        return PipelineError(
            stage=ErrorStage.EXTRACTION,
            error_code=self.error_code,
            message=self.message,
            recoverable=True,
            relative_path=self.relative_path,
            exception_type=type(self).__name__,
            details=self.details,
        )


def decode_text_source(
    source: SourceFile,
    *,
    encodings: tuple[str, ...],
    max_extracted_chars: int,
) -> DecodedText:
    """Lee y decodifica una fuente textual sin reemplazo silencioso."""

    raw = source.discovered.runtime_path.read_bytes()
    decoded = decode_text_bytes(
        raw,
        encodings=encodings,
        relative_path=source.discovered.relative_path,
    )
    if len(decoded.text) > max_extracted_chars:
        raise TextExtractionError(
            error_code=EXTRACTION_LIMIT_EXCEEDED,
            message="El texto extraido supera el limite configurado.",
            relative_path=source.discovered.relative_path,
            details={
                "chars": len(decoded.text),
                "max_extracted_chars": max_extracted_chars,
            },
        )
    return decoded


def decode_text_bytes(
    raw: bytes,
    *,
    encodings: tuple[str, ...],
    relative_path: PurePosixPath,
) -> DecodedText:
    """Decodifica bytes usando BOM, UTF-8 estricto y fallbacks configurados."""

    try:
        bom_decoded = _decode_bom(raw)
    except UnicodeDecodeError as exc:
        raise TextExtractionError(
            error_code=TEXT_DECODE_FAILED,
            message="No se pudo decodificar el BOM textual sin reemplazos.",
            relative_path=relative_path,
            details={
                "encoding": exc.encoding,
                "reason": exc.reason,
            },
        ) from exc
    if bom_decoded is not None:
        return bom_decoded

    attempted: list[str] = []
    for encoding in _candidate_encodings(encodings):
        attempted.append(encoding)
        try:
            text = raw.decode(encoding, errors="strict")
        except UnicodeDecodeError:
            continue
        warnings = (LOW_CONFIDENCE_ENCODING,) if _is_latin_1(encoding) else ()
        return DecodedText(text=text, encoding=encoding, warnings=warnings)

    raise TextExtractionError(
        error_code=TEXT_DECODE_FAILED,
        message="No se pudo decodificar el archivo textual sin reemplazos.",
        relative_path=relative_path,
        details={"attempted_encodings": attempted},
    )


def _decode_bom(raw: bytes) -> DecodedText | None:
    if raw.startswith(b"\xef\xbb\xbf"):
        return DecodedText(
            text=raw[3:].decode("utf-8", errors="strict"),
            encoding="utf-8",
        )
    if raw.startswith(b"\xff\xfe"):
        return DecodedText(
            text=raw[2:].decode("utf-16-le", errors="strict"),
            encoding="utf-16-le",
        )
    if raw.startswith(b"\xfe\xff"):
        return DecodedText(
            text=raw[2:].decode("utf-16-be", errors="strict"),
            encoding="utf-16-be",
        )
    return None


def _candidate_encodings(encodings: tuple[str, ...]) -> tuple[str, ...]:
    candidates: list[str] = []
    for encoding in ("utf-8", *encodings):
        normalized = encoding.strip().lower()
        if normalized and normalized not in candidates:
            candidates.append(normalized)
    return tuple(candidates)


def _is_latin_1(encoding: str) -> bool:
    return encoding.replace("_", "-").lower() in {"latin-1", "iso-8859-1"}
