# Configuracion del analisis Data-Driven

Este manual explica como incorporar a Barbarion configuraciones tecnicas
exportadas como sentencias SQL. Esta pensado para equipos que necesitan modelar
un caso nuevo sin leer el codigo fuente ni consultar documentos internos de
implementacion.

## Proposito y alcance

Usa Data-Driven cuando una parte relevante del comportamiento del sistema esta
almacenada como filas de tablas de configuracion y dispones de una exportacion
local autorizada en archivos `.sql`. Es apropiado para catalogos, reglas,
formulas, parametros, mappings, jerarquias y referencias que no aparecen de
forma completa en el codigo Oracle o PowerBuilder.

Data-Driven:

- analiza estaticamente un subconjunto de `INSERT` y `UPDATE`;
- crea conocimiento tecnico trazable sin conectarse a una base de datos;
- representa entidades, registros y valores declarados como simbolos;
- extrae referencias explicitas y candidatos desde formulas o reglas;
- resuelve relaciones solo cuando existe evidencia compatible en el catalogo;
- integra el resultado con `inventory`, `describe`, `impact` y RAG.

No lo uses para ejecutar migraciones, reconstruir el estado completo de una
base, interpretar PL/SQL, procesar SQL arbitrario, implementar ETL o evaluar
formulas. El archivo de entrada debe ser `.sql` y estar incluido en los paths de
ingesta autorizados.

## Flujo de conocimiento

```text
archivo .sql
    -> sentencias separadas fuera de strings y comentarios
    -> registros canonicos INSERT/UPDATE
    -> simbolos de entidad, registro y valores derivados
    -> referencias declaradas o detectadas
    -> relaciones resueltas o conservadas con su estado
```

La unidad de analisis DML es el documento completo y ordenado. Los chunks de
ingesta sirven como evidencia y ubicacion, pero el parser no analiza cada chunk
por separado. Esto permite reconocer sentencias multilinea, evita duplicados por
overlap y conserva las lineas originales.

Una fila produce normalmente:

1. Un simbolo `configuration_entity` para la familia configurada.
2. Un simbolo `configuration_record` con identidad estable.
3. Simbolos hijos para reglas, formulas, variables, parametros, mappings y
   columnas de secuencia declaradas.
4. Referencias desde columnas explicitas, columnas padre y tokens de formulas o
   reglas.
5. Relaciones cuando el catalogo vigente ofrece destinos compatibles.

## Configuracion obligatoria, opcional e interna

El contrato publico se divide en:

- **Obligatorio al habilitar:** `enabled = true`, al menos un patron global y
  al menos una tabla `[[data_driven.configurations]]` valida.
- **Obligatorio por configuracion:** `name`, `symbol_type`, `tables` e
  `identity_columns`.
- **Opcional:** el resto de las propiedades; sus valores por defecto se indican
  en las tablas siguientes.
- **Interno no configurable:** separacion de sentencias por `;` fuera de strings
  y comentarios, aceptacion segura de la ultima sentencia sin terminador,
  normalizacion de nombres, IDs deterministas, deduplicacion, reconciliacion y
  uso del documento completo como unidad de parsing.

Las claves desconocidas se rechazan. Las listas deben ser listas TOML de
cadenas no vacias; Barbarion elimina duplicados conservando el primer orden.

## Contrato de `[data_driven]`

| Propiedad | Tipo | Requisito y default | Restricciones | Efecto |
|---|---|---|---|---|
| `enabled` | boolean | Opcional; `false` | Debe ser booleano TOML | Habilita clasificacion y analisis Data-Driven. |
| `file_patterns` | lista de string | Obligatoria y no vacia cuando `enabled = true`; `[]` | Cada patron debe terminar en `.sql` | Limita globalmente los archivos candidatos. La comparacion de rutas es case-insensitive y acepta globs. |
| `max_statements_per_file` | integer | Opcional; `10000` | Entre `1` y `1000000` | Rechaza de forma recuperable un documento que excede el limite. |
| `max_literal_chars` | integer | Opcional; `200000` | Entre `1` y `50000000` | Limita la longitud de cada literal o expresion de columna. |
| `token_patterns` | lista de string | Opcional; tres patrones predeterminados | Debe ser no vacia; cada valor debe ser una expresion regular utilizable | Extrae tokens de columnas declaradas como formula o regla. Se usa el primer grupo capturado no vacio, o el match completo. |
| `configurations` | lista de tablas TOML | Obligatoria y no vacia cuando se habilita | Los nombres `name` no pueden repetirse | Declara una o mas familias de registros. Se expresa repitiendo `[[data_driven.configurations]]`. |

Patrones de tokens predeterminados:

```toml
token_patterns = [
  '\{([A-Za-z_][A-Za-z0-9_]*)\}',
  '\$\{([^}]+)\}',
  ':([A-Za-z_][A-Za-z0-9_]*)'
]
```

Un patron invalido puede cargar como texto, pero fallara al compilarse durante
el analisis. Valida siempre con una corrida `--dry-run`.

Los patrones se evaluan contra la ruta relativa a cada root de ingesta. Si el
root configurado es `sources`, un archivo bajo `sources/configuration/catalog`
se compara como `configuration/catalog/...`.

## Contrato de `[[data_driven.configurations]]`

| Propiedad | Tipo | Requisito y default | Restricciones | Efecto |
|---|---|---|---|---|
| `name` | string | Obligatoria | Identificador: letras, numeros o `_`; no inicia con numero; unico | Nombre estable de la familia y prefijo de sus nombres canonicos. |
| `symbol_type` | string | Obligatoria | Mismo formato de identificador | Declaracion tecnica de la familia. En la implementacion vigente, los registros emitidos son `configuration_record`; usa ese valor para mantener coherencia. |
| `tables` | lista de string | Obligatoria y no vacia | Strings no vacios | Tablas SQL aceptadas para esta familia. Los nombres se comparan normalizados. |
| `identity_columns` | lista de string | Obligatoria y no vacia | Strings no vacios | Define la identidad simple o compuesta y participa en el ID determinista. |
| `file_patterns` | lista de string | Opcional; `[]` | Si se usa, cada patron termina en `.sql` | Aplica un filtro adicional a esta familia despues del patron global. Una lista vacia no agrega filtro. |
| `default_column_order` | lista de string | Opcional; `[]` | Strings no vacios | Orden usado para `INSERT INTO table VALUES (...)` sin lista explicita de columnas. Sin esta propiedad, esa forma se omite. |
| `name_columns` | lista de string | Opcional; `[]` | Strings no vacios | Proporciona nombre visible y `display_values`; la identidad canonica sigue dependiendo de `identity_columns`. |
| `description_columns` | lista de string | Opcional; `[]` | Strings no vacios | Conserva descripciones declaradas dentro de la metadata consultable del registro. |
| `rule_columns` | lista de string | Opcional; `[]` | Strings no vacios | Crea hijos `configuration_rule` y analiza tokens de la regla sin evaluarla. |
| `formula_columns` | lista de string | Opcional; `[]` | Strings no vacios | Crea hijos `configuration_formula`, analiza tokens y detecta llamadas `NAME(...)` como candidatas. |
| `variable_columns` | lista de string | Opcional; `[]` | Strings no vacios | Crea hijos `configuration_variable`; su valor participa en aliases semanticos activos. |
| `parameter_columns` | lista de string | Opcional; `[]` | Strings no vacios | Crea hijos `configuration_parameter`; su valor participa en aliases semanticos activos. |
| `mapping_columns` | lista de string | Opcional; `[]` | Strings no vacios | Crea hijos `configuration_mapping` conservando valor y hash como metadata. |
| `reference_columns` | lista de tablas inline | Opcional; `[]` | Contrato detallado mas adelante | Produce referencias explicitas desde valores de columnas. |
| `parent_columns` | lista de tablas inline | Opcional; `[]` | Contrato detallado mas adelante | Produce referencias jerarquicas `parent_of`. |
| `sequence_columns` | lista de string | Opcional; `[]` | Strings no vacios | Conserva orden como metadata y crea un hijo `configuration_step`. No crea `precedes` automaticamente. |
| `status_columns` | lista de tablas inline | Opcional; `[]` | Contrato detallado mas adelante | Mapea valores declarados a simbolos `active` o `stale`. |
| `effective_from_columns` | lista de string | Opcional; `[]` | Strings no vacios | Conserva inicio de vigencia como metadata; no interpreta calendarios. |
| `effective_to_columns` | lista de string | Opcional; `[]` | Strings no vacios | Conserva fin de vigencia como metadata; no interpreta calendarios. |
| `metadata_columns` | lista de string | Opcional; `[]` | Strings no vacios | Conserva columnas adicionales en `metadata.values` sin crear simbolos hijos. |

Todas las listas de columnas son declarativas. Una columna ausente o con `NULL`
no produce su simbolo o referencia derivada. Los valores se conservan como
evidencia; no se ejecutan ni se incluyen en la identidad de los simbolos hijos.
La identidad de un hijo se forma con registro padre, tipo derivado y columna.

## Identidad simple y compuesta

### Identidad simple

Usa una columna que identifique de manera estable y unica cada fila:

```toml
identity_columns = ["ENTRY_ID"]
```

El `INSERT` debe contener `ENTRY_ID`. En un `UPDATE`, `ENTRY_ID` debe aparecer
en el `WHERE` como igualdad.

### Identidad compuesta

Declara todas las partes en un orden estable:

```toml
identity_columns = ["CATALOG_ID", "REVISION"]
```

Cada `INSERT` debe incluir ambas columnas y cada `UPDATE` debe restringir ambas
en el `WHERE`. Cambiar el orden de `identity_columns` cambia el nombre canonico;
define el orden una vez y mantenlo. No uses formulas, descripciones, estados ni
valores mutables como identidad.

Los `UPDATE` se representan como registros parciales: conservan las columnas
del `WHERE` y del `SET`, pero no intentan recuperar columnas que no aparecen en
la sentencia.

## Columnas semanticas

### Formula y regla

`formula_columns` y `rule_columns` preservan el texto completo en metadata y
extraen tokens con `token_patterns`. Solo las formulas detectan ademas llamadas
lexicas `NAME(...)`. Una llamada es candidata, no una funcion Oracle confirmada:
se resuelve unicamente contra evidencia compatible del catalogo.

Los tokens repetidos dentro de la misma columna y registro se deduplican. Los
delimitadores `[@...]` identifican variables y `[%...]` parametros cuando sus
patrones se declaran. Un parametro no se enlaza accidentalmente con una
variable.

### Variable y parametro

Los hijos `configuration_variable` y `configuration_parameter` activos forman
aliases semanticos en memoria:

```text
configuration name + valor normalizado de metadata["value"]
```

La busqueda se restringe por configuracion y tipo. No cambia la identidad del
simbolo y no consulta SQLite una vez por referencia.

### Mapping

`mapping_columns` crea un simbolo hijo por columna declarada con valor no nulo.
Utilizalo para hacer visible una correspondencia tecnica. El contenido queda en
metadata; no se infiere automaticamente una relacion entre sus extremos.

### Secuencia

`sequence_columns` conserva posiciones u ordenes como metadata y genera hijos
`configuration_step` para consulta. Una posicion no demuestra cual es el
registro siguiente, por lo que no crea relaciones `precedes`.

Para declarar `precedes`, usa una `reference_column` cuyo valor identifique
explicitamente el destino:

```toml
reference_columns = [
  { column = "NEXT_ENTRY_ID", target_configuration = "catalog_entries", target_type = "configuration_record", relation_type = "precedes" }
]
```

### Estado y vigencia

Cada elemento de `status_columns` contiene:

| Propiedad | Tipo | Obligatoria | Efecto |
|---|---|---|---|
| `column` | string | Si | Columna que contiene el estado. |
| `active_values` | lista de string no vacia | Si | Valores que producen estado `active`. |
| `inactive_values` | lista de string no vacia | Si | Valores que producen estado `stale`. |

La comparacion de estados se normaliza sin distinguir mayusculas. Si ninguna
declaracion coincide o la columna no esta presente, el registro queda `active`.
Los hijos heredan el estado del registro. Los candidatos `stale` no participan
en la resolucion normal.

`effective_from_columns` y `effective_to_columns` preservan evidencia temporal,
pero no activan o desactivan registros segun la fecha. La politica temporal debe
reflejarse en `status_columns` o revisarse externamente.

### Metadata

`metadata_columns` agrega contexto consultable sin crear nuevos simbolos. Las
columnas de identidad, nombre, descripcion, regla, formula, variable, parametro,
mapping, secuencia, estado y vigencia tambien quedan dentro del conjunto
declarado y pueden conservarse en metadata cuando estan presentes.

## Referencias explicitas

Cada elemento de `reference_columns` admite:

| Propiedad | Tipo | Requisito | Valores y efecto |
|---|---|---|---|
| `column` | string | Obligatoria | Columna cuyo valor identifica o describe el destino. |
| `target_technology` | string | Obligatoria si no se usa `target_configuration` | `configuration`, `oracle` o `powerbuilder`; restringe candidatos por tecnologia. |
| `target_configuration` | string | Obligatoria si no se usa `target_technology` | Nombre de una configuracion declarada; restringe la busqueda a esa familia. |
| `target_type` | string | Opcional | Identificador del tipo esperado. Para aliases semanticos se admiten actualmente `configuration_variable` y `configuration_parameter`. |
| `relation_type` | string | Opcional | `references`, `parent_of`, `precedes`, `uses` o `calls`. Sin valor, Barbarion deriva un tipo conservador desde el destino. |

Debe existir al menos `target_technology` o `target_configuration`; ambos pueden
declararse. Para una referencia explicita a variable o parametro, Barbarion
reutiliza el indice de aliases, filtra por `target_configuration`, restringe por
`target_type` y compara el valor normalizado de la columna.

Ejemplo de alias semantico:

```toml
reference_columns = [
  { column = "VARIABLE_REF", target_configuration = "catalog_entries", target_type = "configuration_variable", relation_type = "uses" }
]
```

## Relaciones padre-hijo

Cada elemento de `parent_columns` requiere exactamente:

| Propiedad | Tipo | Efecto |
|---|---|---|
| `column` | string | Contiene la identidad declarada del registro padre. |
| `target_configuration` | string | Familia donde debe buscarse el padre. |

Ejemplo:

```toml
parent_columns = [
  { column = "PARENT_ENTRY_ID", target_configuration = "catalog_entries" }
]
```

La columna produce una referencia `parent_of`. La jerarquia solo queda resuelta
si existe un unico registro activo compatible.

## Estados de resolucion

| Estado | Significado | Accion recomendada |
|---|---|---|
| `resolved` | Existe un unico simbolo activo compatible por nombre/alias, tecnologia y tipo. | Verifica que la relacion represente la semantica esperada. |
| `ambiguous` | Existen varios candidatos activos compatibles. | Refina `target_configuration`, `target_type`, identidad o datos fuente. |
| `unresolved` | No existe todavia un candidato compatible. | Ingresa y analiza el destino, o corrige el valor/declaracion. |
| `dynamic` | El valor usa placeholders, concatenacion o una expresion incompleta que impide una identidad exacta. | Conserva como evidencia y modela una referencia explicita si existe una clave estable. |
| `external` | La referencia apunta a una funcion o destino conocido fuera del catalogo administrado. | No requiere destino interno; revisa solo si deberia formar parte del corpus. |

Las llamadas `NAME(...)` se tratan de forma conservadora. Una coincidencia unica
compatible puede resolverse, varias quedan ambiguas, una construccion dinamica
queda `dynamic`, una funcion conocida no administrada puede quedar `external` y
una llamada sin destino permanece `unresolved`.

## Capacidades y limites del parser

El parser soporta:

- `INSERT INTO table (columns...) VALUES (values...)` de una fila;
- `INSERT INTO table VALUES (...)` cuando existe `default_column_order`;
- `UPDATE table SET column = value, ... WHERE identity = value AND ...`;
- strings SQL con comillas escapadas, numeros, `NULL`, literales `DATE` y
  `TIMESTAMP`, placeholders y expresiones preservadas como texto;
- sentencias multilinea y comentarios `--` o `/* ... */`;
- `;` dentro de strings, identificadores delimitados y comentarios;
- ultima sentencia sin `;` cuando el fragmento termina en un estado seguro;
- lineas SQL*Plus `PROMPT` y `SET`, que se neutralizan sin alterar el numero de
  linea;
- `COMMIT` como sentencia omitida con diagnostico recuperable.

No soporta:

- `INSERT ALL`, `INSERT ... SELECT`, `RETURNING` ni subqueries;
- `UPDATE` con `FROM`, `RETURNING`, `OR`, `IN`, `LIKE` o subqueries;
- `WHERE` diferente de igualdades simples unidas por `AND`;
- `UPDATE` que no contenga todas las columnas de identidad en el `WHERE`;
- bloques `BEGIN` o `DECLARE`; sus DML internos no se aceptan como registros;
- reconstruccion del estado completo posterior a varios DML;
- evaluacion de funciones, formulas, reglas o placeholders.

Una sentencia no soportada genera un diagnostico recuperable y no impide que
otros documentos validos del mismo alcance sean procesados.

## Procedimiento para modelar un DML nuevo

1. Trabaja con una copia autorizada y sanitizada del export `.sql`.
2. Identifica las tablas que contienen configuracion, no tablas meramente
   mencionadas por codigo.
3. Confirma que cada familia tiene una clave simple o compuesta estable.
4. Revisa las formas reales de `INSERT` y `UPDATE` contra los limites anteriores.
5. Define un `name` tecnico unico y declara `tables` e `identity_columns`.
6. Agrega un `file_patterns` global estrecho y, si es necesario, otro por
   configuracion.
7. Declara `default_column_order` solo si existen `INSERT` sin columnas y el
   orden es conocido y estable.
8. Clasifica columnas por funcion: nombre, descripcion, formula, regla,
   variable, parametro, mapping, secuencia, estado, vigencia o metadata.
9. Declara referencias solo cuando una columna contiene evidencia del destino.
10. Usa `parent_columns` para jerarquia y una `reference_column` explicita para
    `precedes`; no derives relaciones desde posiciones.
11. Ajusta `token_patterns` a las sintaxis reales sin hacerlos excesivamente
    amplios.
12. Empieza con limites conservadores y aumentalos solo con evidencia medible.
13. Ejecuta la validacion progresiva de la siguiente seccion.
14. Revisa manualmente ambiguas, no resueltas, dinamicas y externas antes de
    publicar el conocimiento como aceptado.

## Validacion progresiva

Los comandos usan `barbarion.toml` por defecto. Para validar otro archivo sin
reemplazarlo, agrega `--config RUTA` antes del comando.

### 1. Ver configuracion efectiva

```bash
barbarion --config candidate.toml config show
```

Confirma `data_driven.enabled`, patrones, limites y cantidad de configuraciones.
Este comando no modifica SQLite.

### 2. Ingerir el corpus

```bash
barbarion --config candidate.toml ingest --full
```

Verifica que los `.sql` esperados se clasifiquen como `configuration`. La
clasificacion requiere simultaneamente habilitacion, coincidencia con el patron
global, coincidencia con el patron especifico si existe y presencia de una tabla
declarada en un `INSERT` o `UPDATE`.

### 3. Simular el analisis

```bash
barbarion --config candidate.toml analyze --dry-run
```

Revisa archivos, sentencias soportadas/omitidas, registros, simbolos,
referencias y estados. El dry-run no publica cambios.

### 4. Persistir y comprobar idempotencia

```bash
barbarion --config candidate.toml analyze
barbarion --config candidate.toml analyze
```

Los conteos de la segunda ejecucion deben ser iguales. Un cambio o eliminacion
posterior debe reconciliar simbolos y relaciones del alcance sin modificar
conocimiento de rutas no analizadas.

### 5. Revisar inventario

```bash
barbarion --config candidate.toml inventory --technology configuration
barbarion --config candidate.toml inventory --technology configuration --format markdown
```

El inventario normal muestra conocimiento activo; los simbolos historicos
`stale` no aparecen salvo que se soliciten con `--status stale`.

### 6. Describir una entidad o registro

```bash
barbarion --config candidate.toml describe catalog_entries --no-llm
```

Usa el nombre mostrado por `inventory`. Si hay homonimos, agrega `--type` o
`--id`.

### 7. Revisar impacto y estados

```bash
barbarion --config candidate.toml impact catalog_entries --direction both --no-llm
barbarion --config candidate.toml impact catalog_entries --resolution-status unresolved --no-llm
```

Revisa relaciones entrantes y salientes, candidatos ambiguos y cruces de
tecnologia.

### 8. Consultar evidencia sin LLM

Para `ask --no-llm`, primero debe existir un indice RAG. Ejecuta `index` si el
corpus aun no esta indexado y usa modo keyword para la consulta determinista:

```bash
barbarion --config candidate.toml index
barbarion --config candidate.toml ask "catalog_entries" --mode keyword --no-llm
```

`ask --mode keyword --no-llm` no requiere embeddings ni LLM, aunque `index`
puede requerir el proveedor de embeddings configurado.

## Errores y advertencias frecuentes

| Mensaje o diagnostico | Causa habitual | Correccion |
|---|---|---|
| `Claves de configuracion desconocidas` | Typo o propiedad no admitida | Compara la clave con las tablas de este manual. |
| `data_driven.enabled debe ser booleana` | Se uso string como `"true"` | Usa `true` o `false` sin comillas. |
| `file_patterns debe contener al menos un patron .sql` | Data-Driven habilitado sin patrones | Declara al menos un glob terminado en `.sql`. |
| `configurations debe contener al menos una configuracion` | No existe ninguna tabla `[[...]]` | Agrega una declaracion completa. |
| Nombre duplicado | Dos configuraciones usan el mismo `name` | Asigna identificadores unicos. |
| `missing_default_column_order` | `INSERT` omite columnas | Declara el orden real o exporta columnas explicitas. |
| `column_value_mismatch` | Cantidades de columnas y valores distintas | Corrige el DML exportado. |
| `missing_identity` | Un `INSERT` no contiene toda la identidad | Incluye todas las columnas de identidad. |
| `missing_identity_where` | Un `UPDATE` no restringe toda la identidad | Agrega igualdades para cada columna de identidad al `WHERE`. |
| `unsupported_where` | El `WHERE` no contiene asignaciones simples | Exporta igualdades unidas por `AND`. |
| `unsupported_insert` | `INSERT ALL`, `SELECT`, `RETURNING` o forma excluida | Genera `INSERT ... VALUES` de una fila. |
| `unsupported_update` | Usa `FROM`, `OR`, `IN`, `LIKE`, `RETURNING` o subquery | Simplifica el export o conserva la omision documentada. |
| `undeclared_table` | La sentencia apunta a una tabla no configurada | Corrige `tables` o separa el archivo del alcance. |
| `subquery` | Un valor contiene una subconsulta | Exporta el valor resultante como literal autorizado. |
| `max_statements_per_file` | El documento supera el limite | Divide el export de forma trazable o aumenta el limite con medicion. |
| `max_literal_chars` | Un valor excede el limite | Revisa el dato; aumenta el limite solo si es necesario y seguro. |
| `unsupported_statement` | `COMMIT`, bloque PL/SQL u otra sentencia fuera del subconjunto | Acepta el warning si es esperado o limpia el export. |
| Referencia `ambiguous` | Varios destinos activos compatibles | Refina configuracion, tipo o identidad. |
| Referencia `unresolved` | El destino no fue ingerido o no coincide | Analiza el destino y revisa valor, tipo y configuracion. |
| Referencia `dynamic` | Placeholder, concatenacion o expresion incompleta | Declara una clave estable o conserva la evidencia para revision. |

## Seguridad, privacidad, rendimiento e idempotencia

- Autoriza el corpus antes de ingerirlo y mantenlo en rutas locales ignoradas por
  Git.
- No copies datos internos a ejemplos, fixtures, informes versionados o tickets.
- Barbarion no ejecuta SQL ni formulas Data-Driven y no se conecta a la base de
  origen.
- Usa `max_statements_per_file`, `max_literal_chars` y los limites de ingesta
  para acotar consumo de memoria y tiempo.
- Prefiere patrones de archivo estrechos para reducir falsos positivos y
  reprocesamiento.
- Usa `--path` para analizar un alcance concreto; el conocimiento de otros
  archivos no debe cambiar.
- Ejecuta primero `--dry-run` y compara conteos antes de persistir.
- Repite una ejecucion sin cambios: IDs, nombres, jerarquia y conteos deben ser
  identicos.
- Al modificar o eliminar registros, confirma que el conocimiento obsoleto se
  reconcilie y que el inventario activo no muestre simbolos `stale`.
- Una interrupcion no debe publicar un resultado parcial; vuelve a ejecutar el
  mismo alcance despues de revisar el diagnostico.

## Ejemplo TOML completo

Este archivo es valido por si mismo porque las demas secciones de Barbarion usan
sus defaults. Supone que el corpus autorizado se encuentra bajo `sources/`.

```toml
[data_driven]
enabled = true
file_patterns = ["configuration/**/*.sql"]
max_statements_per_file = 10000
max_literal_chars = 200000
token_patterns = [
  '\[@([A-Za-z_][A-Za-z0-9_]*)\]',
  '\[%([A-Za-z_][A-Za-z0-9_]*)\]',
  '\{([A-Za-z_][A-Za-z0-9_]*)\}',
  '\$\{([^}]+)\}',
  ':([A-Za-z_][A-Za-z0-9_]*)'
]

[[data_driven.configurations]]
name = "catalog_entries"
symbol_type = "configuration_record"
tables = ["APP_CONFIG.CATALOG_ENTRIES"]
identity_columns = ["ENTRY_ID"]
file_patterns = ["configuration/catalog/*.sql"]
default_column_order = [
  "ENTRY_ID",
  "ENTRY_NAME",
  "DESCRIPTION_TEXT",
  "RULE_TEXT",
  "EXPRESSION_TEXT",
  "VARIABLE_KEY",
  "PARAMETER_KEY",
  "MAPPING_KEY",
  "VARIABLE_REF",
  "PARENT_ENTRY_ID",
  "NEXT_ENTRY_ID",
  "HANDLER_NAME",
  "DISPLAY_ORDER",
  "STATUS_CODE",
  "VALID_FROM",
  "VALID_TO",
  "OWNER_TAG"
]
name_columns = ["ENTRY_NAME"]
description_columns = ["DESCRIPTION_TEXT"]
rule_columns = ["RULE_TEXT"]
formula_columns = ["EXPRESSION_TEXT"]
variable_columns = ["VARIABLE_KEY"]
parameter_columns = ["PARAMETER_KEY"]
mapping_columns = ["MAPPING_KEY"]
reference_columns = [
  { column = "VARIABLE_REF", target_configuration = "catalog_entries", target_type = "configuration_variable", relation_type = "uses" },
  { column = "NEXT_ENTRY_ID", target_configuration = "catalog_entries", target_type = "configuration_record", relation_type = "precedes" },
  { column = "HANDLER_NAME", target_technology = "oracle", target_type = "function", relation_type = "calls" }
]
parent_columns = [
  { column = "PARENT_ENTRY_ID", target_configuration = "catalog_entries" }
]
sequence_columns = ["DISPLAY_ORDER"]
status_columns = [
  { column = "STATUS_CODE", active_values = ["ACTIVE"], inactive_values = ["INACTIVE"] }
]
effective_from_columns = ["VALID_FROM"]
effective_to_columns = ["VALID_TO"]
metadata_columns = ["OWNER_TAG"]

[[data_driven.configurations]]
name = "catalog_bindings"
symbol_type = "configuration_record"
tables = ["APP_CONFIG.CATALOG_BINDINGS"]
identity_columns = ["BINDING_ID", "REVISION"]
file_patterns = ["configuration/bindings/*.sql"]
name_columns = ["BINDING_NAME"]
reference_columns = [
  { column = "VARIABLE_REF", target_configuration = "catalog_entries", target_type = "configuration_variable", relation_type = "uses" }
]
metadata_columns = ["NOTES_TEXT"]
```

Observa que el primer `default_column_order` solo se usa para `INSERT` sin lista
de columnas. Las referencias deben estar presentes en el DML para producir
evidencia.

## Lista de comprobacion para puesta en marcha

- [ ] El corpus esta autorizado, es local y no se versiona.
- [ ] Todos los archivos candidatos terminan en `.sql` y estan bajo un path de
  ingesta.
- [ ] El patron global coincide solo con los exports deseados.
- [ ] Cada configuracion tiene `name`, `symbol_type`, `tables` e identidad.
- [ ] Las identidades son estables y estan presentes en `INSERT` y `UPDATE`.
- [ ] Los `INSERT` sin columnas tienen `default_column_order` verificado.
- [ ] Cada columna fue clasificada por su semantica real.
- [ ] `sequence_columns` se usa solo como orden; cada `precedes` tiene una
  `reference_column` explicita.
- [ ] Padres y referencias declaran configuracion, tecnologia y tipo suficientes.
- [ ] Los patrones de tokens reconocen solo sintaxis esperadas.
- [ ] Los limites defensivos son adecuados para el corpus medido.
- [ ] `config show` presenta la configuracion efectiva esperada.
- [ ] `ingest` clasifica los documentos correctos como `configuration`.
- [ ] `analyze --dry-run` no muestra omisiones inesperadas.
- [ ] Dos analisis persistentes sin cambios conservan los mismos conteos.
- [ ] `inventory`, `describe` e `impact` muestran conocimiento activo y trazable.
- [ ] Los estados `ambiguous`, `unresolved`, `dynamic` y `external` fueron
  revisados.
- [ ] `ask --no-llm` recupera el DML esperado cuando existe indice RAG.
- [ ] No se publicaron nombres, valores, rutas ni formulas privadas.
