# H3 - RAG

**Estado:** especificado para implementacion; depende de H2-Ingestion aceptado.

Convertir los chunks persistidos por H2 en un sistema local de recuperacion semantica e hibrida que permita buscar conocimiento tecnico y responder preguntas con evidencia verificable.

El alcance inicial esta en [ROADMAP.md](../../docs/ROADMAP.md#5-h3--rag). H3 conserva las decisiones maestras de operacion on-premise, CLI-first, aplicacion Python modular de un solo proceso y Ollama para modelos locales. Para el MVP de H3, SQLite se mantiene como fuente de verdad y tambien se usa como almacenamiento vectorial inicial mediante `sqlite-vec`.

## Documentos

- [Requisitos](requirements.md)
- [Diseno](design.md)
- [Plan de tareas](tasks.md)
- [Plan de pruebas](test-plan.md)
- [Decisiones H3](decisions.md)
- [Evidencia de aceptacion](acceptance.md)
- Diagramas:
  - [Arquitectura RAG](diagrams/architecture.mmd)
  - [Flujo de indexacion](diagrams/indexing-flow.mmd)
  - [Flujo de recuperacion](diagrams/retrieval-flow.mmd)
  - [Secuencia de preguntas y respuestas](diagrams/qa-sequence.mmd)
  - [Modelo de datos](diagrams/data-model.mmd)

## Decisiones principales

- embeddings locales mediante Ollama como proveedor inicial;
- modelo por defecto configurable, inicialmente `nomic-embed-text`;
- interfaz pequena `EmbeddingProvider` para desacoplar negocio, configuracion y adaptador Ollama;
- SQLite + `sqlite-vec` como vector store inicial del MVP;
- SQLite mantiene metadata, runs, manifest de embeddings, vectores y trazabilidad;
- Qdrant queda como alternativa futura, reevaluable en H4 si `sqlite-vec` no cubre volumen, filtros o rendimiento;
- versionamiento explicito de embeddings por proveedor, modelo, dimension, normalizacion y firma de contenido;
- indexacion incremental basada en chunks vigentes de H2, `content_sha256` y version de embedding;
- busqueda semantica con filtros por dominio, tipo, lenguaje, documento, carpeta y extension;
- recuperacion hibrida inicial mediante vector search con `sqlite-vec` + keyword search local en SQLite FTS5 si esta disponible; fallback LIKE documentado cuando FTS5 no exista;
- ranking combinado simple y explicito, preparado para BM25, cross encoder y rerankers locales futuros;
- context builder determinista con deduplicacion, presupuesto de tokens, agrupacion por documento y fuentes;
- contexto acotado por fuente y presupuesto global antes de invocar LLM;
- respuestas con citas inline obligatorias o declaracion de evidencia insuficiente;
- fuentes con rangos reales de chunk para citas y navegacion;
- comandos CLI `index`, `reindex`, `search`, `ask`, `embeddings` y `stats`;
- observabilidad local sin telemetria remota ni volcado de corpus en logs.

La implementacion debe seguir estos documentos. Cualquier cambio de proveedor, vector store, contrato de citas o alcance de comandos debe reflejarse primero en la spec.
