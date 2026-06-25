# H2 - Ingestion: Evidencia de aceptacion

## 1. Resultado

**Fecha:** 2026-06-24  
**Estado:** aceptado  
**Version:** `0.2.0`  
**Base evaluada:** `9b08a8e` con cambios H2 pendientes en el working tree.

H2 cumple los requisitos Must del hito y puede cerrarse. La aceptacion se ejecuto con una instalacion editable en un entorno virtual temporal limpio y con el entry point instalado `barbarion.exe`.

## 2. Entorno validado

- Windows local;
- CPython `3.12.13`;
- instalacion: `python -m pip install -e ".[dev]"`;
- SQLite local con esquema version `2` y WAL activo;
- corpus sintetico publico generado desde `tests/fixtures/h2_corpus` y `tests/support/h2_corpus.py`;
- Ollama no disponible durante la aceptacion manual; H2 no lo requiere.

El venv temporal se creo en `%TEMP%\barbarion-h2-acceptance-venv` y se elimina al finalizar la tarea.

## 3. Suite automatizada

Comando ejecutado desde el venv limpio:

```text
python -m pytest -o cache_dir=%TEMP%\barbarion_pytest_cache
```

Resultado:

```text
260 collected
258 passed, 2 skipped in 38.63s
```

La suite incluye unit tests, integracion y smoke tests contra `barbarion.exe` instalado. Los smoke tests cubren ayuda, version, `config show`, `doctor`, `ingest`, `--path` repetible, `--full`, `--stats`, bootstrap requerido y argumentos invalidos.

## 4. Comandos manuales de aceptacion

Workspace temporal: `%TEMP%\barbarion-h2-acceptance-run`.

| Comando | Codigo | Resultado |
|---|---:|---|
| `barbarion --config barbarion.toml doctor` | `0` | `6 PASS`, `1 WARN`, `0 FAIL`; SQLite en esquema version `2` |
| `barbarion --config barbarion.toml ingest --full` | `0` | `28` descubiertos, `27` procesados, `1` omitido, `0` errores, `44` chunks |
| `barbarion --config barbarion.toml ingest` | `0` | incremental sin cambios: `0` procesados, `27` sin cambios, `1` omitido |
| `barbarion --config barbarion.toml ingest` tras modificar `docs/notes.txt` | `0` | `1` procesado, `26` sin cambios, `1` omitido |
| `barbarion --config barbarion.toml ingest --stats` | `0` | inventario desde SQLite sin reescanear corpus |

Salida resumida de stats:

```text
ultimo_run = 3
ultimo_estado = completed
archivos_vigentes = 27
documentos_vigentes = 27
chunks_vigentes = 44
artefactos = config:4, docx:1, markdown:1, oracle:11, pdf:1, powerbuilder:7, text:2
```

## 5. Conteos SQLite e integridad

Despues de full, incremental sin cambios e incremental con modificacion:

| Metrica | Valor |
|---|---:|
| files `processed` | 27 |
| files `skipped` | 1 |
| documents | 27 |
| chunks | 44 |
| errores persistidos | 3 |
| chunks huerfanos | 0 |

Los errores persistidos corresponden a la `.pbl` binaria sintetica omitida en cada run. No incrementan `error_count` del run porque `UNSUPPORTED_BINARY_PBL` es un caso `skipped` esperado.

## 6. Rendimiento incremental

Corpus sintetico de referencia: `1000` archivos `.txt`, `44,890` bytes.

| Escenario | Codigo | Procesados | Sin cambios | Chunks | Duracion CLI | Duracion run |
|---|---:|---:|---:|---:|---:|---:|
| full inicial | `0` | 1000 | 0 | 1000 | `35.343s` | `34.500s` |
| incremental sin cambios | `0` | 0 | 1000 | 0 | `6.424s` | `5.577s` |
| incremental con 1% modificado | `0` | 10 | 990 | 10 | `7.448s` | `6.655s` |

Ratio incremental sin cambios / full: `18.2%`, dentro del umbral H2-NFR-001 de `<=25%`.

## 7. Revision manual de chunks

Se revisaron chunks representativos desde SQLite:

| Fuente | Resultado |
|---|---|
| `oracle/package_body.pkb` | Package body, procedure `refresh_totals` y function `status_label` con lineas y objeto correctos |
| `powerbuilder/window.srw` | Window textual con evento preservado |
| `powerbuilder/datawindow.srd` | DataWindow con SQL `retrieve` y metadata de objeto |
| `docs/guide.md` | Secciones Markdown con breadcrumbs y bloque SQL preservado |
| `docs/manual.pdf` | Dos paginas con `page_start` y `page_end` correctos |
| `docs/manual.docx` | Heading, parrafo y tabla en orden estable |

La revision no detecto perdida de evidencia ni contenido fuente en logs. Los chunks contienen localizadores o metadata aplicable segun formato.

## 8. Trazabilidad de requisitos

- H2-REQ-001: configuracion `[ingestion]`, defaults y `config show` cubiertos por unit tests y docs.
- H2-REQ-002 a H2-REQ-008: runs, fingerprints, incremental, full y reconciliacion cubiertos por unit/integration.
- H2-REQ-009 a H2-REQ-018: parsers, normalizacion, chunking, IDs y confidence cubiertos por unit tests y corpus sintetico.
- H2-REQ-019 a H2-REQ-021: SQLite v2, WAL, FK, atomicidad y rollback cubiertos por unit tests.
- H2-REQ-022: errores recuperables, fallos fatales y ausencia de contenido fuente en logs cubiertos por service/CLI tests.
- H2-REQ-023 a H2-REQ-027: CLI, stats, inventario, interrupcion e independencia de H3 cubiertos por integration/smoke.
- H2-NFR-001: medicion de 1000 archivos aprobada.
- H2-NFR-002 a H2-NFR-008: determinismo, portabilidad local, observabilidad, imports sin efectos, integridad y estructura modular cubiertos por tests y revision.

## 9. Limitaciones conocidas

- La ejecucion manual se valido en Windows; Linux queda para CI o una matriz posterior.
- Ollama no estaba disponible y aparece como `WARN` en `doctor`; H2 no depende de Ollama.
- H2 no implementa OCR, decompilacion PBL, embeddings, vector store, RAG, analisis de dependencias ni UI.
- Los smoke tests requieren instalar el entry point antes de ejecutarse; esto fue validado en el venv temporal.

## 10. Conclusion

H2 entrega una ingesta local, incremental, trazable y consultable desde SQLite. El corpus sintetico cubre los formatos declarados, la suite automatizada pasa en instalacion limpia, el inventario no reescanea filesystem y la medicion incremental cumple el umbral del hito.
