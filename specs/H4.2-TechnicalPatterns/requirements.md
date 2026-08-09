# H4.2 — Patrones técnicos: requisitos

## 1. Problema y contexto

H4 ya construye conocimiento estructurado local sobre símbolos, referencias,
relaciones y dependencias. H3.3 usa ese conocimiento para recuperar evidencia
relacionada durante una consulta; todavía no existe una capacidad separada que
analice el conjunto acumulado y reporte patrones estructurales reproducibles.

La hipótesis inicial se valida y se acota así:

> H4.2 debe inferir, de forma determinista y trazable, patrones estructurales
> observables a partir de símbolos y relaciones activas que H4/H4.1 ya conocen.

Esto no demuestra semántica funcional, criticidad de negocio, pertenencia a un
módulo o una capa arquitectónica.

## 2. Objetivo y pregunta

H4.2 responderá: **¿qué patrones estructurales pueden inferirse de forma
determinista y trazable a partir de los componentes y relaciones conocidas?**

El primer incremento debe producir hechos, métricas, patrones, evidencia y
limitaciones separadamente, para que un patrón nunca se presente como hecho de
negocio.

## 3. Alcance

- Inventariar la capacidad real antes de implementar detectores.
- Definir y detectar patrones basados en conectividad estructural observada.
- Considerar como candidatos `component_reuse` y `structural_centrality`, si
  T01 confirma evidencia suficiente.
- Emitir explicación, métricas, IDs y provenance hacia símbolos, relaciones y
  evidencia fuente cuando exista.
- Usar SQLite y los repositorios/navegadores H4 existentes, sin segundo grafo.
- Probar con fixtures sintéticos, benchmark determinista y corpus legacy
  autorizado cuyos resultados públicos sean agregados.

## 4. No alcance

`critical_dependency` queda explícitamente diferido: centralidad estructural no
demuestra criticidad. H4.2 no convertirá conectividad, impacto o número de
callers en una afirmación funcional. No se incluyen inicialmente capas, módulos,
código duplicado ni hotspots como
afirmaciones generales. Se difieren porque requieren clasificación semántica,
comparación de contenido o una definición observable y baseline que el estado
actual no demuestra. Tampoco se implementan LLM detectors, nuevos embeddings,
otra RAG, graph database, API, UI o egress.

## 5. Requisitos funcionales

| ID | Requisito |
|---|---|
| H42-RF-001 | La primera tarea será un inventario versionado de tipos de símbolo, tipos/dirección/estado de relación, resolución, confianza, origen, trazabilidad, navegación y limitaciones reales. |
| H42-RF-002 | El inventario incluirá explícitamente que no está demostrada la relación navegable completa `package → member`. |
| H42-RF-003 | La matriz de viabilidad de los seis candidatos de `EVOLUTION.md` determinará inclusión, definición acotada o diferimiento; no todos son requisitos. |
| H42-RF-004 | Todo detector usará solo símbolos y relaciones elegibles según estado, resolución, confianza y política declarada. |
| H42-RF-005 | Cada patrón conservará componentes afectados, métricas, relaciones contribuyentes, IDs de evidencia y limitaciones. |
| H42-RF-006 | La detección será determinista: misma base y política producen el mismo resultado y orden canónico, independientemente del LLM. |
| H42-RF-007 | No se llamará al LLM para detectar; `--no-llm` permitirá ejecutar e inspeccionar el análisis determinista. |
| H42-RF-008 | Los umbrales, si son necesarios, serán configurables y justificados por benchmark/baseline; no se fijarán por intuición. |
| H42-RF-009 | H4.2 reutilizará la navegación estructural H4 y no alterará la expansión, ranking, presupuesto ni defaults de H3/H3.1/H3.3. |
| H42-RF-010 | La integración CLI extenderá una superficie existente solo si T01 demuestra que no rompe contratos; un comando nuevo requiere caso de uso aprobado. |
| H42-RF-011 | El benchmark cubrirá positivos, negativos, ambigüedad, ciclos, faltantes, aislados, duplicados, stale y cambios incrementales aplicables. |
| H42-RF-012 | La última tarea de implementación generará `acceptance.md`; esta spec no lo crea. |

## 6. Requisitos no funcionales

| ID | Requisito |
|---|---|
| H42-RNF-001 | Resultados reproducibles, ordenados y explicables. |
| H42-RNF-002 | SQLite continúa siendo la fuente local; no se introduce persistencia derivada sin necesidad demostrada. |
| H42-RNF-003 | No se agrega egress ni se persisten preguntas, prompts, respuestas o contenido sensible nuevo. |
| H42-RNF-004 | Fixtures, benchmarks y reportes versionados son sintéticos y publicables. |
| H42-RNF-005 | Compatible con H2, H3, H3.1, H3.2, H3.3, H4, H4.1, H5, Ollama y Anthropic. |
| H42-RNF-006 | Mantiene monolito modular, Python 3.12, SQLite y ejecución local en `--no-llm`. |

## 7. Criterios de aceptación de la spec/implementación

- Existe inventario real y matriz de viabilidad revisados.
- Cada patrón incluido tiene definición observable, política de elegibilidad,
  algoritmo, evidencia y casos negativos.
- La repetición del benchmark produce el mismo resultado byte a byte o JSON
  canónico.
- No se reportan patrones sin relaciones/símbolos inspeccionables.
- La suite H3/H4 existente no presenta regresiones y H3.3 sigue opt-in.
- La validación humana sobre corpus autorizado juzga utilidad y falsos positivos;
  solo se publican agregados.

## 8. Riesgos, dependencias y diferimientos

Dependencias: contratos H4/H4.1, SQLite, navegación de relaciones, fixtures
H3.3 y baseline de métricas. Riesgos: relaciones incompletas, stale, nombres
ambiguos, confundir conectividad con criticidad y umbrales inestables.

Quedan diferidos capas, módulos, duplicación, hotspot como categoría no acotada,
criticidad funcional, package completo y cualquier persistencia nueva hasta que
T01 y el benchmark los justifiquen.

## 9. Supuestos y aprobación humana pendiente

Supuestos: los repositorios H4 pueden consultarse en modo solo lectura; las
relaciones activas son la base inicial; la evidencia de chunk puede faltar.

Requieren aprobación antes de implementar: vocabulario final de patrones,
política de confianza/estado, si se expone mediante `stats`, `inventory` o un
comando nuevo, y cualquier umbral o persistencia derivada.
