# H4 - ReverseEngineering: Plan de pruebas

## 1. Objetivo

Verificar que H4 construye un catalogo tecnico trazable sobre H2/H3, extrae y resuelve relaciones heuristicas, permite navegar dependencias, describe componentes, analiza impacto basico y genera Markdown estable, todo localmente y sin depender de un LLM real.

## 2. Alcance

Incluye:

- migracion SQLite v4;
- simbolos, referencias, relaciones y candidatos;
- analisis incremental;
- CLI `analyze`, `inventory`, `describe`, `impact`;
- Markdown de inventario, componente e impacto;
- integracion con RAG H3 y fakes de LLM;
- cancelacion, errores y observabilidad;
- tres casos representativos.

Excluye:

- H5 Spec Mode;
- pruebas contra Oracle productivo;
- precision universal;
- base de grafos, Qdrant, API HTTP y UI.

## 3. Estrategia

- unit tests para normalizacion, extractores, resolucion, recorridos, renderers y rutas;
- integration tests con SQLite temporal migrada desde v3;
- CLI tests con fakes y fixtures sinteticos;
- golden files Markdown;
- pruebas incrementales y de interrupcion;
- evaluacion de calidad sobre muestra reproducible;
- smoke test del entry point instalado;
- validacion humana documentada en la ultima tarea.

## 4. Ambientes

- Windows local como ambiente principal;
- Python `>=3.12,<3.13`;
- SQLite local con WAL y FK;
- `sqlite-vec` instalado para no romper H3;
- Ollama real opcional;
- LLM fake determinista por defecto;
- `pytest --basetemp .pytest-tmp/h4` recomendado en Windows.

## 5. Fixtures y datos

### Corpus sintetico H4

Debe extender `tests/fixtures/h2_corpus` o crear fixtures H4 equivalentes sin datos privados:

- Oracle package spec/body con procedure y function;
- standalone procedure que llama package;
- trigger asociado a tabla;
- view que lee tabla;
- secuencia o sinonimo detectable;
- PowerBuilder window que abre otra ventana;
- user object con funcion;
- DataWindow con SQL `retrieve`;
- menu que invoca ventana o funcion;
- caso con referencia dinamica;
- caso con nombre ambiguo;
- documento Markdown que menciona componente.

### Casos representativos obligatorios

1. **Oracle:** package/procedure con tablas y llamadas.
2. **PowerBuilder:** window/event/function/DataWindow.
3. **Cruce PB-Oracle:** evento o DataWindow que referencia procedimiento o tabla Oracle.

La muestra debe declarar fuentes esperadas, relaciones esperadas y limites conocidos.

## 6. Pruebas unitarias

### H4-TP-001 - Inventario desde SQLite

Verifica filtros, conteos, estados, confianza, orden canonico y cero acceso al filesystem.

### H4-TP-002 - Normalizacion de simbolos

Casos Oracle quoted/unquoted, schema.package.procedure, casing, PowerBuilder identifiers, nombres vacios invalidos.

### H4-TP-003 - Extraccion Oracle/PLSQL

Detecta llamadas, packages, tablas/vistas, triggers, secuencias, sinonimos simples, SQL dinamico marcado y evita comentarios/literales.

### H4-TP-004 - Extraccion PowerBuilder

Detecta `open`, llamadas, eventos, funciones, user objects, menus, DataWindows, SQL embebido y stored procedures.

### H4-TP-005 - Resolucion exacta

Una referencia con unico simbolo candidato queda `resolved` con `target_symbol_id`.

### H4-TP-006 - Resolucion ambigua

Multiples candidatos razonables quedan `ambiguous` y se persistien candidatos.

### H4-TP-007 - Referencias no resueltas, externas y dinamicas

No inventa destinos; conserva `target_key`, razon y evidencia.

### H4-TP-008 - Persistencia de relaciones

FK, indices, estados, evidencia, candidatos, cascadas y ausencia de huerfanos. Debe verificar como minimo `symbol_references(normalized_target, resolution_status)`, `symbols(normalized_name, symbol_type, status)` y `symbols(container_name, normalized_name, status)`.

### H4-TP-009 - Recorrido por profundidad

Depth 0, 1, 2, maximo, filtros y orden estable.

### H4-TP-010 - Ciclos y limites

Ciclos reportados, limite de nodos alcanzado, sin bucles infinitos.

### H4-TP-011 - Describe estructurado

Objeto unico, inexistente, ambiguo, evidencia insuficiente, modo sin LLM y LLM fake con citas.

### H4-TP-012 - Impact estructurado

Consumidores, dependencias, cruces, unresolved, ambiguous, ciclos y clasificacion detectado/inferido/por_confirmar.

### H4-TP-013 - Deduplicacion e IDs

Misma entrada produce mismos IDs; cambios relevantes cambian IDs o status sin duplicar.

### H4-TP-014 - Formatos de salida

Text/json/markdown validos, JSON parseable y campos esperados.

### H4-TP-015 - Render Markdown

Plantillas incluyen fecha, version, parametros, fuentes, evidencia, inferencias, por confirmar y limitaciones.

### H4-TP-016 - Rutas y no sobrescritura

Nombres seguros, salida dentro de path permitido, archivo existente falla sin `--overwrite`.

### H4-TP-017 - Incrementalidad

Nuevo, cambiado, eliminado, sin cambios, referencia antes unresolved luego resolved, resolved luego unresolved, resolved luego ambiguous y ambiguous luego resolved por cambios de simbolos en otros archivos.

### H4-TP-018 - Clasificacion de confianza

Directo/high, heuristico/medium-low, dinamico/por_confirmar.

### H4-TP-019 - Cancelacion y errores

Interrupcion marca run `interrupted`, rollback del archivo/scope actual, conserva archivos ya confirmados, codigo 130 y errores esperados sin traceback.

### H4-TP-020 - CLI argumentos y codigos

Help en espanol, argumentos invalidos codigo 2, errores operativos codigo 1, exitos codigo 0.

## 7. Pruebas de integracion

### INT-H4-01 - Migracion v4 desde v3

DB v3 con corpus H2/H3 migra a v4, conserva datos previos y crea tablas H4.

### INT-H4-02 - Analyze full

Ejecuta `analyze --full` con corpus H4 y persiste simbolos, referencias y relaciones.

### INT-H4-03 - Analyze incremental sin cambios

Repetir no reprocesa ni duplica; conteos unchanged correctos.

### INT-H4-04 - Archivo modificado

Una modificacion cambia solo simbolos/relaciones afectados.

### INT-H4-05 - Archivo eliminado

Simbolos y relaciones dejan de estar vigentes sin huerfanos.

### INT-H4-06 - Resolucion posterior

Una referencia no resuelta se resuelve cuando aparece el simbolo destino en una corrida posterior.

### INT-H4-07 - Ambiguedad posterior

Una relacion antes resuelta pasa a ambigua si aparece un segundo candidato razonable.

### INT-H4-08 - Dependencias con ciclos

Recorrido devuelve ciclos y no bloquea describe/impact.

### INT-H4-09 - Describe con RAG fake

Usa SearchService/ContextBuilder con fakes y conserva fuentes.

### INT-H4-10 - Impact cruzado PB-Oracle

Detecta relacion entre PowerBuilder y Oracle con evidencia.

### INT-H4-11 - Resumen de analyze y observabilidad

Runs, conteos, duraciones, claves afectadas, referencias re-resueltas y limites coinciden con salida CLI.

### INT-H4-12 - Sin red externa

La suite con fakes no intenta internet ni servicios cloud.

## 8. Pruebas CLI

- `barbarion analyze --help`;
- `barbarion analyze --dry-run`;
- `barbarion analyze --full`;
- `barbarion inventory --format text|json|markdown`;
- `barbarion inventory --output ...`;
- `barbarion describe OBJETO --no-llm`;
- `barbarion describe OBJETO --format json`;
- `barbarion describe OBJETO --output ...`;
- `barbarion impact OBJETO --depth 2 --no-llm`;
- `barbarion impact OBJETO --direction incoming|outgoing|both`;
- objeto inexistente;
- multiples coincidencias;
- profundidad invalida;
- salida sin Ollama;
- codigos 0, 1, 2 y 130.

## 9. Golden files

Golden files minimos:

- `inventory.md`;
- `component-oracle.md`;
- `component-powerbuilder.md`;
- `impact-cross-stack.md`;
- `impact-cycle.md`;
- `impact-unresolved.md`;
- `component-partial-evidence.md`.

Reglas:

- fechas pueden fijarse con clock fake;
- IDs y orden canonico;
- contenido LLM fake determinista;
- no rutas personales;
- secciones obligatorias siempre presentes.

## 10. Pruebas de migracion

- base vacia -> v4;
- v1 -> v4;
- v2 -> v4;
- v3 -> v4;
- migracion idempotente;
- version futura falla;
- FK activas;
- WAL activo;
- rollback si una sentencia falla.

## 11. Pruebas incrementales

Escenarios:

| Escenario | Esperado |
|---|---|
| nuevo archivo Oracle | nuevos simbolos y relaciones |
| nuevo archivo PowerBuilder | nuevos simbolos y relaciones |
| cambio de nombre de procedure | simbolo anterior stale/deleted y nuevo active |
| cambio solo de comentario | no genera relaciones nuevas |
| archivo eliminado | relaciones no vigentes y sin huerfanos |
| destino aparece despues | referencia de archivo sin cambios pasa unresolved -> resolved |
| destino duplicado aparece despues | referencia de archivo sin cambios pasa resolved -> ambiguous |
| destino eliminado despues | referencia de archivo sin cambios pasa resolved -> unresolved |
| ambiguedad resuelta despues | referencia de archivo sin cambios pasa ambiguous -> resolved |
| cambia contenedor o nombre normalizado | se re-resuelven referencias que coinciden con claves afectadas |
| interrupcion | run interrupted, archivos confirmados siguen vigentes y sin reconciliacion insegura |

## 12. Pruebas de interrupcion

Simular `KeyboardInterrupt`:

- durante seleccion;
- durante extraccion;
- durante resolucion;
- durante persistencia;
- durante escritura Markdown.

Resultados esperados:

- codigo 130;
- run `interrupted`;
- transaccion del archivo/scope actual revertida;
- archivos ya confirmados siguen consistentes;
- no se marca como vigente un archivo/scope incompleto.

## 13. Pruebas de rendimiento

Sin linea base previa, H4-T12 debe registrar:

1. `analyze --full`;
2. `analyze` incremental sin cambios;
3. incremental con 1 % de archivos modificados;
4. `inventory`;
5. `describe --no-llm`;
6. `impact --depth 2 --no-llm`.

Metricas:

- duracion total;
- duracion por etapa;
- simbolos/s;
- relaciones/s;
- nodos recorridos;
- limite alcanzado;
- memoria si existe forma simple de medirla.

No se fija umbral de precision o rendimiento sin la medicion inicial; la tarea final registra baseline y criterio relativo para iteraciones futuras.

## 14. Evaluacion de calidad de relaciones

Para cada caso representativo:

- simbolos esperados;
- relaciones esperadas;
- relaciones no esperadas importantes;
- falsos positivos;
- falsos negativos conocidos;
- referencias unresolved/ambiguous justificadas;
- utilidad de `describe`;
- utilidad de `impact`;
- evidencia por hallazgo;
- revision humana.

Metricas iniciales:

- `expected_symbols_found / expected_symbols`;
- `expected_relations_found / expected_relations`;
- conteo de falsos positivos;
- conteo de falsos negativos conocidos;
- porcentaje de relaciones con evidencia;
- relaciones ambiguous/unresolved por caso.

No se declara porcentaje objetivo hasta tener muestra cerrada; el criterio de aceptacion inicial es que los tres casos produzcan evidencia revisable y al menos dos sean utiles para el revisor humano sin rehacer toda la investigacion.

## 15. Validacion manual

La ultima tarea debe pedir revision humana de:

- inventario del caso;
- ficha Oracle;
- ficha PowerBuilder;
- impacto cruzado;
- falsos positivos/negativos;
- puntos por confirmar;
- utilidad practica.

La evidencia se registra en `specs/H4-ReverseEngineering/acceptance.md` solo durante H4-T12.

## 16. Matriz requisito-prueba

| Requisito | Pruebas principales |
|---|---|
| H4-RF-001 | TP-001, TP-014, TP-020, INT-H4-11 |
| H4-RF-002 | TP-002, TP-013, TP-017, INT-H4-02 |
| H4-RF-003 | TP-003, TP-004, TP-018, INT-H4-02 |
| H4-RF-004 | TP-005, TP-006, TP-007, INT-H4-06, INT-H4-07 |
| H4-RF-005 | TP-008, TP-013, TP-017 |
| H4-RF-006 | TP-009, TP-010, INT-H4-08 |
| H4-RF-007 | TP-011, TP-015, TP-020, INT-H4-09 |
| H4-RF-008 | TP-012, TP-015, INT-H4-10 |
| H4-RF-009 | TP-015, TP-016, golden files |
| H4-RF-010 | TP-017, TP-019, INT-H4-03 a INT-H4-07 |
| H4-RF-011 | TP-019, TP-020, INT-H4-11 |
| H4-RF-012 | calidad, validacion manual, H4-T12 |
| H4-RNF-001 | INT-H4-12 |
| H4-RNF-002 | TP-011, TP-012, TP-015 |
| H4-RNF-003 | TP-019, migracion/incremental |
| H4-RNF-004 | TP-013, TP-017 |
| H4-RNF-005 | rendimiento |
| H4-RNF-006 | TP-009, TP-010 |
| H4-RNF-007 | golden files |
| H4-RNF-008 | smoke Windows/Python 3.12 |
| H4-RNF-009 | revision estructural/imports |
| H4-RNF-010 | scan de fixtures/logs/reportes |
| H4-RNF-011 | suite completa H1-H3 |
| H4-RNF-012 | TP-011, TP-012, CLI sin Ollama |

## 17. Criterios para declarar H4 listo para aceptacion

- todos los Must tienen pruebas pasando;
- SQLite v4 migra desde v3 sin perdida de H2/H3;
- `analyze` full e incremental son idempotentes;
- referencias de archivos sin cambios se re-resuelven cuando cambian simbolos destino;
- no quedan relaciones vigentes huerfanas;
- referencias ambiguas y no resueltas son visibles;
- `inventory`, `describe` e `impact` funcionan sin LLM;
- salidas Markdown son validas, estables y no sobrescriben silenciosamente;
- ciclos y limites se reportan;
- los tres casos representativos tienen evidencia revisable;
- al menos dos casos son utiles segun revision humana;
- suite completa no presenta regresiones H1/H2/H3;
- smoke test instalado pasa o sus limitaciones quedan justificadas;
- no hay Qdrant, base de grafos, API HTTP, UI ni H5 implementado;
- no hay secretos, rutas personales ni datos sensibles en fixtures/reportes;
- `acceptance.md` se crea solo en la ultima tarea de implementacion con evidencia real.
