# H4.2 — Aceptación

## Estado

**Aceptada técnicamente con alcance descriptivo.** H4.2 calcula y expone
métricas estructurales deterministas y trazables. No clasifica criticidad,
impacto funcional ni significado de negocio.

## Alcance aceptado

| Patrón | Métrica primaria | Política |
|---|---|---|
| `component_reuse` | `distinct_source_symbols` | Ranking descriptivo / `not_evaluated` |
| `structural_centrality` | `distinct_total_neighbors` | Ranking descriptivo / `not_evaluated` |

`component_reuse` acepta únicamente `calls`, `uses`, `references` y `opens`.
`parent_of` y `precedes` quedan excluidas de ese patrón. `structural_centrality`
conserva los tipos estructurales confirmados porque mide vecinos locales.

## Evidencia y pruebas

- Detector determinista en `src/barbarion/domain/technical_patterns.py`.
- CLI local `barbarion patterns` con JSON/texto, `--limit`, `--all`, `--pattern`
  y `--debug`.
- Identidad lógica separada de fingerprint del resultado.
- Provenance completa en JSON y resumen seguro en texto.
- Sujetos visibles con nombre/tipo; colisiones distinguidas mediante ID corto.
- Sin persistencia de `PatternResult`.
- Pruebas H4.2 focalizadas finales: **10 passed**.
- Regresión focalizada H2–H5 en T08: **62 passed**.
- Suite completa ejecutada en T08, antes de ajustes manuales posteriores:
  **1107 passed, 14 skipped**.

El estado final posterior fue verificado con las 10 pruebas focalizadas y
verificación manual de la salida normal y `--all`. Las pruebas cubren
deduplicación, vecinos, identidad/fingerprint, provenance parcial, estados, CLI,
debug, privacidad, ausencia de LLM, ausencia de Privacy Preflight, ausencia de
egress, ausencia de escrituras en `rag_queries` y ausencia de persistencia.

## Benchmark y validación legacy

El benchmark sintético/publicable verificó cálculo, deduplicación, ciclos,
aislados y determinismo; no justificó thresholds generalizables. Reporte:
`reports/h42/benchmark-v1.md`.

Sobre el corpus autorizado local se evaluaron 161 símbolos y 313 relaciones.
`component_reuse` tuvo mediana 0, p75 0, p90 2 y máximo 12.
`structural_centrality` tuvo mediana 0, p75 2, p90 3 y máximo 12.

La revisión estructural agregada muestreó 16 posiciones: top 5, una posición
media y dos aislados por métrica. Resultado: 4 útiles, 10 plausibles pero débiles,
0 falsos positivos y 2 ambiguos.

La revisión manual posterior detectó que `parent_of` contaminaba inicialmente
`component_reuse`. El defecto fue corregido restringiendo el patrón a `calls`,
`uses`, `references` y `opens`. `parent_of` y `precedes` permanecen únicamente
como señales válidas de conectividad para `structural_centrality`.

## Privacidad y compatibilidad

El análisis opera localmente sobre SQLite. No usa LLM, no ejecuta Privacy
Preflight, no hace egress, no escribe preguntas/prompts/respuestas ni `rag_queries`,
y no persiste resultados derivados. Los logs contienen solo contadores,
categorías, duración y `policy_id`.

La suite completa de T08 confirmó compatibilidad con H2, H3, H3.1, H3.2, H3.3,
H4, H4.1 y H5 antes de los ajustes de presentación/elegibilidad posteriores;
las pruebas focalizadas finales cubren el detector y CLI H4.2. H3.3 conserva su
configuración opt-in y sus contratos.

## Limitaciones aceptadas

- No se demuestra una relación navegable completa `package → member`.
- La cobertura depende de relaciones H4/H4.1 resolubles y activas.
- No se implementan thresholds ni percentiles.
- `critical_dependency`, capas, módulos, duplicación y hotspots siguen fuera de
  alcance.
- La validación no demuestra criticidad funcional ni utilidad de negocio.

## Decisiones posteriores

H4.2 no se integra actualmente con `barbarion ask`; `barbarion patterns` es una
capacidad independiente de análisis/reporte estructural. Una integración futura
con `ask` deberá definirse como evolución separada y no forma parte de esta
aceptación.

Una evolución futura podrá evaluar nuevas señales, más corpus y calibración.
Cualquier threshold deberá justificarse con nueva baseline y revisión humana;
ninguno se promueve por esta aceptación.
