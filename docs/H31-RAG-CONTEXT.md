# H3.1 — Contexto RAG medible y selección relevance-first

H3.1 resolvió un problema de control y calidad del input RAG: Barbarion ahora
puede explicar cuánto ocupa cada componente del prompt, presupuestar el input
completo de forma opt-in y comparar políticas de selección sin confundir una
estimación local con el consumo informado por el proveedor.

El benchmark mostró que el orden de selección podía dejar fuera una fuente más
relevante —el caso `relevant-at-six`— antes de agotar los candidatos.
`optimized_v1` corrige ese caso y evita comparar como absolutos los scores
heterogéneos de H3 y H4.1: ordena dentro de cada familia, transforma la posición
en una señal relativa y fusiona después. Una validación autorizada posterior
también demostró que el overlap de ventanas podía ser material, por lo que T08
fue reabierta y `trim_overlap_v1` quedó implementado de forma conservadora.

## Políticas disponibles

| Política | Selección | Presupuesto | Estado |
|---|---|---|---|
| `baseline_v1` | Conserva la precedencia y el comportamiento legado | `context_token_budget` o, de forma opt-in, presupuesto del input completo | Default vigente |
| `optimized_v1` | Ordena cada familia por su score original, fusiona por rango relativo, deduplica y recorta solo overlap exacto/continuo | Requiere `input_token_budget_est` | Candidata; todavía no es default |

`optimized_v1` no incorpora reranker, diversidad semántica ni inferencia de
hechos. El score original permanece visible para trazabilidad, pero no se
compara directamente entre familias. Los candidatos empatados dentro de una
familia comparten rango denso y `relative_score`: el orden incidental ya no
crea percentiles distintos. Si la consulta contiene literalmente un
identificador compuesto, su coincidencia exacta con la identidad de un símbolo
estructurado se conserva como `selection_exact_identifier_match`; esta señal
de precisión desempata frente a nombres solo parciales. El orden documental se
aplica después para presentar fuentes.

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

La decisión inicial de diferir `trim_overlap_v1` se reabrió cuando una ejecución
autorizada midió `2,446` caracteres o `612` tokens locales estimados repetidos,
aproximadamente `14%` del contexto. La política recorta únicamente cuando el
sufijo de una fuente coincide exactamente con el prefijo de otra, ambas
pertenecen al mismo documento y sus rangos confirman continuidad. No aplica
similitud semántica, normalización aproximada ni manipulación entre documentos.
Los caracteres/tokens evitados y el overlap residual permanecen trazables.

## Integridad entre ingesta e índice vectorial

Una reingesta puede reemplazar IDs de chunks. Los vectores correspondientes a
IDs que ya no existen no son evidencia materializable y nunca deben consumir un
cupo de `optimized_v1`: se omiten como `missing_content` antes de aplicar
`top_k`, y la selección continúa con el siguiente candidato relevante.

El indexado global elimina además vectores huérfanos antes de persistir los
chunks vigentes. Las reindexaciones parciales no realizan esta limpieza global,
porque operan sobre un alcance deliberadamente incompleto.

Para reparar una instalación que fue ingerida después de su última indexación:

```bash
barbarion reindex --full --delete-obsolete
```

Después del comando, repite la consulta con `--debug`: los candidatos válidos
deben tener contenido y cualquier `missing_content` residual debe quedar visible
como omisión, sin desplazar evidencia posterior. No es necesario cambiar
`top_k`, el modelo de embeddings ni la política predeterminada.

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

## Validación de inferencias directas

La validación de citas continúa siendo estricta para afirmaciones positivas.
Además del soporte léxico, reconoce inferencias sintácticas cerradas y
reproducibles, como `ROUND(expresión, 2)` expresado como “redondea a 2
decimales”. Una enumeración de variables solo es válida si todos sus
identificadores aparecen en la fuente citada.

Las frases de limitación deben referirse explícitamente a “la evidencia” o “la
fuente” y describir una ausencia comprobable en ese texto. Si el concepto está
presente literalmente o mediante un patrón sintáctico conocido, el claim
negativo falla. Esta excepción no desactiva la detección de contradicciones ni
autoriza inferencias semánticas abiertas.
