# H3.1 — Contexto RAG medible y selección relevance-first

H3.1 resolvió un problema de control y calidad del input RAG: Barbarion ahora
puede explicar cuánto ocupa cada componente del prompt, presupuestar el input
completo de forma opt-in y comparar políticas de selección sin confundir una
estimación local con el consumo informado por el proveedor.

El hallazgo principal no fue el overlap. El benchmark mostró que el orden de
selección podía dejar fuera una fuente más relevante —el caso
`relevant-at-six`— antes de agotar los candidatos. `optimized_v1` corrige ese
caso comparando primero la relevancia global. En cambio, la redundancia medida
fue marginal: un duplicado exacto ya omitido y `27` caracteres, aproximadamente
`7` tokens estimados, de overlap enviado (`0.277%` del prompt observado).

## Políticas disponibles

| Política | Selección | Presupuesto | Estado |
|---|---|---|---|
| `baseline_v1` | Conserva la precedencia y el comportamiento legado | `context_token_budget` o, de forma opt-in, presupuesto del input completo | Default vigente |
| `optimized_v1` | Ordena candidatos globalmente por score, deduplica exactamente y desempata por `chunk_id` | Requiere `input_token_budget_est` | Candidata calificada; todavía no es default |

`optimized_v1` no incorpora reranker, diversidad semántica ni inferencia de
hechos. La precedencia estructurada y el orden documental se conservan para la
presentación de las fuentes seleccionadas, no para desplazar evidencia con
mejor score.

## Presupuesto y medición

`rag.input_token_budget_est` es opcional, no tiene un valor predeterminado y se
define a partir de una baseline reproducible del corpus de cada instalación. Al
configurarlo, Barbarion valida por separado los prompts completos de generation
y repair. Si no cabe evidencia suficiente, termina de forma segura sin llamar
al LLM.

La configuración legacy permanece intacta mientras la clave nueva no se
declare. `context_token_budget` e `input_token_budget_est` son contratos
alternativos y no pueden declararse juntos.

`chars4_v1` calcula `estimate_tokens(text)` localmente y siempre es una
estimación. `provider_input_tokens` y `provider_output_tokens`, cuando existen,
son los contadores reales informados por el proveedor; no se reconstruyen ni se
infieren desde `chars4_v1`.

Para probar la política optimizada, parte de tu propia baseline y configura un
valor medido, no uno copiado de este documento:

```toml
[rag]
input_token_budget_est = <valor decidido tras medir>
context_selection_policy = "optimized_v1"
```

## Decisión sobre overlap

`trim_overlap_v1` fue diferido y no se implementó en H3.1. El impacto observado
no justifica añadir manipulación de contenido y rangos. El diagnóstico
`report_only` se conserva para detectar futuros casos y la decisión puede
reevaluarse si aparece evidencia reproducible y material.

## Reproducir el benchmark

Desde la raíz del repositorio, con el entorno de desarrollo instalado:

```bash
python -m tests.support.h31_baseline_benchmark --output reports/h31
```

`python` debe ser el intérprete del entorno de desarrollo activo (por ejemplo,
el de `.venv` una vez activada); la guía no depende de una ruta absoluta.

Los principales artefactos son:

- `t03-baseline.json`/`.md`: composición, tamaños, retrieval, hechos, citas e
  insuficiencia de la baseline;
- `t04-redundancy-report.json`/`.md`: duplicados, overlap y razones de
  selección/omisión;
- `t07-relevance-first.json`/`.md`: comparación funcional de políticas;
- `t09-observability.json`/`.md`: contrato seguro y comparable de observabilidad;
- `t10-regression.json`/`.md`: puertas de regresión y decisión sobre el default.

Para leerlos, separa tres familias de datos:

- retrieval: `recall@5`, `recall@10` y MRR describen si los candidatos correctos
  fueron recuperados;
- selección y respuesta: cobertura de fuentes/hechos, comportamiento
  `insufficient` y precisión/recall/validez de citas describen qué evidencia
  llegó al prompt y cómo se usó;
- tamaño y consumo: `chars`, `utf8_bytes` y `tokens_est_local` describen el input
  controlado; `provider_*_tokens` solo aparece cuando un proveedor lo informa.

La comparación T07 recuperó la fuente relevante en posición seis y elevó la
cobertura agregada de fuentes/hechos y el recall de citas de `0.888889` a
`1.0`, sin regresión de retrieval ni validez de citas. T10 calificó por ello a
`optimized_v1` como candidata a default. Promoverla requiere una decisión
posterior explícita; H3.1 mantiene `baseline_v1` como default.

## Privacidad y límites

El benchmark versionado usa exclusivamente casos públicos o sintéticos. No
incluye nombres de sistemas internos, objetos privados, rutas personales,
credenciales ni contenido de corpus reales. Los reportes agregan métricas y
razones seguras: no persisten preguntas, prompts, respuestas ni contenido de
fuentes. Una ejecución con un corpus privado debe conservar sus artefactos fuera
de Git y revisar cualquier dato antes de publicarlo.
