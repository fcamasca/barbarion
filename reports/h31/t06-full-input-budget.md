# H3.1-T06 - Presupuesto del input completo

## Resultado

Cuando `rag.input_token_budget_est` esta configurado, Barbarion mide con
`chars4_v1` el prompt completo de generacion: instrucciones, pregunta, metadata,
evidencia y formato. Primero calcula el overhead fijo, entrega el remanente al
`ContextBuilder` de `baseline_v1` y revalida la composicion final antes de llamar
al proveedor.

La medicion sigue siendo una estimacion local; no se presenta como tokens reales
del proveedor.

## Reglas efectivas

- sin la clave nueva, `context_token_budget` y el comportamiento legado quedan
  intactos;
- con la clave nueva, cada prompt de generacion debe quedar dentro del limite;
- si no cabe evidencia localmente relevante, retorna `INSUFFICIENT_EVIDENCE`
  sin llamar al LLM;
- generation y repair se verifican como solicitudes separadas;
- si repair excede el limite, no se envia y el run termina de forma segura con
  error de citas;
- T06 conserva orden, scores, dedupe y politica de seleccion `baseline_v1`;
  relevance-first sigue reservado para T07.

## Observabilidad

El debug efimero registra presupuesto configurado, `estimator_id`, overhead,
remanente para evidencia, estimacion final y resultado (`fits`,
`insufficient_evidence` o `fixed_overhead_exceeds_budget`). No persiste prompt,
pregunta, respuesta ni contenido.
