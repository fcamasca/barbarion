# T09 — Revisión humana estructural agregada

Muestra: 16 posiciones, compuesta por top 5, una posición media y dos aislados
para cada métrica.

```yaml
sampled: 16
useful: 4
plausible_but_weak: 10
false_positive: 0
ambiguous: 2
status: completed_structural_review
```

La revisión verificó correspondencia entre métrica y relaciones observables,
utilidad para orientación estructural, falsos positivos y provenance. Los
extremos de ambas métricas están dominados por relaciones `parent_of` de
configuraciones: confirman conectividad estructural y provenance inspeccionable,
pero hacen débil la interpretación de reutilización si se mezclan jerarquía y
uso. Esto es una limitación documentada, no una justificación de threshold.

Los resultados agregados no incluyen sujetos, rutas, SQL, chunks ni contenido
del corpus. La política permanece `ranking_descriptive` / `not_evaluated`.
