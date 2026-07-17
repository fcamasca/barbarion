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
from barbarion.domain.rag import (
    EmbeddingManifest,
    EmbeddingRequest,
    EmbeddingVector,
    RetrievalCandidate,
    RetrievalFilter,
    VectorMetadata,
)
from barbarion.domain.reverse_engineering import (
    AnalysisRunMode,
    AnalysisRunRecord,
    AnalysisRunStatus,
    DependencyDirection,
    TechnicalReference,
    TechnicalRelation,
    RelationCandidate,
    TechnicalSymbol,
)
from barbarion.domain.ingestion import PersistedFileState


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
        processing_signature: str,
        parser_id: str,
        parser_version: str,
        encoding: str | None,
        document: NormalizedDocument,
        chunks: Sequence[ChunkCandidate],
        artifact_kind: str | None = None,
    ) -> None:
        """Reemplaza documento y chunks de un archivo en una transaccion.

        Args:
            artifact_kind: Clasificacion opcional que debe persistirse para el
                archivo cuando difiere de la inferencia por extension.
        """

    def mark_seen(
        self,
        *,
        run_id: int,
        discovered_file: DiscoveredFile,
        state: PersistedFileState,
    ) -> None:
        """Actualiza metadata de un archivo vigente sin reemplazar contenido."""

    def mark_seen_many(
        self,
        *,
        run_id: int,
        seen_files: Sequence[tuple[DiscoveredFile, PersistedFileState]],
    ) -> None:
        """Actualiza metadata de archivos vigentes en lote."""

    def record_skipped(
        self,
        *,
        run_id: int,
        discovered_file: DiscoveredFile,
        error: PipelineError,
    ) -> None:
        """Registra un archivo omitido con razon recuperable."""

    def record_error(
        self,
        *,
        run_id: int,
        error: PipelineError,
        discovered_file: DiscoveredFile | None = None,
    ) -> None:
        """Registra un error tipado sin contenido fuente."""

    def get_file_state(
        self,
        *,
        domain: str,
        discovered_file: DiscoveredFile,
    ) -> PersistedFileState | None:
        """Devuelve el estado vigente conocido de un archivo."""

    def reconcile_deleted(
        self,
        *,
        run_id: int,
        domain: str,
        completed_roots: Sequence[Path],
    ) -> int:
        """Marca como deleted archivos no vistos en roots completas."""

    def finish_run(
        self,
        *,
        run_id: int,
        outcome: IngestionOutcome,
    ) -> None:
        """Cierra una ejecucion con metricas finales."""

    def current_metrics(self) -> IngestionMetrics:
        """Devuelve metricas de solo lectura del inventario vigente."""


class EmbeddingProviderPort(Protocol):
    """Contrato para proveedores de embeddings locales."""

    provider: str
    model: str

    def embed(self, request: EmbeddingRequest) -> tuple[EmbeddingVector, ...]:
        """Genera embeddings para un batch de textos."""


class VectorStorePort(Protocol):
    """Contrato para almacenamiento vectorial local inicial."""

    def upsert(
        self,
        *,
        manifest: EmbeddingManifest,
        chunk_id: str,
        vector: Sequence[float],
        metadata: VectorMetadata,
    ) -> None:
        """Inserta o reemplaza un vector asociado a un chunk."""

    def delete(self, *, manifest: EmbeddingManifest, chunk_id: str) -> None:
        """Elimina o invalida un vector asociado a un chunk."""

    def search(
        self,
        *,
        manifest: EmbeddingManifest,
        query_vector: Sequence[float],
        filters: RetrievalFilter,
        top_k: int,
    ) -> tuple[RetrievalCandidate, ...]:
        """Devuelve candidatos ordenados por similitud."""


class LlmProviderPort(Protocol):
    """Contrato para generacion local asistida por LLM."""

    provider: str
    model: str

    def generate(self, *, prompt: str, timeout_seconds: float) -> str:
        """Genera una respuesta desde un prompt controlado."""


class ReverseEngineeringRepositoryPort(Protocol):
    """Contrato minimo de persistencia para reverse engineering."""

    def begin_analysis_run(
        self,
        *,
        mode: AnalysisRunMode,
        scope: dict[str, object] | None = None,
    ) -> int:
        """Crea una corrida de reverse engineering y devuelve su identificador."""

    def analysis_run(self, run_id: int) -> AnalysisRunRecord | None:
        """Lee una corrida de reverse engineering persistida."""

    def finish_analysis_run(
        self,
        *,
        run_id: int,
        status: AnalysisRunStatus,
        symbols_detected: int = 0,
        references_detected: int = 0,
        relations_resolved: int = 0,
        relations_unresolved: int = 0,
        relations_ambiguous: int = 0,
        warning_count: int = 0,
        error_count: int = 0,
        duration_ms: int | None = None,
    ) -> None:
        """Cierra una corrida de reverse engineering con contadores consolidados."""

    def upsert_symbol(self, *, run_id: int, symbol: TechnicalSymbol) -> None:
        """Inserta o actualiza el estado vigente de un simbolo."""

    def get_symbol(self, symbol_id: str) -> TechnicalSymbol | None:
        """Lee un simbolo por ID determinista."""

    def active_symbols(self) -> tuple[TechnicalSymbol, ...]:
        """Lista simbolos activos del catalogo reverse engineering vigente."""

    def upsert_reference(self, *, run_id: int, reference: TechnicalReference) -> None:
        """Inserta o actualiza una referencia vigente."""

    def get_reference(self, reference_id: str) -> TechnicalReference | None:
        """Lee una referencia por ID determinista."""

    def upsert_relation(self, *, run_id: int, relation: TechnicalRelation) -> None:
        """Inserta o actualiza una relacion canonica."""

    def get_relation(self, relation_id: str) -> TechnicalRelation | None:
        """Lee una relacion por ID determinista."""

    def active_relations_for_symbol(
        self,
        symbol_id: str,
        *,
        direction: DependencyDirection,
    ) -> tuple[TechnicalRelation, ...]:
        """Lista relaciones activas adyacentes a un simbolo."""

    def relation_candidates(
        self,
        relation_id: str,
    ) -> tuple[RelationCandidate, ...]:
        """Lee candidatos de una relacion ambigua."""
