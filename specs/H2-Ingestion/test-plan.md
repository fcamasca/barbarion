# H2 — Ingestion: Plan de pruebas

## 1. Objetivo

Verificar que H2 descubre, extrae, normaliza, fragmenta y persiste un corpus autorizado de forma local, incremental, determinista y tolerante a errores, sin romper contratos H1 ni introducir dependencias de H3.

## 2. Estrategia

- unit tests para reglas puras, parsers y SQL;
- integration tests con filesystem y SQLite temporales;
- smoke tests del ejecutable instalado fuera del source tree;
- aceptación manual de calidad de chunks;
- fixtures públicos o sintéticos, nunca corpus privado;
- pruebas sin red y con Ollama detenido;
- comparación de estado antes/después para comandos read-only.

Cada test debe ser independiente y reproducible. No comparte DB, directorios o configuración mutable con otros tests.

## 3. Entorno

- Python `>=3.12,<3.13`;
- Windows como entorno local principal;
- Linux mediante CI o entorno equivalente;
- SQLite incluido con Python;
- `pypdf` y `python-docx` instalados;
- directorios temporales para roots, data, output y logs;
- subprocess con encoding UTF-8 explícito en Windows.

Instalación de aceptación:

```text
python -m venv <temp-venv>
python -m pip install -e ".[dev]"
pytest
```

## 4. Fixtures

### Oracle

- package spec;
- package body con procedimientos y funciones;
- procedure standalone;
- function standalone;
- view en `.vw` y `.vws`;
- package/type variantes en `.pck`, `.pkg` y `.tps`;
- trigger;
- script SQL con DDL/DML y comandos no reconocidos;
- archivo grande que requiere varios chunks;
- comentarios, strings y delimitadores que desafíen heurísticas;
- UTF-8 y cp1252.

### PowerBuilder

- `.srw` con eventos;
- `.sru` con funciones;
- `.srf`, `.srm`, `.srj`;
- `.srd` con SQL DataWindow;
- variante desconocida que active fallback;
- `.pbl` binaria sintética;
- export cp1252.

### Documentación/configuración

- Markdown con headings ATX/Setext y bloques de código;
- TXT con párrafos y Unicode;
- JSON, YAML e INI conservables como texto;
- PDF textual de varias páginas;
- PDF cifrado, sin texto y corrupto;
- DOCX con headings, párrafos y tabla;
- DOCX corrupto.

### Filesystem y límites

- root vacía;
- paths solapados;
- symlink;
- archivo que desaparece;
- extensión en mayúsculas;
- archivo sobre tamaño máximo;
- documento sobre páginas/caracteres máximos;
- directorio sin permiso cuando la plataforma permita simularlo.

## 5. Pruebas unitarias

### Configuración

- defaults completos;
- sección válida;
- clave raíz o anidada desconocida;
- tipos inválidos;
- path relativo al TOML;
- extensión sin punto/duplicada;
- overlap negativo o mayor al size;
- encoding desconocido;
- default `max_file_size_mb = 50`;
- límites mínimos/máximos;
- precedencia H1 conservada;
- `config show` sin efectos.

### Discovery

- orden estable;
- root directorio y archivo;
- deduplicación;
- symlink ignorado;
- patrones con `/`;
- pruning de directorio;
- extensión case-insensitive;
- extensiones Oracle ampliadas `.pck`, `.vw`, `.vws`, `.pkg` y `.tps`;
- clasificación por artifact kind;
- size limit;
- errores root/file tipados.

### Fingerprint

- SHA-256 de vector conocido;
- archivo vacío;
- lectura por bloques;
- nuevo;
- metadata igual;
- metadata distinta con SHA igual;
- SHA distinto;
- error previo;
- modo full;
- firma estable;
- cambio de parser/chunker/config transformativa;
- cambio de logging/paths no altera firma.

### Encoding

- BOM UTF-8, UTF-16 LE/BE;
- UTF-8 sin BOM;
- cp1252;
- Latin-1 con warning;
- bytes inválidos sin reemplazo silencioso;
- orden configurable.

### Parsers

Para cada parser:

- ID, versión y extensiones;
- texto completo preservado;
- unidades, localizadores y `confidence` correctos;
- metadata estable;
- fallback ante estructura desconocida;
- límites de extracción;
- errores tipados;
- cero acceso a DB, CLI o red.

Casos específicos:

- Oracle: objeto, package, view, type spec, subprogramas, comentarios, extensiones ampliadas y ambigüedad;
- PowerBuilder: objeto, eventos, funciones, DataWindow y PBL;
- Markdown: breadcrumb y code fences;
- texto: clasificación sin reserialización;
- PDF: páginas, cifrado, vacío y corrupción;
- DOCX: orden de bloques, headings y tablas.

### Normalización

- BOM removido;
- CRLF/CR convertidos a LF;
- LF idempotente;
- tabs, casing, comentarios y whitespace preservados;
- offsets ajustados;
- SHA normalizado estable;
- Unicode no reescrito innecesariamente.

### Chunking

- archivo pequeño produce un chunk;
- unidad semántica dentro del límite;
- agrupación de unidades pequeñas compatibles;
- corte por párrafo, línea y caracteres;
- overlap cero y no cero;
- ordinales continuos;
- rangos válidos;
- páginas/objetos/breadcrumbs y `logical_unit_confidence`;
- contenido vacío rechazado;
- ID estable;
- cambio de contenido, localizador o firma cambia ID;
- metadata canónica.

### SQLite

- DB nueva aplica v1 y v2;
- DB v1 migra a v2;
- v2 no remigra;
- versión futura falla con mensaje definido;
- foreign keys activas;
- WAL activo/verificado;
- constraints e índices presentes;
- cascade document→chunks;
- transacción por archivo;
- rollback sin resultado parcial;
- error persistido separadamente;
- consulta de documentos vigentes.

### Imports

Importar cada módulo H2 en un proceso nuevo y comprobar que no:

- crea filesystem;
- abre SQLite;
- configura handlers;
- ejecuta discovery;
- hace HTTP.

## 6. Pruebas de integración

### INT-01 — Primera ingesta

**Preparación:** corpus mixto válido y DB v1.

**Resultado:** migra a v2/WAL, crea run, files, documents y chunks; métricas cuadran.

### INT-02 — Incremental sin cambios

**Acción:** repetir INT-01.

**Resultado:** todos quedan unchanged; no cambian documento, chunks, IDs o timestamps de extracción; parsers no son llamados.

### INT-03 — Touch sin cambio de contenido

**Acción:** cambiar solo mtime.

**Resultado:** calcula SHA, actualiza metadata y no reemplaza documento/chunks.

### INT-04 — Modificación real

**Acción:** editar un archivo.

**Resultado:** reemplaza solo ese documento/chunks; conserva resto; IDs afectados cambian.

### INT-05 — Cambio de firma

**Acción:** cambiar chunk size o versión simulada del parser.

**Resultado:** reprocesa archivos aplicables aunque SHA fuente no cambie.

### INT-06 — Eliminación

**Acción:** borrar un archivo y ejecutar incremental.

**Resultado:** file `deleted`; documento/chunks eliminados; sin huérfanos.

### INT-07 — Root fallida

**Acción:** hacer inaccesible una root antes de ejecutar.

**Resultado:** registra error y no marca sus archivos como deleted; procesa otras roots.

### INT-08 — Archivo inválido

**Acción:** corpus con PDF/DOCX corrupto y fuentes válidas.

**Resultado:** válidos procesados, inválido `error`, run `completed_with_errors`, salida 1.

### INT-09 — Omitidos

**Acción:** incluir archivo grande y PBL.

**Resultado:** ambos skipped con razón; no incrementan error_count; no tienen documento.

### INT-10 — Full

**Acción:** ejecutar `--full` sin cambios.

**Resultado:** reprocesa todos sin truncado previo ni duplicados.

### INT-11 — Interrupción

**Acción:** simular KeyboardInterrupt durante persistencia.

**Resultado:** rollback del actual, run interrupted, salida 130, sin reconciliación.

### INT-12 — Reintento SQLite

**Acción:** simular busy/locked transitorio y permanente.

**Resultado:** reintenta 100/250/500 ms; transitorio continúa; permanente falla seguro.

### INT-13 — Stats e inventario read-only

**Acción:** ejecutar stats con DB existente y ausente.

**Resultado:** muestra estado e inventario agregado sin crear, migrar, escanear ni mutar.

### INT-14 — Consulta de inventario sin filesystem

**Acción:** obtener número de archivos, documentos, chunks y tipos de artefactos desde SQLite con el filesystem fuente inaccesible.

**Resultado:** la consulta funciona con metadata persistida y no intenta reescanear.

### INT-15 — Sin red

**Acción:** bloquear socket/HTTP y detener Ollama.

**Resultado:** ingesta completa sin intento de red.

## 7. Smoke tests

### SMK-01 — Ayuda

`barbarion ingest --help` finaliza 0, está en español y muestra todas las opciones sin crear recursos.

### SMK-02 — Bootstrap requerido

Sin recursos H1, `barbarion ingest` falla con mensaje que indica ejecutar `barbarion doctor`; no introduce `init`.

### SMK-03 — Ingesta por configuración

Tras doctor, `barbarion ingest` usa los paths TOML y finaliza 0 sobre corpus válido.

### SMK-04 — Path ad hoc repetible

`barbarion ingest --path <fixture-a> --path <fixture-b>` procesa ambas roots y reemplaza paths configurados para ese run.

### SMK-05 — Incremental repetido

La segunda ejecución informa procesados 0 y unchanged igual a los archivos compatibles.

### SMK-06 — Full

`barbarion ingest --full` procesa de nuevo y mantiene el mismo estado lógico.

### SMK-07 — Errores parciales

Corpus mixto finaliza código 1, muestra resumen español y conserva válidos.

### SMK-08 — Estadísticas

`barbarion ingest --stats` finaliza 0 y no cambia hash/tamaño/mtime de la DB.

### SMK-09 — Opciones inválidas

Combinar full/incremental o stats/path finaliza 2 sin crear run.

### SMK-10 — Instalación real

Todos los anteriores se ejecutan mediante el entry point instalado y con cwd fuera del repositorio.

## 8. Rendimiento

Corpus sintético de referencia:

- al menos 1 000 archivos pequeños mixtos;
- varios archivos grandes dentro del límite;
- tamaño total registrado con la evidencia.

Medir en la misma máquina:

1. full inicial;
2. incremental sin cambios;
3. incremental con 1 % modificado.

Éxito:

- incremental sin cambios ≤25 % de full, salvo limitación documentada de filesystem;
- uso de memoria no crece proporcionalmente al corpus completo;
- throughput y duración coinciden con métricas persistidas;
- la medición no se convierte en benchmark universal de hardware.

## 9. Aceptación manual de chunks

Revisar al menos:

- package body grande;
- procedure standalone;
- Window PowerBuilder con eventos;
- DataWindow con SQL;
- Markdown jerárquico;
- PDF multipágina;
- DOCX con tabla.

Para cada uno verificar:

- no se pierde evidencia;
- límites son razonables;
- líneas/páginas/objeto apuntan al origen;
- fallback es comprensible;
- metadata incierta está marcada;
- no hay cortes sistemáticos que inutilicen código.

## 10. Trazabilidad

| Requisito | Pruebas principales |
|---|---|
| H2-REQ-001 | unit config, SMK-03/04/09; default 50 MB |
| H2-REQ-002 | INT-01, INT-08, INT-11 |
| H2-REQ-003–004 | unit discovery, INT-07/09 |
| H2-REQ-005–008 | fingerprint, INT-02–06/10 |
| H2-REQ-009–015 | unit parsers, extensiones ampliadas y fixtures |
| H2-REQ-016–018 | unit normalization/chunking, confidence y revisión manual |
| H2-REQ-019–021 | unit SQLite, INT-01/04/12 |
| H2-REQ-022 | INT-07/08/12 |
| H2-REQ-023–025 | SMK-01–10, INT-11/13 |
| H2-REQ-026 | INT-15, instalación limpia |
| H2-REQ-027 | INT-13/14, stats e inventario sin reescaneo |
| H2-NFR-001 | medición de rendimiento |
| H2-NFR-002 | INT-02/05/10 |
| H2-NFR-003 | Windows + Linux |
| H2-NFR-004 | captura de logs |
| H2-NFR-005 | prueba de imports |
| H2-NFR-006–008 | integridad, revisión estructural |

## 11. Criterios de éxito

- [ ] todos los requisitos Must pasan;
- [ ] cada formato incluido tiene fixture;
- [ ] todos los compatibles quedan processed, skipped o error explícito;
- [ ] cada chunk es trazable e incluye metadata de confidence cuando deriva de `LogicalUnit`;
- [ ] incremental no reprocesa unchanged;
- [ ] cambios/eliminaciones no dejan duplicados o huérfanos;
- [ ] errores recuperables no detienen el lote;
- [ ] schema v2, FK y WAL están activos;
- [ ] imports y comandos read-only no tienen efectos;
- [ ] el inventario puede consultarse sin reescanear filesystem;
- [ ] no hay red, embeddings o vector store;
- [ ] mensajes de usuario están en español;
- [ ] ejecutable instalado pasa smoke tests fuera del source tree;
- [ ] revisión manual es satisfactoria.

## 12. Evidencia de cierre

Al completar H2 se debe crear un documento de aceptación separado con:

- commit o versión evaluada;
- sistema operativo y Python;
- comandos ejecutados;
- resultado y duración de tests;
- salida resumida de full/incremental/stats;
- conteos SQLite e integridad;
- resultado de revisión manual;
- limitaciones conocidas y decisiones diferidas.
