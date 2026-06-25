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

5. Consultar evidencia:

```bash
barbarion search "Donde se usa NOM_OPERACION_DIA?" --mode hybrid
```

6. Responder con contexto o inspeccionarlo sin LLM:

```bash
barbarion ask "Que documentos hablan de CDVAL?" --no-llm --mode keyword
barbarion ask "Que documentos hablan de CDVAL?" --mode hybrid
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
| `stats` | muestra estadisticas H2 + H3 |

`search` y `ask` aceptan `--mode semantic|keyword|hybrid`, `--top-k`, `--candidate-k`, `--threshold`, `--format text|json|markdown`, `--domain`, `--artifact-kind`, `--language`, `--document`, `--folder`, `--extension` y `--debug`.

## Modelos

`[embeddings]` configura el modelo de embeddings de Ollama. Cambiar proveedor, modelo, dimension, distancia o normalizacion produce una version de embeddings distinta y exige reindexar.

`[llm]` configura el modelo local usado por `ask`. `search` y `ask --no-llm` no requieren LLM.

## Privacidad

Barbarion no envia corpus a servicios cloud. Los prompts completos no se almacenan por defecto. `rag_queries` guarda hash de la consulta, modo, filtros, conteos y latencias. El modo `--debug` puede mostrar scores, filtros, fuentes y snippets; debe usarse con la misma cautela que cualquier salida que pueda incluir fragmentos de codigo.

## Errores esperados

- Base ausente: ejecutar `barbarion doctor` e ingesta antes de RAG.
- Ollama embeddings no disponible: `index` falla con error operativo; `index --dry-run`, `search --mode keyword` y `ask --no-llm --mode keyword` siguen siendo utiles.
- Evidencia insuficiente: `ask` declara que no hay fuentes suficientes y no inventa respuesta.
- Citas invalidas: la respuesta candidata se rechaza antes de mostrarse como valida.

## Limites H3

H3 no implementa ingenieria inversa profunda, grafo de dependencias ni extraccion avanzada de simbolos. Los campos preparados para H4 pueden quedar nulos y `symbol_occurrences` permanece reservado salvo metadata simple disponible desde H2.
