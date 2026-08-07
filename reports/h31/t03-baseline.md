# H3.1-T03 - Benchmark baseline

## Estado

Baseline reproducible sobre corpus sintetico. No habilita optimizaciones
ni fija un objetivo de reduccion.
El dataset y todas sus fuentes son sinteticos y publicables.

## Metricas agregadas

| Metrica | Valor |
|---|---:|
| `recall_at_5` | `0.888889` |
| `recall_at_10` | `1.0` |
| `mrr` | `0.851852` |
| `selected_source_recall` | `0.888889` |
| `fact_coverage` | `0.888889` |
| `citation_precision` | `1.0` |
| `citation_recall` | `0.888889` |
| `citation_valid_rate` | `1.0` |
| `insufficient_case_count` | `2` |
| `exact_duplicate_pairs` | `1` |
| `exact_duplicate_prompt_tokens_est_local` | `0` |
| `exact_duplicate_avoided_content_tokens_est_local` | `17` |
| `overlap_pairs` | `1` |
| `overlap_chars` | `27` |
| `overlap_tokens_est_local` | `7` |
| `redundancy_prompt_tokens_est_local` | `7` |
| `redundancy_share_of_generation_prompt` | `0.002229` |
| `generation_prompt_chars_total` | `12543` |
| `generation_prompt_utf8_bytes_total` | `12583` |
| `generation_prompt_tokens_est_local_total` | `3140` |
| `repair_prompt_count` | `1` |
| `repair_prompt_chars_total` | `1418` |
| `repair_prompt_utf8_bytes_total` | `1420` |
| `repair_prompt_tokens_est_local_total` | `355` |

## Composicion de generation

| Componente | Chars | UTF-8 bytes | Tokens est. local |
|---|---:|---:|---:|
| `instructions` | 8229 | 8229 | 2062 |
| `output_format` | 603 | 603 | 153 |
| `question` | 467 | 489 | 118 |
| `source_content` | 1163 | 1181 | 299 |
| `source_metadata` | 2081 | 2081 | 539 |

Metadata de fuentes: `539` tokens (`17.2%` del prompt de generacion). Evidencia: `299` tokens (`9.5%`).

## Composicion de repair

| Componente | Chars | UTF-8 bytes | Tokens est. local |
|---|---:|---:|---:|
| `instructions` | 1140 | 1140 | 285 |
| `output_format` | 20 | 20 | 5 |
| `question` | 52 | 54 | 13 |
| `rejected_answer` | 51 | 51 | 13 |
| `source_content` | 46 | 46 | 12 |
| `source_metadata` | 109 | 109 | 29 |

## Casos

| Caso | R@5 | R@10 | MRR | Evidencia | Hechos | Citas | Estado |
|---|---:|---:|---:|---:|---:|---:|---|
| `literal-single` | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | PASS | completed |
| `semantic-rank-two` | 1.000 | 1.000 | 0.500 | 1.000 | 1.000 | PASS | completed |
| `hybrid-multi-source` | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | PASS | completed |
| `window-overlap` | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | PASS | completed |
| `exact-duplicate` | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | PASS | completed |
| `relevant-at-six` | 0.000 | 1.000 | 0.167 | 0.000 | 0.000 | PASS | insufficient |
| `ambiguous-evidence` | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | PASS | completed |
| `insufficient-empty` | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | PASS | insufficient |
| `structured-evidence` | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | PASS | completed |
| `citation-repair` | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | PASS | completed |

## Decision T03

T03 no autoriza ninguna optimizacion. T04-T08 requieren revision
humana de estos numeros y pueden confirmar, rechazar o diferir cada
hipotesis inicial.

Hallazgos observados: metadata supera a evidencia en la composicion
medida; existe duplicacion exacta y overlap contiguo demostrable; y
el caso con evidencia relevante en posicion seis conserva R@10 pero
pierde cobertura bajo el top-k vigente. Son datos, no autorizaciones
para modificar seleccion, ranking, presupuesto u overlap.

## Reproduccion

```powershell
python -m tests.support.h31_baseline_benchmark --output reports/h31
```
