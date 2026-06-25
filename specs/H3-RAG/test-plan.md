# H3 - RAG: Plan de pruebas

## 1. Objetivo

Verificar que H3 indexa chunks H2 de forma local, incremental y reconstruible; recupera fuentes por busqueda semantica, keyword e hibrida; construye contexto trazable; y responde preguntas con citas validas o evidencia insuficiente.

## 2. Estrategia

- unit tests para configuracion, versionamiento, ranking, filtros, contexto y validacion de citas;
- integration tests con SQLite y `sqlite-vec` temporales;
- proveedores fake para embeddings y LLM por defecto;
- servidor HTTP fake para adaptadores Ollama;
- smoke tests del entry point instalado;
- evaluacion RAG con 10 preguntas, categorias explicitas y fuentes esperadas;
- pruebas sin internet y sin descargar modelos;
- pruebas reales con Ollama marcadas como opcionales o condicionadas.

## 3. Entorno

- Python `>=3.12,<3.13`;
- Windows como entorno local principal;
- Linux mediante CI o equivalente;
- SQLite incluido con Python, con WAL;
- SQLite temporal con tablas `sqlite-vec`;
- modelos fake para suite normal;
- Ollama real solo para smoke manual u opcional.

## 4. Fixtures

### Corpus base

- reutilizar corpus H2 sintetico;
- incluir Oracle package, procedure, function, view y trigger;
- incluir PowerBuilder window, user object, DataWindow y eventos;
- incluir Markdown, TXT, PDF y DOCX;
- incluir nombres tecnicos buscables por identificador exacto;
- incluir documentos similares para probar deduplicacion.

### Preguntas de evaluacion

Al menos 10 preguntas versionadas con:

- texto de pregunta;
- categoria: navegacion, dependencias, ubicacion de objetos, explicaciones, impacto o documentacion;
- modo recomendado;
- filtros opcionales;
- fuentes esperadas por `chunk_id` o documento;
- tipo de evidencia esperada;
- nota de por que la fuente es relevante.

Ejemplos obligatorios dentro del dataset o sus equivalentes sinteticos:

- `Donde se calcula COSTO_AMORT_DIA?`
- `Que objetos llaman p_insertarCompraVenta?`
- `Donde se usa NOM_OPERACION_DIA?`
- `Que documentos hablan de CDVAL?`

## 5. Pruebas unitarias

### Configuracion

- defaults completos H3;
- secciones validas;
- claves desconocidas;
- tipos invalidos;
- paths relativos;
- batch size fuera de rango;
- `candidate_k < top_k`;
- pesos hibridos invalidos;
- budget insuficiente;
- `config show` sin crear tablas vectoriales ni abrir Ollama.

### Versionamiento

- version estable con misma configuracion;
- cambia por proveedor, modelo, dimension, distancia o normalizacion;
- no cambia por logging o formato de salida;
- dimension cero rechazada;
- manifest activo/obsoleto.

### Embeddings

- fake determinista;
- batch conserva orden;
- dimension estable;
- dimension mixta falla;
- timeout y modelo ausente tipados;
- adaptador Ollama contra servidor fake;
- respuesta corrupta no se acepta.

### Vector store sqlite-vec

- crea tablas vectoriales temporales;
- valida dimension;
- upsert idempotente;
- delete idempotente;
- filtros por dominio, tipo, lenguaje, documento, carpeta y extension;
- dimension incompatible o extension ausente falla con error claro.

### Seleccion incremental

- chunks nuevos;
- chunks unchanged;
- cambio de `content_sha256`;
- cambio de embedding version;
- chunks eliminados o no vigentes;
- metadata H4 presente o NULL: `symbol_name`, `symbol_kind`, `parent_symbol`, `package_name`, `procedure_name`, `class_name`, `event_name`;
- dry-run no escribe;
- orden canonico.

### Keyword

- FTS5 disponible;
- FTS5 ausente con fallback;
- identificadores con guiones bajos;
- literales y nombres de tabla;
- chunks no vigentes excluidos;
- score separado.

### Ranking hibrido

- normalizacion vectorial;
- normalizacion keyword;
- combinacion de pesos;
- deduplicacion por chunk;
- empate estable;
- pesos cero permitidos solo si la suma es mayor que cero.

### Context builder

- deduplicacion por chunk y hash;
- presupuesto de tokens;
- truncado por max chunk;
- agrupacion por documento;
- source ids estables;
- omitidos registrados;
- metricas `context_precision`, `context_recall`, `duplicate_ratio` y `token_waste`;
- render debug sin LLM.

### Citaciones

- cita valida;
- cita inexistente rechazada;
- fuente sin lineas usa chunk/documento;
- evidencia insuficiente no llama LLM por defecto;
- supuestos separados de evidencia.

### Imports

Importar modulos H3 en proceso nuevo y comprobar que no:

- crea filesystem;
- abre SQLite;
- abre tablas vectoriales;
- configura handlers;
- llama HTTP;
- carga modelos.

## 6. Pruebas de integracion

### INT-01 - Migracion v3

**Preparacion:** DB v2 con corpus H2.

**Resultado:** migra a v3, conserva H2, activa FK/WAL y crea tablas H3, incluyendo `symbol_occurrences`.

### INT-02 - Index inicial

**Accion:** ejecutar index con provider fake y SQLite/`sqlite-vec` temporal.

**Resultado:** todos los chunks vigentes quedan indexed, manifest activo y conteos correctos.

### INT-03 - Incremental sin cambios

**Accion:** repetir index.

**Resultado:** todo queda unchanged; no se llama embedding provider.

### INT-04 - Chunk modificado

**Accion:** simular reingesta H2 que cambia un chunk.

**Resultado:** solo ese chunk se reembolsa y actualiza en las tablas vectoriales.

### INT-05 - Eliminacion

**Accion:** simular archivo eliminado por H2.

**Resultado:** vector eliminado y estado deleted/stale sin huerfanos.

### INT-06 - Cambio de modelo

**Accion:** cambiar modelo/dimension configurada.

**Resultado:** nuevo manifest o reindex requerido; no mezcla colecciones incompatibles.

### INT-07 - Reindex full

**Accion:** ejecutar `reindex --full`.

**Resultado:** reconstruye coleccion, mantiene H2 y deja manifest consistente.

### INT-08 - Reindex parcial

**Accion:** ejecutar por path, documento y chunk.

**Resultado:** solo alcance indicado cambia; metricas reflejan scope.

### INT-09 - Error recuperable de embedding

**Accion:** fake falla para un chunk.

**Resultado:** run completed_with_errors, chunk error, resto indexado.

### INT-10 - Busqueda semantica

**Accion:** query con fuente esperada.

**Resultado:** fuente aparece en top-k, score y metadata completos.

### INT-11 - Filtros

**Accion:** buscar con extension, carpeta, lenguaje y documento.

**Resultado:** resultados respetan filtros y vacio produce mensaje claro.

### INT-12 - Keyword e hibrida

**Accion:** buscar identificador exacto.

**Resultado:** keyword mejora posicion frente a vector-only en caso definido.

### INT-13 - Ask sin LLM

**Accion:** `ask --no-llm`.

**Resultado:** muestra contexto, fuentes, omitidos y no llama LLM.

### INT-14 - Ask con LLM fake

**Accion:** fake devuelve respuesta con citas validas.

**Resultado:** salida incluye conclusion, evidencia, supuestos y limites.

### INT-15 - Cita invalida

**Accion:** fake devuelve `[F99]`.

**Resultado:** validador rechaza y reporta error o evidencia insuficiente.

### INT-16 - Stats read-only

**Accion:** ejecutar stats y embeddings.

**Resultado:** no muta DB, tablas vectoriales ni filesystem.

### INT-17 - Interrupcion

**Accion:** simular KeyboardInterrupt durante index.

**Resultado:** run interrupted, estado consistente y salida 130.

### INT-18 - Sin red externa

**Accion:** bloquear conexiones no loopback.

**Resultado:** suite con fakes pasa; ningun comando intenta internet.

## 7. Smoke tests

### SMK-01 - Ayuda

`barbarion index --help`, `reindex --help`, `search --help`, `ask --help` y `embeddings --help` finalizan 0 y estan en espanol.

### SMK-02 - Bootstrap requerido

Sin recursos H1/H2, comandos H3 fallan con mensaje accionable y no crean indices inesperados.

### SMK-03 - Index dry-run

`barbarion index --dry-run` muestra alcance sin escribir.

### SMK-04 - Index incremental

Tras H2, `barbarion index` indexa chunks vigentes con provider fake o fixture configurada.

### SMK-05 - Search

`barbarion search "consulta"` devuelve resultados con score, archivo y chunk.

### SMK-06 - Search JSON

`barbarion search "consulta" --format json` devuelve JSON valido.

### SMK-07 - Ask no-llm

`barbarion ask "pregunta" --no-llm` devuelve contexto y fuentes sin LLM.

### SMK-08 - Embeddings

`barbarion embeddings` muestra manifest activo y conteos.

### SMK-09 - Stats

`barbarion stats` incluye seccion RAG y no muta DB.

### SMK-10 - Instalacion real

Los smoke tests se ejecutan mediante entry point instalado y con cwd fuera del repo.

## 8. Evaluacion RAG

Medir para las 10 preguntas:

- fuente esperada en top 1;
- fuente esperada en top 5;
- fuente esperada en top 10;
- recall@5;
- recall@10;
- mrr;
- latencia de search;
- context_precision;
- context_recall;
- duplicate_ratio;
- token_waste;
- categoria;
- modo usado;
- filtros usados;
- observaciones.

`benchmark.md` debe incluir una seccion `Baseline` con:

- recall@5;
- recall@10;
- mrr;
- latency.

Cada ejecucion debe conservar historico local con fecha, commit o version, configuracion relevante, modelo de embeddings, chunk size, overlap y pesos de ranking.

Exito minimo:

- al menos 8 de 10 preguntas recuperan una fuente esperada en top 5;
- se reportan recall@5, recall@10, mrr y latencia agregadas;
- el baseline queda registrado en `benchmark.md`;
- una segunda ejecucion conserva historico y permite comparar contra la primera;
- ninguna respuesta factual de `ask` se muestra sin cita valida;
- evidencia insuficiente se declara cuando no hay fuente sobre umbral.

## 9. Rendimiento

Corpus de referencia:

- al menos 1 000 chunks;
- mezcla de codigo Oracle, PowerBuilder y docs;
- al menos 10 documentos grandes.

Mediciones:

1. index full inicial;
2. incremental sin cambios;
3. incremental con 1 % modificado;
4. search top 10;
5. ask con LLM fake y con LLM real opcional.

Objetivos:

- incremental sin cambios <=20 % del full;
- search top 10 <2 s p95 sin cold start;
- memoria acotada por batch;
- metricas persistidas coinciden con salida CLI.

## 10. Trazabilidad

| Requisito | Pruebas principales |
|---|---|
| H3-REQ-001 | unit config, SMK-01/03 |
| H3-REQ-002-004 | unit embeddings/version, INT-06 |
| H3-REQ-005 | unit vector store, INT-02/07 |
| H3-REQ-006 | INT-01 |
| H3-REQ-007-009 | unit incremental, INT-02-09/17 |
| H3-REQ-010 | INT-10/11, SMK-05/06 |
| H3-REQ-011-012 | unit keyword/ranking, INT-12 |
| H3-REQ-013-014 | unit context/citations, INT-13-15 |
| H3-REQ-015-017 | INT-10-15 |
| H3-REQ-018-019 | SMK-01-10 |
| H3-REQ-020 | INT-02/10/14/16, rendimiento |
| H3-REQ-021 | evaluacion RAG categorizada |
| H3-REQ-022 | unit metadata/context, revision de diseno |
| H3-REQ-023 | benchmark dataset, reportes y metricas de contexto |
| H3-NFR-001 | INT-18 |
| H3-NFR-002-004 | rendimiento |
| H3-NFR-005 | Windows + Linux |
| H3-NFR-006 | revision estructural/imports |
| H3-NFR-007 | captura de logs |
| H3-NFR-008 | determinismo e incremental |

## 11. Criterios de exito

- [ ] todos los requisitos Must pasan;
- [ ] SQLite v3 migra desde v2 sin perdida;
- [ ] SQLite + `sqlite-vec` es reconstruible desde chunks H2;
- [ ] index incremental no llama embeddings para unchanged;
- [ ] reindex full y parcial funcionan;
- [ ] search semantic, keyword e hybrid devuelven metadata trazable;
- [ ] filtros reducen resultados correctamente;
- [ ] context builder respeta presupuesto y conserva fuentes;
- [ ] ask cita fuentes validas o declara evidencia insuficiente;
- [ ] evaluacion cumple 8/10 top-5;
- [ ] benchmark reporta recall@5, recall@10, mrr, latencia y metricas de contexto;
- [ ] benchmark conserva baseline e historico de ejecuciones;
- [ ] reportes `reports/h3/metrics.json`, `topk-report.md`, `smoke-report.md` y `benchmark.md` se generan;
- [ ] comandos read-only no mutan estado;
- [ ] no hay servicios cloud ni internet durante uso normal;
- [ ] mensajes de usuario estan en espanol;
- [ ] smoke tests pasan con entry point instalado.

## 12. Evidencia de cierre

El ultimo task de H3 debe preparar la informacion para una aceptacion posterior:

- commit o version evaluada;
- sistema operativo y Python;
- comandos ejecutados;
- resultados de tests y duracion;
- resumen index full/incremental/reindex;
- reporte de evaluacion top-k y benchmark;
- ejemplos de search y ask con citas;
- limitaciones conocidas;
- decisiones que deben reevaluarse antes de H4.
