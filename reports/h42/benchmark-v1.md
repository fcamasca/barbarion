# H4.2 — Benchmark sintético v1

Dataset: `tests/fixtures/h42_pattern_benchmark.json`  
Prueba: `tests/unit/test_h42_benchmark.py`  
Resultado ejecutado: `9 passed`

## Regla de lectura

Este benchmark demuestra que las métricas se calculan y deduplican conforme al
contrato. No demuestra que un número tenga significado técnico generalizable.
Los casos son sintéticos y sus valores fueron construidos para probar el
comportamiento del algoritmo.

## `component_reuse`

```yaml
primary_metric: distinct_source_symbols
distribution:
  cases:
    reuse_multiple_sources: 3
    reuse_repeated_same_source: 1
  min: 1
  max: 3
  sample_size: 2
separation: observable_in_synthetic_fixture_only
decision: ranking_descriptive
status: not_evaluated
justification: >
  La métrica distingue tres símbolos fuente de repeticiones del mismo símbolo,
  pero dos casos sintéticos no justifican un threshold generalizable.
```

## `structural_centrality`

```yaml
primary_metric: distinct_total_neighbors
distribution:
  cases:
    centrality_multiple_neighbors: 3
    centrality_cycle: 2
  min: 2
  max: 3
  sample_size: 2
separation: weak_and_synthetic_only
decision: ranking_descriptive
status: not_evaluated
justification: >
  La métrica cuenta vecinos distintos y no usa ciclos como criterio, pero la
  muestra no permite justificar threshold, percentil ni centralidad global.
```

## Decisión T07

Ambos candidatos pasan a T09 como métricas descriptivas. T07 no calibra ni
promueve thresholds. Una futura calibración solo podrá proponerse después de
observar un corpus legacy real autorizado y comprobar estabilidad, utilidad y
falsos positivos.
