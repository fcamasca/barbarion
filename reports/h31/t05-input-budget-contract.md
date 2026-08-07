# H3.1-T05 - Contrato de presupuesto de input

## Contrato congelado

| Aspecto | Decision |
|---|---|
| Clave nueva | `rag.input_token_budget_est` |
| Tipo | entero opcional |
| Default | no configurado; no se fija un numero arbitrario |
| Rango | `501..200000` |
| Estimador | `chars4_v1` |
| Alcance futuro | input completo de cada solicitud de generacion o reparacion |
| Clave legada | `rag.context_token_budget` |
| Compatibilidad | configuraciones legadas conservan `baseline_v1` |
| Ambiguedad | declarar ambas claves explicitamente es error |

## Estado en T05

T05 valida y muestra el contrato, pero no lo aplica. Aunque
`input_token_budget_est` este configurado, el armado vigente continua usando
`context_token_budget=6000` como default legado. T06 sera la primera tarea
autorizada para aplicar el presupuesto al prompt completo.

No cambian retrieval, ranking, seleccion, contexto, prompts ni llamadas a
proveedores.
