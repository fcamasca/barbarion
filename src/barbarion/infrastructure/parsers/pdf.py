"""Parser local de PDF con capa de texto."""

from __future__ import annotations

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from barbarion.domain.models import (
    Confidence,
    ExtractionContext,
    ExtractionResult,
    LogicalUnit,
    SourceFile,
)
from barbarion.infrastructure.parsers.base import BaseParser
from barbarion.infrastructure.parsers.encoding import (
    DOCUMENT_CORRUPT,
    EXTRACTION_LIMIT_EXCEEDED,
    TextExtractionError,
)


PDF_ENCRYPTED = "PDF_ENCRYPTED"
PDF_NO_EXTRACTABLE_TEXT = "PDF_NO_EXTRACTABLE_TEXT"


class PdfParser(BaseParser):
    """Extrae texto por pagina sin ejecutar acciones ni OCR."""

    parser_id = "pdf"
    parser_version = "1"
    supported_extensions = (".pdf",)

    def extract(
        self,
        source: SourceFile,
        context: ExtractionContext,
    ) -> ExtractionResult:
        try:
            reader = PdfReader(source.discovered.runtime_path)
        except (PdfReadError, OSError, ValueError) as exc:
            raise TextExtractionError(
                error_code=DOCUMENT_CORRUPT,
                message="No se pudo leer el PDF.",
                relative_path=source.discovered.relative_path,
                details={"exception": type(exc).__name__},
            ) from exc

        if reader.is_encrypted:
            raise TextExtractionError(
                error_code=PDF_ENCRYPTED,
                message="El PDF esta cifrado y no se extrae en H2.",
                relative_path=source.discovered.relative_path,
            )

        page_count = len(reader.pages)
        if page_count > context.max_pdf_pages:
            raise TextExtractionError(
                error_code=EXTRACTION_LIMIT_EXCEEDED,
                message="El PDF supera el limite de paginas configurado.",
                relative_path=source.discovered.relative_path,
                details={
                    "pages": page_count,
                    "max_pdf_pages": context.max_pdf_pages,
                },
            )

        page_texts: list[str] = []
        units: list[LogicalUnit] = []
        current_char = 0
        for index, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as exc:
                raise TextExtractionError(
                    error_code=DOCUMENT_CORRUPT,
                    message="No se pudo extraer texto de una pagina PDF.",
                    relative_path=source.discovered.relative_path,
                    details={"page": index, "exception": type(exc).__name__},
                ) from exc
            text = text.strip()
            if not text:
                continue
            start_char = current_char + 1
            page_texts.append(text)
            current_char += len(text)
            units.append(
                LogicalUnit(
                    unit_type="page",
                    name=f"pagina {index}",
                    confidence=Confidence.HIGH,
                    start_char=start_char,
                    end_char=current_char,
                    page_start=index,
                    page_end=index,
                    metadata={
                        "format": "pdf",
                        "page": index,
                        "breadcrumb": (f"pagina {index}",),
                    },
                )
            )
            current_char += 2

        if not page_texts:
            raise TextExtractionError(
                error_code=PDF_NO_EXTRACTABLE_TEXT,
                message="El PDF no contiene texto extraible.",
                relative_path=source.discovered.relative_path,
                details={"pages": page_count},
            )

        text = "\n\n".join(page_texts)
        if len(text) > context.max_extracted_chars:
            raise TextExtractionError(
                error_code=EXTRACTION_LIMIT_EXCEEDED,
                message="El texto extraido del PDF supera el limite configurado.",
                relative_path=source.discovered.relative_path,
                details={
                    "chars": len(text),
                    "max_extracted_chars": context.max_extracted_chars,
                },
            )

        return ExtractionResult(
            text=text,
            title=source.discovered.relative_path.name,
            encoding=None,
            units=tuple(units),
            metadata={
                "format": "pdf",
                "pages": page_count,
            },
        )
