"""Contrato base para parsers concretos de infraestructura."""

from __future__ import annotations

from abc import ABC, abstractmethod

from barbarion.domain.models import (
    ExtractionContext,
    ExtractionResult,
    SourceFile,
)


class BaseParser(ABC):
    """Base comun para extractores de formatos soportados por ingesta."""

    parser_id: str
    parser_version: str
    supported_extensions: tuple[str, ...]

    @abstractmethod
    def extract(
        self,
        source: SourceFile,
        context: ExtractionContext,
    ) -> ExtractionResult:
        """Extrae texto y unidades logicas desde una fuente."""
