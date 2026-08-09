# H4.2 — Plan de pruebas

## Estrategia

Pruebas unitarias para políticas, métricas, elegibilidad, determinismo y
serialización; integración contra SQLite temporal y fixtures sintéticas; CLI
con `--no-llm`; benchmark sin juez generativo; regresión de la suite existente.

## Fixtures

Usar componentes genéricos con relaciones `calls`, `uses`, `opens`, `references`,
`parent_of` y `precedes` solo si T01 confirma su presencia. Incluir grafo lineal,
estrella, aislados, ciclo, duplicados, destinos ambiguos/no resueltos, relaciones
stale/deleted, configuración H4.1 y mutaciones que agreguen/eliminan destinos.

## Unit tests

### Gate T03 — contrato y provenance

- la misma política, patrón y sujeto conservan `logical_identity` aunque cambie
  el grafo;
- cambiar relaciones, métricas o estado cambia `result_fingerprint`, no
  `logical_identity`;
- `component_reuse` distingue métrica primaria de contexto explicativo;
- se conservan ramas completas o parciales de provenance sin exigir reference o
  chunk textual;
- la ausencia de reference/chunk se declara como evidencia estructural sin cita
  textual, sin fabricar niveles inexistentes;
- `not_detected`, `insufficient_evidence` y `ambiguous` no se intercambian;
- no superar un umbral futuro produce `not_detected`, no
  `insufficient_evidence`.

### Gate T02 — semántica de candidatos

- `component_reuse` distingue `A→X`, `B→X`, `C→X` de tres repeticiones `A→X`;
- `source_symbol_id` es la unidad primaria de origen independiente y los
  archivos son métrica secundaria;
- `structural_centrality` distingue vecinos entrantes/salientes distintos y no
  usa ciclos, bridging o número bruto de relaciones como sustituto;
- ningún caso se etiqueta por umbral numérico antes de T07;
- cada candidato devuelve métricas, exclusiones e insuficiencia separadas del
  patrón y no produce interpretaciones funcionales.

- política filtra estados, resolución y confianza correctamente;
- conteos de entrada/salida, fuentes distintas y tipos son exactos;
- cada patrón tiene evidencia e IDs; insuficiencia no se convierte en detección;
- ciclos terminan y conservan diagnóstico;
- orden e IDs son estables;
- no se confunde `centralidad estructural` con impacto funcional;
- serialización JSON/Markdown es estable y no contiene contenido sensible;
- mismo SQLite/configuración produce mismo resultado con y sin proveedor LLM.

## Integration tests

- lectura solo desde tablas H4/H4.1, sin segundo grafo;
- símbolos y relaciones incrementales cambian métricas sin duplicarlas;
- stale/deleted quedan fuera según política;
- evidencia a archivo/chunk/referencia se conserva cuando existe;
- ausencia de relación `package → member` se muestra como limitación;
- H3.3 conserva expansión, scores, top-k, presupuesto, fallback y default;
- `analyze`, `inventory`, `describe`, `impact` y `stats` no cambian contratos.

## Benchmark

El benchmark versionado es `tests/fixtures/h42_pattern_benchmark.json` y su
prueba es `tests/unit/test_h42_benchmark.py`. Debe medir la distribución real de
las métricas por caso antes de considerar thresholds. Si no hay separación
estable entre positivos y negativos, la decisión aceptable para v1 es ranking
descriptivo con `not_evaluated`. El reporte agregado es
`reports/h42/benchmark-v1.md`; la separación sintética no se interpreta como
threshold generalizable.

El dataset debe declarar por caso los patrones esperados, no esperados y
ambiguos. Medir por patrón: detecciones correctas, omisiones, falsos positivos,
insuficiencia explicada, evidencia completa, tiempo y determinismo. Repetir cada
caso y comparar baseline descriptiva antes de proponer umbrales. Publicar solo
fixture y agregados.

## CLI, privacidad y no-LLM

- `barbarion patterns --format json` expone patrón, sujeto, estado, métricas
  primarias/secundarias, provenance, limitaciones y política;
- `barbarion patterns --pattern component_reuse` y
  `--pattern structural_centrality` filtran de forma determinista;
- `patterns` no llama LLM, no cambia H3/H3.1/H3.3 y conserva `not_evaluated`.
- `--debug` solo contiene contadores seguros, duración y `policy_id`; no contiene
  nombres, contenido, SQL, preguntas, prompts, respuestas ni provenance textual.
- `patterns` no invoca privacy preflight, no hace egress, no escribe `rag_queries`
  y no persiste `PatternResult`.

Cubrir formato JSON/Markdown/texto, errores de argumentos, base vacía, límites,
interrupción, `--no-llm`, ausencia de Ollama y ausencia de red. Inspeccionar logs
y SQLite para asegurar que no se persisten preguntas, prompts, respuestas ni
contenido sensible nuevo.

## Regresión y validación real

La validación agregada actual está en `reports/h42/validation-t09.md`. La
La revisión humana ya se realizó sobre top 5, posición media y aislados. El
resultado agregado está en `reports/h42/validation-t09-human-review.md`; no se
promovieron thresholds ni percentiles.

Ejecutar la suite H2/H3/H3.1/H3.2/H3.3/H4/H4.1/H5 y pruebas de Ollama/Anthropic
existentes. En el corpus legacy autorizado comparar utilidad humana, falsos
positivos, patrones no demostrables y limitaciones; registrar únicamente
agregados públicos.

## Criterio final

No se acepta un detector sin definición observable, fixture positiva y negativa,
resultado determinista, explicación y trazabilidad o limitación explícita. La
aceptación final requiere benchmark reproducible, regresión completa, privacidad
verificada y revisión humana documentada en `acceptance.md` por T10.
