# H4.2 — Patrones técnicos: diseño

## 1. Arquitectura vigente relevante

H2 ingiere archivos, documentos y chunks. H4 persiste en SQLite `analysis_runs`,
`symbols`, `symbol_references`, `relations` y `relation_candidates`. El dominio
expone `TechnicalSymbol`, `TechnicalReference`, `TechnicalRelation`, estados
`active/stale/deleted`, resolución `resolved/ambiguous/unresolved/external/dynamic`,
confianza y clasificación de evidencia. Las relaciones son `source → target`
cuando están resueltas; la dirección de consulta se calcula. H4 ofrece
inventario, describe, impacto y recorridos BFS con ciclos, límites y hojas no
resueltas. H4.1 reutiliza estas tablas para configuraciones y símbolos hijos.

La evidencia puede apuntar a `file_id`, `chunk_id`, líneas, `reference_id` y
`relation_id`. El código ya contempla `parent_symbol_id`, pero H3.3 documenta
que no se ha demostrado una relación completa y navegable `package → member`.

## 2. Inventario resumido y frontera con H3.3

### Resultado T01 — capacidad real verificada

| Área | Capacidad confirmada |
|---|---|
| Símbolos | `TechnicalSymbol` conserva ID determinista, nombres original/normalizado, `symbol_type`, tecnología, extracción, confianza, file/document/chunk, líneas, metadata, estado, `container_name`, `parent_symbol_id` opcional y `signature`. |
| Tipos de símbolo | No hay enum cerrado: son strings de los extractores. H4.1 añade `configuration_entity`, `configuration_record`, `configuration_variable` y `configuration_parameter`; puede existir `unknown`. Los valores deben inventariarse desde la base. |
| Relaciones | `TechnicalRelation` conserva origen, destino o `target_key`, tipo, clasificación, resolución, confianza, estado, referencia, archivo, chunk, líneas y notas. |
| Tipos de relación | El catálogo de navegación/configuración es `calls`, `uses`, `opens`, `references`, `parent_of`, `precedes`; no se asumen otros tipos. |
| Dirección | Persistencia conceptual `source → target`; el repositorio calcula `incoming`, `outgoing` o `both`. No hay columna de dirección independiente. |
| Resolución | `resolved`, `ambiguous`, `unresolved`, `external`, `dynamic`; las dinámicas exigen `por_confirmar`; candidatos alternativos se persisten. |
| Estados | Símbolos: `active`, `stale`, `deleted`, `ambiguous`. Relaciones: `active`, `stale`, `deleted`. |
| Confianza/origen | Confianza `high`, `medium`, `low`; referencias/relaciones conservan método de detección y clasificación de evidencia. |
| Trazabilidad | Enlaces a file/document/chunk, referencia, líneas y texto detectado cuando existen. Una métrica puede carecer de cita textual si no hay chunk vigente. |
| Llamadas/uso/acceso | `calls`, `uses`, `opens` y `references` representan relaciones técnicas; no prueban runtime ni impacto de negocio. |
| Jerarquía | `parent_symbol_id` y `parent_of` se usan en H4.1. En Oracle/PowerBuilder no se demuestra una navegación persistida completa `package → member`; `container_name`/metadata no se trata como arista equivalente. |
| Navegación | Inventario, resolución, `describe`, `impact` y BFS H4 con profundidad, límites, ciclos y hojas no resueltas; H3.3 reutiliza la navegación en query-time. |
| Persistencia/observabilidad | SQLite persiste `analysis_runs`, símbolos, referencias, relaciones y candidatos; `stats` agrega conteos por estado/run. No existe persistencia de patrones. |
| Limitaciones | Parsers heurísticos, relaciones dinámicas/ambiguas/no resueltas, cobertura parcial, ausencia demostrada de package→member y falta de semántica de capas/módulos/criticidad. |

Este inventario confirma que H4.2 puede calcular conectividad estructural sobre
relaciones elegibles, pero no autoriza inferencias funcionales, arquitectónicas
ni de criticidad.

Tipos observables se obtendrán de los datos, no de una lista inventada: Oracle y
PowerBuilder producen símbolos técnicos; H4.1 añade `configuration_entity`,
`configuration_record` y símbolos derivados. Los relation types observados por
los contratos actuales incluyen `calls`, `uses`, `opens`, `references`,
`parent_of` y `precedes`; T01 debe confirmar los valores presentes en la base.

H3.3 hace BFS acotado en tiempo de consulta para obtener chunks candidatos y
entrega el resultado a H3.1. H4.2 hace análisis offline/on-demand del conjunto
estructural. Comparte repositorios y tipos; no comparte un segundo RAG, no
recalcula scores H3 ni altera el fallback graph-aware.

## 3. Matriz de viabilidad

| Candidato | Evidencia real | Detección determinista | Faltante | Decisión inicial |
|---|---|---|---|---|
| Componentes reutilizados | Relaciones entrantes/salientes, tipos, estados, fuentes y conteos de inventario | Sí, como alta reutilización estructural por política explícita | Baseline y política de elegibilidad | Incluir acotado |
| Dependencias críticas | Grafo dirigido y recorridos/ciclos | No; centralidad estructural no demuestra criticidad | Flujo, impacto y criterio funcional validado | Diferir `critical_dependency` |
| Hotspots | Grados y frecuencia de relaciones | Parcial; “hotspot” es ambiguo | Serie temporal/cambio, carga o definición aprobada | Diferir como nombre general |
| Módulos | Nombres, tipos y relaciones | No demuestra agrupación funcional | Clustering/semántica y validación | Diferir |
| Capas | Tecnología y direcciones | No demuestra arquitectura por capas | Reglas arquitectónicas declaradas | Diferir |
| Código duplicado | Chunks y fuentes | No con el contrato de patrones actual | Comparación normalizada/AST y política de equivalencia | Diferir |

## 4. Flujo conceptual

```text
SQLite H4/H4.1
  → inventario y política
  → selección de símbolos/relaciones elegibles
  → métricas estructurales deterministas
  → detección de patrones incluidos
  → explicación + provenance
  → JSON/Markdown/CLI existente o nueva superficie aprobada
```

## 5. Resultado T02 — semántica y política

T02 define la cadena contractual sin calibrar valores:

```text
relaciones elegibles
  → métricas observables
  → regla/política
  → patrón estructural
```

Los umbrales numéricos y la decisión de implementación definitiva quedan para
la baseline de T07.

### `component_reuse`

```yaml
pattern_type: component_reuse
meaning: "El componente tiene relaciones estructurales desde múltiples símbolos origen independientes."
eligible_relations:
  - status: active
  - resolution_status: resolved
  - source_symbol_id: presente
  - target_symbol_id: presente y activo
  - relation_type: observado por H4 y permitido por la política
metrics:
  - inbound_relation_count
  - distinct_source_symbols
  - distinct_source_files
  - relation_type_distribution
  - repeated_relation_count
source_definition: "symbol_id distinto; el archivo es una métrica secundaria, no independencia adicional."
excluded_cases:
  - relaciones stale/deleted
  - destinos ambiguos, unresolved, external o dynamic
  - relaciones sin origen o destino estructural resoluble
  - repeticiones del mismo source_symbol_id contadas como nuevos reutilizadores
insufficient_evidence_when:
  - no hay relaciones elegibles
  - la identidad de los símbolos origen no es resoluble
  - la cobertura de relaciones no permite distinguir origen independiente de repetición
interpretations_not_allowed:
  - importancia funcional
  - criticidad
  - impacto de negocio
  - calidad arquitectónica
threshold_strategy: "pendiente de baseline T07"
```

La unidad primaria de independencia es `source_symbol_id`. `distinct_source_files`
se conserva para explicar distribución y detectar concentración, pero no convierte
varias referencias del mismo símbolo en varios reutilizadores. La política debe
definir si los relation types se agrupan o separan; no se mezclan silenciosamente.

### `structural_centrality`

T02 acota este candidato a **conectividad local por vecinos distintos**, no a una
teoría general de centralidad. No incluye participación en ciclos, conexión entre
grupos, betweenness, caminos globales ni flujo.

```yaml
pattern_type: structural_centrality
meaning: "El componente ocupa una posición localmente conectada con múltiples vecinos estructurales distintos."
eligible_relations:
  - status: active
  - resolution_status: resolved
  - source_symbol_id: presente
  - target_symbol_id: presente y activo
  - relation_type: observado por H4 y permitido por la política
metrics:
  - distinct_inbound_neighbors
  - distinct_outbound_neighbors
  - distinct_total_neighbors
  - inbound_relation_count
  - outbound_relation_count
  - relation_type_distribution
  - cycle_membership: "solo diagnóstico, no criterio de detección en T02"
neighbor_definition: "symbol_id distinto conectado por una relación elegible; se deduplica por dirección efectiva."
excluded_cases:
  - relaciones stale/deleted
  - destinos/orígenes ambiguos, unresolved, external o dynamic
  - ciclos usados como prueba suficiente de centralidad
  - inferencia de bridging o centralidad global
insufficient_evidence_when:
  - no hay vecinos resolubles
  - solo existen relaciones repetidas sin vecinos adicionales
  - la cobertura parcial impide comparar la conectividad observada con el universo analizado
interpretations_not_allowed:
  - dependencia crítica
  - importancia funcional
  - impacto de negocio
  - cuello de botella
  - pertenencia a capa o módulo
threshold_strategy: "pendiente de baseline T07"
```

La decisión de T02 es tratarlo como candidato a patrón estructural local, no como
familia abierta de métricas. T07 podrá confirmar esta definición, calibrarla,
limitarla a una métrica o diferirla si la cobertura no es suficiente.

### Contrato de métricas

Las métricas son hechos calculados y no patrones. Por ejemplo,
`inbound_relation_count=17` y `distinct_source_symbols=12` no implican por sí
solos `component_reuse`; la regla/política y la baseline son necesarias. Ninguna
métrica se presenta como cita textual ni como interpretación funcional.

## 6. Modelo lógico mínimo

No se propone tabla nueva todavía. Un resultado derivado puede ser un DTO con:

```text
PatternResult
  pattern_type
  subject_symbol_id(s)
  status: detected | insufficient_evidence | ambiguous
  metrics: mapa numérico estable
  relation_ids
  symbol_ids
  evidence: file_id/chunk_id/reference_id cuando existan
  policy_id/configuration
  limitations
```

La persistencia solo se considerará si el benchmark muestra que el cálculo
repetido es costoso o que se necesita comparar corridas. En ese caso se evaluará
cache derivada invalidable por `analysis_run`/fingerprint; nunca se crea una
graph database.

## 6. Algoritmos candidatos

- **Reutilización estructural:** para cada símbolo activo, contar relaciones
  entrantes elegibles, fuentes distintas y distribución por `relation_type`;
  reportar métrica, no “importancia”.
- **Centralidad estructural condicionada:** calcular grados de entrada/salida y,
  si T01 lo justifica, componentes/ciclos o conteo de caminos acotado reutilizando
  BFS H4. No usar “crítico” sin regla aprobada.
- Todos los conteos excluyen por política relaciones stale/deleted; ambiguous,
  dynamic y unresolved se cuentan como limitación, no como dependencia resuelta.
- Ordenar por tipo, nombre normalizado e ID estable. Ciclos no deben bloquear.

No se fijan umbrales en esta spec. T02 define si el mecanismo será absoluto,
percentil derivado del corpus o ranking descriptivo sin umbral; T07 construye la
baseline y solo entonces puede calibrarse o confirmarse un valor. La centralidad
estructural nunca se etiqueta como dependencia crítica.

## 7. Explicabilidad y provenance

La jerarquía contractual es:

```text
EVIDENCIA → RELACIÓN → MÉTRICA → PATRÓN ESTRUCTURAL → INTERPRETACIÓN
```

H4.2 llega como máximo a `PATRÓN ESTRUCTURAL`. La interpretación funcional o
arquitectónica fuerte pertenece a evoluciones posteriores. Por tanto,
`in_degree=17` y `distinct_sources=12` son métricas, `high_structural_reuse` es
un patrón sujeto a una política, y `critical_component` es una interpretación
no demostrada.

La provenance concreta será `archivo/chunk → referencia → relación → métrica →
patrón`. Cada explicación debe mostrar la política, conteos, tipos de relación,
sujetos, IDs y evidencia disponible. Si solo existe una métrica sin chunk citable, se
declara “evidencia estructural sin cita textual”; no se inventa una cita.

## 8. Ambigüedad, incompletitud y privacidad

Un resultado puede ser `insufficient_evidence` o `ambiguous`; nunca se fuerza un
destino. Relaciones no resueltas, stale, duplicadas o faltantes se reportan como
limitaciones. El análisis es local y no agrega entradas a `rag_queries`; logs
solo contienen categorías, conteos, tiempos e IDs seguros según contratos
vigentes.

## 9. CLI, observabilidad y compatibilidad

T01 inspeccionará `analyze`, `inventory`, `describe`, `impact` y `stats`. La
opción preferida es extender una salida existente; un comando `patterns` solo se
creará con caso de uso y aprobación. Métricas mínimas: símbolos elegibles,
relaciones por estado/tipo, sujetos evaluados, patrones detectados, insuficiencia,
ciclos, límites, duración y política. H3.3 conserva `enabled=false`, límites,
scores, ranking, presupuesto y fallback actuales.

## 10. Alternativas y decisiones

Se descartan NetworkX obligatorio, Neo4j, un segundo RAG, embeddings nuevos,
LLM como clasificador, clustering semántico y microservicios: no son necesarios
para métricas pequeñas y explicables. `component_reuse` y
`structural_centrality` son candidatos iniciales para T01; su inclusión
definitiva, e incluso si se incluye uno solo, depende del inventario y baseline.
No se asume que H4.2 v1 tendrá dos patrones.

## 11. Riesgos

La cobertura de relaciones puede ser parcial; `package → member` no está
demostrada; nombres comunes generan ambigüedad; la centralidad puede interpretarse
erróneamente como impacto funcional; y los umbrales pueden sobreajustar un
corpus. Por eso T01 y el benchmark son puertas de alcance.

## 12. Decisión T01

Pasan a T02 como candidatos condicionados `component_reuse` y
`structural_centrality`. `critical_dependency` queda diferido: el grafo actual
no demuestra criticidad. Capas, módulos, duplicación y hotspot permanecen
diferidos.
