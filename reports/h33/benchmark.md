# H3.3 — Benchmark Graph-Aware Retrieval

| Política | Recall multi | Ruido | Chunks | Tokens contexto | Latencia ms |
|---|---:|---:|---:|---:|---:|
| baseline | 0.383 | 0.000 | 1.167 | 42.000 | 0.264 |
| shallow | 0.867 | 0.000 | 2.500 | 148.833 | 0.809 |
| balanced | 1.000 | 0.150 | 3.333 | 226.500 | 0.479 |
| wide | 1.000 | 0.150 | 3.333 | 226.500 | 0.411 |
| deep_wide | 1.000 | 0.150 | 3.333 | 226.500 | 0.446 |

Recomendación: `balanced` — menor contexto y menor amplitud entre políticas con recall>=0.95, simple sin regresión y ruido<=0.15
