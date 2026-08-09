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

El dataset debe declarar por caso los patrones esperados, no esperados y
ambiguos. Medir por patrón: detecciones correctas, omisiones, falsos positivos,
insuficiencia explicada, evidencia completa, tiempo y determinismo. Repetir cada
caso y comparar baseline descriptiva antes de proponer umbrales. Publicar solo
fixture y agregados.

## CLI, privacidad y no-LLM

Cubrir formato JSON/Markdown/texto, errores de argumentos, base vacía, límites,
interrupción, `--no-llm`, ausencia de Ollama y ausencia de red. Inspeccionar logs
y SQLite para asegurar que no se persisten preguntas, prompts, respuestas ni
contenido sensible nuevo.

## Regresión y validación real

Ejecutar la suite H2/H3/H3.1/H3.2/H3.3/H4/H4.1/H5 y pruebas de Ollama/Anthropic
existentes. En el corpus legacy autorizado comparar utilidad humana, falsos
positivos, patrones no demostrables y limitaciones; registrar únicamente
agregados públicos.

## Criterio final

No se acepta un detector sin definición observable, fixture positiva y negativa,
resultado determinista, explicación y trazabilidad o limitación explícita. La
aceptación final requiere benchmark reproducible, regresión completa, privacidad
verificada y revisión humana documentada en `acceptance.md` por T10.
