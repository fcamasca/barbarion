"""Puertos minimos del dominio para el pipeline de ingesta."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Protocol

from barbarion.domain.models import (
    ChunkCandidate,
    DiscoveredFile,
    ExtractionContext,
    ExtractionResult,
    FileFingerprint,
    IngestionMetrics,
    IngestionMode,
    IngestionOutcome,
    NormalizedDocument,
    PipelineError,
    SourceFile,
)


class ParserPort(Protocol):
    """Contrato comun para parsers concretos de infraestructura."""

    parser_id: str
    parser_version: str
    supported_extensions: tuple[str, ...]

    def extract(
        self,
        source: SourceFile,
        context: ExtractionContext,
    ) -> ExtractionResult:
        """Extrae texto y unidades logicas desde una fuente."""


class DiscoveryPort(Protocol):
    """Contrato para descubrir archivos autorizados."""

    def discover(
        self,
        roots: Sequence[Path],
        extensions: Sequence[str],
        ignore_patterns: Sequence[str],
        max_file_size_mb: int,
    ) -> Iterable[DiscoveredFile | PipelineError]:
        """Devuelve archivos descubiertos o errores recuperables."""


class FingerprintPort(Protocol):
    """Contrato para calcular fingerprints sin exponer el adaptador."""

    def fingerprint(self, discovered_file: DiscoveredFile) -> FileFingerprint:
        """Calcula la huella de bytes de una fuente."""


class IngestionRepositoryPort(Protocol):
    """Contrato de persistencia requerido por el caso de uso."""

    def begin_run(
        self,
        *,
        domain: str,
        mode: IngestionMode,
        roots: Sequence[Path],
        config_sha256: str,
    ) -> int:
        """Crea una ejecucion y devuelve su identificador."""

    def replace_document(
        self,
        *,
        run_id: int,
        discovered_file: DiscoveredFile,
        fingerprint: FileFingerprint,
        document: NormalizedDocument,
        chunks: Sequence[ChunkCandidate],
    ) -> None:
        """Reemplaza documento y chunks de un archivo en una transaccion."""

    def record_error(self, *, run_id: int, error: PipelineError) -> None:
        """Registra un error tipado sin contenido fuente."""

    def finish_run(
        self,
        *,
        run_id: int,
        outcome: IngestionOutcome,
    ) -> None:
        """Cierra una ejecucion con metricas finales."""

    def current_metrics(self) -> IngestionMetrics:
        """Devuelve metricas de solo lectura del inventario vigente."""

