# H3.1-T08 - Decisión revisada sobre trim de overlap

## Decisión inicial

T04 encontró `27` caracteres o `7` tokens locales estimados de overlap
(`0.277%` del prompt sintético). Con esa evidencia, T08 se difirió y mantuvo el
diagnóstico `report_only`.

## Evidencia que reabre T08

Una validación autorizada posterior detectó un único overlap exacto de `2,446`
caracteres, equivalente a `612` tokens con `chars4_v1`, aproximadamente `14%`
del contexto de esa ejecución. Los valores son métricas agregadas y este reporte
no contiene preguntas, rutas, nombres ni contenido del corpus validado.

El resultado demuestra que la baseline sintética inicial no representaba todas
las ventanas extensas posibles y satisface la condición explícita de
reevaluación de la decisión anterior.

## Decisión revisada

**IMPLEMENTAR `trim_overlap_v1` de forma conservadora.**

El recorte solo se aplica cuando:

- el sufijo de una fuente es exactamente igual al prefijo de otra;
- ambas fuentes pertenecen al mismo documento;
- sus rangos confirman continuidad o intersección;
- el recorte no elimina por completo la fuente posterior.

No se usa similitud semántica, normalización lexical aproximada ni comparación
entre documentos. El contexto conserva IDs de cita y scores originales. Debug
registra caracteres/tokens estimados evitados y overlap residual.

## Validación sintética

El benchmark `window-overlap` conserva cobertura y citas, reduce el overlap
residual de `7` a `0` tokens estimados y registra `7` tokens evitados. Una prueba
de presupuesto adicional demuestra que `400` caracteres/`100` tokens estimados
liberados permiten incorporar una fuente útil posterior.
