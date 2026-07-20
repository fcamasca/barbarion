# Benchmark de modelos locales

## Resumen y alcance

- Run: `20260720T120000Z-golden`
- Estado: `interrupted`
- Dataset: `barbarion-local-llm-synthetic-v1`
- Hash del dataset: `dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd`
- Unidades confirmadas: 0 de 16
- Alcance: compara modelos generativos locales; no evalua retrieval ni modifica RAG.

## Condiciones de ejecucion

- Fecha UTC: `2026-07-20T12:00:00Z`
- Barbarion: `0.6.0`
- Python: `3.12.10`
- Plataforma: `TestOS 1 (test-machine)`
- Ollama: `no informado`
- Timeout por generacion: 30 s
- Temperatura: 0
- Repeticiones: una por caso/modelo
- Rotacion: `offset = case_index % model_count`

### Metadata Ollama acotada

| Modelo | Formato | Familia | Parametros | Cuantizacion | Capacidades | Diagnostico |
|---|---|---|---|---|---|---|

## Comparacion

| Modelo | Completitud | Aceptacion | Quality | Quality recomendacion | Latencia mediana ms | Tokens salida | Cobertura tokens | Elegible |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| m1 | 0.00% | null | null | null | null | null | 0.00% | no |
| m2 | 0.00% | null | null | null | null | null | 0.00% | no |

## Candidato recomendado

- Candidato: ninguno.
- Motivo: La corrida no esta completa.
- Regla: corrida completa, todos los casos completados y aceptacion >= 0.90; luego aceptacion descendente, quality de respuestas aceptadas descendente, mediana de latencia ascendente y nombre exacto.
- Esta recomendacion no selecciona ni configura el modelo. La decision y `models select` son acciones humanas separadas.

## Resultados por categoria

| Categoria | Unidades | Quality promedio | Aceptadas | Fallidas |
|---|---:|---:|---:|---:|

## Resultados por caso

| Caso | Modelo | Orden | Estado | Validador | Quality | Duracion ms | Hash contexto | Codigo |
|---|---|---:|---|---|---:|---:|---|---|

## Rendimiento y tokens

Los tokens son aproximados y solo se agregan cuando Ollama los informa. `null` no se convierte en cero.

| Modelo | Latencia promedio ms | Latencia mediana ms | Prompt tokens | Cobertura prompt | Salida tokens | Cobertura salida |
|---|---:|---:|---:|---:|---:|---:|
| m1 | null | null | null | 0.00% | null | 0.00% |
| m2 | null | null | null | 0.00% | null | 0.00% |

## Fallas y diagnosticos

- Fallas operativas: 0.
- Respuestas rechazadas por el validador: 0.
- No se registraron codigos de falla operativa.

## Metodologia y formulas

Las metricas son lexicales y deterministas; no se usa un LLM juez.

```text
quality_score =
  0.20 * answer_quality +
  0.10 * instruction_following +
  0.20 * groundedness +
  0.10 * context_use +
  0.15 * citation_score +
  0.25 * validator_acceptance
```

Las metricas no aplicables quedan `null` y los pesos restantes se renormalizan. Una respuesta rechazada conserva scores descriptivos, pero su score de recomendacion queda `null`.

## Limitaciones

- El score lexical aproxima calidad; no es una verdad semantica ni sustituye revision humana.
- El resultado solo aplica al dataset, versiones, opciones y hardware registrados.
- H1.1 usa una ejecucion por caso/modelo; no calcula p95 ni estima variabilidad.
- No se ejecuta retrieval y el contexto sintetico permanece congelado.
- El reporte omite respuestas completas, prompts y contexto para reducir exposicion.
- Una corrida interrumpida o con fallas no produce candidato elegible.
- El candidato, cuando existe, requiere revision humana y seleccion explicita posterior.
