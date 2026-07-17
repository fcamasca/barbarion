# H4.1 - Configuraciones Data-Driven: Requisitos

## 1. Proposito

H4.1 incorpora al catalogo tecnico de Barbarion configuraciones Data-Driven
representadas por sentencias DML contenidas en archivos `.sql` exportados. DML
describe sentencias como `INSERT` y `UPDATE`; no es una extension de archivo.
El hito debe identificar fuentes declaradas, parsear un subconjunto seguro de
DML, extraer registros y valores relevantes, construir simbolos de
configuracion y relacionarlos de forma conservadora con otras configuraciones y
con simbolos Oracle/PowerBuilder existentes.

La capacidad debe ser incremental, local, determinista y trazable. No debe
ejecutar SQL, formulas, reglas ni conectarse a una base de datos.

## 2. Alcance

### Incluido

- declaracion TOML explicita de fuentes, tablas y columnas Data-Driven;
- clasificacion controlada de archivos `.sql` declarados como configuracion;
- soporte inicial para `INSERT` y `UPDATE` en sintaxis acotada;
- sentencias multilinea y separacion segura por `;` fuera de literales;
- ultima sentencia sin `;` aceptable si el splitter queda en estado cerrado y
  el parser puede interpretarla con seguridad;
- extraccion de registros, claves, nombres, descripciones, reglas, formulas,
  variables, parametros, referencias, jerarquias, secuencias, estado y vigencia;
- simbolos Data-Driven dentro de `symbols`;
- referencias Data-Driven dentro de `symbol_references`;
- relaciones y candidatos dentro de `relations` y `relation_candidates`;
- metadatos JSON para conservar sentencia, ordinal, tabla, columnas y valores;
- reconciliacion incremental ante archivos modificados o eliminados;
- integracion con `analyze`, `inventory`, `describe`, `impact`, `stats`,
  renderers text/json/markdown, RAG H3 y H5;
- observabilidad y errores recuperables.

### Excluido

- conexion directa o automatica a bases de datos;
- ejecucion de DML, SQL dinamico, formulas o reglas;
- validacion contra esquema Oracle real;
- parser SQL universal;
- `INSERT ... SELECT`, `MERGE`, `DELETE`, `PL/SQL blocks` y `COPY`;
- archivos o extension `.dml`;
- ETL generico o framework universal de configuraciones;
- motor de reglas, formulas o workflows;
- inferencia funcional completa mediante LLM;
- modificacion de archivos fuente o configuraciones de origen;
- UI, API HTTP, VS Code, agentes, microservicios o base de grafos;
- redisenos de H2, H3, H4 o H5;
- aceptacion tecnica durante la elaboracion de este spec.

## 3. Actores

- **Analista tecnico:** revisa configuraciones, relaciones y evidencia.
- **Desarrollador legacy:** evalua dependencias e impacto de cambios en
  configuraciones.
- **Lider tecnico:** valida riesgos, ambiguedades y alcance.
- **Validador experto:** confirma utilidad y falsos positivos sobre una muestra
  autorizada.

## 4. Supuestos y dependencias

- H1, H2, H3, H4 y H5 estan cerrados para el MVP `0.5.0`.
- SQLite v4 y tablas H4 permanentes ya existen.
- Los archivos `.sql` con sentencias DML son exportaciones locales autorizadas,
  no una base viva.
- La semantica funcional de una tabla no se infiere sin declaracion TOML minima.
- `generated_artifacts` vigente usa `run_id`, `relative_path`,
  `content_sha256` y `metadata_json`.
- El usuario puede declarar varias tablas de configuracion, pero H4.1 no intenta
  descubrir automaticamente cualquier modelo Data-Driven.
- Si una decision no puede deducirse del repositorio y cambia materialmente el
  alcance, se documenta como decision pendiente.

## 5. Convenciones

- **Must:** obligatorio para aceptar H4.1.
- **Should:** requerido salvo limitacion justificada.
- Los estados de resolucion reutilizan `resolved`, `ambiguous`, `dynamic` y
  `external`; H4.1 tambien conserva `unresolved` porque ya existe en el codigo
  H4 vigente aunque no estuviera listado en el prompt.
- Clasificacion de hallazgos: `detectado`, `inferido`, `por_confirmar`.
- Tipos permanentes de simbolo no usan `h41_*`.
- La tecnologia para configuraciones es `configuration`.
- El tipo de artefacto de ingesta para DML de configuracion debe ser
  `configuration`, no `oracle`, cuando el archivo coincida con una declaracion
  Data-Driven.
- Un archivo `.sql` solo se procesa como Data-Driven si se cumplen
  simultaneamente `data_driven.enabled = true`, un `file_pattern` declarado y
  una sentencia contra una tabla declarada.
- H4.1 no introduce ni reconoce la extension `.dml`.

## 6. Requisitos funcionales

### H4.1-REQ-001 - Declaracion Data-Driven en TOML

**Descripcion:** Barbarion debe aceptar una seccion TOML explicita para declarar
que archivos, tablas y columnas representan configuraciones.

**Prioridad:** Must.

**Criterios de aceptacion:**

- existe una seccion `[data_driven]` deshabilitada por defecto;
- permite declarar `file_patterns` de archivos `.sql` y tablas mediante entradas
  `[[data_driven.configurations]]`;
- cada entrada exige `name`, `tables`, `identity_columns` y `symbol_type`;
- puede declarar columnas opcionales `name_columns`, `description_columns`,
  `rule_columns`, `formula_columns`, `variable_columns`, `parameter_columns`,
  `mapping_columns`, `reference_columns`, `parent_columns`, `sequence_columns`,
  `status_columns`, `effective_from_columns`, `effective_to_columns` y
  `metadata_columns`;
- rechaza claves desconocidas y configuraciones incompletas con mensajes en
  espanol;
- no expone un separador configurable; `;` es una regla interna fija del
  splitter DML;
- no cambia el comportamiento de ingesta si `data_driven.enabled = false`.

**Diseno:** H4.1-DD-001, H4.1-DD-002.  
**Pruebas:** H4.1-TP-001, H4.1-TP-002.  
**Tareas:** H4.1-T01.

### H4.1-REQ-002 - Identificacion controlada de archivos DML

**Descripcion:** Solo archivos declarados como Data-Driven deben alimentar el
analisis de configuraciones.

**Prioridad:** Must.

**Criterios de aceptacion:**

- solo archivos `.sql` pueden clasificarse como candidatos Data-Driven;
- un archivo `.sql` se procesa como configuracion solo si `data_driven.enabled`
  es `true`, coincide con un `file_pattern` declarado y la sentencia analizada
  afecta una tabla declarada en `data_driven.configurations`;
- archivos Oracle fuente existentes siguen siendo `artifact_kind='oracle'`
  salvo cumplimiento simultaneo de esas tres condiciones;
- la clasificacion queda persistida en `files.artifact_kind`;
- los metadatos del documento registran la configuracion declarada aplicada;
- archivos no declarados no generan simbolos de configuracion;
- mencionar o utilizar una tabla declarada dentro de codigo Oracle no
  reclasifica automaticamente el archivo como `configuration`;
- una sentencia contra una tabla no declarada dentro de un archivo que coincide
  con `file_patterns` no genera simbolos ni relaciones de configuracion;
- la identificacion de tablas por contenido nunca reemplaza la declaracion
  explicita mediante `file_patterns`.

Regla conceptual:

```text
archivo .sql
    + Data-Driven habilitado
    + patron de archivo declarado
    + tabla declarada
    = configuracion Data-Driven
```

**Diseno:** H4.1-DD-002, H4.1-DD-003.  
**Pruebas:** H4.1-TP-003, INT-H4.1-01.  
**Tareas:** H4.1-T02, H4.1-T05.

### H4.1-REQ-003 - Parsing estatico de `INSERT`

**Descripcion:** Parsear `INSERT` acotados sin ejecutar SQL.

**Prioridad:** Must.

**Sintaxis minima soportada:**

```sql
INSERT INTO [schema.]table (col1, col2, ...)
VALUES (literal1, literal2, ...);
```

**Variantes admitidas:**

- `INSERT INTO table VALUES (...)` solo si la declaracion TOML define
  `default_column_order`;
- nombres con o sin esquema;
- identificadores entre comillas dobles;
- literales string con comillas simples escapadas por `''`;
- numeros enteros y decimales;
- `NULL`;
- fechas como literales o wrappers no evaluados `DATE 'YYYY-MM-DD'`,
  `TO_DATE('...', '...')`, `TIMESTAMP '...'`;
- textos extensos dentro de literales, incluyendo saltos de linea;
- placeholders y variables como `:name`, `&name`, `${name}` conservados como
  valores dinamicos;
- funciones simples como expresiones no evaluadas cuando ocupan un valor.

**Variantes no admitidas:**

- `INSERT ... SELECT`;
- `INSERT ALL`;
- subqueries;
- `RETURNING`;
- hints que alteren estructura;
- DML dentro de bloques PL/SQL;
- comentarios que corten tokens de forma no recuperable.

**Criterios de aceptacion:**

- cada sentencia soportada produce un registro canonico;
- cada valor conserva texto original, tipo estatico y posicion;
- expresiones o funciones no evaluadas se marcan como `dynamic` o
  `por_confirmar` segun su uso;
- sentencias no soportadas generan warning recuperable y no detienen el archivo.

**Diseno:** H4.1-DD-004, H4.1-DD-005.  
**Pruebas:** H4.1-TP-004, H4.1-TP-005, H4.1-TP-006.  
**Tareas:** H4.1-T03.

### H4.1-REQ-004 - Parsing estatico de `UPDATE`

**Descripcion:** Parsear `UPDATE` acotados para capturar modificaciones de
registros declarados.

**Prioridad:** Should.

**Sintaxis minima soportada:**

```sql
UPDATE [schema.]table
SET col1 = literal1, col2 = literal2
WHERE key_col = literal [AND key_col2 = literal2 ...];
```

**Variantes admitidas:**

- nombres con o sin esquema;
- asignaciones literales, `NULL`, fecha, placeholder o expresion no evaluada;
- condiciones `AND` con igualdad sobre columnas de identidad declaradas;
- multilinea.

**Variantes no admitidas:**

- subqueries en `SET` o `WHERE`;
- `OR`, `IN`, `LIKE`, rangos o condiciones complejas;
- `UPDATE` con join;
- `RETURNING`;
- expresiones que no permitan identificar el registro.

**Criterios de aceptacion:**

- solo se convierte en registro si `WHERE` cubre columnas de identidad;
- si no se puede identificar el registro, la sentencia queda como warning y no
  genera simbolo;
- valores actualizados pueden complementar logicamente un registro previamente
  encontrado dentro del mismo archivo y ejecucion;
- si no existe un `INSERT` previo, puede producir una representacion parcial
  solo con identidad y valores demostrables por el `UPDATE`;
- esa representacion parcial queda marcada en `metadata_json`;
- no se intenta conocer el estado previo real de la base ni se consulta una base
  de datos para completar informacion faltante.

**Diseno:** H4.1-DD-004, H4.1-DD-006.  
**Pruebas:** H4.1-TP-007, H4.1-TP-008.  
**Tareas:** H4.1-T03.

### H4.1-REQ-005 - Recuperacion ante DML no reconocido

**Descripcion:** El parser debe continuar despues de sentencias no soportadas.

**Prioridad:** Must.

**Criterios de aceptacion:**

- separa sentencias por `;` fuera de strings y comentarios;
- registra numero de sentencia, rango de lineas, tipo detectado y razon de
  omision;
- errores de una sentencia no invalidan las demas;
- si un archivo excede limites configurados, queda error recuperable o skipped
  segun H2;
- no se guarda contenido completo en logs por defecto.

**Diseno:** H4.1-DD-004, H4.1-DD-014.  
**Pruebas:** H4.1-TP-009, H4.1-TP-010.  
**Tareas:** H4.1-T03, H4.1-T11.

### H4.1-REQ-006 - Construccion de registros de configuracion

**Descripcion:** Convertir sentencias soportadas en registros declarados por
tabla y columnas.

**Prioridad:** Must.

**Criterios de aceptacion:**

- cada registro tiene identidad estable desde `configuration.name`, tabla y
  `identity_columns`;
- conserva tabla original, tabla normalizada, esquema, operacion, sentencia,
  ordinal, lineas y hash de valores canonicos;
- registros incompletos no generan simbolo activo y se reportan como warning;
- duplicados con la misma identidad dentro de un archivo se procesan en orden de
  aparicion de las sentencias, conservando warning;
- un `UPDATE` identificable puede modificar logicamente un registro previamente
  encontrado dentro del mismo archivo y ejecucion;
- Barbarion no reconstruye el estado real de la base de datos;
- duplicados con la misma identidad procedentes de archivos diferentes se
  conservan como `ambiguous`;
- H4.1 no define prioridad entre archivos o fuentes y no escoge
  silenciosamente un registro ante falta de evidencia.

**Diseno:** H4.1-DD-005, H4.1-DD-007.  
**Pruebas:** H4.1-TP-011, H4.1-TP-012.  
**Tareas:** H4.1-T04.

### H4.1-REQ-007 - Simbolos Data-Driven

**Descripcion:** Representar configuraciones como simbolos H4 permanentes.

**Prioridad:** Must.

**Tipos iniciales de simbolo:**

- `configuration_entity`;
- `configuration_record`;
- `configuration_rule`;
- `configuration_formula`;
- `configuration_variable`;
- `configuration_parameter`;
- `configuration_mapping`;
- `configuration_step`.

**Criterios de aceptacion:**

- `technology='configuration'`;
- el simbolo padre de un registro es la entidad de configuracion;
- reglas, formulas, variables, parametros, mappings y pasos pueden ser simbolos
  hijos cuando una columna declarada lo justifique;
- `original_name` se obtiene de columnas declaradas o de la identidad;
- `normalized_name` es determinista y no depende de ruta absoluta;
- `metadata_json` conserva valores relevantes y omite valores no declarados
  salvo `metadata_columns`;
- estado activo/inactivo se deriva de `status_columns` solo con mapeo declarado;
- simbolos incompletos quedan omitidos o `ambiguous`, no falsamente activos.

**Diseno:** H4.1-DD-007, H4.1-DD-008.  
**Pruebas:** H4.1-TP-013, H4.1-TP-014.  
**Tareas:** H4.1-T04, H4.1-T05.

### H4.1-REQ-008 - Referencias explicitas entre configuraciones

**Descripcion:** Extraer referencias desde columnas declaradas hacia otras
configuraciones.

**Prioridad:** Must.

**Criterios de aceptacion:**

- `reference_columns` define destino esperado por columna;
- relaciones padre-hijo se extraen desde `parent_columns`;
- relaciones de orden se extraen desde `sequence_columns` cuando referencian
  otros pasos o elementos;
- si existe un unico destino compatible, se crea relacion `resolved`;
- si hay varios destinos compatibles, se crea relacion `ambiguous` con
  candidatos;
- si el destino no existe aun, la referencia queda `unresolved` y puede
  resolverse en una corrida posterior.

**Diseno:** H4.1-DD-009, H4.1-DD-010.  
**Pruebas:** H4.1-TP-015, H4.1-TP-016.  
**Tareas:** H4.1-T06.

### H4.1-REQ-009 - Referencias hacia Oracle y PowerBuilder

**Descripcion:** Resolver referencias declaradas hacia simbolos tecnicos H4
existentes.

**Prioridad:** Must.

**Criterios de aceptacion:**

- columnas declaradas pueden indicar `target_technology = "oracle"` o
  `"powerbuilder"`;
- nombres calificados se normalizan con las reglas H4 existentes;
- coincidencias unicas producen `resolved`;
- coincidencias debiles o multiples producen `ambiguous`;
- nombres con placeholders, concatenacion o tokens dinamicos producen `dynamic`;
- referencias a objetos no administrados pueden marcarse `external` por mapeo
  declarado o patron explicito.

**Diseno:** H4.1-DD-010.  
**Pruebas:** H4.1-TP-017, H4.1-TP-018.  
**Tareas:** H4.1-T06, H4.1-T07.

### H4.1-REQ-010 - Analisis estatico de formulas, reglas y tokens

**Descripcion:** Identificar estructura y dependencias en columnas declaradas
como formulas o reglas, sin evaluar resultados.

**Prioridad:** Must.

**Criterios de aceptacion:**

- conserva el valor original;
- extrae tokens `{TOKEN}`, `${TOKEN}`, `:TOKEN`, `@TOKEN@` y nombres simples
  segun `token_patterns` configurados;
- identifica posibles variables y parametros declarados;
- identifica llamadas tipo `NAME(...)` como referencia a funcion solo si el
  patron esta habilitado para la columna;
- expresiones incompletas o con concatenacion se marcan `dynamic` o
  `por_confirmar`;
- no ejecuta ni interpreta semanticamente el lenguaje de formula.

**Diseno:** H4.1-DD-011.  
**Pruebas:** H4.1-TP-019, H4.1-TP-020.  
**Tareas:** H4.1-T07.

### H4.1-REQ-011 - Modelo de datos compatible

**Descripcion:** Priorizar reutilizacion de tablas H4 existentes y agregar
persistencia solo si es necesaria.

**Prioridad:** Must.

**Criterios de aceptacion:**

- `symbols`, `symbol_references`, `relations` y `relation_candidates` son la
  fuente de verdad de conocimiento Data-Driven vigente;
- no se crean tablas con prefijo `h41_`;
- H4.1 no crea una tabla `configuration_records`;
- H4.1 no requiere una migracion de esquema para registros Data-Driven;
- la trazabilidad adicional de archivo, sentencia, registro, columnas y valores
  se conserva en `metadata_json` de las estructuras H4 existentes;
- si durante la implementacion se demuestra mediante evidencia que el modelo H4
  existente no puede satisfacer un requisito obligatorio, la implementacion debe
  detenerse y el diseno debe actualizarse antes de introducir una nueva tabla o
  migracion.

**Diseno:** H4.1-DD-012.  
**Pruebas:** H4.1-TP-021, INT-H4.1-09.  
**Tareas:** H4.1-T01, H4.1-T05.

### H4.1-REQ-012 - Pipeline incremental de analisis

**Descripcion:** `barbarion analyze` debe incorporar configuraciones Data-Driven
de forma incremental e idempotente.

**Prioridad:** Must.

**Criterios de aceptacion:**

- procesa solo archivos nuevos, modificados o incluidos por scope cuando sea
  posible;
- usa hashes de archivo, chunk y declaracion Data-Driven;
- confirma resultados por archivo o scope consistente;
- re-resuelve referencias afectadas por cambios de simbolos de configuracion;
- elimina o marca `deleted` el conocimiento derivado de archivos borrados;
- repetir sin cambios no duplica simbolos, referencias ni relaciones;
- Ctrl+C deja run `interrupted` y no publica unidad parcial.

**Diseno:** H4.1-DD-013.  
**Pruebas:** H4.1-TP-022, H4.1-TP-023, INT-H4.1-03 a INT-H4.1-08.  
**Tareas:** H4.1-T08.

### H4.1-REQ-013 - Integracion con inventario, descripcion, dependencias e impacto

**Descripcion:** Las configuraciones deben participar en comandos H4 existentes.

**Prioridad:** Must.

**Criterios de aceptacion:**

- `inventory --technology configuration` lista entidades, registros y simbolos
  derivados;
- `describe` muestra columnas clave, reglas, formulas, referencias, estado,
  evidencia y limitaciones;
- `impact` incluye consumidores y dependencias Data-Driven;
- recorridos de dependencias soportan cruces `configuration -> oracle`,
  `configuration -> powerbuilder` y `configuration -> configuration`;
- renderers text/json/markdown incluyen tecnologia `configuration` sin romper
  salidas previas.

**Diseno:** H4.1-DD-015.  
**Pruebas:** H4.1-TP-024, H4.1-TP-025.  
**Tareas:** H4.1-T09.

### H4.1-REQ-014 - Integracion minima con H3 y H5

**Descripcion:** El conocimiento Data-Driven debe quedar disponible para RAG y
Spec Mode mediante contratos existentes.

**Prioridad:** Should.

**Criterios de aceptacion:**

- chunks DML conservan contenido y metadata indexable;
- `search` y `ask` pueden recuperar archivos DML por keyword y, si indexados,
  por modo semantico/hibrido;
- H5 recibe simbolos, relaciones e impacto Data-Driven desde H4 sin pipeline
  nuevo;
- H4.1 no rediseña ranking RAG ni plantillas H5.

**Diseno:** H4.1-DD-016.  
**Pruebas:** H4.1-TP-026, INT-H4.1-10.  
**Tareas:** H4.1-T10.

### H4.1-REQ-015 - CLI y mensajes

**Descripcion:** Extender comandos existentes sin crear un comando nuevo salvo
necesidad demostrada.

**Prioridad:** Must.

**Criterios de aceptacion:**

- `ingest` no requiere opcion nueva obligatoria;
- `analyze` incorpora Data-Driven si la configuracion esta habilitada;
- `analyze --dry-run` reporta archivos DML candidatos y sentencias soportadas;
- `stats` incluye conteos Data-Driven;
- errores esperados devuelven codigos `0`, `1`, `2` o `130` segun contratos
  existentes;
- mensajes CLI estan en espanol;
- no se implementa la CLI durante esta elaboracion de spec.

**Diseno:** H4.1-DD-017.  
**Pruebas:** H4.1-TP-027.  
**Tareas:** H4.1-T09, H4.1-T11.

### H4.1-REQ-016 - Observabilidad

**Descripcion:** Registrar metricas utiles del analisis Data-Driven.

**Prioridad:** Must.

**Criterios de aceptacion:**

- reporta archivos DML identificados;
- sentencias procesadas, soportadas, omitidas y con error;
- registros extraidos;
- simbolos generados;
- referencias detectadas;
- relaciones resueltas, ambiguas, dinamicas, externas y no resueltas;
- configuraciones reconciliadas;
- advertencias por tabla/columna;
- duracion total y por etapa;
- metricas son verificables desde salida CLI, logs o SQLite.

**Diseno:** H4.1-DD-014.  
**Pruebas:** H4.1-TP-028.  
**Tareas:** H4.1-T11.

### H4.1-REQ-017 - Seguridad

**Descripcion:** Garantizar procesamiento local y seguro.

**Prioridad:** Must.

**Criterios de aceptacion:**

- no hay conexion automatica a bases de datos;
- no se ejecuta SQL, DML, formulas, reglas ni codigo importado;
- limites de tamano y caracteres reutilizan H2;
- entradas malformadas no consumen memoria sin control;
- logs no vuelcan valores completos salvo debug explicito y limitado;
- no depende obligatoriamente de LLM;
- pruebas normales no requieren red.

**Diseno:** H4.1-DD-018.  
**Pruebas:** H4.1-TP-029, INT-H4.1-11.  
**Tareas:** H4.1-T03, H4.1-T12.

## 7. Requisitos no funcionales

### H4.1-RNF-001 - Operacion on-premise

H4.1 opera sobre archivos locales autorizados, SQLite local y Ollama local
opcional solo por integraciones existentes.

### H4.1-RNF-002 - Privacidad

No se envia corpus, DML, formulas ni configuraciones a servicios externos en el
flujo normal.

### H4.1-RNF-003 - Determinismo

La misma entrada, declaracion TOML y version de parser producen los mismos IDs,
orden y conteos.

### H4.1-RNF-004 - Trazabilidad

Todo simbolo, referencia y relacion Data-Driven conserva archivo, sentencia,
registro, columnas y lineas cuando existan.

### H4.1-RNF-005 - Idempotencia e incrementalidad

Repetir `analyze` sin cambios no duplica conocimiento; cambios acotados no
reprocesan innecesariamente todo el corpus.

### H4.1-RNF-006 - Compatibilidad hacia atras

Con `data_driven.enabled=false` el comportamiento H1-H5 y sus pruebas aceptadas
permanecen sin cambios.

### H4.1-RNF-007 - Rendimiento medible

La aceptacion debe registrar baseline full, incremental sin cambios e
incremental con cambios en una muestra Data-Driven. No se fija umbral duro sin
medicion inicial.

### H4.1-RNF-008 - Observabilidad accionable

Las metricas deben explicar que se proceso, que se omitio y por que.

### H4.1-RNF-009 - Seguridad y recuperacion

Errores de parsing son recuperables por sentencia; interrupciones no dejan
unidad parcial publicada.

### H4.1-RNF-010 - Mantenibilidad

La implementacion debe respetar `cli`, `application`, `domain` e
`infrastructure`, sin microservicios, plugins, frameworks SQL ni parsers
universales.

## 8. Casos de uso

### CU-01 - Analizar plantillas y reglas configuradas

1. El usuario declara una tabla de plantillas y `file_patterns` `.sql` en TOML.
2. Ejecuta `barbarion ingest` sobre archivos `.sql` exportados.
3. Ejecuta `barbarion analyze`.
4. Barbarion crea entidad, registros, formulas y referencias.
5. `inventory` y `describe` muestran evidencia y limitaciones.

### CU-02 - Impactar un procedimiento usado por configuracion

1. Una columna declarada referencia `PKG_RULES.CALCULATE`.
2. H4.1 resuelve la referencia contra un simbolo Oracle activo.
3. `impact PKG_RULES.CALCULATE --direction incoming` muestra configuraciones
   consumidoras.

### CU-03 - Formula con tokens ambiguos

1. Una columna de formula contiene `{AMOUNT} + TAX_RATE()`.
2. H4.1 conserva el texto, extrae tokens y llamada candidata.
3. Si hay varias variables `AMOUNT`, queda `ambiguous`.
4. Si `TAX_RATE` no existe, queda `unresolved` o `external` segun declaracion.

### CU-04 - UPDATE parcial no identificable

1. Un archivo contiene `UPDATE CONFIG_RULE SET VALUE='X' WHERE STATUS='A';`.
2. La declaracion exige `RULE_ID` como identidad.
3. H4.1 registra warning y no genera simbolo activo para esa sentencia.

### CU-05 - UPDATE parcial identificable sin INSERT previo

1. Un archivo `.sql` declarado contiene `UPDATE CONFIG_RULE SET VALUE='X' WHERE RULE_ID='R1';`.
2. La declaracion exige `RULE_ID` como identidad.
3. H4.1 genera una representacion parcial con `RULE_ID` y `VALUE`.
4. La metadata indica que el registro es parcial y que no se conoce el estado
   previo real de la base.

## 9. Riesgos

- Exportaciones DML heterogeneas pueden superar el subconjunto soportado.
- Declaraciones TOML incompletas pueden ocultar conocimiento valido.
- Formulas con lenguaje propio pueden producir falsos negativos.
- Nombres comunes de variables o parametros pueden generar ambiguedad alta.
- `UPDATE` sin valores previos reales solo representa intencion del archivo, no
  estado final de base.
- Duplicados entre archivos pueden quedar ambiguos hasta que exista evidencia
  externa revisable; H4.1 no incorpora prioridad entre fuentes.
- Si se intenta inferir semantica funcional sin experto, aumenta el riesgo de
  falsas conclusiones.

## 10. Matriz inicial de trazabilidad

| Requisito | Diseno | Pruebas | Tareas |
|---|---|---|---|
| H4.1-REQ-001 | DD-001, DD-002 | TP-001, TP-002 | T01 |
| H4.1-REQ-002 | DD-002, DD-003 | TP-003, INT-01 | T02, T05 |
| H4.1-REQ-003 | DD-004, DD-005 | TP-004, TP-005, TP-006 | T03 |
| H4.1-REQ-004 | DD-004, DD-006 | TP-007, TP-008 | T03 |
| H4.1-REQ-005 | DD-004, DD-014 | TP-009, TP-010 | T03, T11 |
| H4.1-REQ-006 | DD-005, DD-007 | TP-011, TP-012 | T04 |
| H4.1-REQ-007 | DD-007, DD-008 | TP-013, TP-014 | T04, T05 |
| H4.1-REQ-008 | DD-009, DD-010 | TP-015, TP-016 | T06 |
| H4.1-REQ-009 | DD-010 | TP-017, TP-018 | T06, T07 |
| H4.1-REQ-010 | DD-011 | TP-019, TP-020 | T07 |
| H4.1-REQ-011 | DD-012 | TP-021, INT-09 | T01, T05 |
| H4.1-REQ-012 | DD-013 | TP-022, TP-023, INT-03..08 | T08 |
| H4.1-REQ-013 | DD-015 | TP-024, TP-025 | T09 |
| H4.1-REQ-014 | DD-016 | TP-026, INT-10 | T10 |
| H4.1-REQ-015 | DD-017 | TP-027 | T09, T11 |
| H4.1-REQ-016 | DD-014 | TP-028 | T11 |
| H4.1-REQ-017 | DD-018 | TP-029, INT-11 | T03, T12 |

## 11. Criterio global

H4.1 queda listo para implementarse cuando estos requisitos, el diseno, las
tareas, el plan de pruebas y el analisis de impacto conservan trazabilidad
completa. La aceptacion tecnica se ejecutara solo en la ultima tarea de
implementacion, no durante la elaboracion de esta especificacion.
