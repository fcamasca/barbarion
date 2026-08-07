# H3.1-T07 - Seleccion relevance-first

## Comparacion

| Metrica | baseline_v1 | optimized_v1 | Delta |
|---|---:|---:|---:|
| `recall_at_5` | 0.888889 | 0.888889 | +0.000000 |
| `recall_at_10` | 1.0 | 1.0 | +0.000000 |
| `mrr` | 0.851852 | 0.851852 | +0.000000 |
| `selected_source_recall` | 0.888889 | 1.0 | +0.111111 |
| `fact_coverage` | 0.888889 | 1.0 | +0.111111 |
| `citation_precision` | 1.0 | 1.0 | +0.000000 |
| `citation_recall` | 0.888889 | 1.0 | +0.111111 |
| `citation_valid_rate` | 1.0 | 1.0 | +0.000000 |

## Caso clave

`relevant-at-six` pasa de cobertura de hechos `0.0` a `1.0` y de estado `insufficient` a `completed`.

## Alcance

`optimized_v1` ordena globalmente por `combined_score`, evita duplicados
exactos antes de gastar `top_k`, desempata por `chunk_id` y ordena para
presentacion despues de seleccionar. No agrega diversidad semantica,
cobertura inteligente, embeddings adicionales ni reranker.
