# Aceptacion H4.1 - Configuraciones Data-Driven

## Estado

**Estado tecnico y funcional:** aprobado con limitaciones conocidas aceptadas.

**Estado de T12:** completada. El mantenedor aprobo la evidencia tecnica y
funcional despues de revisar el corpus piloto, las salidas y los hallazgos
descritos aqui.

La validacion cubre instalacion editable real, suite completa, smoke CLI,
regresion H1-H5, flujo Data-Driven integral, incrementalidad, reconciliacion,
interfaces H4, RAG, Spec Mode, seguridad y privacidad.

## Version y entorno

- Fecha: 2026-07-19.
- Sistema operativo: Windows.
- Workspace: `D:\barbarion`.
- Rama: `feature/H4.1-DataDrivenConfigurations`.
- Revision base evaluada: `916d8a7`.
- Candidato evaluado: revision base mas cambios locales de H4.1 y la correccion
  del filtro CLI descubierta durante T12.
- Python: `3.12.10`, distribucion oficial CPython.
- Barbarion: `0.5.0`, instalacion editable desde el workspace.
- Pytest: `8.4.2`.
- SQLite: `3.49.1`.
- sqlite-vec: `0.1.9`.
- Entorno virtual: `.venv`.

La `.venv` anterior apuntaba a un interprete removido. Se instalo CPython
3.12.10 para el usuario, se conservo la venv anterior como
`.venv.broken-20260717`, se creo una `.venv` nueva y se instalo `.[dev]` en
modo editable. El entry point instalado reporto `barbarion 0.5.0` e importo el
paquete desde `D:\barbarion\src\barbarion`.

## Suite y smoke

La primera ejecucion con `--basetemp .pytest-tmp\h41` encontro un problema de
preparacion local: el directorio padre `.pytest-tmp` no existia. Ese intento
termino con 218 pruebas aprobadas y 341 errores de creacion de directorio; no
fueron fallos funcionales. Se creo el directorio y se repitio la validacion.

Comando final:

```powershell
.venv\Scripts\python.exe -m pytest --basetemp .pytest-tmp\h41-accepted-final -q
```

Resultado:

```text
568 passed, 2 skipped in 116.40s
```

Smoke del paquete instalado:

```powershell
.venv\Scripts\python.exe -m pytest --basetemp .pytest-tmp\h41-final-smoke tests\smoke -q
```

Resultado:

```text
10 passed in 37.73s
```

La suite completa incluye la regresion H1-H5. No se observaron regresiones en
simbolos no Data-Driven, RAG, Spec Mode ni contratos CLI existentes.

## Hallazgo corregido durante T12

El piloto encontro que `inventory --technology configuration` era rechazado
por `argparse`, aunque la capa de aplicacion y los renderers ya soportaban el
filtro. El mismo defecto afectaba el filtro equivalente de `impact`.

Se agrego `configuration` a las opciones de ambos comandos y una prueba del
contrato CLI. La prueba focalizada quedo en:

```text
7 passed in 1.35s
```

La suite y el smoke finales se ejecutaron despues de esta correccion.

## Ajuste SQL*Plus posterior

Antes de la revision humana se incorporo una validacion adicional para scripts
exportados mediante SQL*Plus:

- las lineas `PROMPT` y `SET` se neutralizan antes del splitter conservando su
  longitud y sus terminadores de linea;
- los comentarios de cabecera no desplazan el inicio trazable de la sentencia;
- un `INSERT` solo se despacha como sentencia independiente y no como fragmento
  interno de un bloque `BEGIN` o `DECLARE`;
- `COMMIT` se conserva como diagnostico recuperable `unsupported_statement`.

El caso de regresion usa comentario de cabecera, `PROMPT`, `SET FEEDBACK OFF`,
`SET DEFINE OFF`, dos `INSERT`, otro `PROMPT` intermedio y `COMMIT`. Los dos
registros se localizaron en sus lineas originales 5 y 7; `COMMIT` quedo
diagnosticado en la linea 8. Una prueba separada verifico que dos `INSERT`
internos de PL/SQL no generan registros. La regresion Data-Driven obtuvo 53
pruebas aprobadas y la suite completa indicada arriba se ejecuto despues del
ajuste.

## Corpus sintetico

El piloto vive bajo `.pytest-tmp\h41-pilot` y esta ignorado por Git. Usa solo
nombres y valores sinteticos:

- `sources\config\pricing\pricing_rules.sql`;
- `sources\oracle\tax_rate.fnc`;
- `sources\powerbuilder\apply_discount.srf`;
- `barbarion.toml` con la configuracion `pricing_rules` para la tabla
  `APP_CFG.PRICING_RULES`.

La declaracion usa:

- `RULE_ID` como identidad;
- `FORMULA` como columna de formula;
- `VARIABLE_NAME` como variable;
- `DISPLAY_ORDER` como metadata de secuencia;
- `NEXT_STEP_ID` como referencia explicita `precedes`;
- `HANDLER_NAME` como referencia a `function_object` PowerBuilder.

El SQL contiene dos `INSERT`, un `UPDATE` parcial identificable y un
`INSERT ... SELECT` no soportado. La formula referencia `TAX_RATE()` y el token
`AMOUNT`. Ningun archivo del piloto contiene datos productivos.

## Flujo integral

`doctor` informo 8 PASS, 0 WARN y 0 FAIL. La ingesta inicial descubrio y
proceso 3 archivos, creo 4 chunks y no produjo errores.

| Ejecucion | Resultado Data-Driven | Duracion |
|---|---|---:|
| `analyze --dry-run` | 1 archivo, 4 sentencias, 3 soportadas, 1 omitida, 3 registros, 10 simbolos, 6 referencias | 32 ms |
| `analyze --full` | mismos conteos; 5 referencias resueltas y 1 no resuelta | 687 ms |
| incremental sin cambios | mismos IDs, nombres, jerarquia y conteos; sin duplicados | 671 ms |
| ingesta tras modificar una formula | 1 archivo procesado, 2 sin cambios, 2 chunks | 93 ms |
| `analyze --path config/pricing` tras el cambio | conocimiento acotado reconciliado; 10 simbolos y 6 referencias | 796 ms |

No existe umbral de rendimiento previo. Estas cifras constituyen el baseline
solicitado. El incremental sin cambios sigue recorriendo los tres documentos;
es idempotente, pero no aplica una optimizacion de omision completa.

## Determinismo y reconciliacion

Dos ejecuciones con la misma entrada conservaron exactamente los IDs de la
entidad `pricing_rules` y de los registros `R1` y `R2`, sus nombres canonicos,
padres y conteos. No aparecieron simbolos ni relaciones duplicadas.

Al cambiar solo la formula de `R1`:

- la ingesta proceso un archivo y dejo dos sin cambios;
- `analyze --path config/pricing` no modifico conocimiento de los otros
  archivos;
- entidad, registros y jerarquia conservaron sus IDs;
- las relaciones activas quedaron reconciliadas sin huerfanos.

El piloto original revelo que el simbolo de formula era retirado y recreado
porque su valor formaba parte del nombre canonico. Ese comportamiento se
clasifico como defecto y se corrigio antes de la revision humana. La identidad
de todos los derivados ahora se forma exclusivamente con registro padre, tipo y
columna. Una regresion que cambia solo `ROUND({AMOUNT}, 2)` por
`ROUND({AMOUNT}, 4)` confirma que `symbol_id`, `normalized_name`,
`parent_symbol_id` y `symbol_type` permanecen iguales; `metadata.value` y
`metadata.source_hash` cambian. El contenido ya no aparece en
`original_name`, nombre canonico ni inventario.

## Aliases de tokens e inventario vigente

La revision previa a la aceptacion encontro dos defectos adicionales y ambos
quedaron corregidos:

1. El resolvedor construye una vez por corrida un indice en memoria para
   aliases `configuration_name + metadata.value` de variables y parametros
   activos. No consulta `metadata_json` por referencia. La busqueda permanece
   dentro de la misma configuracion y conserva la identidad estructural del
   simbolo. Un destino compatible produce `resolved`, varios `ambiguous` y
   ninguno `unresolved`. `[@...]` solo acepta `configuration_variable` y
   `[%...]` solo `configuration_parameter` cuando existe una declaracion.
2. El inventario sin filtro de estado agrega ahora `symbols.status = 'active'`
   tanto a filas como a resumen. Los simbolos reconciliados siguen almacenados
   como `stale` y pueden consultarse explicitamente con `--status stale`, pero
   no contaminan el inventario tecnico vigente.

La prueba sintetica usa un catalogo neutral con `VARIABLE_KEY = 'INPUT_ALPHA'`
y la expresion `ROUND([@INPUT_ALPHA], 2)`. La referencia por alias resuelve de
forma unica hacia el hijo estructural de la columna declarada. Casos adicionales
verifican ambiguedad entre dos activos, exclusion de candidatos `stale` y
aislamiento de parametros. Una prueba SQLite persiste una identidad reemplazada,
la reconcilia como `stale` y confirma que `InventoryService` solo devuelve la
version activa por defecto.

El mismo indice semantico se reutiliza para referencias explicitas que declaran
`target_configuration` y un `target_type` compatible. La resolucion restringe
primero por configuracion destino, luego por tipo y finalmente compara el valor
normalizado de la columna con el alias. El fixture arbitrario conecta un
registro de bindings con `catalog_entries.input_alpha` y resuelve hacia el hijo
`configuration_variable` de `VARIABLE_KEY`, sin cambiar la identidad del
destino ni crear un segundo mecanismo de aliases.

La validacion sobre datos locales ignorados por Git confirmo el mismo contrato.
Sus nombres, rutas y valores se omiten deliberadamente; solo se registran
metricas agregadas y anonimizadas. La comprobacion versionada usa datos
sinteticos y valida:

```text
resolved + ambiguous + unresolved + dynamic + external = references
general_unresolved = unresolved + dynamic + external
```

## Validacion real anonimizada

El corpus local proceso 63 sentencias: 62 fueron soportadas y una se omitio de
forma recuperable. Se extrajeron 62 registros y quedaron vigentes 163 simbolos
y 202 referencias.

La resolucion produjo 96 relaciones resueltas, ninguna ambigua y 106 no
resueltas. El ultimo grupo se descompone en 34 referencias `external`, 72
`unresolved` y ninguna `dynamic`. Los conteos satisfacen:

```text
96 + 0 + 106 = 202
34 + 72 + 0 = 106
```

Dos ejecuciones persistentes consecutivas conservaron exactamente los mismos
conteos. Tambien se verifico un registro con una relacion padre resuelta y una
referencia explicita resuelta hacia un alias semantico. Esta evidencia no
registra nombres de tablas, columnas, configuraciones, archivos ni valores del
dominio validado.

## Conteos generales vigentes

La validacion final detecto que `analyze` comparaba referencias extraidas en el
alcance actual con la resolucion global de referencias persistidas. Ademas, la
reconciliacion dejaba referencias reemplazadas como `unresolved`; al no existir
una columna de vigencia en `symbol_references`, esas filas historicas volvian a
participar y podian duplicar hallazgos y relaciones.

La correccion aplica dos reglas:

- despues de reconciliar, el resumen general usa el numero de referencias
  vigentes devuelto por `active_references()`, el mismo conjunto que se resuelve;
- las referencias del alcance no vistas en la corrida se eliminan y sus
  relaciones desaparecen mediante FK en cascada. Los simbolos mantienen su
  historia `stale` porque si poseen estado explicito.

Por contrato, los conteos generales cumplen:

```text
resolved + ambiguous + no_resueltas = referencias
no_resueltas = unresolved + dynamic + external
```

Una prueba ejecuta dos veces exactamente el mismo `analyze` y confirma que los
conteos generales, filas de referencias y relaciones no aumentan. Tambien
compara el resumen general con el desglose Data-Driven del mismo alcance e
incluye una referencia `external` para verificar que se agrega una sola vez a
`no_resueltas`.

Las pruebas automatizadas cubren ademas eliminacion de registros y documentos,
re-resolucion `unresolved`/`resolved`/`ambiguous`, aislamiento de `--path`,
errores parciales y cancelacion sin publicacion parcial.

## Interfaces H4

Se validaron salidas `text`, `json` y `markdown`:

- `inventory --technology configuration`: 1 archivo, 10 simbolos, 6
  referencias y 5 relaciones;
- `describe pricing_rules.r1`: registro, evidencia de lineas y cuatro
  dependencias salientes;
- `impact pricing_rules.r1 --direction both`: relaciones hacia otra
  configuracion, Oracle y PowerBuilder;
- `impact tax_rate --direction incoming --technology configuration`: consumidor
  Data-Driven entrante correctamente filtrado;
- valores extensos se presentan truncados con indicacion, mientras la evidencia
  completa permanece almacenada.

Artefactos revisables:

- `.pytest-tmp\h41-pilot\output\inventory.md`;
- `.pytest-tmp\h41-pilot\output\inventory.json`;
- `.pytest-tmp\h41-pilot\output\describe-r1.md`;
- `.pytest-tmp\h41-pilot\output\impact-r1.md`;
- `.pytest-tmp\h41-pilot\output\impact-tax-rate.md`.

## RAG y Spec Mode

El indice local proceso 4 chunks y genero 4 vectores sin fallos. La busqueda
keyword por `pricing_rules` recupero el DML con metadata `configuration`.
`ask --no-llm` devolvio respuesta con citas al archivo Data-Driven.

`spec create --no-llm` genero una spec piloto para modificar
`pricing_rules.r1`. El diseno identifico como afectados:

- la configuracion `pricing_rules.r1`;
- la funcion Oracle `tax_rate`;
- el objeto PowerBuilder `apply_discount`;
- la configuracion `pricing_rules.r2`;
- la variable Data-Driven relacionada.

`spec validate` devolvio `valid=true` y `strict_valid=true`. Conservo una
advertencia no bloqueante por tres evidencias declaradas y no citadas fuera de
su seccion. Los documentos estan en
`.pytest-tmp\h41-pilot\output\specs\pricing-rule-change`.

## Calidad y diagnosticos

El piloto produjo los conteos esperados:

- 4 sentencias detectadas;
- 3 sentencias soportadas y 1 omitida con warning recuperable;
- 3 registros extraidos, incluidos los datos parciales del `UPDATE`;
- 10 simbolos Data-Driven activos;
- 6 referencias Data-Driven, 5 resueltas y 1 no resuelta;
- 5 relaciones activas, todas resueltas.

La referencia Data-Driven no resuelta es `AMOUNT`: el token se conserva como
candidato, pero no existe un simbolo compatible declarado. Es el comportamiento
conservador esperado y no un falso negativo demostrado.

Se registran dos limitaciones conocidas:

1. `impact --direction both` vuelve a recorrer aristas ya vistas y reporta
   cuatro ciclos en el grafo sintetico, aunque las relaciones dirigidas del
   piloto son aciclicas. Es un falso positivo de presentacion del recorrido
   bidireccional.
2. El parser PowerBuilder existente extrae `from function_object` como una
   referencia no resuelta en el fixture sintetico. Es un falso positivo previo
   y no procede del parser Data-Driven.

No se identificaron falsos negativos Data-Driven adicionales en el corpus
acotado. El subconjunto DML y las expresiones dinamicas permanecen limitados por
diseno y se diagnostican sin inventar semantica.

## Seguridad y privacidad

La revision estatica de los modulos Data-Driven no encontro usos de `eval`,
`exec`, `subprocess`, `os.system`, ejecucion mediante cursor o conexion SQL, ni
clientes HTTP, sockets o URLs. El DML y las formulas se tokenizan y persisten
como evidencia; no se ejecutan.

El scan de secretos y rutas personales no encontro credenciales ni rutas de
usuario en codigo, documentacion o especificacion. Las coincidencias de
`password`, `token`, `api_key` y `secret` estan confinadas a pruebas sinteticas
del enmascarado y sus aserciones. No se envia corpus a servicios externos; el
unico proveedor usado por el piloto fue Ollama local mediante la integracion ya
existente.

Una busqueda global case-insensitive sobre todos los archivos versionados no
encontro marcadores del dominio usado durante la validacion local. Una segunda
busqueda en `src` tampoco encontro nombres de configuraciones, tablas, columnas,
valores ni fixtures sinteticos: la resolucion depende solo de las declaraciones
TOML, `target_configuration`, `target_type` y la metadata generica. Las fuentes,
la configuracion, las bases y los artefactos de validacion locales permanecen
ignorados por Git y no fueron modificados durante esta auditoria.

## Requisitos no funcionales

| Requisito | Resultado | Evidencia o limitacion |
|---|---|---|
| RNF-001 operacion on-premise | Cumple | archivos, SQLite y Ollama locales |
| RNF-002 privacidad | Cumple | sin clientes externos en Data-Driven; scan limpio |
| RNF-003 determinismo | Cumple | IDs, nombres, jerarquia y conteos estables |
| RNF-004 trazabilidad | Cumple | archivo, sentencia, registro, columnas, lineas y chunks |
| RNF-005 idempotencia e incrementalidad | Cumple con limitacion | sin duplicados; recorrido sin cambios aun no se omite |
| RNF-006 compatibilidad | Cumple | suite H1-H5 y smoke verdes |
| RNF-007 rendimiento medible | Cumple | baseline full e incremental registrado |
| RNF-008 observabilidad | Cumple | conteos, tiempos, warnings y omisiones visibles |
| RNF-009 seguridad y recuperacion | Cumple | parsing estatico, errores parciales y cancelacion probados |
| RNF-010 mantenibilidad | Cumple | capas existentes, parser acotado y docstrings Google Style |

## Decision final

El mantenedor aprobo la aceptacion tecnica y funcional. Las salidas de
inventario, descripcion e impacto, la spec piloto y sus dependencias fueron
consideradas adecuadas. Las limitaciones conocidas se aceptan para H4.1 y
pueden registrarse como trabajo posterior sin bloquear el cierre.

H4.1 queda completado con todas las tareas H4.1-T01 a H4.1-T12 cerradas.
