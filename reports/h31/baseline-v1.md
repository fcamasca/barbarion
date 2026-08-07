# H3.1-T01 - Baseline vigente de contexto RAG

## Estado

`h31-baseline-v1` caracteriza el comportamiento de Barbarion `0.6.0` antes de
cualquier optimizacion H3.1. No cambia algoritmos, defaults ni contratos de
produccion.

La fuente ejecutable de los valores congelados es
[`baseline-v1.json`](baseline-v1.json), validada por
`tests/unit/test_h31_baseline_characterization.py`.

## Reproduccion

```powershell
python -m pytest tests/unit/test_h31_baseline_characterization.py -q --basetemp .pytest-tmp/h31-t01
```

La prueba usa SQLite temporal, embeddings fake deterministas y contenido
sintetico. No requiere Ollama, Anthropic, secretos ni red.

## Defaults congelados

| Area | Valor vigente |
|---|---|
| retrieval | `hybrid` |
| `top_k` | `10` |
| `candidate_k` | `40` |
| threshold | `0.20` |
| pesos vector/keyword | `0.70 / 0.30` |
| presupuesto de contexto estimado | `6000` |
| maximo estimado por chunk | `1200` |
| prefijo hash para dedupe | `16` |
| estimador | `max(1, ceil(caracteres / 4))` |

## Retrieval y seleccion vigentes

- semantic y keyword recuperan hasta `candidate_k` y terminan en `top_k`;
- hybrid fusiona por `chunk_id`, normaliza cada canal y aplica pesos;
- no existe cross-encoder ni segunda etapa de reranking;
- `AskService` coloca candidatos estructurados antes que chunks H3 y vuelve a
  limitar a `top_k`;
- `ContextBuilder` aplica threshold, dedupe exacto, orden documental, truncado y
  presupuesto, en ese orden;
- el orden documental puede colocar una fuente de menor score antes que otra de
  mayor score;
- no existe deteccion de overlap parcial.

## Escenario sintetico congelado

Cuatro candidatos ejercitan threshold, hash duplicado y orden documental:

| Entrada | Score | Resultado |
|---|---:|---|
| `highest` | 0.95 | seleccionada como F2 |
| `document-first` | 0.60 | seleccionada como F1 |
| `duplicate` | 0.90 | omitida por hash duplicado |
| `below` | 0.10 | omitida por threshold |

El contexto resultante tiene `191` caracteres, `48` tokens estimados localmente,
dos fuentes truncadas y un hash SHA-256 estable registrado en JSON.

## Prompt, reparacion y citas

- el prompt inicial incluye instrucciones, IDs, pregunta, contexto y formato;
- el prompt de reparacion vuelve a enviar pregunta/contexto y agrega la respuesta
  rechazada;
- los hashes de ambos prompts quedan congelados sobre el escenario sintetico;
- citas desconocidas y respuestas sin cita inline valida se rechazan;
- debug expone metricas de tamano y contenido solo de forma efimera y explicita;
- prompt y respuesta no se persisten en SQLite.

## Observacion historica H1.2

| Metrica | Valor |
|---|---:|
| estimacion local de prompt | 6,190 |
| input real Anthropic | 10,198 |
| output real Anthropic | 529 |
| total real calculado | 10,727 |
| diferencia input real - estimacion | 4,008 |

Estos son totales agregados conservados por el acta H1.2. No existe evidencia
para reconstruir su composicion exacta y no se usan como expectativa ficticia
del escenario sintetico.

## Limites de T01

- no propone presupuesto nuevo;
- no cambia el estimador;
- no cambia ranking, merge, orden ni dedupe;
- no mide aun componentes internos del prompt;
- no implementa overlap ni relevance-first;
- no establece puertas de optimizacion; eso corresponde a T03.
