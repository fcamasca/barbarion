# H3.1-T08 - Decision sobre trim de overlap

## Decision

**DIFERIDO — no implementar `trim_overlap_v1` en H3.1.**

T04 encontro un unico overlap contiguo demostrado: `27` caracteres, equivalentes
a `7` tokens estimados con `chars4_v1`. Esto representa `0.277%` del prompt de
generacion medido. El duplicado exacto observado ya era omitido por
`baseline_v1` y no aportaba tokens al prompt.

T07, en contraste, produjo una mejora funcional medible mediante seleccion
relevance-first: la cobertura de fuentes, hechos y citas aumento sin regresion
en recall@5, recall@10, MRR, precision o validez de citas.

## Justificacion

El beneficio medido de recortar overlap es marginal y no justifica incorporar
en H3.1 complejidad para modificar contenido, reconciliar rangos originales y
enviados, o ampliar riesgos sobre citas. Diferir la implementacion es el
resultado previsto por T08 cuando la evidencia no supera las puertas empiricas.

## Estado conservado

- el diagnostico de overlap permanece `report_only`;
- no se elimina ni modifica contenido recuperado;
- no cambian IDs, rangos, citas, seleccion ni presupuesto;
- `trim_overlap_v1` no es una politica configurable ni activa.

## Condicion de reevaluacion

La decision puede revisarse si un benchmark reproducible futuro demuestra una
proporcion material de overlap enviado y una reduccion segura que preserve
recall, cobertura de hechos y citas. No se fija ahora un umbral arbitrario.
