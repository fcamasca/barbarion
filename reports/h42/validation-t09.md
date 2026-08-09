# H4.2 — Validación T09 sobre corpus legacy autorizado

## Alcance y privacidad

La ejecución se realizó localmente sobre la base configurada en `barbarion.toml`.
Este reporte contiene únicamente agregados; no incluye nombres de objetos,
packages, tablas, rutas, SQL, chunks ni provenance textual.

## Distribución real

```yaml
symbols_evaluated: 161
relations_evaluated: 313
component_reuse:
  primary_metric: distinct_source_symbols
  min: 0
  median: 0
  p75: 0
  p90: 2
  max: 12
structural_centrality:
  primary_metric: distinct_total_neighbors
  min: 0
  median: 0
  p75: 2
  p90: 3
  max: 12
result_status:
  not_evaluated: 105
  insufficient_evidence: 217
  detected: 0
  not_detected: 0
  ambiguous: 0
```

Los percentiles se calculan sobre el orden ascendente de los sujetos evaluados,
con índice `floor((n-1)*p)`. No representan un threshold.

## Utilidad humana

```yaml
sampled: 0
useful: 0
false_positive: 0
ambiguous: 0
status: pending_authorized_human_review
```

La ejecución automatizada no se presenta como revisión humana. La siguiente
acción autorizada debe revisar extremos del ranking (top 5, posición media y
aislados) sobre el corpus local, registrando únicamente conteos agregados.

## Decisión de política

```yaml
component_reuse:
  decision: ranking_descriptive
  status: not_evaluated
  justification: >
    La métrica tiene distribución real concentrada en cero y una cola pequeña,
    pero no existe validación humana ni evidencia de un corte natural estable.
structural_centrality:
  decision: ranking_descriptive
  status: not_evaluated
  justification: >
    La métrica aporta un ranking local de vecinos distintos, pero la distribución
    observada y la ausencia de validación humana no justifican threshold ni
    percentil como regla de clasificación.
```

T09 no busca producir un número por obligación. Una futura revisión humana puede
confirmar utilidad, falsos positivos o falta de valor; cualquier calibración queda
fuera de esta ejecución.
