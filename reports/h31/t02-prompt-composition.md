# H3.1-T02 - Composicion y tamaños del prompt

## Resultado

T02 agrega observabilidad estructurada sin cambiar el prompt, retrieval,
seleccion, contexto, ranking, presupuesto, overlap ni citas.

## Implementacion

- `PromptComponent` clasifica fragmentos como instrucciones, pregunta, metadata
  de fuente, contenido de fuente, respuesta rechazada y formato de salida.
- `PromptComposition` concatena esos fragmentos sin insertar ni normalizar
  caracteres.
- `PromptBuilder.compose()` y `compose_repair()` producen la representacion
  estructurada.
- `build()` y `repair()` conservan el contrato `str` y los seams existentes.
- `estimate_tokens(text)` conserva la formula historica `ceil(chars / 4)` con
  minimo `1` y queda identificada como `chars4_v1`.
- cada componente mide `chars`, `utf8_bytes` y `tokens_est_local`;
- la composicion mide el string final y verifica reconciliacion exacta de
  caracteres y bytes UTF-8;
- `ask --debug` expone tamaños por componente sin copiar su texto en las
  metricas;
- generacion y reparacion conservan composiciones separadas.

## Compatibilidad byte a byte

Las nueve pruebas de H3.1-T01 continuan pasando. Esto incluye los hashes SHA-256
congelados de:

- prompt de generacion:
  `8275ed041cc3d8de6001056d9bbdf9b55bcdec08faf33fdd33ee908dd18d15a9`;
- prompt de reparacion:
  `d0fcae51103419dd21a987a3ac18d165abf687eed66d3ca6a4e6e4b4c34659c2`.

La integracion Anthropic fake conserva ademas el seam que observa
`PromptBuilder.build()` y `repair()`. La prueba de seguridad H1.2 representa su
canario efimero como componente para que todo byte enviado quede contabilizado.

## Verificacion

| Grupo | Resultado |
|---|---:|
| T01 + T02 focalizadas | `16 passed` |
| Unitarias | `757 passed, 3 skipped` |
| Integracion | `98 passed` |
| Golden | `6 passed` |
| Smoke local no instalado | `11 skipped` |
| Total por grupos | `861 passed, 14 skipped` |

La primera ejecucion monolitica de la suite excedio el timeout local del shell;
la misma cobertura se ejecuto por grupos para aislar el entorno. No se registran
fallos funcionales.

## Limites conservados

- no existe presupuesto nuevo;
- no se usa un tokenizer de proveedor;
- no se creo un puerto `TokenEstimator`;
- no se detecta ni recorta overlap;
- no se cambia orden, top-k, fusion, dedupe ni seleccion;
- no se persisten prompt, pregunta, respuesta o contenido de componentes;
- T03 sigue siendo la puerta previa a cualquier optimizacion.
