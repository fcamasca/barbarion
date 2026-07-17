# H4.1 - Configuraciones Data-Driven

**Estado:** especificacion creada, pendiente de implementacion.

H4.1 extiende la ingenieria inversa H4 para incorporar conocimiento tecnico
definido como datos de configuracion exportados en archivos `.sql`. El hito
analiza sentencias DML soportadas de forma estatica, sin conectarse a bases de
datos y sin ejecutar SQL, formulas ni reglas. En H4.1, DML describe sentencias
como `INSERT` y `UPDATE`; no es una extension de archivo.

Esta evolucion no reabre el MVP `0.5.0`, H4 ni H5. Trabaja sobre la arquitectura
existente: CLI local, TOML, ingesta H2, SQLite, parsers heuristicos, catalogo H4,
RAG H3 y Spec Mode H5.

## Objetivo

Permitir que Barbarion represente configuraciones persistidas como simbolos,
referencias y relaciones trazables, para que inventario, descripcion,
dependencias, impacto, RAG y Spec Mode puedan considerar logica Data-Driven que
no esta expresada directamente en codigo Oracle/PLSQL o PowerBuilder.

## Entregables

- [requirements.md](requirements.md)
- [design.md](design.md)
- [tasks.md](tasks.md)
- [test-plan.md](test-plan.md)
- [impact-analysis.md](impact-analysis.md)

No se crea `acceptance.md` durante esta tarea. La aceptacion tecnica queda
planificada como la ultima tarea de implementacion en [tasks.md](tasks.md).

## Alcance resumido

Incluye:

- declaracion explicita de fuentes y tablas Data-Driven en TOML;
- analisis estatico de `INSERT` y `UPDATE` acotados dentro de archivos `.sql`
  declarados;
- extraccion de registros, campos, formulas, tokens y referencias;
- simbolos de configuracion usando el modelo H4 vigente;
- relaciones conservadoras entre configuraciones y hacia simbolos Oracle o
  PowerBuilder existentes;
- trazabilidad a archivo, sentencia, registro, columnas y lineas;
- integracion incremental con `ingest`, `analyze`, `inventory`, `describe`,
  `impact`, `search`, `ask` y `spec create`.

Fuera de alcance:

- conexion a bases de datos;
- ejecucion de DML, formulas o reglas;
- parser SQL universal;
- ETL generico;
- motor de reglas o workflows;
- inferencia funcional completa mediante LLM;
- redisenos de H2, H3, H4 o H5;
- H4.2, H4.3, H4.4 o Reasoning Package.
- la extension `.dml` o cualquier extension nueva para DML.

## Decisiones que condicionan H4.1

- D-001: operacion local/on-premise.
- D-003: CLI como primera interfaz.
- D-004: aplicacion Python modular de un solo proceso.
- D-005: SQLite como fuente de verdad.
- D-010: parsers heuristicos con fallback y limites explicitos.
- D-013: comunicacion de usuario, errores y documentacion en espanol.
- D-014: SQLite + sqlite-vec para RAG.
- D-015: tablas permanentes H4 sin prefijo de hito.

## Estado actual confirmado

El repositorio ya contiene:

- H1-H5 completados y MVP publicado como `0.5.0`;
- SQLite schema version `4`;
- tablas H4 permanentes `analysis_runs`, `symbols`, `symbol_references`,
  `relations`, `relation_candidates` y `generated_artifacts`;
- parsers Oracle y PowerBuilder orientados a codigo fuente y SQL embebido;
- comandos `ingest`, `index`, `search`, `ask`, `analyze`, `inventory`,
  `describe`, `impact`, `spec create` y `spec validate`;
- configuracion TOML sin seccion Data-Driven aun;
- ningun parser DML dedicado y ninguna declaracion de tablas de configuracion.

Regla de clasificacion:

```text
archivo .sql
    + Data-Driven habilitado
    + patron de archivo declarado
    + tabla declarada
    = configuracion Data-Driven
```

Un archivo `.sql` conserva su comportamiento Oracle por defecto. Mencionar una
tabla declarada en codigo Oracle no reclasifica automaticamente el archivo como
`configuration`.

## Convenciones

- Identificadores de requisitos: `H4.1-REQ-NNN`.
- Decisiones de diseno: `H4.1-DD-NNN`.
- Tareas: `H4.1-TNN`.
- Pruebas: `H4.1-TP-NNN` e `INT-H4.1-NN`.
- Mensajes CLI y documentacion de usuario en espanol.
- Identificadores de codigo, opciones y claves TOML en ingles.
- Comentarios y docstrings de codigo en espanol cuando se implemente.
