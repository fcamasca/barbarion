# H4 - ReverseEngineering: Evidencia de aceptacion

## Estado

**Estado:** aceptado.

H4 queda aceptado por feedback humano recibido el 2026-06-30. La evidencia T12, las correcciones puntuales posteriores y la revision de utilidad practica se consideran suficientes para cerrar el hito.

## Contexto de ejecucion

| Campo | Valor |
|---|---|
| Fecha | 2026-06-30 |
| Branch | `feature/H4-ReverseEngineering` |
| Commit evaluado | `0cd50cd` |
| Version Barbarion evaluada en T12 | `barbarion 0.3.0` |
| Version Barbarion candidata post-correccion | `barbarion 0.4.0` |
| Python | `3.12.13` |
| Sistema | Windows |
| Operacion | Local/on-premise; sin servicios cloud |

## Comandos ejecutados

### Suite completa

```bash
C:\Users\Rodrigo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest --basetemp .pytest-tmp/h4
```

Resultado:

- `412 passed`
- `12 skipped`
- `1 warning`
- duracion reportada por pytest: `45.80s`

Observacion: el warning corresponde a permisos de escritura sobre `.pytest_cache` en Windows; no afecta el resultado funcional de la suite.

### Smoke sin entry point instalado

```bash
C:\Users\Rodrigo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest --basetemp .pytest-tmp/h4-smoke tests/smoke
```

Resultado:

- `10 skipped`
- motivo: el entry point `barbarion` no estaba instalado en ese interprete.

### Smoke con venv editable temporal

Instalacion editable offline:

```bash
.pytest-tmp\h4-venv\Scripts\python.exe -m pip install -e . --no-deps --no-build-isolation
```

Resultado de instalacion:

- paquete editable construido e instalado como `barbarion-0.3.0`.
- intento previo sin `--no-build-isolation` fallo por bloqueo de red al resolver `setuptools>=77`; no se modifico codigo.

Smoke instalado:

```bash
.pytest-tmp\h4-venv\Scripts\python.exe -m pytest --basetemp .pytest-tmp\h4-smoke-installed tests/smoke
```

Resultado:

- `8 passed`
- `2 failed`
- `2 warnings`
- duracion reportada por pytest: `30.11s`

Fallas observadas:

1. `test_version_from_installed_cli_has_no_side_effects`
   - esperado por smoke: `barbarion 0.2.0`
   - obtenido: `barbarion 0.3.0`
   - interpretacion: contrato smoke desactualizado frente a la version vigente.

2. `test_repeated_doctor_is_idempotent`
   - esperado por smoke: migraciones `[(1,), (2,)]`
   - obtenido: `[(1,), (2,), (3,), (4,)]`
   - interpretacion: contrato smoke desactualizado frente a migraciones H3/H4 vigentes.

No se corrigieron estas pruebas durante H4-T12 para respetar el alcance: cualquier cambio de smoke debe tratarse como correccion puntual posterior.

## Evidencia generada

Directorio:

- `reports/h4/`

Artefactos principales:

| Archivo | Contenido |
|---|---|
| `reports/h4/metrics.json` | metricas de muestra representativa Oracle, PowerBuilder y cruce PB-Oracle |
| `reports/h4/baseline-metrics.json` | baseline de comandos `analyze`, `inventory`, `describe`, `impact` |
| `reports/h4/inventory-oracle.md` | inventario Markdown de muestra Oracle |
| `reports/h4/describe-oracle.md` | ficha Markdown de componente Oracle |
| `reports/h4/describe-powerbuilder.md` | ficha Markdown de componente PowerBuilder |
| `reports/h4/impact-cross-stack.md` | impacto Markdown de cruce PowerBuilder-Oracle |
| `reports/h4/*debug.txt` | metricas operativas enviadas a `stderr` por `--debug` |

## Metricas de muestra representativa

Fuente: `reports/h4/metrics.json`.

Muestra: grafo sintetico `tests.integration.test_describe_cli._seed_graph`.

| Metrica | Valor |
|---|---:|
| Simbolos esperados | 5 |
| Simbolos encontrados | 5 |
| Relaciones esperadas | 2 |
| Relaciones resueltas encontradas | 2 |
| Falsos positivos conocidos | 0 |
| Falsos negativos conocidos | 0 |
| Relaciones ambiguas | 0 |
| Relaciones no resueltas | 0 |
| Relaciones dinamicas | 0 |
| Relaciones externas | 0 |
| Revision humana | aceptada |

Comandos de muestra:

| Comando logico | Exit code | Duracion ms | Evidencia |
|---|---:|---:|---|
| `inventory-oracle` | 0 | 41.221 | `reports/h4/inventory-oracle.md` |
| `describe-oracle` | 0 | 58.658 | `reports/h4/describe-oracle.md` |
| `describe-powerbuilder` | 0 | 46.694 | `reports/h4/describe-powerbuilder.md` |
| `impact-cross-stack` | 0 | 37.932 | `reports/h4/impact-cross-stack.md` |
| `stats-json` | 0 | 27.521 | `reports/h4/stats-json.json` |

Nota: esta muestra fue sembrada directamente en SQLite para evaluar renderizado, trazabilidad y navegacion; por eso `latest_run_status` aparece como `running` en `stats-json`. El baseline con `analyze` real se registra aparte.

## Baseline de rendimiento

Fuente: `reports/h4/baseline-metrics.json`.

Muestra: chunks Oracle sinteticos de `tests.unit.test_inventory_cli`.

| Comando logico | Exit code | Duracion CLI ms | Evidencia |
|---|---:|---:|---|
| `analyze --full` | 0 | 183.477 | `reports/h4/baseline-analyze-full.stdout.txt` |
| `analyze` incremental sin cambios | 0 | 206.002 | `reports/h4/baseline-analyze-incremental-no-changes.stdout.txt` |
| `inventory` | 0 | 41.945 | `reports/h4/baseline-inventory.stdout.txt` |
| `describe --no-llm` | 0 | 39.357 | `reports/h4/baseline-describe-no-llm.stdout.txt` |
| `impact --depth 2 --no-llm` | 0 | 40.951 | `reports/h4/baseline-impact-depth-2-no-llm.stdout.txt` |

Runs de analisis:

| Run | Modo | Estado | Simbolos | Referencias | Resueltas | No resueltas | Ambiguas | Duracion ms |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| 1 | `full` | `completed` | 2 | 1 | 1 | 0 | 0 | 125 |
| 2 | `incremental` | `completed` | 2 | 1 | 1 | 0 | 0 | 172 |

## Validacion H1-H4

| Area | Evidencia | Resultado |
|---|---|---|
| H1 Foundation | suite completa, `test_cli`, `test_config`, `test_doctor`, smoke parcial | sin regresion en suite |
| H2 Ingestion | suite completa, `test_ingest_incremental_cli`, repositorio SQLite, corpus sintetico | sin regresion en suite |
| H3 RAG | suite completa, `test_h3_rag_cli`, RAG domain/search/index/reporting | sin regresion en suite |
| H4 Reverse Engineering | tests H4, golden files, CLI `analyze/inventory/describe/impact`, reportes H4 | suite verde; smoke instalado requiere actualizacion de contratos |

## Scan de privacidad

Comando:

```bash
rg -n "password|passwd|secret|token|api[_-]?key|jdbc:|Data Source=|User ID=|C:\\Users\\|G:\\|D:\\|Mi unidad|Produccion|Productivo|<domain-marker>" reports\h4 tests\fixtures tests\support specs\H4-ReverseEngineering --glob "!acceptance.md"
```

Resultado:

- sin secretos, rutas personales ni datos sensibles en `reports/h4`, `tests/fixtures` o `tests/support`.
- coincidencias no sensibles:
  - `token cooperativo` en el diseno;
  - texto normativo de requisitos/test-plan sobre no versionar secretos.

## Limitaciones conocidas

- SQL dinamico y llamadas PowerBuilder dinamicas pueden quedar como falsos negativos o `por_confirmar`.
- Nombres no calificados pueden producir ambiguedad; H4 debe mostrar candidatos y no resolver silenciosamente.
- El parser es heuristico; no garantiza cobertura completa de PLSQL ni PowerBuilder.
- La muestra de calidad es sintetica y pequena; no se declara porcentaje objetivo de precision.
- Smoke instalado estaba desactualizado en version esperada y migraciones esperadas durante T12; se corrige posteriormente como contrato de pruebas.
- No se ejecuto validacion con corpus privado/productivo, por privacidad y alcance.
- No se midio memoria; se registraron duraciones y conteos disponibles por CLI/SQLite.

## Falsos positivos y falsos negativos conocidos

| Tipo | Conteo | Detalle |
|---|---:|---|
| Falsos positivos conocidos | 0 | En la muestra sintetica revisada no aparecieron relaciones no esperadas. |
| Falsos negativos conocidos | 0 | En la muestra sintetica revisada se encontraron las relaciones esperadas. |
| Pendientes de revision | 0 | Feedback humano recibido; H4 se considera cerrado. |

## Decision de aceptacion

H4 queda **aceptado y cerrado**.

Condiciones revisadas antes de declarar aceptacion:

1. Revisar `reports/h4/inventory-oracle.md`.
2. Revisar `reports/h4/describe-oracle.md`.
3. Revisar `reports/h4/describe-powerbuilder.md`.
4. Revisar `reports/h4/impact-cross-stack.md`.
5. Confirmar o corregir falsos positivos y falsos negativos.
6. Revisar el addendum post-T12 de version candidata y smoke corregido.

## Addendum post-T12: version candidata 0.4.0

Despues de T12 se realizo una correccion puntual de metadata y contratos de smoke:

- version del paquete: `0.3.0` -> `0.4.0`;
- contrato smoke de `barbarion --version`: `barbarion 0.4.0`;
- contrato smoke de migraciones esperadas: `[(1,), (2,), (3,), (4,)]`.

Validacion posterior:

```bash
.pytest-tmp\h4-venv\Scripts\python.exe -m pip install -e . --no-deps --no-build-isolation
.pytest-tmp\h4-venv\Scripts\barbarion.exe --version
.pytest-tmp\h4-venv\Scripts\python.exe -m pytest --basetemp .pytest-tmp\version-smoke-reinstalled tests\smoke
```

Resultado:

- paquete editable construido e instalado como `barbarion-0.4.0`;
- CLI instalada reporta `barbarion 0.4.0`;
- `10 passed`
- `1 warning` de cache pytest por permisos sobre `.pytest_cache` en Windows.

Esta correccion queda incorporada al cierre de H4.

## Addendum de cierre: feedback humano

Fecha: 2026-06-30.

Resultado:

- H4 se da por cerrado.
- Los ajustes posteriores de `ask`, diagnostico `--debug`, validacion y repair se tratan como correcciones puntuales posteriores a T12.
- `docs/EVOLUTION.md` queda fuera del MVP y no forma parte del cierre de H4.
