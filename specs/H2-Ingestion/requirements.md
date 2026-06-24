# H2 — Ingestion: Requisitos

## 1. Propósito

H2 agrega a Barbarion la capacidad de descubrir, extraer, normalizar, fragmentar y persistir un corpus autorizado de artefactos Oracle/PLSQL, exportaciones textuales PowerBuilder y documentación técnica. Su salida será consumida por H3 sin volver a interpretar los archivos fuente.

H2 conserva el monolito modular, la CLI y la operación local de H1. No implementa embeddings, búsqueda, RAG ni ingeniería inversa avanzada.

## 2. Alcance

### Incluido

- discovery recursivo, exclusiones y límites;
- fingerprint SHA-256 e ingesta incremental;
- detección de altas, cambios, archivos sin cambios y eliminaciones;
- extracción heurística y fallback seguro;
- normalización conservadora y chunking trazable;
- persistencia SQLite versionada y WAL;
- CLI, métricas, logging, errores y pruebas.

| Familia | Extensiones |
|---|---|
| Oracle/PLSQL | `.sql`, `.pks`, `.pkb`, `.prc`, `.fnc`, `.trg`, `.pck`, `.vw`, `.vws`, `.pkg`, `.tps` |
| PowerBuilder textual | `.srw`, `.sru`, `.srf`, `.srm`, `.srj`, `.srd` |
| PowerBuilder binario | `.pbl`, solo inventario como no soportado |
| Documentación | `.md`, `.txt`, `.docx`, `.pdf` |
| Configuración | `.yaml`, `.yml`, `.json`, `.ini` |

Una `.pbl` nativa no es un export textual. H2 no la descompila; su contenido debe exportarse previamente a formatos textuales compatibles.

### Excluido

- embeddings, ChromaDB, Qdrant, Ollama y RAG;
- AST o parser perfecto de PL/SQL o PowerScript;
- descompilación de `.pbl`, OCR, imágenes y `.doc` binario;
- análisis de dependencias, call graph o lineage;
- ejecución de SQL, scripts, macros o contenido embebido;
- file watcher, workers, procesamiento distribuido o FastAPI;
- UI web, VS Code, autenticación y multiusuario;
- plugins dinámicos, entry points y servicios cloud.

## 3. Convenciones

- **Must:** obligatorio para aceptar H2.
- **Should:** requerido para operabilidad salvo impedimento documentado.
- Mensajes, ayuda, errores, logs y docstrings dirigidos al usuario están en español.
- Identificadores, opciones, claves y códigos técnicos pueden estar en inglés.
- `config show` e `ingest --stats` son read-only.
- Importar módulos no genera efectos secundarios.
- El modo predeterminado es incremental.

## 4. Requisitos funcionales

### H2-REQ-001 — Configuración de ingesta

**Descripción:** Admitir una sección `[ingestion]` sin romper las claves planas ni la precedencia de H1.

**Prioridad:** Must.

**Criterios de aceptación:**

- admite `paths`, `extensions`, `chunk_size`, `chunk_overlap`, `ignore_patterns`, `max_file_size_mb`, `max_extracted_chars`, `max_pdf_pages` y `encodings`;
- paths relativos se resuelven respecto del TOML;
- claves desconocidas, tipos inválidos o límites incoherentes producen código `2`;
- `0 <= chunk_overlap < chunk_size`;
- `max_file_size_mb` usa default `50`;
- `config show` no crea recursos ni abre SQLite.

### H2-REQ-002 — Registro de ejecución

**Descripción:** Cada ingesta debe crear un run identificable con configuración, modo, paths, timestamps, estado y métricas.

**Prioridad:** Must.

**Criterios de aceptación:**

- estados: `running`, `completed`, `completed_with_errors`, `failed`, `interrupted`;
- cada ejecución real tiene `run_id`;
- configuración inválida falla antes de crear el run;
- `--stats` no crea un run.

### H2-REQ-003 — Discovery determinista

**Descripción:** Descubrir archivos regulares recursivamente de forma segura y estable.

**Prioridad:** Must.

**Criterios de aceptación:**

- roots y rutas se procesan en orden estable;
- admite directorios y archivos individuales;
- deduplica roots repetidos o solapados;
- no sigue symlinks;
- una root fallida no detiene otras válidas;
- ninguna root válida produce un error explícito.

### H2-REQ-004 — Filtros y límites

**Descripción:** Aplicar ignores, extensiones y límites antes de extraer.

**Prioridad:** Must.

**Criterios de aceptación:**

- extensiones case-insensitive y rutas relativas con `/`;
- archivos ignorados no se leen ni persisten individualmente;
- compatibles demasiado grandes quedan `skipped` con `FILE_TOO_LARGE`;
- límites de páginas y caracteres detienen solo el archivo afectado.

### H2-REQ-005 — Identidad y fingerprint

**Descripción:** Mantener identidad estable y fingerprint de contenido por archivo.

**Prioridad:** Must.

**Criterios de aceptación:**

- identidad `(domain, source_root, relative_path)`;
- almacena tamaño y `mtime_ns` como firma rápida;
- calcula SHA-256 en streaming para nuevos, candidatos y full;
- un rename equivale a eliminación y alta.

### H2-REQ-006 — Reingesta incremental

**Descripción:** Evitar procesamiento innecesario sin ignorar cambios relevantes.

**Prioridad:** Must.

**Criterios de aceptación:**

- tamaño, `mtime_ns`, estado y firma iguales evitan parser y chunker;
- metadata cambiada exige SHA-256;
- mismo SHA actualiza metadata sin reprocesar;
- contenido o firma de procesamiento distintos reemplazan documento y chunks;
- un error previo se reintenta.

### H2-REQ-007 — Reingesta completa

**Descripción:** `--full` debe reprocesar todos los archivos compatibles.

**Prioridad:** Must.

**Criterios de aceptación:**

- ignora el fast path;
- no trunca el corpus antes de empezar;
- mantiene consistencia frente a fallos;
- no duplica registros.

### H2-REQ-008 — Reconciliación de eliminados

**Descripción:** Detectar archivos que desaparecieron del corpus.

**Prioridad:** Must.

**Criterios de aceptación:**

- solo reconcilia roots completadas;
- nunca reconcilia tras interrupción;
- mantiene tombstone `deleted`;
- elimina documento y chunks por cascada;
- no quedan huérfanos.

### H2-REQ-009 — Interfaz de parsers

**Descripción:** Integrar formatos mediante `BaseParser` y registro interno explícito.

**Prioridad:** Must.

**Criterios de aceptación:**

- cada parser declara ID, versión, extensiones y extracción;
- el registro rechaza extensiones duplicadas;
- parsers no conocen CLI ni SQLite;
- agregar un parser no modifica el pipeline;
- contratos y reglas puras residen en `domain/`, el caso de uso en `application/` y los parsers en `infrastructure/`;
- no hay carga dinámica de plugins.

### H2-REQ-010 — Decodificación textual

**Descripción:** Decodificar fuentes mediante política determinista.

**Prioridad:** Must.

**Criterios de aceptación:**

- respeta BOM UTF-8/UTF-16;
- intenta UTF-8 estricto y luego encodings configurados;
- no ignora ni reemplaza errores silenciosamente;
- registra encoding y warning para Latin-1;
- el fallo produce `TEXT_DECODE_FAILED`.

### H2-REQ-011 — Parser Oracle/PLSQL

**Descripción:** Extraer texto y unidades lógicas mediante heurísticas tolerantes.

**Prioridad:** Must.

**Criterios de aceptación:**

- reconoce package spec/body, type spec, view, procedure, function y trigger en fixtures;
- identifica unidades internas cuando los límites son confiables;
- conserva tipo, nombre y líneas;
- acepta las extensiones Oracle declaradas, incluyendo `.pck`, `.vw`, `.vws`, `.pkg` y `.tps`;
- siempre preserva texto completo;
- sintaxis desconocida usa unidad de archivo.

### H2-REQ-012 — Parser PowerBuilder

**Descripción:** Extraer exports textuales PowerBuilder sin requerir PBL nativa.

**Prioridad:** Must.

**Criterios de aceptación:**

- reconoce tipo y nombre del objeto;
- detecta eventos, funciones y SQL de DataWindow en fixtures;
- conserva propiedades, declaraciones y texto completo;
- estructura desconocida usa fallback;
- `.pbl` queda `skipped` con `UNSUPPORTED_BINARY_PBL`.

### H2-REQ-013 — Markdown, texto y configuración

**Descripción:** Convertir Markdown, texto, YAML, JSON e INI sin ejecutar o reserializar contenido.

**Prioridad:** Must.

**Criterios de aceptación:**

- Markdown conserva headings, breadcrumb y bloques de código;
- texto/configuración conserva líneas;
- JSON, YAML e INI no se reordenan ni evalúan;
- cada formato queda clasificado.

### H2-REQ-014 — PDF

**Descripción:** Extraer localmente PDFs con capa de texto.

**Prioridad:** Must.

**Criterios de aceptación:**

- usa dependencia open source y conserva páginas;
- no ejecuta acciones ni adjuntos;
- cifrado produce `PDF_ENCRYPTED`;
- sin texto produce `PDF_NO_EXTRACTABLE_TEXT`;
- no realiza OCR.

### H2-REQ-015 — DOCX

**Descripción:** Extraer documentos Open XML localmente.

**Prioridad:** Must.

**Criterios de aceptación:**

- extrae headings, párrafos y tablas en orden estable;
- tablas se representan determinísticamente;
- conserva breadcrumb y ordinales;
- no ejecuta macros o contenido embebido;
- `.doc` no se admite.

### H2-REQ-016 — Normalización conservadora

**Descripción:** Facilitar chunking sin alterar evidencia técnica.

**Prioridad:** Must.

**Criterios de aceptación:**

- elimina BOM y convierte CRLF/CR a LF;
- no cambia formato, casing, comentarios, tabs o whitespace interno;
- ajusta y valida localizadores;
- calcula SHA-256 del texto normalizado UTF-8.

### H2-REQ-017 — Chunking semántico

**Descripción:** Fragmentar primero por unidades lógicas y después por tamaño.

**Prioridad:** Must.

**Criterios de aceptación:**

- usa objetos/procedimientos Oracle, objetos/eventos PowerBuilder, secciones documentales y páginas PDF;
- texto usa archivo o párrafos;
- unidades grandes cortan por párrafo, línea y caracteres, en ese orden;
- `chunk_size` y overlap se miden en caracteres, no tokens;
- todo documento no vacío genera al menos un chunk.

### H2-REQ-018 — Trazabilidad de chunks

**Descripción:** Cada chunk debe rastrearse y sincronizarse posteriormente con H3.

**Prioridad:** Must.

**Criterios de aceptación:**

- contiene documento, ordinal, tipo, contenido y hash;
- incluye líneas, caracteres, página, objeto o breadcrumb cuando aplique;
- el ID deriva de identidad de archivo, SHA fuente, firma, localizador y hash del contenido;
- cada `LogicalUnit` incluye `confidence` con valor `high`, `medium` o `low`;
- la confianza de la unidad se propaga a la metadata de los chunks derivados;
- misma entrada produce mismos IDs y orden;
- metadata incierta se marca heurística.

### H2-REQ-019 — SQLite v2

**Descripción:** Migrar la base H1 a un esquema de ingesta versionado.

**Prioridad:** Must.

**Criterios de aceptación:**

- crea `ingestion_runs`, `files`, `documents`, `chunks` y `errors`;
- conserva migración v1 y `schema_migrations`;
- habilita foreign keys;
- una versión superior falla con `Database schema version X is newer than this Barbarion version supports.`;
- no almacena embeddings.

### H2-REQ-020 — SQLite WAL

**Descripción:** Activar y verificar WAL antes de escribir metadata H2.

**Prioridad:** Must.

**Criterios de aceptación:**

- ejecuta `PRAGMA journal_mode=WAL` en inicialización/migración;
- verifica respuesta `wal`;
- si no puede garantizarlo, falla con `DATABASE_WAL_UNAVAILABLE`;
- requiere filesystem local.

### H2-REQ-021 — Atomicidad por archivo

**Descripción:** Confirmar documento y chunks como una unidad.

**Prioridad:** Must.

**Criterios de aceptación:**

- reemplazo ocurre en una transacción;
- un fallo revierte el archivo completo;
- el error se registra por separado;
- un documento previo solo es vigente si status es `processed` y los SHA coinciden.

### H2-REQ-022 — Tolerancia a errores

**Descripción:** Aislar errores recuperables sin ocultarlos.

**Prioridad:** Must.

**Criterios de aceptación:**

- registra run, archivo, etapa, código, mensaje y recuperabilidad;
- un archivo corrupto no bloquea válidos;
- DB, esquema, disco y configuración son fallos fatales;
- SQLite locked usa reintentos acotados;
- no registra contenido fuente.

### H2-REQ-023 — CLI

**Descripción:** Exponer ingesta incremental, completa, paths ad hoc y estadísticas.

**Prioridad:** Must.

**Criterios de aceptación:**

- admite `barbarion ingest`, `--path`, `--incremental`, `--full`, `--stats`;
- `--path` puede repetirse múltiples veces; todos los valores indicados forman las roots efectivas y reemplazan los paths configurados para esa ejecución;
- incremental/full son excluyentes y stats no se combina con ejecución;
- sin paths efectivos falla antes del run;
- help, errores y resumen están en español.

### H2-REQ-024 — Métricas y estadísticas

**Descripción:** Proveer evidencia cuantitativa por ejecución y corpus vigente.

**Prioridad:** Must.

**Criterios de aceptación:**

- informa descubiertos, procesados, sin cambios, omitidos, eliminados, errores y chunks;
- informa bytes, duración y throughput;
- contadores coinciden con SQLite;
- `--stats` no escanea filesystem ni modifica estado.

### H2-REQ-025 — Interrupción segura

**Descripción:** Ctrl+C debe detener sin corromper el corpus.

**Prioridad:** Should.

**Criterios de aceptación:** revierte archivo actual, conserva confirmados, evita reconciliación, marca `interrupted` y devuelve `130`.

### H2-REQ-026 — Independencia de H3

**Descripción:** H2 debe operar sin red ni componentes posteriores.

**Prioridad:** Must.

**Criterios de aceptación:** no hace HTTP, funciona sin Ollama, no inicializa vector store y permite a H3 leer chunks vigentes desde SQLite.

### H2-REQ-027 — Exportación del inventario

**Descripción:** El modelo persistido debe permitir obtener en el futuro un resumen exportable del inventario sin reescanear el filesystem.

**Prioridad:** Must.

**Criterios de aceptación:**

- SQLite permite consultar número de archivos, documentos y chunks vigentes;
- permite agrupar archivos vigentes por `artifact_kind`;
- las consultas usan únicamente metadata persistida y no acceden al filesystem;
- H2 no agrega todavía formatos de exportación ni un comando CLI nuevo;
- `ingest --stats` reutiliza el mismo contrato de lectura cuando corresponda.

## 5. Requisitos no funcionales

### H2-NFR-001 — Rendimiento incremental

**Descripción:** El fast path evita parser y chunker; hashing usa bloques y el pipeline no carga el corpus completo.

**Prioridad:** Must.

**Criterio:** en el corpus de aceptación, incremental sin cambios tarda como máximo 25 % de full en la misma máquina, salvo filesystem sin timestamps fiables.

### H2-NFR-002 — Idempotencia y determinismo

**Descripción:** Repetir una ejecución equivalente no cambia documentos, chunks, IDs u orden.

**Prioridad:** Must.

**Criterio:** discovery, metadata JSON y chunking tienen serialización y orden canónicos.

### H2-NFR-003 — Portabilidad

**Descripción:** Operar en Windows y Linux con Python `>=3.12,<3.13`.

**Prioridad:** Must.

**Criterio:** pruebas no usan rutas personales; rutas relativas persistidas usan `/`; SQLite reside en filesystem local.

### H2-NFR-004 — Observabilidad segura

**Descripción:** Diagnosticar sin filtrar el corpus.

**Prioridad:** Must.

**Criterio:** logs incluyen run/etapa/ruta relativa, no contenido, y usan UTF-8 con `delay=True`.

### H2-NFR-005 — Imports sin efectos secundarios

**Descripción:** Importar módulos no crea archivos/directorios, no abre SQLite, no configura logging, no escanea y no hace HTTP.

**Prioridad:** Must.

**Criterio:** prueba aislada verifica filesystem, conexiones y red sin cambios.

### H2-NFR-006 — Integridad

**Descripción:** Fallos parciales no rompen relaciones.

**Prioridad:** Must.

**Criterio:** foreign keys pasan; no hay huérfanos; errores recuperables terminan código `1`; fallos fatales hacen rollback.

### H2-NFR-007 — Escalabilidad MVP

**Descripción:** Soportar decenas de miles de archivos mediante índices, streaming y límites, sin concurrencia prematura.

**Prioridad:** Should.

**Criterio:** consultas frecuentes usan índices y el uso de memoria se acota por archivo.

### H2-NFR-008 — Simplicidad estructural

**Descripción:** Mantener un monolito modular sin capas o interfaces especulativas.

**Prioridad:** Must.

**Criterio:** respeta la separación ligera `application/`, `domain/` e `infrastructure/` definida en la arquitectura maestra; no crea un árbol paralelo `ingestion/` al mismo nivel que esas capas; y no introduce microservicios, colas, DDD completo, Clean Architecture estricta, repositorios genéricos ni framework de plugins.

## 6. Códigos de salida

| Código | Significado |
|---:|---|
| 0 | Run sin errores o stats exitoso |
| 1 | Run con errores o fallo fatal |
| 2 | Argumentos/configuración inválidos |
| 130 | Interrupción por usuario |

## 7. Criterio global

H2 se acepta cuando todos los Must pasan, cada formato posee fixtures públicos o sintéticos, la reingesta es idempotente, el inventario puede consultarse sin reescaneo, cambios y eliminaciones no dejan huérfanos, un archivo defectuoso no detiene el lote y el ejecutable instalado funciona sin red, embeddings ni vector store.
