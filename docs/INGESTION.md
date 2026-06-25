# Operacion de ingesta H2

H2 transforma un corpus local autorizado en metadata, documentos normalizados y chunks trazables dentro de SQLite. No genera embeddings, no usa Ollama y no necesita red.

## Flujo recomendado

1. Crear o revisar `barbarion.toml`.
2. Ejecutar `barbarion doctor` para inicializar `data/`, `output/`, `logs/` y `data/barbarion.db`.
3. Ejecutar `barbarion ingest`.
4. Revisar el resumen en consola y `logs/barbarion.log`.
5. Consultar `barbarion ingest --stats` cuando se necesite inventario sin reescanear el filesystem.

`barbarion config show` e `ingest --stats` son comandos de inspeccion: no crean directorios, no inicializan SQLite y no escanean el corpus.

## Configuracion

La seccion `[ingestion]` controla roots, formatos y limites:

```toml
[ingestion]
paths = ["sources/oracle", "sources/powerbuilder", "sources/docs"]
extensions = [".sql", ".pks", ".pkb", ".prc", ".fnc", ".trg", ".pck", ".vw", ".vws", ".pkg", ".tps", ".srw", ".sru", ".srf", ".srm", ".srj", ".srd", ".pbl", ".md", ".txt", ".docx", ".pdf", ".yaml", ".yml", ".json", ".ini"]
chunk_size = 4000
chunk_overlap = 400
ignore_patterns = [".git/**", ".venv/**", "data/**", "output/**", "logs/**"]
max_file_size_mb = 50
max_extracted_chars = 5000000
max_pdf_pages = 1000
encodings = ["utf-8", "cp1252", "latin-1"]
```

Las rutas relativas se resuelven desde el TOML. `--path RUTA` puede repetirse y reemplaza `ingestion.paths` solo para esa ejecucion.

## Comandos

```bash
barbarion ingest
barbarion ingest --full
barbarion ingest --path sources/oracle --path sources/docs
barbarion ingest --stats
```

El modo predeterminado es incremental. `--full` reprocesa archivos compatibles sin truncar el corpus anterior. `--stats` no se combina con `--path`, `--full` ni `--incremental`.

## Formatos soportados

| Familia | Extensiones | Tratamiento |
|---|---|---|
| Oracle/PLSQL | `.sql`, `.pks`, `.pkb`, `.prc`, `.fnc`, `.trg`, `.pck`, `.vw`, `.vws`, `.pkg`, `.tps` | Heuristicas de objeto, package, vista, trigger, procedure y function; fallback de archivo |
| PowerBuilder textual | `.srw`, `.sru`, `.srf`, `.srm`, `.srj`, `.srd` | Export textual; eventos, funciones y SQL DataWindow cuando sea detectable |
| PowerBuilder binario | `.pbl` | Inventario como omitido con `UNSUPPORTED_BINARY_PBL`; no se descompila |
| Documentacion | `.md`, `.txt`, `.docx`, `.pdf` | Extraccion local de texto, headings, tablas o paginas |
| Configuracion | `.yaml`, `.yml`, `.json`, `.ini` | Preservacion textual sin reserializar ni ejecutar |

Una `.pbl` nativa debe exportarse previamente a formatos textuales compatibles. H2 no ejecuta SQL, macros, adjuntos ni acciones embebidas.

PDF requiere capa de texto. H2 no hace OCR; PDFs escaneados quedan como error recuperable si no tienen texto extraible.

## Salidas y codigos

La consola muestra descubiertos, procesados, sin cambios, omitidos, eliminados, errores, chunks, bytes y duracion. Los contadores se persisten por run en SQLite.

| Codigo | Significado |
|---:|---|
| `0` | Ingesta completada sin errores o stats exitoso |
| `1` | Ingesta con errores recuperables o fallo operativo |
| `2` | Argumentos o configuracion invalidos |
| `130` | Interrupcion por usuario |

Los logs incluyen inicio, cierre, estado, etapa, ruta relativa y codigo de error. No registran contenido fuente.

## Inventario

`barbarion ingest --stats` consulta metadata persistida:

- ultimo run y estado;
- archivos, documentos y chunks vigentes;
- agrupacion por `artifact_kind`.

La consulta no accede al corpus y sigue funcionando aunque las fuentes ya no esten disponibles.
