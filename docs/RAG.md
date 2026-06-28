# Operacion RAG H3

H3 agrega recuperacion local sobre los chunks H2. SQLite sigue siendo la fuente de verdad y el almacenamiento vectorial inicial usa SQLite + sqlite-vec. Qdrant queda diferido como alternativa futura.

## Flujo operativo

1. Inicializar recursos:

```bash
barbarion doctor
```

2. Ingerir el corpus:

```bash
barbarion ingest
```

3. Revisar alcance de indexacion sin escribir ni llamar modelos:

```bash
barbarion index --dry-run
```

4. Indexar embeddings locales:

```bash
barbarion index
```

Durante `index` y `reindex`, Barbarion muestra progreso por etapas en `stderr`:

- Descubriendo chunks
- Planificando indexacion
- Generando embeddings
- Persistiendo vectores
- Actualizando metadata
- Finalizando

Cada etapa reporta avance, porcentaje y contadores `new`, `update`, `unchanged`, `delete` y `errores`. Si hay errores, el detalle se consulta con `barbarion embeddings --errors`; SQLite es la fuente principal del detalle y el log conserva solo un resumen.

5. Consultar evidencia:

```bash
barbarion search "Donde se usa process_customer?" --mode hybrid
```

6. Responder con contexto o inspeccionarlo sin LLM:

```bash
barbarion ask "Que documentos hablan de generate_invoice?" --no-llm --mode keyword
barbarion ask "Que documentos hablan de generate_invoice?" --mode hybrid
```

## Comandos H3

| Comando | Uso |
|---|---|
| `index` | indexacion incremental de chunks vigentes |
| `reindex --full` | reindexacion completa de la version activa |
| `reindex --path RUTA` | reindexacion parcial por prefijo persistido |
| `reindex --document ID` | reindexacion parcial por documento |
| `reindex --chunk-id ID` | reindexacion parcial por chunk |
| `search TEXTO` | recupera candidatos estructurados |
| `ask TEXTO` | recupera contexto, llama LLM local y valida citas |
| `ask TEXTO --no-llm` | muestra contexto y fuentes sin llamar LLM |
| `embeddings` | lista manifests, modelos, versiones y conteos |
| `embeddings --errors` | muestra errores de indexacion persistidos en SQLite |
| `stats` | muestra estadisticas H2 + H3 |

`search` y `ask` aceptan `--mode semantic|keyword|hybrid`, `--top-k`, `--candidate-k`, `--threshold`, `--format text|json|markdown`, `--domain`, `--artifact-kind`, `--language`, `--document`, `--folder`, `--extension` y `--debug`.

## Modos de recuperacion

`--mode keyword` usa coincidencia textual. Es la mejor opcion cuando conoces el identificador exacto: variables, tablas, procedimientos, funciones, clases, eventos, codigos de negocio o literales del corpus.

```bash
barbarion search "order_total" --mode keyword
barbarion ask "que fuentes explican order_total?" --mode keyword --no-llm
```

`--mode semantic` usa similitud por significado sobre embeddings. Es util para explorar una idea cuando no conoces los nombres exactos usados por el sistema legacy.

```bash
barbarion search "logica de descuentos comerciales" --mode semantic
```

`--mode hybrid` combina ambos enfoques. Mantiene la capacidad de encontrar terminos literales y tambien recupera evidencia relacionada por significado. Es el modo recomendado para preguntas naturales y exploracion general.

```bash
barbarion search "donde se calcula order_total" --mode hybrid
barbarion ask "que hace el calculo diario?" --mode hybrid
```

Regla rapida:

- usa `keyword` para nombres exactos;
- usa `semantic` para conceptos amplios;
- usa `hybrid` cuando la pregunta esta en lenguaje natural o no sabes si las palabras coinciden con el codigo.

## Cancelacion segura

`index` y `reindex` manejan Ctrl+C de forma cooperativa. Al interrumpir, Barbarion termina la unidad minima en curso para no separar vector y metadata, cierra la corrida como `interrupted` y muestra un resumen con procesados, pendientes, embeddings generados y vectores persistidos.

Una nueva ejecucion puede continuar desde el ultimo estado consistente mediante la logica incremental existente. No se requiere rollback completo: los chunks ya persistidos quedan como `indexed` y los pendientes se planifican de nuevo.

## Modelos

`[embeddings]` configura el modelo de embeddings de Ollama. Cambiar proveedor, modelo, dimension, distancia o normalizacion produce una version de embeddings distinta y exige reindexar.

`[llm]` configura el modelo local usado por `ask`. `search` y `ask --no-llm` no requieren LLM.

## Privacidad

Barbarion no envia corpus a servicios cloud. Los prompts completos no se almacenan por defecto. `rag_queries` guarda hash de la consulta, modo, filtros, conteos y latencias. El modo `--debug` puede mostrar scores, filtros, fuentes y snippets; debe usarse con la misma cautela que cualquier salida que pueda incluir fragmentos de codigo.

## Errores esperados

- Base ausente: ejecutar `barbarion doctor` e ingesta antes de RAG.
- Ollama embeddings no disponible: `index` falla con error operativo; `index --dry-run`, `search --mode keyword` y `ask --no-llm --mode keyword` siguen siendo utiles.
- Errores de indexacion: consultar `barbarion embeddings --errors` para ver `run_id`, `chunk_id`, codigo y mensaje persistidos.
- Evidencia insuficiente: `ask` declara que no hay fuentes suficientes y no inventa respuesta.
- Citas invalidas: la respuesta candidata se rechaza antes de mostrarse como valida.

## Limites H3

H3 no implementa ingenieria inversa profunda, grafo de dependencias ni extraccion avanzada de simbolos. Los campos preparados para H4 pueden quedar nulos y `symbol_occurrences` permanece reservado salvo metadata simple disponible desde H2.
