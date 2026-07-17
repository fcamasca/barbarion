"""Casos de uso reverse engineering para catalogo, referencias y relaciones.

Este modulo coordina la capa de aplicacion del reverse engineering reverse engineering. Mantiene
separadas las reglas de normalizacion y resolucion del flujo de orquestacion,
de modo que los comandos de CLI deleguen en servicios y repositorios sin
duplicar decisiones de negocio.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any

from barbarion.config import Settings
from barbarion.domain.data_driven import build_configuration_symbols
from barbarion.domain.models import Confidence
from barbarion.domain.ports import LlmProviderPort
from barbarion.domain.progress import (
    CancellationTokenPort,
    ProgressReporterPort,
    ProgressSnapshot,
    ProgressStage,
)
from barbarion.domain.rag import RetrievalFilter, RetrievalMode, SearchRequest
from barbarion.domain.reverse_engineering import (
    AnalysisRunMode,
    AnalysisRunStatus,
    EvidenceClassification,
    ComponentDescription,
    DependencyDirection,
    DependencyEdge,
    DependencyFilters,
    DependencyNode,
    DependencyWalk,
    EvidenceItem,
    Inventory,
    InventoryFilters,
    ImpactAnalysis,
    ObjectResolution,
    TechnicalReference,
    TechnicalRelation,
    RelationCandidate,
    ResolutionStatus,
    TechnicalSymbol,
    SymbolStatus,
    technical_symbol_id,
    technical_relation_id,
    normalize_symbol_name,
)
from barbarion.infrastructure.sqlite import (
    SymbolSource,
    SQLiteReverseEngineeringRepository,
)
from barbarion.infrastructure.parsers.oracle import extract_oracle_references
from barbarion.infrastructure.parsers.data_driven_dml import parse_dml_configurations
from barbarion.infrastructure.parsers.powerbuilder import extract_powerbuilder_references


@dataclass(frozen=True, slots=True)
class SymbolCatalogSummary:
    """Resume una corrida de catalogacion de simbolos de reverse engineering.

    El resumen se usa como contrato de salida de aplicacion para reportar
    conteos de fuentes, simbolos aceptados y descartes conservadores sin
    exponer detalles de persistencia.
    """

    run_id: int
    status: AnalysisRunStatus
    sources_scanned: int
    symbols_detected: int
    duplicates_skipped: int
    unknown_symbols: int
    duration_ms: int


@dataclass(frozen=True, slots=True)
class RelationResolutionSummary:
    """Resume una corrida de resolucion de relaciones de reverse engineering.

    Distingue relaciones resueltas, ambiguas, dinamicas, externas y referencias
    que permanecen sin relacion para conservar la trazabilidad del criterio
    aplicado por el resolvedor.
    """

    run_id: int
    status: AnalysisRunStatus
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
    status: AnalysisRunStatus
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
class ObjectRequest:
    """Solicitud comun para resolver un objeto reverse engineering por ID o nombre.

    Args:
        query: Nombre simple o calificado recibido desde capas superiores.
        symbol_id: Identificador determinista opcional; cuando se informa,
            tiene prioridad sobre `query`.
        symbol_type: Tipo tecnico opcional usado para desambiguar.
    """

    query: str
    symbol_id: str | None = None
    symbol_type: str | None = None


@dataclass(frozen=True, slots=True)
class DescribeRequest:
    """Solicitud estructurada para producir una descripcion de componente."""

    target: ObjectRequest
    depth: int = 1
    no_llm: bool = True
    include_rag: bool = False


@dataclass(frozen=True, slots=True)
class ImpactRequest:
    """Solicitud estructurada para producir un analisis de impacto basico."""

    target: ObjectRequest
    direction: DependencyDirection = DependencyDirection.BOTH
    depth: int = 2
    node_limit: int = 500
    no_llm: bool = True
    include_rag: bool = False
    filters: DependencyFilters | None = None


@dataclass(frozen=True, slots=True)
class InventoryRequest:
    """Solicitud estructurada para consultar inventario reverse engineering.

    Attributes:
        filters: Filtros efectivos de simbolos, tecnologia, ruta y confianza.
    """

    filters: InventoryFilters = InventoryFilters()


@dataclass(frozen=True, slots=True)
class SymbolCatalogService:
    """Puebla el catalogo reverse engineering de simbolos desde chunks vigentes.

    Este servicio conserva el flujo historico la tarea de reverse engineering: toma las fuentes vigentes,
    infiere un simbolo por fuente y persiste una identidad logica estable por
    simbolo. No extrae referencias ni intenta resolver relaciones.
    """

    settings: Settings
    repository: SQLiteReverseEngineeringRepository

    def run(
        self,
        *,
        mode: AnalysisRunMode = AnalysisRunMode.INCREMENTAL,
    ) -> SymbolCatalogSummary:
        """Ejecuta una corrida de catalogacion de simbolos.

        Args:
            mode: Modo registrado para la corrida de reverse engineering.

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
        for symbol in _iter_symbols_from_sources(sources, settings=self.settings):
            if symbol.symbol_id in seen:
                duplicates += 1
                continue
            seen.add(symbol.symbol_id)
            if symbol.symbol_type == "unknown":
                unknowns += 1
            self.repository.upsert_symbol(run_id=run_id, symbol=symbol)

        duration_ms = int((time.monotonic() - started) * 1000)
        status = AnalysisRunStatus.COMPLETED
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
        mode: AnalysisRunMode = AnalysisRunMode.INCREMENTAL,
        scope: AnalyzeScope | None = None,
        dry_run: bool = False,
        progress: ProgressReporterPort | None = None,
        cancellation: CancellationTokenPort | None = None,
    ) -> AnalyzeSummary:
        """Ejecuta catalogacion, extraccion, reconciliacion y resolucion reverse engineering.

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

        symbols = _symbols_from_sources(sources, settings=self.settings)
        references = _references_from_sources(sources, symbols)
        counters = replace(
            counters,
            symbols_detected=len(symbols),
            references_detected=len(references),
        )
        _report(progress, "extract", stages, len(sources), len(sources), counters)
        if _is_cancelled(cancellation):
            if progress is not None:
                progress.finish(AnalysisRunStatus.INTERRUPTED.value)
            return _interrupted_analyze_summary(counters, started, dry_run=dry_run)

        if dry_run:
            resolved, ambiguous, unresolved = _resolution_counts(
                references,
                symbols,
            )
            counters = replace(
                counters,
                relations_resolved=resolved,
                relations_ambiguous=ambiguous,
                relations_unresolved=unresolved,
            )
            _report(
                progress,
                "resolve",
                stages,
                len(references),
                len(references),
                counters,
            )
            summary = AnalyzeSummary(
                run_id=None,
                status=AnalysisRunStatus.COMPLETED,
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
        self.repository.reconcile_analysis_scope(run_id=run_id, file_ids=file_ids)
        self.repository.reconcile_deleted_files()
        _report(progress, "persist", stages, 1, 1, counters)
        if _is_cancelled(cancellation):
            self.repository.finish_analysis_run(
                run_id=run_id,
                status=AnalysisRunStatus.INTERRUPTED,
                symbols_detected=counters.symbols_detected,
                references_detected=counters.references_detected,
                duration_ms=_duration_ms(started),
            )
            if progress is not None:
                progress.finish(AnalysisRunStatus.INTERRUPTED.value)
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
        status = AnalysisRunStatus.COMPLETED
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
        references: tuple[TechnicalReference, ...],
        symbols: tuple[TechnicalSymbol, ...],
    ) -> tuple[int, int, int]:
        """Re-resuelve referencias vigentes y persiste sus transiciones.

        Args:
            run_id: Corrida reverse engineering a la que se asocian los cambios persistidos.
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
                        resolution_status=ResolutionStatus.UNRESOLVED,
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
            if relation.resolution_status == ResolutionStatus.RESOLVED:
                resolved += 1
            elif relation.resolution_status == ResolutionStatus.AMBIGUOUS:
                ambiguous += 1
            else:
                unresolved += 1
        return (resolved, ambiguous, unresolved)


@dataclass(frozen=True, slots=True)
class RelationResolutionService:
    """Convierte referencias reverse engineering en relaciones trazables cuando hay evidencia.

    Este servicio conserva el flujo la tarea de reverse engineering independiente de `analyze`: lee
    simbolos y referencias ya persistidos, aplica resolucion conservadora y
    guarda relaciones o candidatos sin convertir referencias sin evidencia en
    relaciones de baja calidad.
    """

    settings: Settings
    repository: SQLiteReverseEngineeringRepository

    def run(
        self,
        *,
        mode: AnalysisRunMode = AnalysisRunMode.INCREMENTAL,
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
            if relation.resolution_status == ResolutionStatus.RESOLVED:
                resolved += 1
            elif relation.resolution_status == ResolutionStatus.AMBIGUOUS:
                ambiguous += 1
            elif relation.resolution_status == ResolutionStatus.DYNAMIC:
                dynamic += 1
            elif relation.resolution_status == ResolutionStatus.EXTERNAL:
                external += 1

        duration_ms = int((time.monotonic() - started) * 1000)
        status = AnalysisRunStatus.COMPLETED
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


@dataclass(frozen=True, slots=True)
class InventoryService:
    """Consulta el inventario tecnico sin reanalizar el corpus.

    El servicio delega toda lectura al repositorio SQLite para respetar el
    contrato la tarea de reverse engineering: `inventory` no ejecuta parsers, no accede al filesystem del
    corpus y solo presenta estado persistido.
    """

    repository: SQLiteReverseEngineeringRepository

    def inventory(self, request: InventoryRequest) -> Inventory:
        """Consulta inventario tecnico desde SQLite.

        Args:
            request: Filtros estructurados de inventario.

        Returns:
            Inventario con resumen agregado y filas ordenadas de simbolos.
        """
        return Inventory(
            filters=request.filters,
            summary=self.repository.inventory_summary(request.filters),
            items=self.repository.inventory_items(request.filters),
        )


@dataclass(frozen=True, slots=True)
class DependencyWalkService:
    """Recorre dependencias reverse engineering con BFS local, profundidad y limite de nodos.

    El servicio consulta relaciones activas desde el repositorio y calcula la
    direccion en tiempo de consulta. No construye un grafo externo ni intenta
    resolver referencias nuevas durante el recorrido.
    """

    repository: SQLiteReverseEngineeringRepository

    def walk(
        self,
        seed_symbol_id: str,
        *,
        direction: DependencyDirection = DependencyDirection.OUTGOING,
        max_depth: int = 1,
        node_limit: int = 500,
        filters: DependencyFilters | None = None,
    ) -> DependencyWalk:
        """Recorre dependencias desde un simbolo semilla.

        Args:
            seed_symbol_id: Simbolo activo desde el que inicia el recorrido.
            direction: Direccion calculada para leer relaciones adyacentes.
            max_depth: Profundidad maxima permitida, entre 0 y 5.
            node_limit: Cantidad maxima de simbolos activos incluidos.
            filters: Filtros opcionales aplicados sobre relaciones activas.

        Returns:
            Resultado BFS con nodos, aristas visibles, ciclos detectados e
            indicador de limite alcanzado.

        Raises:
            ValueError: Si la semilla no existe, no esta activa, o los limites
            solicitados estan fuera del contrato reverse engineering.
        """
        _validate_dependency_limits(max_depth=max_depth, node_limit=node_limit)
        filters = filters or DependencyFilters()
        seed = self.repository.get_symbol(seed_symbol_id)
        if seed is None or seed.status != SymbolStatus.ACTIVE:
            raise ValueError("seed_symbol_id debe identificar un simbolo activo.")

        nodes: dict[str, DependencyNode] = {
            seed.symbol_id: DependencyNode(symbol=seed, depth=0),
        }
        edges: list[DependencyEdge] = []
        cycles: list[tuple[str, ...]] = []
        limit_reached = False
        queue: deque[tuple[TechnicalSymbol, int, tuple[str, ...]]] = deque(
            [(seed, 0, (seed.symbol_id,))]
        )

        while queue:
            current, depth, path = queue.popleft()
            if depth >= max_depth:
                continue
            adjacent = self.repository.active_relations_for_symbol(
                current.symbol_id,
                direction=direction,
            )
            for relation in _filter_relations(adjacent, filters, self.repository):
                edge_direction = _edge_direction(current.symbol_id, relation)
                source = _relation_symbol(relation.source_symbol_id, self.repository)
                target = _relation_symbol(relation.target_symbol_id, self.repository)
                candidate_ids = _candidate_symbol_ids(relation, self.repository)
                next_symbol = _next_symbol(current.symbol_id, relation, source, target)
                is_cycle = (
                    next_symbol is not None and next_symbol.symbol_id in path
                )
                if is_cycle:
                    cycle = (*path, next_symbol.symbol_id)
                    if cycle not in cycles:
                        cycles.append(cycle)
                edges.append(
                    DependencyEdge(
                        relation=relation,
                        depth=depth + 1,
                        direction=edge_direction,
                        source_symbol=source,
                        target_symbol=target,
                        target_key=relation.target_key,
                        candidate_symbol_ids=candidate_ids,
                        is_cycle=is_cycle,
                    )
                )
                if next_symbol is None or is_cycle:
                    continue
                if next_symbol.symbol_id in nodes:
                    continue
                if len(nodes) >= node_limit:
                    limit_reached = True
                    continue
                nodes[next_symbol.symbol_id] = DependencyNode(
                    symbol=next_symbol,
                    depth=depth + 1,
                )
                queue.append((next_symbol, depth + 1, (*path, next_symbol.symbol_id)))

        ordered_nodes = tuple(
            sorted(
                nodes.values(),
                key=lambda node: (node.depth, _symbol_sort_key(node.symbol)),
            )
        )
        ordered_edges = tuple(sorted(edges, key=_edge_sort_key))
        return DependencyWalk(
            seed_symbol_id=seed.symbol_id,
            direction=direction,
            max_depth=max_depth,
            node_limit=node_limit,
            nodes=ordered_nodes,
            edges=ordered_edges,
            cycles=tuple(cycles),
            limit_reached=limit_reached,
        )


@dataclass(frozen=True, slots=True)
class DescribeService:
    """Produce DTOs deterministas para descripcion de componentes reverse engineering.

    El servicio resuelve el objeto, consume `DependencyWalkService` para
    dependencias y consumidores, y opcionalmente agrega contexto RAG o una
    sintesis LLM. El LLM no participa en la seleccion de relaciones.
    """

    repository: SQLiteReverseEngineeringRepository
    dependency_walk_service: DependencyWalkService
    search_service: Any | None = None
    context_builder: Any | None = None
    llm_provider: LlmProviderPort | None = None
    llm_timeout_seconds: float = 30.0

    def describe(self, request: DescribeRequest) -> ComponentDescription:
        """Describe un componente tecnico desde simbolos y relaciones de reverse engineering.

        Args:
            request: Parametros de resolucion, profundidad y uso opcional de
                RAG o LLM.

        Returns:
            DTO con identificacion, relaciones relevantes, evidencia,
            inferencias, puntos por confirmar y limitaciones.
        """
        resolution = _resolve_object(self.repository, request.target)
        if resolution.symbol is None:
            return _unresolved_description(resolution)

        outgoing = self.dependency_walk_service.walk(
            resolution.symbol.symbol_id,
            direction=DependencyDirection.OUTGOING,
            max_depth=request.depth,
        )
        incoming = self.dependency_walk_service.walk(
            resolution.symbol.symbol_id,
            direction=DependencyDirection.INCOMING,
            max_depth=request.depth,
        )
        evidence = _walk_evidence((*outgoing.edges, *incoming.edges))
        to_confirm = _to_confirm_from_edges((*outgoing.edges, *incoming.edges))
        limitations = _walk_limitations(outgoing) + _walk_limitations(incoming)
        rag_sources = _rag_sources(
            query=f"describe {resolution.symbol.normalized_name}",
            include_rag=request.include_rag,
            search_service=self.search_service,
            context_builder=self.context_builder,
        )
        responsibilities = _component_responsibilities(
            resolution.symbol,
            outgoing,
            incoming,
        )
        deterministic_summary = _describe_summary(
            resolution.symbol,
            outgoing,
            incoming,
        )
        summary, no_llm, llm_limitations = _maybe_llm_summary(
            deterministic_summary,
            request.no_llm,
            self.llm_provider,
            self.llm_timeout_seconds,
        )
        return ComponentDescription(
            resolution=resolution,
            outgoing=outgoing,
            incoming=incoming,
            responsibilities=responsibilities,
            evidence=evidence,
            inferences=_description_inferences(outgoing, incoming),
            to_confirm=to_confirm,
            limitations=(*limitations, *llm_limitations),
            rag_sources=rag_sources,
            summary=summary,
            no_llm=no_llm,
        )


@dataclass(frozen=True, slots=True)
class ImpactService:
    """Produce DTOs deterministas para analisis de impacto reverse engineering.

    El servicio usa exclusivamente `DependencyWalkService` para seleccionar
    nodos y aristas de impacto. RAG y LLM pueden sintetizar evidencia, pero no
    agregan ni remueven elementos del impacto.
    """

    repository: SQLiteReverseEngineeringRepository
    dependency_walk_service: DependencyWalkService
    search_service: Any | None = None
    context_builder: Any | None = None
    llm_provider: LlmProviderPort | None = None
    llm_timeout_seconds: float = 30.0

    def analyze(self, request: ImpactRequest) -> ImpactAnalysis:
        """Analiza impacto basico desde relaciones de reverse engineering persistidas.

        Args:
            request: Parametros de resolucion, direccion, profundidad, limites
                y uso opcional de RAG o LLM.

        Returns:
            DTO con consumidores, dependencias, indirectos, ciclos, riesgos,
            puntos por confirmar, evidencia y limitaciones.
        """
        resolution = _resolve_object(self.repository, request.target)
        if resolution.symbol is None:
            return _unresolved_impact(resolution)

        walk = self.dependency_walk_service.walk(
            resolution.symbol.symbol_id,
            direction=request.direction,
            max_depth=request.depth,
            node_limit=request.node_limit,
            filters=request.filters,
        )
        consumers = tuple(
            edge for edge in walk.edges if edge.direction == DependencyDirection.INCOMING
        )
        dependencies = tuple(
            edge for edge in walk.edges if edge.direction == DependencyDirection.OUTGOING
        )
        indirect = tuple(edge for edge in walk.edges if edge.depth > 1)
        cross_technology = _cross_technology_edges(walk.edges)
        risks = _impact_risks(walk)
        to_confirm = _to_confirm_from_edges(walk.edges)
        limitations = _walk_limitations(walk)
        rag_sources = _rag_sources(
            query=f"impact {resolution.symbol.normalized_name}",
            include_rag=request.include_rag,
            search_service=self.search_service,
            context_builder=self.context_builder,
        )
        deterministic_summary = _impact_summary(resolution.symbol, walk)
        summary, no_llm, llm_limitations = _maybe_llm_summary(
            deterministic_summary,
            request.no_llm,
            self.llm_provider,
            self.llm_timeout_seconds,
        )
        return ImpactAnalysis(
            resolution=resolution,
            walk=walk,
            consumers=consumers,
            dependencies=dependencies,
            indirect=indirect,
            cross_technology=cross_technology,
            risks=risks,
            to_confirm=to_confirm,
            evidence=_walk_evidence(walk.edges),
            limitations=(*limitations, *llm_limitations),
            rag_sources=rag_sources,
            summary=summary,
            no_llm=no_llm,
        )


def relation_from_reference(
    reference: TechnicalReference,
    symbols: tuple[TechnicalSymbol, ...],
) -> tuple[TechnicalRelation, tuple[RelationCandidate, ...]] | None:
    """Resuelve una referencia contra simbolos compatibles sin inventar destino.

    Args:
        reference: Referencia textual detectada por extractores reverse engineering.
        symbols: Catalogo vigente de simbolos candidatos.

    Returns:
        Una relacion con sus candidatos ambiguos, o `None` cuando no existe
        evidencia suficiente para crear una relacion trazable.

    Note:
        Las referencias `dynamic` y `external` conservan su propio estado y no
        entran al flujo de resolucion exacta contra simbolos internos.
    """
    if reference.resolution_status == ResolutionStatus.DYNAMIC:
        return (
            _relation(
                reference,
                classification=EvidenceClassification.TO_CONFIRM,
                resolution_status=ResolutionStatus.DYNAMIC,
                target_key=reference.normalized_target,
                notes="referencia dinamica conservada sin resolucion exacta",
            ),
            (),
        )
    if _is_external_reference(reference):
        return (
            _relation(
                reference,
                classification=EvidenceClassification.TO_CONFIRM,
                resolution_status=ResolutionStatus.EXTERNAL,
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
                classification=EvidenceClassification.DETECTED,
                resolution_status=ResolutionStatus.RESOLVED,
                target_symbol_id=target.symbol_id,
                target_key=reference.normalized_target,
            ),
            (),
        )

    relation = _relation(
        reference,
        classification=EvidenceClassification.TO_CONFIRM,
        resolution_status=ResolutionStatus.AMBIGUOUS,
        target_key=reference.normalized_target,
        notes="multiples candidatos compatibles",
    )
    return (
        relation,
        tuple(
            RelationCandidate(
                relation_id=relation.relation_id,
                candidate_symbol_id=symbol.symbol_id,
                rank=index + 1,
                reason="nombre y tipo compatibles",
            )
            for index, symbol in enumerate(candidates)
        ),
    )


def symbol_from_source(source: SymbolSource) -> TechnicalSymbol:
    """Convierte un chunk vigente en un simbolo reverse engineering normalizado.

    Args:
        source: Fuente de simbolo derivada de chunks vigentes.

    Returns:
        Simbolo reverse engineering con identidad determinista, tecnologia, contenedor y
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
    symbol_id = technical_symbol_id(
        normalized_name=normalized_name,
        symbol_type=symbol_type,
        technology=technology,
        container_name=normalized_container,
    )
    return TechnicalSymbol(
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
        """Adapta los conteos reverse engineering al contrato generico de progreso."""
        return {
            "new": self.symbols_detected,
            "update": self.references_detected,
            "unchanged": self.relations_resolved,
            "delete": self.relations_ambiguous,
            "errores": self.relations_unresolved,
        }


def _symbols_from_sources(
    sources: tuple[SymbolSource, ...],
    *,
    settings: Settings | None = None,
) -> tuple[TechnicalSymbol, ...]:
    """Construye simbolos unicos por identidad determinista."""
    by_id: dict[str, TechnicalSymbol] = {}
    for symbol in _iter_symbols_from_sources(sources, settings=settings):
        by_id.setdefault(symbol.symbol_id, symbol)
    return tuple(by_id.values())


def _iter_symbols_from_sources(
    sources: tuple[SymbolSource, ...],
    *,
    settings: Settings | None = None,
) -> tuple[TechnicalSymbol, ...]:
    """Construye simbolos preservando duplicados entre fuentes equivalentes."""
    symbols: list[TechnicalSymbol] = []
    configuration_sources_by_document: dict[int, list[SymbolSource]] = {}
    for source in sources:
        if _is_data_driven_configuration_source(source, settings):
            configuration_sources_by_document.setdefault(
                source.document_id,
                [],
            ).append(source)
            continue
        for symbol in _symbols_from_source(source, settings=settings):
            symbols.append(symbol)
    for document_sources in configuration_sources_by_document.values():
        for symbol in _configuration_symbols_from_document(
            tuple(document_sources),
            settings=settings,
        ):
            symbols.append(symbol)
    return tuple(symbols)


def _symbols_from_source(
    source: SymbolSource,
    *,
    settings: Settings | None,
) -> tuple[TechnicalSymbol, ...]:
    if not _is_data_driven_configuration_source(source, settings):
        return (symbol_from_source(source),)
    return _configuration_symbols_from_document((source,), settings=settings)


def _configuration_symbols_from_document(
    sources: tuple[SymbolSource, ...],
    *,
    settings: Settings | None,
) -> tuple[TechnicalSymbol, ...]:
    if settings is None or not sources:
        return ()
    document_source = sources[0]

    parse_result = parse_dml_configurations(
        document_source.document_content,
        settings.data_driven.configurations,
        max_statements_per_file=settings.data_driven.max_statements_per_file,
        max_literal_chars=settings.data_driven.max_literal_chars,
    )
    if not parse_result.records:
        return ()

    plan = build_configuration_symbols(
        parse_result.records,
        settings.data_driven.configurations,
    )
    return tuple(
        _with_source_trace(symbol, _evidence_source_for_symbol(symbol, sources))
        for symbol in plan.symbols
    )


def _is_data_driven_configuration_source(
    source: SymbolSource,
    settings: Settings | None,
) -> bool:
    return (
        settings is not None
        and source.artifact_kind == "configuration"
        and settings.data_driven.enabled
        and bool(settings.data_driven.configurations)
    )


def _evidence_source_for_symbol(
    symbol: TechnicalSymbol,
    sources: tuple[SymbolSource, ...],
) -> SymbolSource:
    if symbol.start_line is not None:
        for source in sources:
            if (
                source.start_line is not None
                and source.end_line is not None
                and source.start_line <= symbol.start_line <= source.end_line
            ):
                return source
    return sources[0]


def _with_source_trace(
    symbol: TechnicalSymbol,
    source: SymbolSource,
) -> TechnicalSymbol:
    metadata = {
        **symbol.metadata,
        "artifact_kind": source.artifact_kind,
        "relative_path": source.relative_path,
        "source_chunk_id": source.chunk_id,
    }
    return replace(
        symbol,
        file_id=source.file_id,
        document_id=source.document_id,
        chunk_id=source.chunk_id,
        start_line=symbol.start_line,
        end_line=symbol.end_line,
        metadata=metadata,
    )


def _resolve_object(
    repository: SQLiteReverseEngineeringRepository,
    request: ObjectRequest,
) -> ObjectResolution:
    """Resuelve un objeto reverse engineering por ID o nombre sin elegir candidatos ambiguos."""
    if request.symbol_id is not None:
        symbol = repository.get_symbol(request.symbol_id)
        if symbol is not None and symbol.status == SymbolStatus.ACTIVE:
            return ObjectResolution(query=request.query, symbol=symbol)
        return ObjectResolution(query=request.query, status="not_found")

    normalized_query = normalize_symbol_name(request.query)
    requested_type = request.symbol_type.lower() if request.symbol_type else None
    candidates = tuple(
        symbol
        for symbol in repository.active_symbols()
        if (
            symbol.normalized_name == normalized_query
            or symbol.original_name.lower() == request.query.lower()
        )
        and (requested_type is None or symbol.symbol_type == requested_type)
    )
    candidates = tuple(sorted(candidates, key=_symbol_sort_key))
    if not candidates:
        return ObjectResolution(query=request.query, status="not_found")
    if len(candidates) > 1:
        return ObjectResolution(
            query=request.query,
            candidates=candidates,
            status="ambiguous",
        )
    return ObjectResolution(query=request.query, symbol=candidates[0])


def _unresolved_description(resolution: ObjectResolution) -> ComponentDescription:
    """Construye una descripcion para objetos inexistentes o ambiguos."""
    if resolution.status == "ambiguous":
        summary = "Objeto ambiguo; se requiere seleccionar un candidato explicito."
        limitations = ("multiples simbolos compatibles",)
        to_confirm = tuple(symbol.normalized_name for symbol in resolution.candidates)
    else:
        summary = "Objeto no encontrado en el catalogo reverse engineering vigente."
        limitations = ("sin simbolo activo para la consulta",)
        to_confirm = ()
    return ComponentDescription(
        resolution=resolution,
        to_confirm=to_confirm,
        limitations=limitations,
        summary=summary,
        no_llm=True,
    )


def _unresolved_impact(resolution: ObjectResolution) -> ImpactAnalysis:
    """Construye un impacto para objetos inexistentes o ambiguos."""
    if resolution.status == "ambiguous":
        summary = "Impacto no calculado porque el objeto es ambiguo."
        limitations = ("multiples simbolos compatibles",)
        to_confirm = tuple(symbol.normalized_name for symbol in resolution.candidates)
    else:
        summary = "Impacto no calculado porque el objeto no existe en reverse engineering."
        limitations = ("sin simbolo activo para la consulta",)
        to_confirm = ()
    return ImpactAnalysis(
        resolution=resolution,
        to_confirm=to_confirm,
        limitations=limitations,
        summary=summary,
        no_llm=True,
    )


def _component_responsibilities(
    symbol: TechnicalSymbol,
    outgoing: DependencyWalk,
    incoming: DependencyWalk,
) -> tuple[str, ...]:
    """Deriva responsabilidades descriptivas desde relaciones visibles."""
    responsibilities = [
        f"{symbol.symbol_type} {symbol.normalized_name} en tecnologia {symbol.technology}",
    ]
    if outgoing.edges:
        responsibilities.append(f"declara {len(outgoing.edges)} dependencias salientes")
    if incoming.edges:
        responsibilities.append(f"tiene {len(incoming.edges)} consumidores detectados")
    return tuple(responsibilities)


def _description_inferences(
    outgoing: DependencyWalk,
    incoming: DependencyWalk,
) -> tuple[str, ...]:
    """Genera inferencias conservadoras para describe."""
    inferences = []
    if outgoing.edges:
        inferences.append("las dependencias salientes sugieren colaboraciones tecnicas")
    if incoming.edges:
        inferences.append("los consumidores detectados sugieren superficie de cambio")
    return tuple(inferences)


def _walk_evidence(edges: Iterable[DependencyEdge]) -> tuple[EvidenceItem, ...]:
    """Convierte aristas de dependencia en evidencia trazable."""
    return tuple(
        EvidenceItem(
            source="relation",
            detail=(
                f"{edge.relation.relation_type} "
                f"{edge.relation.resolution_status.value}"
            ),
            reference_id=edge.relation.reference_id,
            relation_id=edge.relation.relation_id,
            chunk_id=edge.relation.evidence_chunk_id,
        )
        for edge in edges
    )


def _to_confirm_from_edges(edges: Iterable[DependencyEdge]) -> tuple[str, ...]:
    """Extrae puntos por confirmar desde relaciones no resueltas exactamente."""
    values = []
    for edge in edges:
        if edge.relation.resolution_status in {
            ResolutionStatus.AMBIGUOUS,
            ResolutionStatus.UNRESOLVED,
            ResolutionStatus.DYNAMIC,
            ResolutionStatus.EXTERNAL,
        }:
            values.append(edge.target_key or edge.relation.target_key or "destino sin resolver")
    return tuple(dict.fromkeys(values))


def _walk_limitations(walk: DependencyWalk) -> tuple[str, ...]:
    """Resume limites y ciclos observados en un recorrido."""
    limitations = []
    if walk.limit_reached:
        limitations.append(f"limite de nodos alcanzado: {walk.node_limit}")
    if walk.cycles:
        limitations.append(f"ciclos detectados: {len(walk.cycles)}")
    if walk.max_depth == 0:
        limitations.append("profundidad 0: solo se incluye la semilla")
    return tuple(limitations)


def _cross_technology_edges(
    edges: Iterable[DependencyEdge],
) -> tuple[DependencyEdge, ...]:
    """Selecciona relaciones que cruzan tecnologias entre origen y destino."""
    return tuple(
        edge
        for edge in edges
        if edge.source_symbol is not None
        and edge.target_symbol is not None
        and edge.source_symbol.technology != edge.target_symbol.technology
    )


def _impact_risks(walk: DependencyWalk) -> tuple[str, ...]:
    """Deriva riesgos basicos desde el recorrido determinista."""
    risks = []
    if any(edge.direction == DependencyDirection.INCOMING for edge in walk.edges):
        risks.append("hay consumidores que podrian requerir verificacion")
    if _cross_technology_edges(walk.edges):
        risks.append("existen cruces entre tecnologias")
    if _to_confirm_from_edges(walk.edges):
        risks.append("hay relaciones por confirmar")
    if walk.cycles:
        risks.append("hay ciclos de dependencia")
    if walk.limit_reached:
        risks.append("el impacto puede estar truncado por limite de nodos")
    return tuple(risks)


def _describe_summary(
    symbol: TechnicalSymbol,
    outgoing: DependencyWalk,
    incoming: DependencyWalk,
) -> str:
    """Construye una sintesis determinista para describe."""
    return (
        f"{symbol.normalized_name} es un {symbol.symbol_type} {symbol.technology}. "
        f"Dependencias salientes: {len(outgoing.edges)}. "
        f"Consumidores: {len(incoming.edges)}."
    )


def _impact_summary(symbol: TechnicalSymbol, walk: DependencyWalk) -> str:
    """Construye una sintesis determinista para impact."""
    return (
        f"Impacto basico de {symbol.normalized_name}: "
        f"{len(walk.nodes)} nodos y {len(walk.edges)} relaciones evaluadas "
        f"hasta profundidad {walk.max_depth}."
    )


def _rag_sources(
    *,
    query: str,
    include_rag: bool,
    search_service: Any | None,
    context_builder: Any | None,
) -> tuple[str, ...]:
    """Recupera fuentes RAG complementarias sin seleccionar impacto."""
    if not include_rag or search_service is None or context_builder is None:
        return ()
    search = search_service.search(
        SearchRequest(
            query=query,
            mode=RetrievalMode.KEYWORD,
            filters=RetrievalFilter(),
            top_k=3,
            candidate_k=3,
            similarity_threshold=0.0,
        )
    )
    context = context_builder.build(search.candidates)
    return tuple(
        f"{source.source_id}:{source.candidate.chunk_id}"
        for source in context.sources
    )


def _maybe_llm_summary(
    deterministic_summary: str,
    no_llm: bool,
    llm_provider: LlmProviderPort | None,
    timeout_seconds: float,
) -> tuple[str, bool, tuple[str, ...]]:
    """Sintetiza con LLM opcional y conserva fallback determinista."""
    if no_llm or llm_provider is None:
        return deterministic_summary, True, ()
    prompt = (
        "Sintetiza en espanol sin agregar nodos ni relaciones no provistas.\n"
        f"Datos deterministas:\n{deterministic_summary}\n"
    )
    try:
        summary = llm_provider.generate(
            prompt=prompt,
            timeout_seconds=timeout_seconds,
        )
    except Exception:
        return deterministic_summary, True, ("LLM no disponible; salida deterministica",)
    if not summary.strip():
        return deterministic_summary, True, ("LLM sin contenido; salida deterministica",)
    return summary.strip(), False, ()


def _validate_dependency_limits(*, max_depth: int, node_limit: int) -> None:
    """Valida los limites contractuales del recorrido de dependencias."""
    if isinstance(max_depth, bool) or max_depth < 0 or max_depth > 5:
        raise ValueError("max_depth debe estar entre 0 y 5.")
    if isinstance(node_limit, bool) or node_limit <= 0:
        raise ValueError("node_limit debe ser mayor que 0.")


def _filter_relations(
    relations: Iterable[TechnicalRelation],
    filters: DependencyFilters,
    repository: SQLiteReverseEngineeringRepository,
) -> tuple[TechnicalRelation, ...]:
    """Aplica filtros de navegacion sobre relaciones activas adyacentes."""
    accepted = []
    for relation in relations:
        if (
            filters.relation_type is not None
            and relation.relation_type != filters.relation_type
        ):
            continue
        if (
            filters.resolution_status is not None
            and relation.resolution_status != filters.resolution_status
        ):
            continue
        if (
            filters.min_confidence is not None
            and _confidence_rank(relation.confidence)
            < _confidence_rank(filters.min_confidence)
        ):
            continue
        if filters.technology is not None and not _relation_has_technology(
            relation,
            filters.technology,
            repository,
        ):
            continue
        accepted.append(relation)
    return tuple(accepted)


def _relation_has_technology(
    relation: TechnicalRelation,
    technology: str,
    repository: SQLiteReverseEngineeringRepository,
) -> bool:
    """Comprueba tecnologia contra los simbolos disponibles de la relacion."""
    expected = technology.strip().lower()
    symbols = (
        _relation_symbol(relation.source_symbol_id, repository),
        _relation_symbol(relation.target_symbol_id, repository),
    )
    return any(symbol is not None and symbol.technology == expected for symbol in symbols)


def _confidence_rank(confidence: Confidence) -> int:
    """Convierte `Confidence` en orden numerico para filtros minimos."""
    return {
        Confidence.LOW: 1,
        Confidence.MEDIUM: 2,
        Confidence.HIGH: 3,
    }[confidence]


def _edge_direction(
    current_symbol_id: str,
    relation: TechnicalRelation,
) -> DependencyDirection:
    """Calcula direccion de una arista desde el simbolo que se esta expandiendo."""
    if (
        relation.target_symbol_id == current_symbol_id
        and relation.source_symbol_id != current_symbol_id
    ):
        return DependencyDirection.INCOMING
    return DependencyDirection.OUTGOING


def _relation_symbol(
    symbol_id: str | None,
    repository: SQLiteReverseEngineeringRepository,
) -> TechnicalSymbol | None:
    """Lee un simbolo activo asociado a una relacion, si existe."""
    if symbol_id is None:
        return None
    symbol = repository.get_symbol(symbol_id)
    if symbol is None or symbol.status != SymbolStatus.ACTIVE:
        return None
    return symbol


def _candidate_symbol_ids(
    relation: TechnicalRelation,
    repository: SQLiteReverseEngineeringRepository,
) -> tuple[str, ...]:
    """Lee candidatos visibles solo para relaciones ambiguas."""
    if relation.resolution_status != ResolutionStatus.AMBIGUOUS:
        return ()
    return tuple(
        candidate.candidate_symbol_id
        for candidate in repository.relation_candidates(relation.relation_id)
    )


def _next_symbol(
    current_symbol_id: str,
    relation: TechnicalRelation,
    source: TechnicalSymbol | None,
    target: TechnicalSymbol | None,
) -> TechnicalSymbol | None:
    """Devuelve el simbolo vecino que debe entrar a la cola BFS."""
    if relation.source_symbol_id == current_symbol_id:
        return target
    if relation.target_symbol_id == current_symbol_id:
        return source
    return None


def _symbol_sort_key(symbol: TechnicalSymbol) -> tuple[str, str, str, str]:
    """Clave canonica de orden para simbolos en resultados de dependencia."""
    return (
        symbol.technology,
        symbol.normalized_name,
        symbol.symbol_type,
        symbol.symbol_id,
    )


def _edge_sort_key(edge: DependencyEdge) -> tuple[int, str, str, str, str]:
    """Clave canonica de orden para aristas de dependencia."""
    neighbor = (
        edge.target_symbol
        if edge.direction == DependencyDirection.OUTGOING
        else edge.source_symbol
    )
    return (
        edge.depth,
        edge.relation.relation_type,
        neighbor.technology if neighbor is not None else "",
        neighbor.normalized_name if neighbor is not None else edge.target_key or "",
        edge.relation.relation_id,
    )


def _references_from_sources(
    sources: tuple[SymbolSource, ...],
    symbols: tuple[TechnicalSymbol, ...],
) -> tuple[TechnicalReference, ...]:
    """Extrae referencias unicas y las vincula con el simbolo fuente si existe."""
    source_symbol_by_chunk = {
        symbol.chunk_id: symbol.symbol_id
        for symbol in symbols
        if symbol.chunk_id is not None
    }
    by_id: dict[str, TechnicalReference] = {}
    for source in sources:
        references = _extract_references_from_source(
            source,
            source_symbol_id=source_symbol_by_chunk.get(source.chunk_id),
        )
        for reference in references:
            by_id.setdefault(reference.reference_id, reference)
    return tuple(by_id.values())


def _extract_references_from_source(
    source: SymbolSource,
    *,
    source_symbol_id: str | None,
) -> tuple[TechnicalReference, ...]:
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
    references: tuple[TechnicalReference, ...],
    symbols: tuple[TechnicalSymbol, ...],
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
        if relation.resolution_status == ResolutionStatus.RESOLVED:
            resolved += 1
        elif relation.resolution_status == ResolutionStatus.AMBIGUOUS:
            ambiguous += 1
        else:
            unresolved += 1
    return (resolved, ambiguous, unresolved)


def _analyze_stages() -> tuple[ProgressStage, ...]:
    """Define las etapas visibles del progreso de `barbarion analyze`."""
    return (
        ProgressStage("discover", "Seleccionando chunks", total=1),
        ProgressStage("extract", "Extrayendo reverse engineering", total=None),
        ProgressStage("persist", "Persistiendo reverse engineering", total=1),
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
        status=AnalysisRunStatus.INTERRUPTED,
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
    reference: TechnicalReference,
    *,
    classification: EvidenceClassification,
    resolution_status: ResolutionStatus,
    target_symbol_id: str | None = None,
    target_key: str | None = None,
    notes: str | None = None,
) -> TechnicalRelation:
    """Crea la relacion canonica asociada a una referencia detectada."""
    relation_id = technical_relation_id(
        reference_id=reference.reference_id,
        relation_type=_relation_type(reference),
        target_symbol_id=target_symbol_id,
        target_key=target_key,
    )
    return TechnicalRelation(
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
    reference: TechnicalReference,
    symbols: tuple[TechnicalSymbol, ...],
) -> tuple[TechnicalSymbol, ...]:
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


def _stable_symbols(symbols: list[TechnicalSymbol]) -> list[TechnicalSymbol]:
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
    reference: TechnicalReference,
    symbols: tuple[TechnicalSymbol, ...],
) -> TechnicalSymbol | None:
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


def _relation_type(reference: TechnicalReference) -> str:
    """Mapea el tipo de referencia al tipo canonico de relacion reverse engineering."""
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


def _is_external_reference(reference: TechnicalReference) -> bool:
    """Detecta referencias que apuntan fuera del catalogo interno."""
    scope = reference.metadata.get("scope")
    if isinstance(scope, str) and scope.lower() == "external":
        return True
    if "@" in reference.raw_text:
        return True
    return reference.normalized_target.startswith("external.")


def _technology(artifact_kind: str, metadata: dict[str, Any]) -> str:
    """Deriva la tecnologia reverse engineering a partir del tipo de artefacto y metadatos."""
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
    breadcrumb = metadata.get("breadcrumb")
    breadcrumb_container = (
        str(breadcrumb[0])
        if isinstance(breadcrumb, (list, tuple)) and len(breadcrumb) > 1
        else None
    )
    explicit = _first_text(
        metadata.get("parent_name"),
        metadata.get("package_name"),
        metadata.get("class_name"),
        breadcrumb_container,
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
