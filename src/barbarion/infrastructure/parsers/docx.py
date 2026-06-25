"""Parser local de documentos DOCX."""

from __future__ import annotations

from dataclasses import dataclass

from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

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


@dataclass(frozen=True, slots=True)
class _DocxBlock:
    unit_type: str
    text: str
    name: str
    breadcrumb: tuple[str, ...]
    ordinal: int


class DocxParser(BaseParser):
    """Extrae headings, parrafos y tablas en orden estable."""

    parser_id = "docx"
    parser_version = "1"
    supported_extensions = (".docx",)

    def extract(
        self,
        source: SourceFile,
        context: ExtractionContext,
    ) -> ExtractionResult:
        try:
            document = Document(source.discovered.runtime_path)
        except Exception as exc:
            raise TextExtractionError(
                error_code=DOCUMENT_CORRUPT,
                message="No se pudo leer el documento DOCX.",
                relative_path=source.discovered.relative_path,
                details={"exception": type(exc).__name__},
            ) from exc

        blocks = tuple(_iter_blocks(document))
        if not blocks:
            raise TextExtractionError(
                error_code=DOCUMENT_CORRUPT,
                message="El documento DOCX no contiene bloques textuales.",
                relative_path=source.discovered.relative_path,
            )

        text = "\n\n".join(block.text for block in blocks)
        if len(text) > context.max_extracted_chars:
            raise TextExtractionError(
                error_code=EXTRACTION_LIMIT_EXCEEDED,
                message="El texto extraido del DOCX supera el limite configurado.",
                relative_path=source.discovered.relative_path,
                details={
                    "chars": len(text),
                    "max_extracted_chars": context.max_extracted_chars,
                },
            )

        units: list[LogicalUnit] = []
        current_char = 0
        for block in blocks:
            start_char = current_char + 1
            current_char += len(block.text)
            units.append(
                LogicalUnit(
                    unit_type=block.unit_type,
                    name=block.name,
                    confidence=Confidence.HIGH,
                    start_char=start_char,
                    end_char=current_char,
                    metadata={
                        "format": "docx",
                        "ordinal": block.ordinal,
                        "breadcrumb": block.breadcrumb,
                    },
                )
            )
            current_char += 2

        return ExtractionResult(
            text=text,
            title=source.discovered.relative_path.name,
            encoding=None,
            units=tuple(units),
            metadata={
                "format": "docx",
                "blocks": len(blocks),
            },
        )


def _iter_blocks(document: DocxDocument) -> tuple[_DocxBlock, ...]:
    blocks: list[_DocxBlock] = []
    breadcrumb: list[str] = []
    ordinal = 0
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            paragraph = Paragraph(child, document)
            text = paragraph.text.strip()
            if not text:
                continue
            style_name = paragraph.style.name if paragraph.style is not None else ""
            if style_name.lower().startswith("heading"):
                level = _heading_level(style_name)
                while len(breadcrumb) >= level:
                    breadcrumb.pop()
                breadcrumb.append(text)
                unit_type = "heading"
                name = text
            else:
                unit_type = "paragraph"
                name = f"parrafo {ordinal}"
            blocks.append(
                _DocxBlock(
                    unit_type=unit_type,
                    text=text,
                    name=name,
                    breadcrumb=tuple(breadcrumb),
                    ordinal=ordinal,
                )
            )
            ordinal += 1
            continue
        if isinstance(child, CT_Tbl):
            table = Table(child, document)
            table_text = _table_text(table)
            if not table_text:
                continue
            blocks.append(
                _DocxBlock(
                    unit_type="table",
                    text=table_text,
                    name=f"tabla {ordinal}",
                    breadcrumb=tuple(breadcrumb),
                    ordinal=ordinal,
                )
            )
            ordinal += 1
    return tuple(blocks)


def _heading_level(style_name: str) -> int:
    parts = style_name.split()
    if parts and parts[-1].isdigit():
        return max(1, int(parts[-1]))
    return 1


def _table_text(table: Table) -> str:
    rows: list[str] = []
    for row in table.rows:
        cells = [" ".join(cell.text.split()) for cell in row.cells]
        rows.append(" | ".join(cells))
    return "\n".join(rows)
