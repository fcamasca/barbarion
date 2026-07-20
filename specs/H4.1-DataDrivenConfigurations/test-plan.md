# H4.1 - Configuraciones Data-Driven: Plan de pruebas

## 1. Objetivo

Verificar que H4.1 analiza configuraciones Data-Driven desde sentencias DML
contenidas en archivos `.sql` declarados, sin ejecutar SQL ni formulas,
generando simbolos, referencias y relaciones trazables e integradas con H4, H3
y H5.

## 2. Alcance

Incluye:

- configuracion TOML Data-Driven;
- clasificacion controlada de archivos `.sql`;
- parser `INSERT` y `UPDATE` acotado;
- registros canonicos;
- simbolos `configuration_*`;
- referencias explicitas, jerarquicas, secuenciales, formulas y tokens;
- resolucion hacia configuraciones, Oracle y PowerBuilder;
- incrementalidad, reconciliacion y cancelacion;
- CLI H4 existente;
- observabilidad;
- regresion H1-H5;
- aceptacion tecnica final.

Excluye:

- pruebas contra Oracle real;
- ejecucion de SQL;
- ejecucion de formulas;
- parser SQL universal;
- ETL generico;
- precision funcional universal;
- UI, API HTTP, agentes o base de grafos.

## 3. Estrategia

- unit tests para configuracion, DML parser, valores, simbolos, referencias,
  formulas, resolucion y diagnostics;
- integration tests con SQLite temporal y corpus DML sintetico;
- CLI tests para `ingest`, `analyze`, `inventory`, `describe`, `impact`,
  `stats`, `search`, `ask` y `spec create`;
- golden files Markdown para inventario, descripcion e impacto Data-Driven;
- pruebas negativas con DML no soportado y configuracion invalida;
- pruebas incrementales con archivos nuevos, modificados y eliminados;
- smoke test instalado y regresion H1-H5;
- validacion humana de una muestra.

## 4. Ambientes

- Windows local como ambiente principal;
- Python `>=3.12,<3.13`;
- SQLite local schema vigente;
- sqlite-vec instalado para no romper H3;
- Ollama real opcional;
- suite normal sin red y sin LLM real;
- `pytest --basetemp .pytest-tmp/h41` recomendado.

## 5. Fixtures y datos

### Corpus sintetico minimo

```text
sources/
  config/
    pricing_rules.sql
    formula_variables.sql
    process_steps.sql
  oracle/
    pkg_pricing.pkb
    fn_tax_rate.fnc
  powerbuilder/
    w_pricing.srw
```

Contenido esperado:

- `INSERT` con lista de columnas;
- `INSERT` sin columnas usando `default_column_order`;
- `UPDATE` con identidad completa;
- `UPDATE` sin identidad completa;
- `TO_DATE`, `DATE`, `NULL`, numeros, strings largos y placeholders;
- formula con `{AMOUNT}`, `${RATE}` y llamada `TAX_RATE()`;
- referencia hacia procedure Oracle;
- referencia hacia objeto PowerBuilder;
- jerarquia padre-hijo;
- secuencia de pasos;
- sentencia no soportada `INSERT ... SELECT`.

Los nombres deben ser sinteticos y no contener datos del dominio privado.

## 6. Pruebas unitarias

### H4.1-TP-001 - Configuracion valida

Valida `[data_driven]`, configuraciones, tablas, columnas, patrones y limites.

### H4.1-TP-002 - Configuracion invalida

Rechaza claves desconocidas, `identity_columns` vacio, `reference_columns`
mal formado, patrones invalidos y limites fuera de rango.

### H4.1-TP-003 - Clasificacion de archivos

`.sql` declarado pasa a `configuration` solo si Data-Driven esta habilitado, el
archivo coincide con `file_patterns` y la sentencia afecta una tabla declarada;
`.sql` no declarado sigue como `oracle`; `.dml` no se reconoce.

### H4.1-TP-004 - Splitter de sentencias

Separa por `;` fuera de strings, comentarios y expresiones soportadas. Acepta
la ultima sentencia sin `;` al final del archivo solo si no quedan strings,
comentarios o delimitadores abiertos y el parser la interpreta de forma segura.
Neutraliza lineas SQL*Plus `PROMPT` y `SET` sin modificar su longitud ni los
saltos de linea. Un caso con comentario de cabecera, directivas antes y entre
dos `INSERT` verifica que ambos registros conserven sus lineas originales.

### H4.1-TP-005 - INSERT soportado

Parsea columnas, valores, schema/table, strings, numeros, `NULL`, fechas,
placeholders y multilinea.

### H4.1-TP-006 - INSERT no soportado

`INSERT ... SELECT`, `INSERT ALL`, subquery y `RETURNING` generan diagnostico
recuperable. Los `INSERT` internos de un bloque `BEGIN` o `DECLARE` no se
interpretan como sentencias independientes. `COMMIT` se omite mediante un
diagnostico recuperable.

### H4.1-TP-007 - UPDATE soportado

Parsea `SET` y `WHERE` con identidad completa y `AND`.

### H4.1-TP-008 - UPDATE no identificable

`WHERE` sin identidad declarada no genera registro activo y reporta warning.

### H4.1-TP-009 - Recuperacion de errores

Una sentencia malformada no detiene las siguientes.

### H4.1-TP-010 - Limites de seguridad

`max_statements_per_file` y `max_literal_chars` cortan procesamiento con
mensaje accionable.

### H4.1-TP-011 - Registro canonico

Identidad, tabla, operacion, ordinal, lineas y hash son deterministas.

### H4.1-TP-012 - Duplicados

Duplicados en archivo y entre archivos producen resultado estable y warning o
ambiguedad segun regla.

### H4.1-TP-013 - Simbolos Data-Driven

Crea `configuration_entity`, `configuration_record` y simbolos hijos con
tecnologia `configuration`. La identidad de cada hijo usa registro padre, tipo
y columna; cambiar solamente el valor conserva `symbol_id`, nombre canonico,
padre y tipo, mientras actualiza `metadata.value` y `metadata.source_hash`.

### H4.1-TP-014 - Estado activo/inactivo

`status_columns` mapea valores activos e inactivos; valores desconocidos quedan
por confirmar.

### H4.1-TP-015 - Referencias entre configuraciones

`reference_columns` resuelve registro unico, ambiguo y no resuelto. Cuando
declara `target_configuration` y un `target_type` semantico compatible,
reutiliza el indice `configuracion.valor` de simbolos activos y restringe la
busqueda por ambos campos.

### H4.1-TP-016 - Jerarquia y secuencia

`parent_columns` produce `parent_of`; `sequence_columns` queda como metadata.
Solo una entrada de `reference_columns` con `relation_type = "precedes"`
produce relacion si identifica destino.

### H4.1-TP-017 - Referencias Oracle/PowerBuilder

Columnas declaradas resuelven hacia simbolos Oracle/PB existentes.

### H4.1-TP-018 - Referencias dinamicas y externas

Placeholders, concatenaciones y patrones externos conservan estado correcto.

### H4.1-TP-019 - Formula tokens

Extrae tokens configurados, variables, parametros y llamadas candidatas. Los
aliases `configuracion.valor` se indexan en memoria solo desde simbolos activos:
un destino compatible resuelve, varios quedan ambiguos y ninguno queda no
resuelto. `[@...]` solo busca variables y `[%...]` solo parametros declarados.

### H4.1-TP-020 - Formula no evaluada

Expresiones incompletas o dinamicas no se ejecutan ni interpretan.

### H4.1-TP-021 - Persistencia H4

Verifica upsert, FK, metadata JSON, candidatos y ausencia de huerfanos.

### H4.1-TP-022 - Idempotencia

Dos ejecuciones equivalentes conservan IDs, conteos y orden. Referencias y
relaciones generales no aumentan en la segunda corrida.

### H4.1-TP-023 - Reconciliacion

Archivo modificado o eliminado actualiza solo conocimiento afectado. Los
simbolos reemplazados permanecen `stale` para auditoria; referencias obsoletas,
que no tienen estado de vigencia, se retiran junto con sus relaciones.

### H4.1-TP-024 - Inventory/describe

Inventario y descripcion muestran configuraciones, columnas clave, formulas,
referencias y evidencia. El inventario sin filtro de estado muestra solo
simbolos activos; `--status stale` permite consultar el historico.

### H4.1-TP-025 - Impact

Impacto muestra cruces configuration/oracle/powerbuilder, ambiguous,
unresolved, dynamic y external.

### H4.1-TP-026 - H3/H5

RAG recupera chunks DML y H5 recibe componentes Data-Driven desde H4.

### H4.1-TP-027 - CLI

Help en espanol, argumentos invalidos codigo 2, errores codigo 1, exito codigo
0 e interrupcion codigo 130.

### H4.1-TP-028 - Observabilidad

Conteos y duraciones coinciden con SQLite y salida CLI. El total general usa
referencias vigentes y cumple `resolved + ambiguous + no_resueltas =
referencias`, donde `no_resueltas` agrega `unresolved + dynamic + external`.
El desglose Data-Driven del mismo alcance produce el mismo total sin duplicados.

### H4.1-TP-029 - Seguridad local

La suite no intenta red, no ejecuta SQL y no llama LLM real.

## 7. Pruebas de integracion

### INT-H4.1-01 - Ingesta de SQL Data-Driven declarado

`ingest` procesa archivos `.sql` declarados y persiste
`artifact_kind='configuration'` solo para los que cumplen la regla conjuntiva.

### INT-H4.1-02 - Ingesta sin Data-Driven

Con `enabled=false`, `.sql` conserva comportamiento Oracle y no genera simbolos
de configuracion.

### INT-H4.1-03 - Analyze full

`analyze --full` crea entidad, registros, referencias y relaciones.

### INT-H4.1-04 - Analyze incremental sin cambios

Repetir no duplica ni reprocesa innecesariamente.

### INT-H4.1-05 - Archivo SQL Data-Driven modificado

Cambio de formula o referencia actualiza relaciones afectadas.

### INT-H4.1-06 - Archivo SQL Data-Driven eliminado

Simbolos y relaciones dejan de estar vigentes sin huerfanos.

### INT-H4.1-07 - Destino aparece despues

Referencia no resuelta pasa a `resolved` cuando aparece el simbolo destino.

### INT-H4.1-08 - Destino se vuelve ambiguo

Relacion resuelta pasa a `ambiguous` cuando aparece segundo candidato.

### INT-H4.1-09 - Sin migracion obligatoria

El conocimiento Data-Driven se persiste en tablas H4 existentes. La prueba
verifica que no se requiere migracion ni tabla `configuration_records`.

### INT-H4.1-10 - Spec Mode

`spec create --no-llm` incluye componente Data-Driven afectado y valida la spec.

### INT-H4.1-11 - Sin red externa

La suite con fakes no intenta internet ni servicios cloud.

## 8. Pruebas CLI

- `barbarion config show`;
- `barbarion ingest --full`;
- `barbarion analyze --dry-run`;
- `barbarion analyze --full`;
- `barbarion analyze`;
- `barbarion inventory --technology configuration --format text|json|markdown`;
- `barbarion describe pricing_rules.R001 --no-llm`;
- `barbarion impact PKG_PRICING.CALCULATE --direction incoming --no-llm`;
- `barbarion stats --format json`;
- `barbarion search "pricing_rules" --mode keyword`;
- `barbarion ask "Donde se configura pricing_rules?" --no-llm`;
- `barbarion spec create "Cambiar regla pricing_rules" --no-llm`;
- configuracion invalida;
- carpeta existente sin overwrite en artefactos Markdown;
- interrupcion durante analyze.

## 9. Golden files

Golden files minimos:

- `data-driven-inventory.md`;
- `data-driven-describe-record.md`;
- `data-driven-impact-oracle.md`;
- `data-driven-impact-powerbuilder.md`;
- `data-driven-spec-requirements.md` si H5 produce salida estable con fake;
- `data-driven-validation-errors.json`.

Reglas:

- fechas fijadas con clock fake;
- IDs deterministas;
- orden canonico;
- sin rutas personales;
- sin datos reales de dominio;
- secciones obligatorias presentes.

## 10. Casos negativos

| Caso | Esperado |
|---|---|
| `data_driven.enabled=false` | no cambia comportamiento previo |
| tabla no declarada | no genera conocimiento Data-Driven |
| tabla declarada en archivo fuera de `file_patterns` | no reclasifica el archivo |
| archivo dentro de `file_patterns` con tabla no declarada | omite esa sentencia para Data-Driven |
| `INSERT ... SELECT` | warning, sentencia omitida |
| `UPDATE` sin identidad | warning, sin simbolo activo |
| `UPDATE` identificable sin `INSERT` previo | simbolo parcial con metadata de parcialidad |
| formula con placeholder dinamico | relacion `dynamic` o `por_confirmar` |
| referencia a destino ausente | `unresolved`, visible |
| multiples destinos | `ambiguous` con candidatos |
| archivo enorme | limite H2/H4.1 accionable |
| config TOML invalida | codigo 2 |
| Ctrl+C | codigo 130, sin unidad parcial vigente |

## 11. Pruebas de regresion

La aceptacion final debe ejecutar:

- H1 configuracion, doctor, CLI base;
- H2 ingesta, chunking, incrementalidad;
- H3 index, search, ask y reportes donde aplique;
- H4 analyze, inventory, describe, impact;
- H5 spec create y validate;
- smoke test instalado.

H4.1 no debe cambiar comportamiento cuando Data-Driven esta deshabilitado.

## 12. Pruebas de rendimiento

Mediciones iniciales:

1. `analyze --full` con corpus `.sql` Data-Driven sintetico;
2. `analyze` incremental sin cambios;
3. incremental con 1 archivo DML modificado;
4. `inventory --technology configuration`;
5. `describe --no-llm`;
6. `impact --depth 2 --no-llm`;
7. `spec create --no-llm` con evidencia Data-Driven.

Metricas:

- duracion total;
- duracion por etapa;
- sentencias/s;
- registros/s;
- simbolos/s;
- referencias/s;
- relaciones/s;
- memoria si existe medicion simple.

No se fija umbral duro sin baseline. H4.1-T12 registra medicion y criterio
relativo para iteraciones futuras.

## 13. Evaluacion de calidad

Para cada caso representativo:

- registros esperados;
- simbolos esperados;
- referencias esperadas;
- relaciones esperadas;
- falsos positivos;
- falsos negativos conocidos;
- ambiguedades justificadas;
- sentencias omitidas justificadas;
- utilidad de `describe`;
- utilidad de `impact`;
- evidencia por hallazgo;
- revision humana.

Metricas iniciales:

- `expected_records_found / expected_records`;
- `expected_symbols_found / expected_symbols`;
- `expected_relations_found / expected_relations`;
- conteo de falsos positivos;
- conteo de falsos negativos conocidos;
- porcentaje de relaciones con evidencia;
- conteo de `ambiguous`, `dynamic`, `external` y `unresolved`.

## 14. Validacion manual

La ultima tarea debe pedir revision humana de:

- declaracion TOML;
- inventario Data-Driven;
- descripcion de una configuracion;
- impacto cruzado hacia Oracle/PowerBuilder;
- formulas/tokens detectados;
- warnings de DML no soportado;
- falsos positivos y falsos negativos;
- utilidad practica.

La evidencia se registra en `acceptance.md` solo durante H4.1-T12.

## 15. Matriz requisito-prueba

| Requisito | Pruebas principales |
|---|---|
| H4.1-REQ-001 | TP-001, TP-002 |
| H4.1-REQ-002 | TP-003, INT-01, INT-02 |
| H4.1-REQ-003 | TP-004, TP-005, TP-006 |
| H4.1-REQ-004 | TP-007, TP-008 |
| H4.1-REQ-005 | TP-009, TP-010 |
| H4.1-REQ-006 | TP-011, TP-012 |
| H4.1-REQ-007 | TP-013, TP-014 |
| H4.1-REQ-008 | TP-015, TP-016 |
| H4.1-REQ-009 | TP-017, TP-018 |
| H4.1-REQ-010 | TP-019, TP-020 |
| H4.1-REQ-011 | TP-021, INT-09 |
| H4.1-REQ-012 | TP-022, TP-023, INT-03..08 |
| H4.1-REQ-013 | TP-024, TP-025 |
| H4.1-REQ-014 | TP-026, INT-10 |
| H4.1-REQ-015 | TP-027 |
| H4.1-REQ-016 | TP-028 |
| H4.1-REQ-017 | TP-029, INT-11 |

## 16. Evidencia esperada para aceptacion

- comandos ejecutados;
- suite completa;
- smoke instalado;
- regresion H1-H5;
- corpus DML sintetico;
- configuracion TOML;
- metricas de DML;
- salidas Markdown;
- spec H5 con evidencia Data-Driven;
- scan de datos sensibles;
- confirmacion de no ejecucion de SQL/formulas;
- revision humana;
- decision final.

## 17. Criterios para declarar H4.1 listo para aceptacion

- todos los requisitos Must tienen pruebas pasando;
- Data-Driven deshabilitado no cambia H1-H5;
- parser DML soporta solo el subconjunto definido;
- sentencias no soportadas son recuperables;
- simbolos, referencias y relaciones son trazables;
- resolucion es conservadora;
- incrementalidad e idempotencia pasan;
- inventario, descripcion e impacto incluyen configuraciones;
- H3/H5 consumen conocimiento por contratos existentes;
- suite normal no requiere red, LLM real ni base de datos externa;
- no hay secretos ni datos reales en fixtures/reportes;
- aceptacion documentada solo en la ultima tarea.
