# H3.1-T10 - Regresion funcional y consumidores

## Resultado

`optimized_v1` supera la puerta de regresion y queda **calificado como candidato
a default**, pero no se promueve en T10. El default efectivo sigue siendo
`baseline_v1`.

## Benchmark

- `relevant-at-six`: fact coverage `0.0 -> 1.0`;
- estado: `insufficient -> completed`;
- selected-source recall, fact coverage y citation recall: `+0.111111`;
- recall@5, recall@10, MRR, precision y validez de citas: sin regresion.

## Matriz opt-in

`76 passed`. Cubre `optimized_v1` con evidencia estructurada H4.1, H4 Impact,
H5 evidencia/spec, `--no-llm`, Ollama fake, Anthropic fake, formatos y Unicode.

## Regresion completa

- suite completa: `907 passed, 3 skipped`;
- smoke del ejecutable instalado: `11 passed`;
- fallos: `0`.

## Decision de default

Estado: `qualified_candidate`. La mejora es funcional y reproducible, y no se
observaron regresiones. Aun asi, T10 no cambia configuraciones existentes ni el
default. La promocion requiere una decision explicita posterior respaldada por
la aceptacion integral de H3.1.

## Limites

El benchmark H3.1 es sintetico y offline. Ollama y Anthropic se validaron con
fakes en T10; no se declara una nueva ejecucion real. `chars4_v1` sigue siendo
una estimacion local, no uso real del proveedor.
