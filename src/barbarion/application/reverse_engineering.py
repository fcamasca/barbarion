"""Casos de uso H4 para catalogo, referencias y relaciones.

Este modulo coordina la capa de aplicacion del reverse engineering H4. Mantiene
separadas las reglas de normalizacion y resolucion del flujo de orquestacion,
de modo que los comandos de CLI deleguen en servicios y repositorios sin
duplicar decisiones de negocio.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Any

from barbarion.config import Settings
from barbarion.domain.models import Confidence
from barbarion.domain.progress import (
    CancellationTokenPort,
    ProgressReporterPort,
    ProgressSnapshot,
    ProgressStage,
)
from barbarion.domain.reverse_engineering import (
    H4AnalysisRunMode,
    H4AnalysisRunStatus,
    H4Classification,
    H4Symbol,
    H4Reference,
    H4Relation,
    H4RelationCandidate,
    H4ResolutionStatus,
    h4_symbol_id,
    h4_relation_id,
    normalize_symbol_name,
)
from barbarion.infrastructure.sqlite import (
    H4SymbolSource,
    SQLiteReverseEngineeringRepository,
)
from barbarion.infrastructure.parsers.oracle import extract_oracle_references
from barbarion.infrastructure.parsers.powerbuilder import extract_powerbuilder_references


@dataclass(frozen=True, slots=True)
class SymbolCatalogSummary:
    """Resume una corrida de catalogacion de simbolos H4.

    El resumen se usa como contrato de salida de aplicacion para reportar
    conteos de fuentes, simbolos aceptados y descartes conservadores sin
    exponer detalles de persistencia.
    """

    run_id: int
    status: H4AnalysisRunStatus
    sources_scanned: int
    symbols_detected: int
    duplicates_skipped: int
    unknown_symbols: int
    duration_ms: int


@dataclass(frozen=True, slots=True)
class RelationResolutionSummary:
    """Resume una corrida de resolucion de relaciones H4.

    Distingue relaciones resueltas, ambiguas, dinamicas, externas y referencias
    que permanecen sin relacion para conservar la trazabilidad del criterio
    aplicado por el resolvedor.
    """

    run_id: int
    status: H4AnalysisRunStatus
    references_seen: int
    relations_resolved: int
    relations_ambiguous: int
    relations_dynamic: int
    relations_external: int
    unresolved_without_relation: int
    duration_ms: int


@dataclass(frozen=True, slots=True)
class AnalyzeSummary:
    """Resume la ejecucion completa de `barbarion analyze`.

    Incluye conteos de descubrimiento, extraccion y resolucion para que la CLI
    pueda mostrar resultados consistentes tanto en modo real como en `dry_run`.
    """

    run_id: int | None
    status: H4AnalysisRunStatus
    files_scanned: int
    chunks_scanned: int
    symbols_detected: int
    references_detected: int
    relations_resolved: int
    relations_ambiguous: int
    relations_unresolved: int
    dry_run: bool = False
    duration_ms: int = 0


@dataclass(frozen=True, slots=True)
class AnalyzeScope:
    """Representa el alcance de archivos que debe procesar `analyze`.

    Attributes:
        path_prefix: Prefijo opcional usado por el repositorio para limitar los
            chunks vigentes considerados por la corrida.
    """

    path_prefix: str | None = None


@dataclass(frozen=True, slots=True)
class SymbolCatalogService:
    """Puebla el catalogo H4 de simbolos desde chunks H2 vigentes.

    Este servicio conserva el flujo historico H4-T02: toma las fuentes vigentes,
    infiere un simbolo por fuente y persiste una identidad logica estable por
    simbolo. No extrae referencias ni intenta resolver relaciones.
    """

    settings: Settings
    repository: SQLiteReverseEngineeringRepository

    def run(
        self,
        *,
        mode: H4AnalysisRunMode = H4AnalysisRunMode.INCREMENTAL,
    ) -> SymbolCatalogSummary:
        """Ejecuta una corrida de catalogacion de simbolos.

        Args:
            mode: Modo registrado para la corrida H4.

        Returns:
            Resumen con el `run_id`, el estado final y los conteos de fuentes,
            simbolos, duplicados e identificaciones incompletas.

        Note:
            La corrida persiste simbolos de forma incremental mediante el
            repositorio y marca el run como completado al finalizar.
        """
        started = time.monotonic()
        run_id = self.repository.begin_analysis_run(
            mode=mode,
            scope={"domain": self.settings.domain, "stage": "symbols"},
        )
        sources = self.repository.symbol_sources(domain=self.settings.domain)
        seen: set[str] = set()
        duplicates = 0
        unknowns = 0
        for source in sources:
            symbol = symbol_from_source(source)
            if symbol.symbol_id in seen:
                duplicates += 1
                continue
            seen.add(symbol.symbol_id)
            if symbol.symbol_type == "unknown":
                unknowns += 1
            self.repository.upsert_symbol(run_id=run_id, symbol=symbol)

        duration_ms = int((time.monotonic() - started) * 1000)
        status = H4AnalysisRunStatus.COMPLETED
        self.repository.finish_analysis_run(
            run_id=run_id,
            status=status,
            symbols_detected=len(seen),
            duration_ms=duration_ms,
        )
        return SymbolCatalogSummary(
            run_id=run_id,
            status=status,
            sources_scanned=len(sources),
            symbols_detected=len(seen),
            duplicates_skipped=duplicates,
            unknown_symbols=unknowns,
            duration_ms=duration_ms,
        )


@dataclass(frozen=True, slots=True)
class AnalyzeService:
    """Orquesta `barbarion analyze` sin duplicar reglas de negocio.

    La clase coordina seleccion de chunks, construccion de simbolos, extraccion
    de referencias, persistencia, reconciliacion de obsoletos y resolucion
    global de referencias vigentes. Las reglas concretas de normalizacion,
    extraccion y resolucion se mantienen en helpers o servicios especializados.
    """

    settings: Settings
    repository: SQLiteReverseEngineeringRepository

    def run(
        self,
        *,
        mode: H4AnalysisRunMode = H4AnalysisRunMode.INCREMENTAL,
        scope: AnalyzeScope | None = None,
        dry_run: bool = False,
        progress: ProgressReporterPort | None = None,
        cancellation: CancellationTokenPort | None = None,
    ) -> AnalyzeSummary:
        """Ejecuta catalogacion, extraccion, reconciliacion y resolucion H4.

        Args:
            mode: Modo de corrida que se persiste cuando `dry_run` es falso.
            scope: Restriccion opcional de archivos a procesar.
            dry_run: Cuando es verdadero, calcula conteos sin escribir cambios.
            progress: Puerto opcional para reportar avance por etapas.
            cancellation: Puerto opcional para interrumpir el flujo entre etapas.

        Returns:
            Resumen de la corrida con conteos de archivos, chunks, simbolos,
            referencias y resultados de resolucion.

        Note:
            En modo real, la persistencia por archivo y la re-resolucion global
            se ejecutan despues de reconciliar simbolos y referencias obsoletos.
        """
        started = time.monotonic()
        scope = scope or AnalyzeScope()
        stages = _analyze_stages()
        if progress is not None:
            progress.start(stages)
        sources = self.repository.symbol_sources(
            domain=self.settings.domain,
            path_prefix=scope.path_prefix,
        )
        file_ids = tuple(sorted({source.file_id for source in sources}))
        counters = _AnalyzeCounters(
            files_scanned=len(file_ids),
            chunks_scanned=len(sources),
        )
        _report(progress, "discover", stages, 1, 1, counters)
        if _is_cancelled(cancellation):
            return _interrupted_analyze_summary(counters, started, dry_run=dry_run)

        run_id = None
        if not dry_run:
            run_id = self.repository.begin_analysis_run(
                mode=mode,
                scope={
                    "domain": self.settings.domain,
                    "path_prefix": scope.path_prefix,
                    "stage": "analyze",
                },
            )

        symbols = _symbols_from_sources(sources)
        references = _references_from_sources(sources, symbols)
        counters = replace(
            counters,
            symbols_detected=len(symbols),
            references_detected=len(references),
        )
        _report(progress, "extract", stages, len(sources), len(sources), counters)
        if _is_cancelled(cancellation):
            if progress is not None:
                progress.finish(H4AnalysisRunStatus.INTERRUPTED.value)
            return _interrupted_analyze_summary(counters, started, dry_run=dry_run)

        if dry_run:
            resolved, ambiguous, unresolved = _resolution_counts(
                references,
                symbols,
            )
            summary = AnalyzeSummary(
                run_id=None,
                status=H4AnalysisRunStatus.COMPLETED,
                files_scanned=counters.files_scanned,
                chunks_scanned=counters.chunks_scanned,
                symbols_detected=counters.symbols_detected,
                references_detected=counters.references_detected,
                relations_resolved=resolved,
                relations_ambiguous=ambiguous,
                relations_unresolved=unresolved,
                dry_run=True,
                duration_ms=_duration_ms(started),
            )
            if progress is not None:
                progress.finish(summary.status.value)
            return summary

        assert run_id is not None
        for symbol in symbols:
            self.repository.upsert_symbol(run_id=run_id, symbol=symbol)
        for reference in references:
            self.repository.upsert_reference(run_id=run_id, reference=reference)
        self.repository.reconcile_h4_scope(run_id=run_id, file_ids=file_ids)
        self.repository.reconcile_h4_deleted_files()
        _report(progress, "persist", stages, 1, 1, counters)
        if _is_cancelled(cancellation):
            self.repository.finish_analysis_run(
                run_id=run_id,
                status=H4AnalysisRunStatus.INTERRUPTED,
                symbols_detected=counters.symbols_detected,
                references_detected=counters.references_detected,
                duration_ms=_duration_ms(started),
            )
            if progress is not None:
                progress.finish(H4AnalysisRunStatus.INTERRUPTED.value)
            return _interrupted_analyze_summary(
                counters,
                started,
                run_id=run_id,
                dry_run=dry_run,
            )

        all_symbols = self.repository.active_symbols()
        all_references = self.repository.active_references()
        resolved, ambiguous, unresolved = self._resolve_references(
            run_id=run_id,
            references=all_references,
            symbols=all_symbols,
        )
        counters = replace(
            counters,
            relations_resolved=resolved,
            relations_ambiguous=ambiguous,
            relations_unresolved=unresolved,
        )
        _report(progress, "resolve", stages, len(all_references), len(all_references), counters)
        status = H4AnalysisRunStatus.COMPLETED
        duration_ms = _duration_ms(started)
        self.repository.finish_analysis_run(
            run_id=run_id,
            status=status,
            symbols_detected=counters.symbols_detected,
            references_detected=counters.references_detected,
            relations_resolved=resolved,
            relations_unresolved=unresolved,
            relations_ambiguous=ambiguous,
            duration_ms=duration_ms,
        )
        if progress is not None:
            progress.finish(status.value)
        return AnalyzeSummary(
            run_id=run_id,
            status=status,
            files_scanned=counters.files_scanned,
            chunks_scanned=counters.chunks_scanned,
            symbols_detected=counters.symbols_detected,
            references_detected=counters.references_detected,
            relations_resolved=resolved,
            relations_ambiguous=ambiguous,
            relations_unresolved=unresolved,
            duration_ms=duration_ms,
        )

    def _resolve_references(
        self,
        *,
        run_id: int,
        references: tuple[H4Reference, ...],
        symbols: tuple[H4Symbol, ...],
    ) -> tuple[int, int, int]:
        """Re-resuelve referencias vigentes y persiste sus transiciones.

        Args:
            run_id: Corrida H4 a la que se asocian los cambios persistidos.
            references: Referencias vigentes que deben evaluarse contra el
                catalogo actual.
            symbols: Simbolos vigentes usados como universo de candidatos.

        Returns:
            Conteos de referencias resueltas, ambiguas y no resueltas despues de
            actualizar relaciones, candidatos y estado de cada referencia.
        """
        resolved = 0
        ambiguous = 0
        unresolved = 0
        for reference in references:
            decision = relation_from_reference(reference, symbols)
            if decision is None:
                unresolved += 1
                self.repository.upsert_reference(
                    run_id=run_id,
                    reference=replace(
                        reference,
                        resolution_status=H4ResolutionStatus.UNRESOLVED,
                    ),
                )
                continue
            relation, candidates = decision
            self.repository.upsert_relation(run_id=run_id, relation=relation)
            self.repository.replace_relation_candidates(
                relation_id=relation.relation_id,
                candidates=candidates,
            )
            self.repository.upsert_reference(
                run_id=run_id,
                reference=replace(
                    reference,
                    resolution_status=relation.resolution_status,
                ),
            )
            if relation.resolution_status == H4ResolutionStatus.RESOLVED:
                resolved += 1
            elif relation.resolution_status == H4ResolutionStatus.AMBIGUOUS:
                ambiguous += 1
            else:
                unresolved += 1
        return (resolved, ambiguous, unresolved)


@dataclass(frozen=True, slots=True)
class RelationResolutionService:
    """Convierte referencias H4 en relaciones trazables cuando hay evidencia.

    Este servicio conserva el flujo H4-T04 independiente de `analyze`: lee
    simbolos y referencias ya persistidos, aplica resolucion conservadora y
    guarda relaciones o candidatos sin convertir referencias sin evidencia en
    relaciones de baja calidad.
    """

    settings: Settings
    repository: SQLiteReverseEngineeringRepository

    def run(
        self,
        *,
        mode: H4AnalysisRunMode = H4AnalysisRunMode.INCREMENTAL,
    ) -> RelationResolutionSummary:
        """Ejecuta resolucion conservadora de referencias ya persistidas.

        Args:
            mode: Modo registrado para la corrida de resolucion.

        Returns:
            Resumen con conteos separados por estado de resolucion.

        Note:
            Las referencias dinamicas y externas se contabilizan aparte porque
            no participan en la resolucion exacta contra simbolos internos.
        """
        started = time.monotonic()
        run_id = self.repository.begin_analysis_run(
            mode=mode,
            scope={"domain": self.settings.domain, "stage": "relations"},
        )
        symbols = self.repository.active_symbols()
        references = self.repository.active_references()
        resolved = 0
        ambiguous = 0
        dynamic = 0
        external = 0
        unresolved = 0
        for reference in references:
            decision = relation_from_reference(reference, symbols)
            if decision is None:
                unresolved += 1
                continue
            relation, candidates = decision
            self.repository.upsert_relation(run_id=run_id, relation=relation)
            self.repository.replace_relation_candidates(
                relation_id=relation.relation_id,
                candidates=candidates,
            )
            if relation.resolution_status == H4ResolutionStatus.RESOLVED:
                resolved += 1
            elif relation.resolution_status == H4ResolutionStatus.AMBIGUOUS:
                ambiguous += 1
            elif relation.resolution_status == H4ResolutionStatus.DYNAMIC:
                dynamic += 1
            elif relation.resolution_status == H4ResolutionStatus.EXTERNAL:
                external += 1

        duration_ms = int((time.monotonic() - started) * 1000)
        status = H4AnalysisRunStatus.COMPLETED
        self.repository.finish_analysis_run(
            run_id=run_id,
            status=status,
            references_detected=len(references),
            relations_resolved=resolved,
            relations_unresolved=unresolved + dynamic + external,
            relations_ambiguous=ambiguous,
            duration_ms=duration_ms,
        )
        return RelationResolutionSummary(
            run_id=run_id,
            status=status,
            references_seen=len(references),
            relations_resolved=resolved,
            relations_ambiguous=ambiguous,
            relations_dynamic=dynamic,
            relations_external=external,
            unresolved_without_relation=unresolved,
            duration_ms=duration_ms,
        )


def relation_from_reference(
    reference: H4Reference,
    symbols: tuple[H4Symbol, ...],
) -> tuple[H4Relation, tuple[H4RelationCandidate, ...]] | None:
    """Resuelve una referencia contra simbolos compatibles sin inventar destino.

    Args:
        reference: Referencia textual detectada por extractores H4.
        symbols: Catalogo vigente de simbolos candidatos.

    Returns:
        Una relacion con sus candidatos ambiguos, o `None` cuando no existe
        evidencia suficiente para crear una relacion trazable.

    Note:
        Las referencias `dynamic` y `external` conservan su propio estado y no
        entran al flujo de resolucion exacta contra simbolos internos.
    """
    if reference.resolution_status == H4ResolutionStatus.DYNAMIC:
        return (
            _relation(
                reference,
                classification=H4Classification.TO_CONFIRM,
                resolution_status=H4ResolutionStatus.DYNAMIC,
                target_key=reference.normalized_target,
                notes="referencia dinamica conservada sin resolucion exacta",
            ),
            (),
        )
    if _is_external_reference(reference):
        return (
            _relation(
                reference,
                classification=H4Classification.TO_CONFIRM,
                resolution_status=H4ResolutionStatus.EXTERNAL,
                target_key=reference.normalized_target,
                notes="referencia marcada como externa",
            ),
            (),
        )

    candidates = _candidate_symbols(reference, symbols)
    if not candidates:
        return None
    if len(candidates) == 1:
        target = candidates[0]
        return (
            _relation(
                reference,
                classification=H4Classification.DETECTED,
                resolution_status=H4ResolutionStatus.RESOLVED,
                target_symbol_id=target.symbol_id,
                target_key=reference.normalized_target,
            ),
            (),
        )

    relation = _relation(
        reference,
        classification=H4Classification.TO_CONFIRM,
        resolution_status=H4ResolutionStatus.AMBIGUOUS,
        target_key=reference.normalized_target,
        notes="multiples candidatos compatibles",
    )
    return (
        relation,
        tuple(
            H4RelationCandidate(
                relation_id=relation.relation_id,
                candidate_symbol_id=symbol.symbol_id,
                rank=index + 1,
                reason="nombre y tipo compatibles",
            )
            for index, symbol in enumerate(candidates)
        ),
    )


def symbol_from_source(source: H4SymbolSource) -> H4Symbol:
    """Convierte un chunk H2 vigente en un simbolo H4 normalizado.

    Args:
        source: Fuente de simbolo derivada de chunks H2 vigentes.

    Returns:
        Simbolo H4 con identidad determinista, tecnologia, contenedor y
        metadatos minimos de trazabilidad hacia archivo y chunk.

    Note:
        Cuando la fuente no expone nombre o tipo, el simbolo se marca como
        `unknown` con confianza baja para no descartar evidencia de entrada.
    """
    metadata = source.metadata
    original_name = _first_text(
        source.object_name,
        metadata.get("object_name"),
        metadata.get("symbol_name"),
        metadata.get("name"),
    )
    symbol_type = _first_text(
        source.object_type,
        metadata.get("object_type"),
        metadata.get("symbol_kind"),
        source.chunk_type if source.chunk_type != "file" else None,
    )
    unknown = original_name is None or symbol_type is None
    if original_name is None:
        original_name = f"{source.relative_path}#{source.chunk_id}"
    if symbol_type is None:
        symbol_type = "unknown"

    technology = _technology(source.artifact_kind, metadata)
    container_name = None if unknown else _container_name(original_name, metadata)
    normalized_name = normalize_symbol_name(original_name)
    normalized_container = (
        normalize_symbol_name(container_name) if container_name is not None else None
    )
    confidence = _confidence(metadata, fallback=Confidence.LOW if unknown else Confidence.HIGH)
    symbol_id = h4_symbol_id(
        normalized_name=normalized_name,
        symbol_type=symbol_type,
        technology=technology,
        container_name=normalized_container,
    )
    return H4Symbol(
        symbol_id=symbol_id,
        original_name=original_name,
        normalized_name=normalized_name,
        symbol_type=symbol_type.lower(),
        technology=technology,
        extraction_method="inferred" if unknown else "parser",
        confidence=confidence,
        file_id=source.file_id,
        document_id=source.document_id,
        chunk_id=source.chunk_id,
        container_name=normalized_container,
        start_line=source.start_line,
        end_line=source.end_line,
        metadata={
            "artifact_kind": source.artifact_kind,
            "relative_path": source.relative_path,
            "source_chunk_type": source.chunk_type,
        },
    )


@dataclass(frozen=True, slots=True)
class _AnalyzeCounters:
    """Agrupa conteos internos usados por `analyze` y el reporte de progreso."""

    files_scanned: int = 0
    chunks_scanned: int = 0
    symbols_detected: int = 0
    references_detected: int = 0
    relations_resolved: int = 0
    relations_ambiguous: int = 0
    relations_unresolved: int = 0

    def as_progress(self) -> dict[str, int]:
        """Adapta los conteos H4 al contrato generico de progreso."""
        return {
            "new": self.symbols_detected,
            "update": self.references_detected,
            "unchanged": self.relations_resolved,
            "delete": self.relations_ambiguous,
            "errores": self.relations_unresolved,
        }


def _symbols_from_sources(sources: tuple[H4SymbolSource, ...]) -> tuple[H4Symbol, ...]:
    """Construye simbolos unicos por identidad determinista."""
    by_id: dict[str, H4Symbol] = {}
    for source in sources:
        symbol = symbol_from_source(source)
        by_id.setdefault(symbol.symbol_id, symbol)
    return tuple(by_id.values())


def _references_from_sources(
    sources: tuple[H4SymbolSource, ...],
    symbols: tuple[H4Symbol, ...],
) -> tuple[H4Reference, ...]:
    """Extrae referencias unicas y las vincula con el simbolo fuente si existe."""
    source_symbol_by_chunk = {
        symbol.chunk_id: symbol.symbol_id
        for symbol in symbols
        if symbol.chunk_id is not None
    }
    by_id: dict[str, H4Reference] = {}
    for source in sources:
        references = _extract_references_from_source(
            source,
            source_symbol_id=source_symbol_by_chunk.get(source.chunk_id),
        )
        for reference in references:
            by_id.setdefault(reference.reference_id, reference)
    return tuple(by_id.values())


def _extract_references_from_source(
    source: H4SymbolSource,
    *,
    source_symbol_id: str | None,
) -> tuple[H4Reference, ...]:
    """Despacha la extraccion de referencias segun la tecnologia del artefacto."""
    if source.artifact_kind == "oracle":
        return extract_oracle_references(
            source.content,
            source_file_id=source.file_id,
            source_chunk_id=source.chunk_id,
            source_symbol_id=source_symbol_id,
        )
    if source.artifact_kind == "powerbuilder":
        return extract_powerbuilder_references(
            source.content,
            source_file_id=source.file_id,
            source_chunk_id=source.chunk_id,
            source_symbol_id=source_symbol_id,
        )
    return ()


def _resolution_counts(
    references: tuple[H4Reference, ...],
    symbols: tuple[H4Symbol, ...],
) -> tuple[int, int, int]:
    """Calcula conteos de resolucion sin persistir relaciones ni referencias."""
    resolved = 0
    ambiguous = 0
    unresolved = 0
    for reference in references:
        decision = relation_from_reference(reference, symbols)
        if decision is None:
            unresolved += 1
            continue
        relation, _ = decision
        if relation.resolution_status == H4ResolutionStatus.RESOLVED:
            resolved += 1
        elif relation.resolution_status == H4ResolutionStatus.AMBIGUOUS:
            ambiguous += 1
        else:
            unresolved += 1
    return (resolved, ambiguous, unresolved)


def _analyze_stages() -> tuple[ProgressStage, ...]:
    """Define las etapas visibles del progreso de `barbarion analyze`."""
    return (
        ProgressStage("discover", "Seleccionando chunks", total=1),
        ProgressStage("extract", "Extrayendo H4", total=None),
        ProgressStage("persist", "Persistiendo H4", total=1),
        ProgressStage("resolve", "Resolviendo relaciones", total=None),
    )


def _report(
    progress: ProgressReporterPort | None,
    stage_key: str,
    stages: tuple[ProgressStage, ...],
    current: int,
    total: int | None,
    counters: _AnalyzeCounters,
) -> None:
    """Publica una fotografia de progreso cuando existe un reporter activo."""
    if progress is None:
        return
    labels = {stage.key: stage.label for stage in stages}
    order = {stage.key: index for index, stage in enumerate(stages, start=1)}
    progress.stage(
        ProgressSnapshot(
            stage_key=stage_key,
            stage_label=labels[stage_key],
            current=current,
            total=total,
            global_current=order[stage_key],
            global_total=len(stages),
            counters=counters.as_progress(),
        )
    )


def _is_cancelled(cancellation: CancellationTokenPort | None) -> bool:
    """Indica si el puerto de cancelacion solicita interrumpir la corrida."""
    return bool(cancellation is not None and cancellation.cancelled)


def _duration_ms(started: float) -> int:
    """Calcula la duracion transcurrida desde una marca monotona."""
    return int((time.monotonic() - started) * 1000)


def _interrupted_analyze_summary(
    counters: _AnalyzeCounters,
    started: float,
    *,
    run_id: int | None = None,
    dry_run: bool,
) -> AnalyzeSummary:
    """Construye un resumen uniforme para corridas interrumpidas."""
    return AnalyzeSummary(
        run_id=run_id,
        status=H4AnalysisRunStatus.INTERRUPTED,
        files_scanned=counters.files_scanned,
        chunks_scanned=counters.chunks_scanned,
        symbols_detected=counters.symbols_detected,
        references_detected=counters.references_detected,
        relations_resolved=counters.relations_resolved,
        relations_ambiguous=counters.relations_ambiguous,
        relations_unresolved=counters.relations_unresolved,
        dry_run=dry_run,
        duration_ms=_duration_ms(started),
    )


def _relation(
    reference: H4Reference,
    *,
    classification: H4Classification,
    resolution_status: H4ResolutionStatus,
    target_symbol_id: str | None = None,
    target_key: str | None = None,
    notes: str | None = None,
) -> H4Relation:
    """Crea la relacion canonica asociada a una referencia detectada."""
    relation_id = h4_relation_id(
        reference_id=reference.reference_id,
        relation_type=_relation_type(reference),
        target_symbol_id=target_symbol_id,
        target_key=target_key,
    )
    return H4Relation(
        relation_id=relation_id,
        reference_id=reference.reference_id,
        source_symbol_id=reference.source_symbol_id,
        target_symbol_id=target_symbol_id,
        target_key=target_key,
        relation_type=_relation_type(reference),
        classification=classification,
        resolution_status=resolution_status,
        confidence=reference.confidence,
        evidence_file_id=reference.source_file_id,
        evidence_chunk_id=reference.source_chunk_id,
        start_line=reference.start_line,
        end_line=reference.end_line,
        notes=notes,
    )


def _candidate_symbols(
    reference: H4Reference,
    symbols: tuple[H4Symbol, ...],
) -> tuple[H4Symbol, ...]:
    """Selecciona candidatos por tecnologia, tipo, nombre y contenedor."""
    compatible = [
        symbol
        for symbol in symbols
        if symbol.technology == reference.technology
        and _type_compatible(reference.reference_type, symbol.symbol_type)
    ]
    target = normalize_symbol_name(reference.normalized_target)
    parts = target.split(".")
    if len(parts) > 1:
        container = ".".join(parts[:-1])
        leaf = parts[-1]
        matches = [
            symbol
            for symbol in compatible
            if symbol.normalized_name == target
            or (
                symbol.normalized_name == leaf
                and symbol.container_name == container
            )
        ]
        return tuple(_stable_symbols(matches))

    matches = [symbol for symbol in compatible if symbol.normalized_name == target]
    source = _source_symbol(reference, symbols)
    if source is not None and source.container_name is not None:
        same_container = [
            symbol
            for symbol in matches
            if symbol.container_name == source.container_name
        ]
        if same_container:
            matches = same_container
    return tuple(_stable_symbols(matches))


def _stable_symbols(symbols: list[H4Symbol]) -> list[H4Symbol]:
    """Ordena candidatos de forma estable para resultados reproducibles."""
    return sorted(
        symbols,
        key=lambda symbol: (
            symbol.container_name or "",
            symbol.normalized_name,
            symbol.symbol_type,
            symbol.symbol_id,
        ),
    )


def _source_symbol(
    reference: H4Reference,
    symbols: tuple[H4Symbol, ...],
) -> H4Symbol | None:
    """Busca el simbolo origen declarado por una referencia."""
    if reference.source_symbol_id is None:
        return None
    for symbol in symbols:
        if symbol.symbol_id == reference.source_symbol_id:
            return symbol
    return None


def _type_compatible(reference_type: str, symbol_type: str) -> bool:
    """Valida si el tipo de referencia puede apuntar al tipo de simbolo dado."""
    allowed = {
        "call": {"procedure", "function", "event", "function_object"},
        "calls": {"procedure", "function", "event", "function_object"},
        "stored_procedure": {"procedure", "function"},
        "table": {"table", "view", "datawindow"},
        "trigger_table": {"table", "view"},
        "sequence": {"sequence"},
        "open": {"window", "userobject", "menu", "application"},
        "event": {"event"},
        "datawindow": {"datawindow"},
    }.get(reference_type, set())
    return symbol_type in allowed


def _relation_type(reference: H4Reference) -> str:
    """Mapea el tipo de referencia al tipo canonico de relacion H4."""
    return {
        "call": "calls",
        "calls": "calls",
        "stored_procedure": "calls",
        "table": "uses",
        "trigger_table": "uses",
        "sequence": "uses",
        "open": "opens",
        "event": "calls",
        "datawindow": "uses",
        "dynamic_sql": "uses",
    }.get(reference.reference_type, "uses")


def _is_external_reference(reference: H4Reference) -> bool:
    """Detecta referencias que apuntan fuera del catalogo interno."""
    scope = reference.metadata.get("scope")
    if isinstance(scope, str) and scope.lower() == "external":
        return True
    if "@" in reference.raw_text:
        return True
    return reference.normalized_target.startswith("external.")


def _technology(artifact_kind: str, metadata: dict[str, Any]) -> str:
    """Deriva la tecnologia H4 a partir del tipo de artefacto y metadatos."""
    format_value = _first_text(metadata.get("format"))
    if format_value in {"oracle", "powerbuilder"}:
        return format_value
    if artifact_kind in {"oracle", "powerbuilder"}:
        return artifact_kind
    if artifact_kind in {"markdown", "pdf", "docx", "text"}:
        return "document"
    return "unknown"


def _container_name(original_name: str, metadata: dict[str, Any]) -> str | None:
    """Obtiene el contenedor logico desde metadatos o nombres calificados."""
    explicit = _first_text(
        metadata.get("parent_name"),
        metadata.get("package_name"),
        metadata.get("class_name"),
    )
    if explicit is not None:
        return explicit
    parts = normalize_symbol_name(original_name).split(".")
    if len(parts) > 1:
        return ".".join(parts[:-1])
    return None


def _confidence(metadata: dict[str, Any], *, fallback: Confidence) -> Confidence:
    """Lee la confianza declarada en metadatos o devuelve el valor de respaldo."""
    raw = _first_text(
        metadata.get("logical_unit_confidence"),
        metadata.get("confidence"),
    )
    if raw is None:
        return fallback
    try:
        return Confidence(raw.lower())
    except ValueError:
        return fallback


def _first_text(*values: object) -> str | None:
    """Devuelve el primer texto no vacio entre los valores recibidos."""
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
