# H3 - RAG: Requisitos

## 1. Proposito

H3 agrega a Barbarion la capacidad de indexar semanticamente los chunks vigentes de H2, recuperar contexto local relevante y responder preguntas tecnicas con fuentes verificables. El hito debe funcionar completamente on-premise, desde CLI, con modelos e indices locales.

H3 no modifica parsers H2 ni implementa ingenieria inversa H4 o generacion de specs H5. Su salida debe habilitar esos hitos mediante recuperacion, citas y servicios internos reutilizables.

## 2. Alcance

### Incluido

- configuracion RAG, embeddings, vector store, recuperacion y generacion;
- proveedor inicial de embeddings mediante Ollama;
- SQLite + `sqlite-vec` como indice vectorial reconstruible;
- manifest de embeddings e indexacion en SQLite;
- indexacion incremental, parcial y completa;
- busqueda semantica con filtros de metadata;
- busqueda keyword local y ranking hibrido inicial;
- context builder con trazabilidad y limites de tokens;
- servicios internos para search, ask, context y debugging;
- CLI `index`, `reindex`, `search`, `ask`, `embeddings` y `stats`;
- metricas, logs y pruebas offline con fakes.

### Excluido

- cambio de parsers H2 salvo ajustes estrictamente necesarios de metadata;
- entrenamiento, fine-tuning o descarga automatica de modelos;
- servidor HTTP, UI web, VS Code, multiusuario o autenticacion;
- agentes autonomos de varios pasos;
- memoria conversacional persistente;
- reranking cross encoder obligatorio;
- grafo avanzado de conocimiento;
- ejecucion de codigo fuente ingerido;
- telemetria remota o servicios cloud.

## 3. Convenciones

- **Must:** obligatorio para aceptar H3.
- **Should:** requerido salvo impedimento documentado.
- Mensajes, ayuda, errores, logs y respuestas de usuario estan en espanol.
- Identificadores, claves de configuracion, APIs internas y codigos tecnicos pueden permanecer en ingles.
- SQLite es fuente de verdad de metadata y almacenamiento vectorial inicial; las tablas `sqlite-vec` son reconstruibles desde chunks H2.
- H3 solo indexa chunks vigentes segun el contrato de H2.
- Comandos read-only no crean ni migran recursos salvo que se indique explicitamente.

## 4. Requisitos funcionales

### H3-REQ-001 - Configuracion RAG

**Descripcion:** Agregar secciones `[rag]`, `[embeddings]`, `[vector_store]`, `[retrieval]` y `[llm]` sin romper configuracion H1/H2.

**Prioridad:** Must.

**Criterios de aceptacion:**

- admite proveedor, modelo, batch size, timeout, top-k, umbral, pesos hibridos, limites de contexto, proveedor vectorial, tablas `sqlite-vec` y politica de reindexacion;
- los defaults permiten ejecutar H3 localmente tras instalar dependencias y modelos;
- valores invalidos producen codigo `2`;
- paths relativos se resuelven respecto del TOML;
- `config show` muestra valores efectivos sin crear tablas vectoriales, abrir modelos ni indexar.

### H3-REQ-002 - Interfaz de embeddings

**Descripcion:** Definir un puerto desacoplado para generar embeddings de textos y consultas.

**Prioridad:** Must.

**Criterios de aceptacion:**

- el contrato expone proveedor, modelo, dimension, version y metodo batch;
- errores de modelo ausente, timeout, dimension invalida y respuesta corrupta son tipados;
- la capa de recuperacion no importa adaptadores Ollama;
- tests unitarios usan un proveedor fake determinista.

### H3-REQ-003 - Adaptador Ollama embeddings

**Descripcion:** Implementar el proveedor inicial mediante endpoint local de Ollama.

**Prioridad:** Must.

**Criterios de aceptacion:**

- usa `ollama_url` y timeout configurados;
- soporta el modelo configurado, por defecto `nomic-embed-text`;
- valida dimension no nula y estable dentro del batch;
- reintenta solo errores transitorios acotados;
- no intenta descargar modelos automaticamente;
- si Ollama no esta disponible, el error indica accion recomendada.

### H3-REQ-004 - Versionamiento de embeddings

**Descripcion:** Identificar cada embedding por contenido, proveedor, modelo, dimension y politica de normalizacion.

**Prioridad:** Must.

**Criterios de aceptacion:**

- calcula `embedding_version` canonica;
- no mezcla dimensiones o modelos en una coleccion;
- un cambio de version marca embeddings previos como obsoletos;
- `barbarion embeddings` muestra proveedor, modelo, dimension, conteos y estado.

### H3-REQ-005 - Vector store SQLite + sqlite-vec

**Descripcion:** Usar SQLite + `sqlite-vec` como indice vectorial persistente inicial del MVP.

**Prioridad:** Must.

**Criterios de aceptacion:**

- crea o abre las tablas vectoriales configuradas dentro de SQLite;
- valida dimension contra el manifest SQLite;
- guarda metadata minima para filtros junto al estado de embedding;
- upsert y delete logico son idempotentes;
- errores de extension ausente, dimension incompatible, path o bloqueo son claros;
- el indice vectorial puede reconstruirse desde chunks H2;
- Qdrant queda fuera de la dependencia inicial y se documenta como alternativa futura.

### H3-REQ-006 - Schema SQLite H3

**Descripcion:** Migrar SQLite a version H3 sin romper datos H2.

**Prioridad:** Must.

**Criterios de aceptacion:**

- crea tablas para runs de indexacion, manifest de embeddings, estado por chunk, almacenamiento vectorial inicial, `symbol_occurrences`, metricas de consulta y evaluacion minima;
- conserva migraciones v1/v2;
- mantiene foreign keys y WAL;
- H3 no modifica tablas H2 salvo lectura;
- version futura falla con mensaje definido.

### H3-REQ-007 - Seleccion de chunks indexables

**Descripcion:** Indexar solo chunks vigentes de documentos procesados por H2.

**Prioridad:** Must.

**Criterios de aceptacion:**

- usa `files.status='processed'` y `documents.source_sha256=files.sha256`;
- excluye chunks vacios o eliminados;
- conserva `chunk_id`, documento, archivo, extension, lenguaje, carpeta, objeto, lineas, hash y metadata preparada para H4: `symbol_name`, `symbol_kind`, `parent_symbol`, `package_name`, `procedure_name`, `class_name` y `event_name`;
- estos campos H4 pueden quedar inicialmente en NULL si H2 no los provee;
- no accede al filesystem fuente para decidir indexacion.

### H3-REQ-008 - Indexacion incremental

**Descripcion:** Indexar nuevos chunks y actualizar solo los modificados u obsoletos.

**Prioridad:** Must.

**Criterios de aceptacion:**

- compara `chunk_id`, `content_sha256` y `embedding_version`;
- unchanged no llama al proveedor de embeddings;
- changed reemplaza vector y estado;
- deleted elimina o invalida el vector y marca estado obsoleto;
- errores por chunk no detienen todo el lote;
- metricas distinguen nuevos, actualizados, sin cambios, eliminados y fallidos.

### H3-REQ-009 - Reindexacion completa y parcial

**Descripcion:** Permitir reconstruir indices de forma controlada.

**Prioridad:** Must.

**Criterios de aceptacion:**

- `reindex --full` reconstruye la coleccion de la version actual sin truncar SQLite H2;
- `reindex --path`, `--document` o `--chunk-id` limitan el alcance cuando sea posible;
- una reindexacion interrumpida deja manifest consistente;
- se puede borrar indices obsoletos con confirmacion u opcion explicita.

### H3-REQ-010 - Busqueda semantica

**Descripcion:** Recuperar chunks por similitud vectorial.

**Prioridad:** Must.

**Criterios de aceptacion:**

- `top_k` y `similarity_threshold` son configurables y sobreescribibles por CLI;
- devuelve score normalizado, chunk, documento y fuente;
- respeta filtros por dominio, tipo de archivo, lenguaje, documento, carpeta y extension;
- los resultados incluyen metadata H4 cuando exista: `symbol_name`, `symbol_kind`, `parent_symbol`, `package_name`, `procedure_name`, `class_name` y `event_name`;
- resultados se ordenan de forma estable ante empates;
- una coleccion vacia produce mensaje accionable, no traceback.

### H3-REQ-011 - Busqueda keyword local

**Descripcion:** Incorporar recuperacion lexica para identificadores y literales.

**Prioridad:** Must.

**Criterios de aceptacion:**

- usa SQLite FTS5 cuando este disponible;
- si FTS5 no esta disponible, usa fallback local documentado con menor calidad;
- consulta sobre chunks vigentes e indexados;
- devuelve score keyword separado del score vectorial;
- no requiere servicios externos.

### H3-REQ-012 - Recuperacion hibrida

**Descripcion:** Combinar resultados vectoriales y keyword mediante ranking explicito.

**Prioridad:** Must.

**Criterios de aceptacion:**

- pesos vector/keyword son configurables;
- normaliza scores antes de combinar;
- deduplica por `chunk_id`;
- conserva scores individuales y combinado;
- la arquitectura permite agregar BM25, cross encoder o reranker local sin cambiar CLI publica.

### H3-REQ-013 - Context builder

**Descripcion:** Ensamblar contexto para LLM con limites y trazabilidad.

**Prioridad:** Must.

**Criterios de aceptacion:**

- selecciona chunks desde resultados recuperados;
- elimina duplicados y chunks casi identicos por hash;
- agrupa por documento cuando mejore legibilidad;
- respeta presupuesto de tokens configurable con estimador local;
- conserva fuente, score, lineas, paginas, objeto y ordinal;
- calcula o deja preparado el calculo de `context_precision`, `context_recall`, `duplicate_ratio` y `token_waste`;
- puede emitirse en modo debug sin invocar LLM.

### H3-REQ-014 - Citaciones y evidencia

**Descripcion:** Toda respuesta factual debe citar fuentes recuperadas o declarar evidencia insuficiente.

**Prioridad:** Must.

**Criterios de aceptacion:**

- cada cita referencia un `source_id` existente en el contexto;
- incluye archivo, chunk, score y lineas/paginas cuando existan;
- el validador rechaza citas inexistentes antes de mostrar respuesta;
- si no hay resultados sobre umbral, `ask` no inventa respuesta;
- los supuestos se separan de la evidencia.

### H3-REQ-015 - Servicio de busqueda

**Descripcion:** Exponer un caso de uso interno para busqueda semantica/hibrida.

**Prioridad:** Must.

**Criterios de aceptacion:**

- recibe query, filtros, modo, top-k y threshold;
- devuelve objetos estructurados, no texto formateado;
- no conoce argparse;
- registra metricas de latencia y conteos.

### H3-REQ-016 - Servicio de preguntas y respuestas

**Descripcion:** Exponer un caso de uso interno para `ask`.

**Prioridad:** Must.

**Criterios de aceptacion:**

- recupera contexto, arma prompt controlado y llama al LLM local;
- usa Ollama como proveedor inicial de generacion;
- permite modo `--no-llm` para inspeccionar contexto;
- valida citas;
- maneja timeout y modelo ausente con errores claros.

### H3-REQ-017 - Debugging RAG

**Descripcion:** Permitir inspeccionar por que se recupero o descarto contexto.

**Prioridad:** Should.

**Criterios de aceptacion:**

- salida debug incluye query normalizada, filtros, candidatos, scores, deduplicacion y presupuesto;
- no imprime contenido completo salvo opcion explicita;
- registra `query_id` para correlacion de logs.

### H3-REQ-018 - CLI de indexacion

**Descripcion:** Agregar comandos `barbarion index` y `barbarion reindex`.

**Prioridad:** Must.

**Criterios de aceptacion:**

- `index` ejecuta incremental por defecto;
- `reindex` exige alcance claro o `--full`;
- soporta `--path`, `--document`, `--chunk-id`, `--dry-run`, `--delete-obsolete`;
- muestra resumen en espanol y codigos de salida consistentes.

### H3-REQ-019 - CLI de consulta

**Descripcion:** Agregar comandos `search`, `ask`, `embeddings` y extender `stats`.

**Prioridad:** Must.

**Criterios de aceptacion:**

- `search "consulta"` admite modo semantic, keyword o hybrid;
- `ask "pregunta"` muestra conclusion, evidencia, supuestos y limites;
- `embeddings` muestra modelos, versiones, colecciones y obsoletos;
- `stats` incluye estado RAG sin reindexar;
- formatos `text`, `json` y `markdown` estan disponibles donde aplique.

### H3-REQ-020 - Observabilidad

**Descripcion:** Registrar metricas y logs locales para indexacion y busqueda.

**Prioridad:** Must.

**Criterios de aceptacion:**

- indexacion mide chunks/s, latencia de embeddings, errores, deletes y duracion;
- busqueda mide latencia vectorial, keyword, combinacion, contexto y LLM;
- logs incluyen run/query id, etapa y codigos, sin volcar corpus por defecto;
- no hay telemetria remota.

### H3-REQ-021 - Evaluacion RAG

**Descripcion:** Mantener un conjunto minimo de preguntas de evaluacion.

**Prioridad:** Must.

**Criterios de aceptacion:**

- al menos 10 preguntas versionadas con fuentes esperadas sobre corpus sintetico/autorizado;
- cada pregunta pertenece a una categoria explicita: navegacion, dependencias, ubicacion de objetos, explicaciones, impacto o documentacion;
- incluye ejemplos representativos como `Donde se calcula order_total?`, `Que objetos llaman calculate_discount?`, `Donde se usa process_customer?` y `Que documentos hablan de generate_invoice?`;
- mide si una fuente esperada aparece en top 5;
- reporte incluye precision top-k basica y latencia;
- aceptacion exige 8/10 top-5 salvo excepcion documentada.

### H3-REQ-022 - Preparacion H4/H5

**Descripcion:** Dejar contratos reutilizables para reverse engineering y spec mode.

**Prioridad:** Must.

**Criterios de aceptacion:**

- resultados exponen objeto, lenguaje, archivo, rangos y scores;
- resultados exponen campos simbolicos preparados para H4, aunque esten NULL inicialmente;
- SQLite v3 crea `symbol_occurrences(id, chunk_id, symbol_name, symbol_kind, line_start, line_end)` para compatibilidad futura;
- H3 no implementa extraccion avanzada ni convierte estas ocurrencias en grafo;
- context builder puede recibir semillas futuras de dependencias H4;
- evidencia puede serializarse para documentos Markdown H5;
- no acopla RAG a un dominio DOMINIO_PRIVADO ni a nombres privados.

### H3-REQ-023 - Retrieval Benchmark Dataset

**Descripcion:** Mantener un dataset de benchmark para medir calidad de recuperacion y contexto.

**Prioridad:** Must.

**Criterios de aceptacion:**

- define preguntas, categoria, filtros opcionales, fuentes esperadas y notas de relevancia;
- mide como minimo `recall@5`, `recall@10`, `mrr` y latencia;
- registra metricas de calidad de contexto: `context_precision`, `context_recall`, `duplicate_ratio` y `token_waste`;
- permite comparar cambios futuros de chunk size, overlap, pesos hibridos y reranking;
- `benchmark.md` incluye una seccion `Baseline` con `recall@5`, `recall@10`, `mrr` y latencia;
- cada ejecucion de benchmark conserva historico local para comparar contra ejecuciones previas;
- genera artefactos locales en `reports/h3/metrics.json`, `reports/h3/topk-report.md`, `reports/h3/smoke-report.md` y `reports/h3/benchmark.md`.

## 5. Requisitos no funcionales

### H3-NFR-001 - Operacion offline

**Descripcion:** El uso normal no requiere internet.

**Criterio:** con dependencias y modelos ya instalados, index, search y ask funcionan en loopback/local.

### H3-NFR-002 - Rendimiento de indexacion

**Descripcion:** El pipeline no carga todo el corpus ni llama embeddings para unchanged.

**Criterio:** incremental sin cambios procesa metadata en menos del 20 % del tiempo de una indexacion completa en el corpus de aceptacion.

### H3-NFR-003 - Latencia de busqueda

**Descripcion:** La busqueda sin LLM debe ser interactiva en hardware de desarrollador.

**Criterio:** sobre corpus de aceptacion, `search` top 10 responde en menos de 2 s p95 sin contar cold start documentado.

### H3-NFR-004 - Consumo de memoria

**Descripcion:** La indexacion usa batches acotados.

**Criterio:** el batch size configurable limita textos y vectores en memoria; no se materializa todo el corpus.

### H3-NFR-005 - Portabilidad

**Descripcion:** Operar en Windows y Linux con Python `>=3.12,<3.13`.

**Criterio:** rutas persistidas usan `/`, tests usan temporales y las tablas `sqlite-vec` residen en la misma base SQLite local.

### H3-NFR-006 - Mantenibilidad

**Descripcion:** Mantener monolito modular sin framework RAG pesado.

**Criterio:** CLI, casos de uso, dominio e infraestructura permanecen separados; no se introducen microservicios, colas ni plugins dinamicos.

### H3-NFR-007 - Seguridad de informacion

**Descripcion:** Evitar filtracion accidental de corpus.

**Criterio:** logs y errores no contienen contenido completo; prompts completos solo se muestran con debug explicito.

### H3-NFR-008 - Reproducibilidad

**Descripcion:** Misma configuracion e indice producen resultados estables.

**Criterio:** IDs, manifests, ranking ante empates y reportes usan orden canonico.

## 6. Codigos de salida

| Codigo | Significado |
|---:|---|
| 0 | Comando completado |
| 1 | Error operativo, indexacion con errores recuperables o evidencia insuficiente en modo estricto |
| 2 | Argumentos o configuracion invalidos |
| 130 | Interrupcion por usuario |

## 7. Criterio global

H3 se considera listo para implementacion cuando todos los requisitos Must tienen tareas y pruebas asociadas. Se acepta al implementarse cuando indexa incrementalmente los chunks H2 con SQLite + `sqlite-vec`, recupera fuentes relevantes para al menos 8 de 10 preguntas de evaluacion en top 5, reporta `recall@5`, `recall@10`, `mrr`, latencia y metricas de contexto, responde con citas validas o evidencia insuficiente, y todo el flujo funciona localmente sin servicios cloud.
