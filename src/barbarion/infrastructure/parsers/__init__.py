"""Parsers locales y registro explicito de ingesta."""

from barbarion.infrastructure.parsers.base import BaseParser
from barbarion.infrastructure.parsers.docx import DocxParser
from barbarion.infrastructure.parsers.encoding import (
    DOCUMENT_CORRUPT,
    EXTRACTION_LIMIT_EXCEEDED,
    LOW_CONFIDENCE_ENCODING,
    TEXT_DECODE_FAILED,
    DecodedText,
    TextExtractionError,
    decode_text_bytes,
    decode_text_source,
)
from barbarion.infrastructure.parsers.markdown import MarkdownParser
from barbarion.infrastructure.parsers.oracle import ORACLE_EXTENSIONS, OracleParser
from barbarion.infrastructure.parsers.pdf import (
    PDF_ENCRYPTED,
    PDF_NO_EXTRACTABLE_TEXT,
    PdfParser,
)
from barbarion.infrastructure.parsers.powerbuilder import (
    POWERBUILDER_EXTENSIONS,
    POWERBUILDER_TEXT_EXTENSIONS,
    UNSUPPORTED_BINARY_PBL,
    PowerBuilderParser,
)
from barbarion.infrastructure.parsers.registry import (
    DuplicateParserExtensionError,
    ParserRegistry,
    ParserRegistryError,
    UnknownParserExtensionError,
)
from barbarion.infrastructure.parsers.text import TextParser

__all__ = [
    "BaseParser",
    "DecodedText",
    "DOCUMENT_CORRUPT",
    "DocxParser",
    "DuplicateParserExtensionError",
    "EXTRACTION_LIMIT_EXCEEDED",
    "LOW_CONFIDENCE_ENCODING",
    "MarkdownParser",
    "ORACLE_EXTENSIONS",
    "POWERBUILDER_EXTENSIONS",
    "POWERBUILDER_TEXT_EXTENSIONS",
    "OracleParser",
    "PDF_ENCRYPTED",
    "PDF_NO_EXTRACTABLE_TEXT",
    "ParserRegistry",
    "ParserRegistryError",
    "PdfParser",
    "PowerBuilderParser",
    "TEXT_DECODE_FAILED",
    "TextExtractionError",
    "TextParser",
    "UNSUPPORTED_BINARY_PBL",
    "UnknownParserExtensionError",
    "decode_text_bytes",
    "decode_text_source",
]
