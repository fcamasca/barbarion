# Aceptación H3.3 - Graph-Aware Retrieval

## Estado

**Estado técnico y funcional:** ACCEPTED.

**Estado de H3.3-T08:** completada por confirmación explícita del usuario el
2026-08-08.

H3.3 queda aceptada como una ampliación conservadora y provider-agnostic del
retrieval RAG. La aceptación no cambia el default: `graph_aware_enabled=false`
permanece vigente y la activación exige límites y tipos de relación explícitos.

## Versión y entorno

- Fecha: 2026-08-08.
- Sistema: Windows.
- Rama: `feature/h3.3-GraphAwareRetrieval`.
- Revisión base observada: `c5bcf2d` más los cambios locales de H3.3 y este
  cierre documental.
- Barbarion: `0.6.0`.
- Python: `3.12.10`.
- pytest: `8.4.2`.

No se modificó configuración ni se repitió la aceptación manual durante este
cierre. Las ejecuciones reales descritas abajo fueron realizadas y confirmadas
por el usuario durante T08.

## Alcance aceptado

H3.3 reutiliza el retrieval H3, las relaciones activas H4/H4.1 y la selección
H3.1. La expansión:

- usa seeds y contratos de dominio deterministas;
- consulta relaciones reales `calls`, `uses`, `opens`, `references`,
  `parent_of` y `precedes` con dirección y filtros explícitos;
- excluye relaciones no activas, no resueltas, ambiguas, dinámicas o externas;
- limita profundidad, seeds, vecinos y candidatos;
- controla ciclos y deduplicación;
- resuelve símbolos a chunks citables vigentes;
- solo admite `evidence_chunk_id` cuando el chunk vigente demuestra el vínculo;
- conserva todas las procedencias al fusionar candidatos;
- entrega el conjunto fusionado a H3.1 y al `ContextBuilder` existente.

No se introdujo una base de grafos, un segundo RAG, un reranker, clasificación
LLM de preguntas ni citas directas sobre relaciones.

## Benchmark T07

El benchmark sintético publicable `h33-graph-aware-v1` compara cinco políticas
sobre seis casos, con 30 repeticiones por caso. Sus artefactos son:

- `tests/fixtures/h33_graph_benchmark.json`;
- `tests/support/h33_graph_benchmark.py`;
- `reports/h33/benchmark.json`;
- `reports/h33/benchmark.md`.

| Política | Límites depth/seeds/vecinos/candidatos | Recall multi | Recall simple | Ruido | Tokens contexto promedio |
|---|---|---:|---:|---:|---:|
| baseline | desactivado | 0.383 | 1.000 | 0.000 | 42.000 |
| shallow | 1/2/3/4 | 0.867 | 1.000 | 0.000 | 148.833 |
| balanced | 2/4/6/8 | 1.000 | 1.000 | 0.150 | 226.500 |
| wide | 2/8/12/16 | 1.000 | 1.000 | 0.150 | 226.500 |
| deep_wide | 3/8/20/30 | 1.000 | 1.000 | 0.150 | 226.500 |

Se acepta `balanced` como recomendación: profundidad 2, 4 seeds, 6 vecinos
por seed y 8 candidatos. Los valores permanecen declaración explícita y opt-in;
no se convierten en defaults implícitos. Las políticas más amplias no aportaron
cobertura adicional.

## Aceptación manual multi-proveedor

La consulta real multi-componente fue validada con Ollama Cloud y Anthropic.
Los detalles del corpus, símbolos, relaciones, rutas y contenido permanecen
fuera del repositorio. La evidencia agregada inicial mostró:

```text
graph_candidates=3
graph_selected_after_h31=2
graph_selected_h31_ranks=[8,9]
graph_selected_in_context=0
graph_omitted_by_budget=2
graph_omitted_by_budget_ranks=[8,9]
```

Esto confirmó que la expansión encontraba evidencia pertinente y H3.1 la
aceptaba, pero el presupuesto de entrada dejaba su cobertura final en cero.
No se aumentó el presupuesto ni se alteraron scores, ranking o `top_k`.

Se incorporó un fallback conservador de una sola sustitución. Solo se activa
cuando H3.3 está habilitado, H3.1 seleccionó evidencia graph, ninguna fuente
graph llegó al contexto y al menos una fue omitida por presupuesto. Sustituye
la fuente presente de peor rango por el candidato graph omitido de mejor rango
y acepta la alternativa solo si conserva el número de fuentes, dedupe,
materialización y el mismo presupuesto.

La ejecución real confirmó:

```text
graph_budget_fallback_triggered=true
graph_budget_fallback_applied=true
graph_budget_fallback_candidate_rank=8
graph_budget_fallback_replaced_rank=3
graph_selected_in_context_after_fallback=1
```

La respuesta mejoró y una fuente graph-aware llegó al prompt. La reconciliación
final conserva como universo todos los candidatos seleccionados por H3.1:

```text
graph_selected_h31_ranks=[8,9]
graph_selected_in_context_ranks=[8]
graph_omitted_by_budget_ranks=[9]
graph_selected_in_context=1
graph_omitted_by_budget=1
```

El candidato sustituido se contabiliza como `budget_fallback` y los demás
candidatos ausentes conservan su razón original. `context_omitted_candidates`
ya no se reduce artificialmente al subconjunto usado para reconstruir el
contexto alternativo.

## Observabilidad y privacidad

`ask --debug` expone un bloque `H3.3 GRAPH-AWARE RETRIEVAL` con conteos,
límites, tiempos, rangos y resultados agregados del fallback. La CLI no imprime
decisiones individuales ni `chunk_id`, `symbol_id`, `relation_id`, caminos,
nombres de símbolos, contenido, snippets, pregunta o prompt.

La procedencia `candidate_origin_kinds` conserva de forma determinista todos
los orígenes acumulados, incluidos `structured_symbol`, `graph_expansion` y
`h3_chunk`. Esa metadata categórica permite reconciliar selección H3.1 y
presupuesto sin revelar evidencia.

No se persisten preguntas, prompts, respuestas ni contenido nuevo. H3.3 no
agrega egress ni modifica el contrato de privacidad de H3/H3.1. `--no-llm`
ejecuta retrieval, expansión y contexto sin invocar un proveedor generativo.

## Pruebas automatizadas

La batería directamente afectada por retrieval, selección, contexto, fallback,
CLI y privacidad terminó en:

```text
165 passed in 39.89s
```

Incluye ciclos, límites, dedupe, resolución citable, provenance tras fusiones,
ranks globales, omisiones por presupuesto, sustitución determinista, rechazo de
alternativas que pierden fuentes, presupuesto invariable, graph desactivado y
ausencia de datos sensibles en debug.

La suite completa del workspace se ejecutó durante el cierre:

```text
1097 passed, 14 skipped, 1 failed in 118.70s
```

El único fallo es de reproducibilidad byte a byte en snapshots JSON históricos
de H3.1 (`test_committed_reports_are_exactly_reproducible`). Los reportes
Markdown y `t09-observability` coinciden; los JSON de baseline, redundancia y
relevance-first difieren por la nueva metadata categórica segura agregada a las
decisiones. No hubo fallo funcional H3.3. Por instrucción de no ampliar alcance
ni realizar más cambios productivos, este cierre no regenera artefactos H3.1.

`git diff --check` finalizó correctamente; solo emitió avisos informativos por
la política local LF/CRLF.

## Compatibilidad

- H3.3 permanece deshabilitado por defecto.
- Con graph desactivado se conserva el pipeline anterior.
- Ollama y Anthropic reciben el mismo contexto lógico antes de generación.
- `input_token_budget_est`, `max_chunk_tokens`, scores, ranking y `top_k` no
  cambian por configuración implícita.
- El fallback realiza como máximo una sustitución y nunca reserva cuotas fijas.
- Si la alternativa no cumple sus invariantes, se conserva exactamente el
  contexto original.

## Limitaciones y diferimientos

- No existe una relación package a miembros persistida y navegable demostrada;
  describir un package completo queda diferido hasta que H4 produzca esa
  relación o una equivalente.
- El benchmark es sintético y pequeño; los límites recomendados deben
  revalidarse antes de promover H3.3 a default.
- Profundidad 2 no implica cobertura completa para cualquier grafo legacy.
- Las relaciones ambiguas, dinámicas, externas y no resueltas no se expanden.
- H3.3 no corrige ausencia de chunks citables ni inventa evidencia para cubrirla.
- Queda pendiente regenerar los snapshots JSON H3.1 en un cambio documental o
  de artefactos separado, si se desea restablecer reproducibilidad byte a byte.

## Decisión final

**H3.3: ACCEPTED.**

T01-T08 quedan completadas. H3.3 demuestra mejora de cobertura
multi-componente, conserva grounding y privacidad, y evita que el presupuesto
neutralice por completo evidencia graph ya aceptada por H3.1 mediante una
sustitución única y conservadora.

Decisión de despliegue:

- default: deshabilitado;
- configuración recomendada opt-in: `balanced` (`2/4/6/8`);
- tipos de relación: declaración explícita;
- promoción a default: diferida hasta validación adicional en corpus
  independientes.
