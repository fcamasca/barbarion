# H3.1-T09 - Observabilidad comparable

Schema: `h31_observability_v1`. Estimador: `chars4_v1`.

| Politica | Generation tokens est. | Repair tokens est. | Seleccion | Hechos | Citas |
|---|---:|---:|---:|---:|---:|
| `baseline_v1` | 2523 | 154 | 0.888889 | 0.888889 | 0.888889 |
| `optimized_v1` | 2522 | 154 | 1.0 | 1.0 | 1.0 |

## Uso real

El benchmark es offline: los campos `provider_*_tokens` permanecen
`null` y la cobertura es `0.0`. No se infieren contadores reales desde
`chars4_v1`.

## Privacidad y formatos

El reporte contiene solo agregados sinteticos. No incluye preguntas,
prompts, respuestas ni contenido de fuentes. La CLI mantiene respuestas
JSON limpias y emite observabilidad detallada solo por stderr con
`--debug`.
