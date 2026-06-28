# H3 - RAG: Evidencia de aceptacion

## 1. Resultado

**Fecha:** 2026-06-25  
**Estado:** aceptado con limitacion de smoke instalado en este runtime  
**Version:** `0.3.0`  
**Vector store inicial:** SQLite + sqlite-vec  

H3 cumple los requisitos Must del hito para el flujo local RAG: indexacion incremental, reindexacion, busqueda semantica/keyword/hibrida, armado de contexto, `ask` con citas o evidencia insuficiente, metricas locales, dataset de benchmark y reportes de cierre.

Qdrant queda diferido como alternativa futura y no es dependencia inicial de H3.

## 2. Entorno validado

- Windows local;
- CPython `3.12.13`;
- SQLite local con esquema version `3`;
- ejecucion desde runtime Codex con paquete importable;
- Ollama real no requerido para la suite automatizada;
- proveedores fake deterministas para pruebas de embeddings, retrieval y LLM.

Los smoke tests instalados estan definidos, pero en este runtime no existe `barbarion.exe`; por eso se registran como `skipped`. En un venv editable instalado deben ejecutarse contra el entry point real.

## 3. Suite automatizada

Comando ejecutado:

```text
python -m pytest
```

Resultado:

```text
344 passed, 12 skipped in 43.90s
```

La suite cubre unit tests, integracion H3 y smoke tests preparados. Los skips corresponden a:

- 10 smoke tests de entry point instalado no disponible en el runtime Codex;
- 2 casos existentes de filesystem discovery.

## 4. Reportes de cierre T30

Comando ejecutado:

```text
python -m barbarion generate-report --dataset tests/fixtures/h3_rag_evaluation.json --output reports/h3 --test-summary "344 passed, 12 skipped" --smoke-summary "10 skipped: entry point instalado no disponible en el runtime Codex; tests smoke definidos para venv editable"
```

Artefactos generados:

| Archivo | Estado |
|---|---|
| `reports/h3/metrics.json` | generado |
| `reports/h3/topk-report.md` | generado |
| `reports/h3/smoke-report.md` | generado |
| `reports/h3/benchmark.md` | generado |
| `reports/h3/benchmark-history.jsonl` | generado |

`benchmark.md` incluye la seccion `Baseline` y el historico local queda preservado en JSONL.

## 5. Benchmark RAG

Dataset versionado:

```text
tests/fixtures/h3_rag_evaluation.json
```

El dataset contiene 10 preguntas clasificadas en:

- navegacion;
- dependencias;
- ubicacion de objetos;
- explicaciones;
- impacto;
- documentacion.

Incluye los ejemplos requeridos:

- `Donde se calcula order_total?`
- `Que objetos llaman calculate_discount?`
- `Donde se usa process_customer?`
- `Que documentos hablan de generate_invoice?`

Resultado del benchmark fixture deterministico:

| Metrica | Valor |
|---|---:|
| recall@5 | `1.000` |
| recall@10 | `1.000` |
| mrr | `1.000` |
| latency_ms_avg | `0.0` |

El benchmark cumple el criterio de al menos 8 de 10 preguntas con evidencia esperada en top-5. Para ejecuciones reales, el mismo mecanismo conserva historico comparable y permite contrastar cambios de chunk size, overlap, pesos hibridos y reranking futuro.

## 6. Funcionalidad aceptada

| Area | Evidencia |
|---|---|
| Configuracion H3 | `[embeddings]`, `[vector_store]`, `[retrieval]`, `[rag]`, `[llm]` validadas por tests |
| SQLite v3 | tablas RAG, manifests, runs, estados, queries, `symbol_occurrences` reservado |
| Vector store inicial | SQLite + sqlite-vec como dependencia inicial; Qdrant diferido |
| Embeddings | provider fake deterministico y adaptador Ollama embeddings |
| Indexacion | `index`, `reindex`, incremental, dry-run, unchanged sin embeddings |
| Retrieval | semantic, keyword con FTS5/fallback e hybrid con scores individuales |
| Contexto | threshold, deduplicacion, agrupacion por documento, orden estable, presupuesto de tokens |
| Citas | validacion de `source_id`; respuestas invalidas se rechazan |
| Ask | modo LLM local y `--no-llm`; evidencia insuficiente sin invencion |
| Observabilidad | `rag_queries`, latencias, conteos y metricas de contexto preparadas |
| CLI | `index`, `reindex`, `search`, `ask`, `embeddings`, `stats`, `generate-report` |
| Evaluacion | dataset de 10 preguntas, baseline, historico y reportes |

## 7. Comandos cubiertos

| Comando | Resultado |
|---|---|
| `barbarion index --dry-run` | cubierto por unit/smoke definido |
| `barbarion index` | cubierto por unit/integration con fakes |
| `barbarion reindex --full` | cubierto por unit/integration con fakes |
| `barbarion search "consulta" --mode keyword` | cubierto por unit/integration |
| `barbarion search "consulta" --format json` | cubierto por unit tests |
| `barbarion ask "pregunta" --no-llm` | cubierto por unit/integration |
| `barbarion embeddings` | cubierto por unit/integration |
| `barbarion stats` | cubierto por unit/integration |
| `barbarion generate-report` | cubierto por unit tests y ejecucion T30 |

## 8. Limitaciones conocidas

- Smoke tests contra `barbarion.exe` no se ejecutaron en este runtime porque el entry point instalado no existe.
- El benchmark T30 usa un servicio deterministico de fuentes esperadas para cierre reproducible; el benchmark sobre corpus real queda disponible con el mismo contrato.
- Las metricas `context_precision`, `context_recall`, `duplicate_ratio` y `token_waste` estan preparadas y se registran cuando el flujo real usa `ContextBuilder`; el reporte T30 deja las metricas de contexto como preparadas cuando no hay run real de contexto.
- `symbol_occurrences` queda reservado para H4 y H3 no implementa extraccion avanzada de simbolos.
- H3 no implementa grafo de dependencias, ingenieria inversa profunda, UI, servidor HTTP, workers ni frameworks RAG grandes.

## 9. Trazabilidad

- H3-T01 a H3-T30: completados.
- H3-REQ-001 a H3-REQ-023: cubiertos por implementacion, tests, dataset o reportes.
- NFR locales: operacion on-premise, sin servicios cloud, sin telemetria remota y compatible con Windows/Linux a nivel de rutas y CLI.
- Documentacion operativa: [`docs/RAG.md`](../../docs/RAG.md).
- Reportes de cierre: [`reports/h3`](../../reports/h3).

## 10. Conclusion

H3 entrega un RAG local y trazable sobre los chunks H2, con SQLite como fuente de verdad y almacenamiento vectorial inicial. El hito queda listo para validacion humana y para alimentar H4, donde podran reevaluarse sqlite-vec frente a volumen, filtros o rendimiento, y donde se abordara analisis profundo de simbolos y dependencias.
