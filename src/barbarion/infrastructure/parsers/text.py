"""Parser de texto plano y configuracion textual."""

from __future__ import annotations

from barbarion.domain.models import (
    Confidence,
    ExtractionContext,
    ExtractionResult,
    LogicalUnit,
    SourceFile,
)
from barbarion.infrastructure.parsers.base import BaseParser
from barbarion.infrastructure.parsers.encoding import decode_text_source


CONFIG_EXTENSIONS = frozenset({".yaml", ".yml", ".json", ".ini"})


class TextParser(BaseParser):
    """Preserva texto y archivos de configuracion sin evaluarlos."""

    parser_id = "text"
    parser_version = "1"
    supported_extensions = (".txt", ".yaml", ".yml", ".json", ".ini")

    def extract(
        self,
        source: SourceFile,
        context: ExtractionContext,
    ) -> ExtractionResult:
        decoded = decode_text_source(
            source,
            encodings=context.encodings,
            max_extracted_chars=context.max_extracted_chars,
        )
        line_count = max(1, len(decoded.text.splitlines()))
        artifact_kind = _artifact_kind(source.discovered.extension)
        unit = LogicalUnit(
            unit_type="file",
            name=source.discovered.relative_path.name,
            confidence=Confidence.HIGH,
            start_line=1,
            end_line=line_count,
            metadata={
                "format": artifact_kind,
                "extension": source.discovered.extension,
            },
        )
        return ExtractionResult(
            text=decoded.text,
            title=source.discovered.relative_path.name,
            encoding=decoded.encoding,
            units=(unit,),
            metadata={
                "format": artifact_kind,
                "extension": source.discovered.extension,
            },
            warnings=decoded.warnings,
        )


def _artifact_kind(extension: str) -> str:
    return "config" if extension in CONFIG_EXTENSIONS else "text"
