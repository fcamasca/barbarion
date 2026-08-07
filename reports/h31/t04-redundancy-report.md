# H3.1-T04 - Diagnostico report-only de redundancia

## Resultado

La duplicacion y el overlap son marginales en esta baseline. La politica
efectiva permanece `baseline_v1`; no se elimina ni recorta evidencia.

| Medicion | Valor |
|---|---:|
| Prompt generation | `3140` tokens est. |
| Duplicados exactos detectados | `1` |
| Duplicados exactos enviados | `0` tokens est. |
| Contenido duplicado ya evitado | `17` tokens est. |
| Pares con overlap | `1` |
| Overlap enviado | `27` chars / `7` tokens est. |
| Fraccion explicada del prompt | `0.223%` |
| Casos con perdida de cobertura | `1` |
| Fuentes seleccionadas no citadas | `8` |

## Interpretacion

El duplicado exacto no desperdicia prompt: la deduplicacion vigente ya lo
omite. El unico overlap demostrado explica menos de 1% del total medido.
En cambio, existe un caso con perdida total de cobertura porque la fuente
necesaria queda en posicion seis. Los datos respaldan concentrar T07 en
seleccion y considerar T08 diferible, sujeto a la decision formal posterior.

## Garantia report-only

Cada candidato registra `selected`, `truncated` u `omitted`, razones y
contribucion estimada. El diagnostico no cambia fuentes, orden, contexto,
presupuesto, prompt ni respuesta.
