# H3.2-T01 - Baseline de la frontera generativa

## Estado

Completada el 2026-08-07 antes de introducir el Privacy Preflight.

## Alcance congelado

- primera invocacion generativa desde `AskService`;
- generation valida con una unica llamada;
- repair con una segunda y ultima llamada al mismo provider;
- ausencia de fallback a otro provider;
- retornos locales `--no-llm` y evidencia insuficiente con cero llamadas;
- `CitationValidator` y rechazo/reparacion vigentes;
- presupuesto completo H3.1 de 4500 para generation y repair;
- recorrido CLI sintetico de retrieval a repair.

## Contratos observados

| Caso | Requests al provider | Resultado |
|---|---:|---|
| generation con cita valida | 1 | `COMPLETED`, citas validas |
| generation sin cita + repair valido | 2 | mismo provider, `COMPLETED` |
| `--no-llm` | 0 | retorno local `COMPLETED` |
| evidencia insuficiente | 0 | retorno local `INSUFFICIENT_EVIDENCE` |

Hashes SHA-256 UTF-8 del prompt sintetico `order_total`:

```text
generation bd711053422d72f510344843a12a7ea3d37648794ade96b3e628acdf754add3e
repair     22393ad2298e506b62c1888e7f62b54fa8c5db3089c631b611d6986014099eb7
```

Los hashes se calculan sobre el `str` renderizado inmediatamente antes de
`LlmProviderPort.generate()`. No se persisten prompts productivos.

## Pruebas

Comando ejecutado con el runtime empaquetado y los paquetes de la `.venv`:

```text
pytest
  tests/unit/test_h32_privacy_preflight_baseline.py
  tests/integration/test_h32_privacy_preflight_cli_baseline.py
  tests/unit/test_rag_context_ask.py
  tests/unit/test_h31_prompt_composition.py
  tests/unit/test_h31_context_diagnostics.py
  tests/unit/test_llm_provider.py
  tests/unit/test_anthropic_llm_provider.py
  tests/integration/test_h3_rag_cli.py
  tests/integration/test_ask_ollama_http.py
  tests/integration/test_ask_anthropic_http.py
```

Resultado:

```text
136 passed in 15.26s
```

## Privacidad

Los fixtures usan un provider, corpus, identificadores y respuestas sinteticos.
El reporte no contiene prompts completos, rutas privadas, credenciales ni datos
de un corpus real.

## Checkpoint

- archivos productivos modificados bajo `src/`: 0;
- nuevos tests H3.2: 4;
- llamadas adicionales o cambios de comportamiento productivo: 0;
- T02 puede comenzar sobre esta baseline.
