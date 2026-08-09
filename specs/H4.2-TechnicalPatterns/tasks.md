# H4.2 — Tareas

Las tareas son de implementación futura. Esta ejecución crea únicamente la
spec y T01 ya fue ejecutada como inventario documental y de código; no se
implementaron detectores ni se modificó código productivo.

## T01 — Inventario real y matriz de viabilidad — COMPLETADA

**Objetivo:** confirmar tipos de símbolos/relaciones, dirección, estados,
confianza, origen, trazabilidad, llamadas, usos, jerarquías, navegación,
configuraciones y limitaciones; confirmar específicamente `package → member`.

**Áreas:** `domain/reverse_engineering.py`, `application/reverse_engineering.py`,
`infrastructure/sqlite.py`, H4/H4.1/H3.3 y pruebas existentes.

**Permitido:** documentación y consultas/tests de solo lectura. **Pruebas:**
inventario sobre fixtures y matriz de los seis candidatos. **Resultado:** decisión
de patrones. **Detener/diferir:** si falta evidencia estructural o requiere
semántica no existente.

## T02 — Definiciones y política de evidencia — COMPLETADA

T02 fija la semántica, relaciones elegibles, métricas, casos excluidos,
insuficiencia e interpretaciones prohibidas para `component_reuse` y
`structural_centrality`. No fija umbrales; la baseline y calibración quedan en
T07. La decisión puede dejar `structural_centrality` diferida si T07 no sostiene
la cobertura.

## T03 — Contrato determinista y provenance

**T03 — COMPLETADA:** definir `logical_identity` estable separado de
`result_fingerprint`, orden canónico, métricas
primarias/secundarias, provenance y estados `detected`, `not_detected`,
`not_evaluated`, `insufficient_evidence` y `ambiguous`. La implementación debe separar “no
cumple la regla” de “no se puede evaluar”.

Diseñar DTO/serialización mínima reutilizando H4. Definir IDs, orden canónico,
traza a relación/símbolo/archivo/chunk y límites. No agregar persistencia salvo
necesidad demostrada. Probar determinismo y ausencia de datos sensibles.

## T04 — Detectores estructurales

Implementar solo los detectores aprobados por T01/T02 con métricas simples y
explicables, reutilizando navegación H4. Probar ciclos, relaciones repetidas,
stale, faltantes, aislados y cambios incrementales.

## T05 — Integración CLI y salidas

**T05 — COMPLETADA:** `inventory`, `describe`, `impact` y `stats` no exponen
simultáneamente patrón, métricas, provenance, limitaciones y política sin
deformar sus contratos; por ello se añade `patterns` como superficie mínima,
local y `--no-llm`.

Extender una superficie existente o justificar `patterns`. Añadir JSON/Markdown
solo donde el contrato lo permita. Probar `--no-llm`, códigos CLI, sin base H4 y
sin modificar H3/H3.1/H3.3.

## T06 — Observabilidad y privacidad

**T06 — COMPLETADA:** `patterns` solo emite contadores, categorías, duración y
`policy_id` en debug; no registra nombres sensibles, contenido, SQL, preguntas,
prompts, respuestas ni provenance textual, y no persiste resultados.

Añadir conteos, tiempos, motivos y límites seguros. Verificar que no se guardan
preguntas, prompts, respuestas ni contenido nuevo y que no existe egress.

## T07 — Benchmark sintético/publicable

**T07 — COMPLETADA:** benchmark `h42-pattern-benchmark-v1` añadido con
distribuciones observables, positivos/negativos, repetición, aislado y ciclo.
El reporte `reports/h42/benchmark-v1.md` muestra distribución y separación por
candidato. No fija thresholds: ambos pasan a T09 como ranking descriptivo y
`not_evaluated`.

Crear fixture versionada con positivos, negativos, falsos positivos, ambiguos,
ciclos, faltantes, aislados, repetidos, stale y mutaciones incrementales según
los patrones aprobados. Definir baseline y corrección por caso; no fijar un
porcentaje universal sin baseline. Calibrar o confirmar los umbrales únicamente
si la baseline demuestra que son necesarios y estables.

## T08 — Regresión y compatibilidad

**T08 — COMPLETADA:** regresión focalizada `62 passed`; suite completa `1107
passed, 14 skipped`. No se requirieron cambios funcionales ni se observaron
regresiones en los contratos H2/H3/H3.1/H3.2/H3.3/H4/H4.1/H5.

Ejecutar unit/integration/CLI y regresión H2, H3, H3.1, H3.2, H3.3, H4, H4.1,
H5, Ollama y Anthropic. Detenerse ante cambios de defaults o contratos.

## T09 — Validación legacy autorizada

**T09 — COMPLETADA:** distribución real ejecutada: 161 símbolos y 313
relaciones. Reporte agregado en `reports/h42/validation-t09.md`. La revisión
humana del ranking fue realizada y documentada; ambas métricas siguen
descriptivas y `not_evaluated`.

Ejecutar sobre corpus real autorizado, registrar utilidad, falsos positivos,
limitaciones y cobertura en agregados. No versionar nombres, código, rutas ni
consultas privadas.

## T10 — Aceptación — COMPLETADA

Con revisión humana de T09, generar `specs/H4.2-TechnicalPatterns/acceptance.md`
con evidencia completa, decisiones de alcance y no regresión. Esta es la única
tarea autorizada para crear `acceptance.md`.
