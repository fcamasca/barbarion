# CLI de Barbarion

Este documento es la referencia oficial de la linea de comandos de Barbarion. La implementacion real en `src/barbarion/cli.py` es la fuente de verdad para comandos, argumentos y codigos de salida.

## Flujo recomendado

```text
doctor
  |
ingest
  |
index
  |
search / ask
  |
analyze
  |
inventory
  |
describe
  |
impact
  |
spec create / spec validate
  |
stats
```

`doctor` inicializa recursos locales y diagnostica el entorno. `ingest` lee el corpus autorizado y persiste metadata/chunks en SQLite. `index` prepara embeddings locales para RAG. `search` recupera evidencia y `ask` construye una respuesta citada. `analyze` extrae simbolos y relaciones para reverse engineering. `inventory`, `describe` e `impact` consultan ese catalogo tecnico. `stats` permite revisar el estado local de ingesta, RAG y reverse engineering.

`spec create` coordina Spec Mode sobre la evidencia ya disponible: H3 para evidencia documental, H4 para impacto tecnico, Review interno, render Markdown, validacion estructural y escritura segura. `spec validate` revisa una carpeta Markdown existente sin regenerarla.


## Preparación del entorno

Instalación local recomendada:

```bash
git clone https://github.com/fcamasca/barbarion.git
cd barbarion
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Activación del entorno:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# Linux o macOS
source .venv/bin/activate
```

Si PowerShell bloquea la ejecución de scripts con `PSSecurityException`, habilita la ejecución solo para la sesión actual:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Configuración local:

```powershell
# Windows PowerShell
Copy-Item barbarion.example.toml barbarion.toml
```

```bash
# Linux o macOS
cp barbarion.example.toml barbarion.toml
```

Edita `barbarion.toml` y apunta `[ingestion].paths` a una carpeta local autorizada, por ejemplo:

```toml
[ingestion]
paths = ["./sources"]
```

Ollama es opcional para comandos que no usan embeddings ni LLM. Para ejecuciones RAG con embeddings o LLM local, instala Ollama desde `https://ollama.com/` y descarga modelos locales:

```bash
ollama --version
ollama pull nomic-embed-text
ollama pull llama3.1:8b
ollama list
```

`nomic-embed-text` se usa para embeddings. `llama3.1:8b` es una opción local para `ask`; puede cambiarse en `[llm]`.

## Operacion con y sin Ollama

| Comando | Requiere embeddings | Requiere LLM | Funciona offline |
|---|---|---|---|
| `version`, `help`, `config show` | No | No | Si |
| `doctor` | No | No | Si; Ollama ausente se reporta como diagnostico |
| `ingest` | No | No | Si |
| `index` | Si, salvo `--dry-run` | No | Si, usando Ollama local |
| `reindex` | Si, salvo `--dry-run` | No | Si, usando Ollama local |
| `search --mode keyword` | No | No | Si |
| `search --mode semantic|hybrid` | Si | No | Si, usando Ollama local |
| `ask --no-llm --mode keyword` | No | No | Si |
| `ask --no-llm --mode semantic|hybrid` | Si | No | Si, usando Ollama local |
| `ask` con LLM | Segun modo | Si | Si, usando Ollama local |
| `embeddings` | No | No | Si |
| `analyze` | No | No | Si |
| `inventory` | No | No | Si |
| `describe --no-llm` | No | No | Si |
| `describe --with-llm` | No; puede usar RAG si se pide `--include-rag` | Si | Si, usando Ollama local |
| `impact --no-llm` | No | No | Si |
| `impact --with-llm` | No; puede usar RAG si se pide `--include-rag` | Si | Si, usando Ollama local |
| `spec create --no-llm` | Segun `--mode` | No | Si |
| `spec create` | Segun `--mode` | No actualmente; la sintesis asistida queda subordinada a evidencia local | Si |
| `spec validate` | No | No | Si |
| `stats` | No | No | Si |
| `generate-report` | No | No | Si |

Offline significa sin servicios cloud. Barbarion esta disenado para operar local/on-premise; cuando usa modelos, los invoca mediante Ollama local.

## Archivos de salida

`--format` selecciona la representacion cuando el comando lo soporta. Los formatos reales son `text`, `json` y `markdown`, excepto `embeddings` y `stats`, que soportan `text` y `json`.

`--output RUTA` escribe la salida en un archivo cuando el comando lo soporta. `inventory`, `describe` e `impact` pueden escribir archivos y rechazan sobrescritura por defecto. Usa `--overwrite` para reemplazar un archivo existente.

`--debug` envia metricas operativas a `stderr` en los comandos que lo soportan. No debe mezclarse mentalmente con la salida principal en `stdout`; sirve para diagnostico y automatizacion.

`generate-report --output DIRECTORIO` es una excepcion: su salida es un directorio de reportes RAG, no una redireccion generica de stdout.

## Referencia de comandos

### Generales

### version

Proposito: mostrar la version instalada y finalizar sin inicializar recursos.

Sintaxis:

```bash
barbarion --version
```

Argumentos principales: no acepta argumentos propios.

Ejemplo:

```bash
barbarion --version
```

Usalo para confirmar que el entorno ejecuta la version esperada. No modifica SQLite, no requiere embeddings y no requiere LLM. Codigo de salida esperado: `0`.

### help

Proposito: mostrar ayuda generada por la CLI.

Sintaxis:

```bash
barbarion --help
barbarion COMANDO --help
```

Argumentos principales: no acepta argumentos propios.

Ejemplos:

```bash
barbarion --help
barbarion search --help
```

Usalo para consultar la ayuda corta disponible en la instalacion actual. No modifica SQLite, no requiere embeddings y no requiere LLM. Codigo de salida esperado: `0`.

### config

Proposito: consultar la configuracion efectiva.

Sintaxis:

```bash
barbarion config show
barbarion --config RUTA config show
```

Argumentos principales: el subcomando real disponible es `show`. La opcion global `--config RUTA` permite indicar un TOML especifico.

Ejemplo:

```bash
barbarion config show
```

Usalo para verificar rutas, modelos y parametros antes de ejecutar ingesta o RAG. No modifica SQLite, no requiere embeddings y no requiere LLM. Codigos de salida: `0` si la configuracion es valida, `2` si hay error de configuracion.

### doctor

Proposito: inicializar recursos locales minimos y diagnosticar el entorno.

Sintaxis:

```bash
barbarion doctor
```

Argumentos principales: no acepta argumentos propios.

Ejemplo:

```bash
barbarion doctor
```

Usalo como primer comando de un proyecto local. Crea directorios configurados, SQLite y log si faltan. No requiere embeddings ni LLM. Codigo de salida: `0` si los checks requeridos pasan, `1` si falla un requisito operativo.

### Ingesta

### ingest

Proposito: leer corpus local autorizado y persistir metadata, documentos y chunks en SQLite, o consultar estadisticas de ingesta.

Sintaxis:

```bash
barbarion ingest [--path RUTA] [--incremental | --full] [--stats]
```

Argumentos principales:

- `--path RUTA`: root de ingesta ad hoc; puede repetirse y reemplaza paths configurados.
- `--incremental`: ejecuta ingesta incremental.
- `--full`: reprocesa todos los archivos descubiertos.
- `--stats`: muestra estadisticas persistidas sin ejecutar ingesta.

Ejemplos:

```bash
barbarion ingest
barbarion ingest --full
barbarion ingest --path sources/oracle --path sources/powerbuilder
barbarion ingest --stats
```

Usalo despues de `doctor` y antes de `index` o `analyze`. Modifica SQLite salvo cuando se usa `--stats`. No requiere embeddings ni LLM. Codigos de salida: `0` si termina correctamente, `1` si hay error operativo o ingesta con errores recuperables, `2` para combinaciones invalidas como `--stats --full`, `130` si se interrumpe.

### RAG

### Notas operativas RAG

`--mode keyword` usa coincidencia textual. Es la mejor opcion cuando conoces el identificador exacto: variables, tablas, procedimientos, funciones, clases, eventos, codigos de negocio o literales del corpus.

`--mode semantic` usa similitud por significado sobre embeddings. Es util para explorar una idea cuando no conoces los nombres exactos usados por el sistema legacy.

`--mode hybrid` combina ambos enfoques. Mantiene la capacidad de encontrar terminos literales y tambien recupera evidencia relacionada por significado. Es el modo recomendado para preguntas naturales y exploracion general.

Regla rapida:

- usa `keyword` para nombres exactos;
- usa `semantic` para conceptos amplios;
- usa `hybrid` cuando la pregunta esta en lenguaje natural o no sabes si las palabras coinciden con el codigo.

`index` y `reindex` manejan Ctrl+C de forma cooperativa. Al interrumpir, Barbarion termina la unidad minima en curso para no separar vector y metadata, cierra la corrida como `interrupted` y muestra un resumen con procesados, pendientes, embeddings generados y vectores persistidos. Una nueva ejecución puede continuar desde el ultimo estado consistente mediante la logica incremental existente.

Cambiar proveedor, modelo, dimension, distancia o normalizacion de embeddings produce una version de embeddings distinta y exige reindexar.

Barbarion no envia corpus a servicios cloud. Los prompts completos no se almacenan por defecto. `rag_queries` guarda hash de la consulta, modo, filtros, conteos y latencias. En RAG, `--debug` puede mostrar scores, filtros, fuentes y snippets; debe usarse con la misma cautela que cualquier salida que pueda incluir fragmentos de codigo.

Con `--debug`, ask escribe en stderr un diagnostico del flujo RAG: consulta, modelos usados, retrieval, chunks, prompt truncado, respuesta del LLM, validacion de citas, reparacion y resumen final. stdout conserva la salida normal, por lo que JSON y Markdown siguen siendo parseables.

Errores operativos frecuentes:

- Base ausente: ejecuta `barbarion doctor` e ingesta antes de RAG.
- Ollama embeddings no disponible: `index` falla con error operativo; `index --dry-run`, `search --mode keyword` y `ask --no-llm --mode keyword` siguen siendo utiles.
- Errores de indexacion: consulta `barbarion embeddings --errors` para ver `run_id`, `chunk_id`, codigo y mensaje persistidos.
- Evidencia insuficiente: `ask` declara que no hay fuentes suficientes y no inventa respuesta.
- Citas invalidas: la respuesta candidata se rechaza antes de mostrarse como valida.

### index

Proposito: indexar incrementalmente chunks vigentes para recuperacion RAG.

Sintaxis:

```bash
barbarion index [--dry-run]
```

Argumentos principales:

- `--dry-run`: muestra alcance sin escribir ni llamar modelos.

Ejemplos:

```bash
barbarion index --dry-run
barbarion index
```

Usalo despues de `ingest`. Modifica SQLite y el almacenamiento vectorial, salvo en `--dry-run`. Requiere embeddings en ejecución real; no requiere LLM. Codigos de salida: `0` si termina sin errores, `1` ante error operativo o chunks fallidos, `130` si se interrumpe.

### reindex

Proposito: reconstruir total o parcialmente el indice RAG.

Sintaxis:

```bash
barbarion reindex [--full] [--path RUTA] [--document ID] [--chunk-id ID] [--dry-run] [--delete-obsolete]
```

Argumentos principales:

- `--full`: reindexa todos los chunks vigentes.
- `--path RUTA`: limita por prefijo de ruta persistida.
- `--document ID`: limita a un documento.
- `--chunk-id ID`: limita a un chunk.
- `--dry-run`: muestra alcance sin escribir ni llamar modelos.
- `--delete-obsolete`: elimina vectores obsoletos durante una reindexacion completa.

Ejemplos:

```bash
barbarion reindex --full
barbarion reindex --path sources/oracle --dry-run
barbarion reindex --document 12
barbarion reindex --chunk-id chunk-abc
```

Usalo cuando cambia el modelo de embeddings, la version de indice o quieres reconstruir un subconjunto. Requiere al menos uno de `--full`, `--path`, `--document` o `--chunk-id`. Modifica SQLite y vectores salvo en `--dry-run`. Requiere embeddings en ejecución real; no requiere LLM. Codigos de salida: `0`, `1`, `2` o `130` segun resultado.

### search

Proposito: recuperar evidencia RAG local.

Sintaxis:

```bash
barbarion search TEXTO [--mode semantic|keyword|hybrid] [--top-k N] [--candidate-k N] [--threshold N] [--format text|json|markdown] [--domain TEXTO] [--artifact-kind TEXTO] [--language TEXTO] [--document ID] [--folder TEXTO] [--extension TEXTO] [--debug]
```

Argumentos principales:

- `TEXTO`: consulta.
- `--mode`: modo de recuperacion; por defecto `hybrid`.
- `--top-k`: cantidad final.
- `--candidate-k`: cantidad inicial de candidatos.
- `--threshold`: score minimo aceptado.
- `--format`: formato de salida.
- `--domain`, `--artifact-kind`, `--language`, `--document`, `--folder`, `--extension`: filtros.
- `--debug`: incluye debug RAG.

Ejemplos:

```bash
barbarion search "order_total" --mode keyword
barbarion search "donde se calcula order_total" --mode hybrid --top-k 5
barbarion search "logica de descuentos" --mode semantic --format json
```

Usalo para encontrar evidencia antes de preguntar o para inspeccion tecnica directa. Registra metricas de consulta en SQLite. `keyword` no requiere embeddings; `semantic` e `hybrid` requieren embeddings. No requiere LLM. Codigos de salida: `0` si ejecuta la busqueda, `1` si falta SQLite o hay error operativo, `2` si los argumentos son invalidos.

### ask

Proposito: responder una pregunta usando contexto RAG local, con evidencia y citas.

Sintaxis:

```bash
barbarion ask TEXTO [--mode semantic|keyword|hybrid] [--top-k N] [--candidate-k N] [--threshold N] [--format text|json|markdown] [--domain TEXTO] [--artifact-kind TEXTO] [--language TEXTO] [--document ID] [--folder TEXTO] [--extension TEXTO] [--debug] [--no-llm]
```

Argumentos principales: comparte los argumentos de `search` y agrega `--no-llm`, que muestra contexto y fuentes sin invocar LLM.

Ejemplos:

```bash
barbarion ask "que fuentes explican order_total?" --mode hybrid
barbarion ask "que fuentes explican order_total?" --mode keyword --no-llm
barbarion ask "donde se calcula el total?" --format markdown
```

Usalo cuando necesitas una respuesta sintetizada y trazable. Registra metricas de consulta/contexto en SQLite. `keyword --no-llm` no requiere embeddings ni LLM. Sin `--no-llm`, requiere LLM local. Codigos de salida: `0` si la respuesta pasa validacion de citas, `1` si hay error operativo, error LLM o citas invalidas, `2` si los argumentos son invalidos, `130` si se interrumpe.

### embeddings

Proposito: consultar manifests, versiones, conteos y errores de indexacion RAG.

Sintaxis:

```bash
barbarion embeddings [--format text|json] [--errors] [--run ID]
```

Argumentos principales:

- `--format`: formato de salida `text` o `json`.
- `--errors`: muestra errores de indexacion persistidos.
- `--run ID`: limita errores a un run especifico.

Ejemplos:

```bash
barbarion embeddings
barbarion embeddings --format json
barbarion embeddings --errors
barbarion embeddings --errors --run 3
```

Usalo para diagnosticar el estado del indice. No modifica SQLite, no requiere embeddings ni LLM. Si no existe la base, informa el estado y devuelve `0`.

### Reverse Engineering

### Notas operativas Data-Driven

Cuando `data_driven.enabled = true`, `ingest` clasifica como `configuration`
solo los `.sql` que coinciden con los patrones declarados y afectan una tabla
configurada. `analyze` procesa cada documento completo; los chunks se conservan
como evidencia y ubicacion, no como unidad de parsing DML.

Antes de publicar cambios, usa `barbarion analyze --dry-run`. El resumen muestra
archivos DML identificados, sentencias procesadas/soportadas/omitidas/con error,
registros, simbolos, referencias, configuraciones reconciliadas, relaciones por
estado, advertencias trazables y duracion por etapa. Las advertencias incluyen
ruta, lineas y un `motivo` estable.

Diagnosticos frecuentes:

- `unsupported_statement`: la sentencia queda omitida; conviertela a un
  `INSERT ... VALUES` o `UPDATE ... SET ... WHERE` soportado si debe analizarse.
- `undeclared_table`: declara la tabla en la configuracion correcta o revisa el
  patron del archivo.
- `missing_identity` o `missing_identity_where`: agrega todas las columnas de
  identidad requeridas.
- `column_value_mismatch`: corrige la cantidad de columnas y valores.
- `max_statements_per_file` o `max_literal_chars`: revisa el archivo y ajusta el
  limite solo si el corpus autorizado lo requiere.

Un diagnostico recuperable no impide procesar otros documentos validos. Una
interrupcion devuelve `130` y no publica conocimiento parcial del alcance.

### analyze

Proposito: extraer simbolos y relaciones desde chunks vigentes.

Sintaxis:

```bash
barbarion analyze [--full] [--path PREFIJO] [--dry-run]
```

Argumentos principales:

- `--full`: analiza todos los chunks vigentes.
- `--path PREFIJO`: limita el analisis por prefijo de ruta persistida; puede repetirse.
- `--dry-run`: calcula alcance y resultados esperados sin escribir SQLite.

Ejemplos:

```bash
barbarion analyze --dry-run
barbarion analyze
barbarion analyze --full
barbarion analyze --path sources/oracle --path sources/powerbuilder
barbarion analyze --path config/pricing --dry-run
```

Usalo despues de `ingest` para poblar el catalogo tecnico H4. Modifica SQLite salvo con `--dry-run`. No requiere embeddings ni LLM. Codigos de salida: `0`, `1` o `130` segun resultado.

### inventory

Proposito: consultar inventario tecnico persistido.

Sintaxis:

```bash
barbarion inventory [--technology oracle|powerbuilder|configuration|document|unknown] [--type TIPO] [--name TEXTO] [--path PREFIJO] [--status active|stale|deleted|ambiguous] [--confidence high|medium|low] [--format text|json|markdown] [--output RUTA] [--overwrite] [--debug]
```

Argumentos principales:

- filtros: `--technology`, `--type`, `--name`, `--path`, `--status`, `--confidence`.
- salida: `--format`, `--output`, `--overwrite`.
- diagnostico: `--debug`.

Ejemplos:

```bash
barbarion inventory
barbarion inventory --technology oracle --format markdown
barbarion inventory --technology configuration --format markdown
barbarion inventory --name order --output reports/inventory.md --overwrite
```

Usalo para revisar el catalogo tecnico sin reanalizar el corpus. No modifica SQLite, no requiere embeddings ni LLM. Codigos de salida: `0`, `1` o `2` segun resultado.

### describe

Proposito: generar una ficha tecnica de un componente.

Sintaxis:

```bash
barbarion describe OBJETO [--type TIPO] [--id SYMBOL_ID] [--depth N] [--include-rag] [--with-llm] [--no-llm] [--format text|json|markdown] [--output RUTA] [--overwrite] [--debug]
```

Argumentos principales:

- `OBJETO`: nombre tecnico a describir.
- `--type`: tipo tecnico para desambiguar.
- `--id`: identificador exacto de simbolo.
- `--depth`: profundidad de dependencias `0..5`.
- `--include-rag`: incluye fuentes RAG complementarias.
- `--with-llm`: intenta sintetizar con LLM local.
- `--no-llm`: fuerza salida deterministica sin LLM.
- `--format`, `--output`, `--overwrite`, `--debug`: salida y diagnostico.

Ejemplos:

```bash
barbarion describe order_total --no-llm
barbarion describe order_total --depth 2 --format markdown
barbarion describe order_total --id oracle:procedure:order_total
```

Usalo para explicar un componente a partir de simbolos y relaciones persistidas. No modifica SQLite. No requiere embeddings salvo que el servicio use RAG por `--include-rag`; requiere LLM solo con `--with-llm`. Codigos de salida: `0`, `1` o `2` segun resultado.

### impact

Proposito: analizar impacto tecnico desde relaciones persistidas.

Sintaxis:

```bash
barbarion impact OBJETO [--type TIPO] [--id SYMBOL_ID] [--direction incoming|outgoing|both] [--depth N] [--node-limit N] [--technology oracle|powerbuilder|document|unknown] [--relation-type TIPO] [--resolution-status resolved|ambiguous|unresolved|external|dynamic] [--min-confidence high|medium|low] [--include-rag] [--with-llm] [--no-llm] [--format text|json|markdown] [--output RUTA] [--overwrite] [--debug]
```

Argumentos principales:

- `OBJETO`: componente base del analisis.
- `--type`, `--id`: desambiguacion.
- `--direction`: direccion del recorrido; por defecto `both`.
- `--depth`: profundidad `0..5`.
- `--node-limit`: limite maximo de nodos visitados.
- filtros: `--technology`, `--relation-type`, `--resolution-status`, `--min-confidence`.
- contexto y sintesis: `--include-rag`, `--with-llm`, `--no-llm`.
- salida: `--format`, `--output`, `--overwrite`, `--debug`.

Ejemplos:

```bash
barbarion impact order_total --depth 2 --no-llm
barbarion impact order_total --direction incoming --format json
barbarion impact order_total --relation-type calls --min-confidence medium
```

Usalo para estimar consumidores, dependencias, cruces de tecnologia y riesgos. No modifica SQLite. No requiere embeddings salvo que el servicio use RAG por `--include-rag`; requiere LLM solo con `--with-llm`. Codigos de salida: `0`, `1` o `2` segun resultado.

### Spec Mode

### Notas operativas Spec Mode

Spec Mode genera una especificacion Markdown editable para un cambio funcional. No modifica codigo fuente, no ejecuta tareas y no reemplaza la revision humana. El pipeline operativo de `spec create` es:

```text
RequirementAnalyzer -> H3 -> H4 -> SpecSynthesizer -> Review -> Markdown -> SpecValidator -> SafeSpecWriter
```

La CLI solo interpreta argumentos y presenta resultados. H3 recupera evidencia documental; H4 aporta simbolos, relaciones e impacto; Review revisa el `SpecDraft` antes del render; `SpecValidator` valida archivos Markdown renderizados; `SafeSpecWriter` escribe sin sobrescribir por defecto.

`--debug` escribe observabilidad en `stderr`: modo RAG, `top_k`, profundidad H4, etapas ejecutadas, estado de Review, conteos de errores/advertencias, evidencia, componentes, reglas, preguntas abiertas, documentos renderizados y archivos escritos. `stdout` queda reservado para el resumen normal.

Errores operativos frecuentes:

- Base SQLite ausente: ejecuta `doctor`, `ingest`, `index` y `analyze` antes de `spec create`.
- Review fallido: no se escriben archivos; revisa los issues sobre evidencia, reglas detectadas y preguntas abiertas.
- Validacion Markdown fallida: no se escriben archivos; corrige los issues de estructura, IDs, citas o trazabilidad.
- Carpeta existente: `spec create` rechaza sobrescritura por defecto; usa `--overwrite` solo cuando quieras reemplazar los cuatro Markdown esperados.
- Spec editada manualmente: ejecuta `spec validate` antes de usarla como entrada de revision humana.

### spec create

Proposito: crear una spec Markdown H5 desde un requerimiento funcional.

Sintaxis:

```bash
barbarion spec create "REQUERIMIENTO" [--name NOMBRE] [--output RUTA] [--mode semantic|keyword|hybrid] [--depth N] [--top-k N] [--no-llm] [--overwrite] [--debug]
```

Argumentos principales:

- `REQUERIMIENTO`: cambio funcional a especificar.
- `--name`: nombre logico para la carpeta de salida.
- `--output`: directorio de salida; por defecto `output/specs/<slug>`.
- `--mode`: modo RAG H3; por defecto `hybrid`.
- `--depth`: profundidad de impacto H4 `0..5`; por defecto `1`.
- `--top-k`: cantidad maxima de fuentes RAG.
- `--no-llm`: fuerza sintesis deterministica.
- `--overwrite`: permite reemplazar los cuatro Markdown esperados.
- `--debug`: muestra observabilidad en `stderr`.

Ejemplos:

```bash
barbarion spec create "Agregar validacion de limite de credito" --name limite-credito --mode keyword --no-llm
barbarion spec create "Agregar validacion de limite de credito" --depth 2 --top-k 12
barbarion spec create "Agregar validacion de limite de credito" --output specs/limite-credito --overwrite
```

Escribe `requirements.md`, `design.md`, `tasks.md` y `test-plan.md` si Review y validacion pasan. Codigos de salida: `0` si escribe correctamente, `1` ante error operativo, Review fallido o validacion fallida, `2` si los argumentos son invalidos.

### spec validate

Proposito: validar una spec Markdown H5 existente, generada o editada manualmente.

Sintaxis:

```bash
barbarion spec validate RUTA [--strict] [--format text|json]
```

Argumentos principales:

- `RUTA`: carpeta con `requirements.md`, `design.md`, `tasks.md` y `test-plan.md`.
- `--strict`: trata advertencias como salida fallida.
- `--format`: reporte `text` o `json`.

Ejemplos:

```bash
barbarion spec validate output/specs/limite-credito
barbarion spec validate output/specs/limite-credito --format json
barbarion spec validate output/specs/limite-credito --strict
```

No ejecuta H3, H4, Review ni sintesis; solo aplica `SpecValidator` sobre archivos existentes. Codigos de salida: `0` si la spec es valida, `1` si hay errores o advertencias en modo `--strict`, `2` si los argumentos son invalidos.

### Observabilidad

### stats

Proposito: mostrar estadisticas locales de ingesta, RAG y reverse engineering.

Sintaxis:

```bash
barbarion stats [--format text|json]
```

Argumentos principales:

- `--format`: salida `text` o `json`.

Ejemplos:

```bash
barbarion stats
barbarion stats --format json
```

Usalo para revisar estado general sin mutar la base. Cuando existen
configuraciones, la salida de texto agrega claves `data_driven.*` y JSON agrega
`reverse_engineering.data_driven` con archivos, simbolos, referencias y
relaciones `resolved`, `ambiguous`, `unresolved`, `dynamic` y `external`. No
modifica SQLite, no requiere embeddings ni LLM. Si no existe SQLite, informa el
estado y devuelve `0`.

### generate-report

Proposito: generar evidencia tecnica RAG local.

Sintaxis:

```bash
barbarion generate-report [--dataset DATASET] [--output OUTPUT] [--test-summary TEXTO] [--smoke-summary TEXTO]
```

Argumentos principales:

- `--dataset`: dataset de evaluacion RAG; por defecto `tests/fixtures/rag_evaluation.json`.
- `--output`: directorio de salida; por defecto `reports/rag`.
- `--test-summary`: resumen de suite a registrar.
- `--smoke-summary`: resumen smoke a registrar.

Ejemplos:

```bash
barbarion generate-report
barbarion generate-report --output reports/rag
barbarion generate-report --test-summary "412 passed, 12 skipped"
```

Usalo para regenerar reportes tecnicos RAG a partir de un dataset de evaluacion. Escribe archivos locales en el directorio de salida. No requiere embeddings ni LLM. Codigo de salida esperado: `0`; errores de archivo o dataset se reportan como errores operativos.

## Codigos de salida

Barbarion usa estos codigos desde la CLI:

| Codigo | Significado |
|---:|---|
| `0` | Comando completado. En `doctor`, todos los checks requeridos pasan, aunque puede haber advertencias opcionales. |
| `1` | Error operativo esperado, fallo requerido de `doctor`, ingesta con errores recuperables, error de base de datos, error LLM o respuesta `ask` con citas invalidas. |
| `2` | Argumentos invalidos o configuracion invalida. |
| `130` | Operacion interrumpida por el usuario. |

Los errores esperados se presentan sin traceback.

## Buenas practicas

- Ejecuta primero `barbarion doctor`.
- Usa `--dry-run` antes de `index`, `reindex` o `analyze` cuando quieras medir alcance.
- Prefiere `--no-llm` para inspeccion determinista.
- Usa `--debug` para diagnostico operativo.
- No versiones `data/`, `output/`, `logs/`, bases SQLite ni salidas generadas.
- Usa `keyword` para nombres exactos y `hybrid` para preguntas naturales.
