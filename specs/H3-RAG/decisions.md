# H3 - RAG: Decisiones

## 1. Proposito

Registrar las decisiones especificas de H3 sin reemplazar `docs/DECISIONS.md`. Las decisiones maestras siguen teniendo prioridad. Este documento explica como se aplican al hito RAG y que alternativas se evaluaron.

## 2. Decisiones

| ID | Estado | Decision | Justificacion | Consecuencia |
|---|---|---|---|---|
| H3-D-001 | Aceptada | Usar Ollama como proveedor inicial de embeddings | `D-007` ya define Ollama para embeddings e inferencia local; reduce integracion y mantiene datos on-premise | La capa de negocio depende de un puerto, no del cliente concreto |
| H3-D-002 | Aceptada | Modelo por defecto `nomic-embed-text` | Disponible en Ollama, razonable para texto tecnico multilingue y de bajo costo operativo frente a modelos mayores | El modelo es configurable; las pruebas no dependen de descargarlo |
| H3-D-003 | Aceptada | Mantener una interfaz `EmbeddingProvider` desacoplada | Permite cambiar a sentence-transformers, BGE, GGUF u otro proveedor sin tocar recuperacion ni CLI | Los adaptadores viven en `infrastructure/`; contratos y errores en `domain/` |
| H3-D-004 | Aceptada | Usar SQLite + `sqlite-vec` como vector store inicial | Reduce componentes, mantiene una sola persistencia local y alinea el MVP con simplicidad operativa | SQLite almacena metadata y vectores; el indice sigue siendo reconstruible desde chunks H2 |
| H3-D-005 | Deferida | Diferir Qdrant local como vector store inicial | Es una alternativa madura para volumen, filtros y rendimiento, pero agrega un componente operativo adicional para H3 | Se reevalua en H4 si `sqlite-vec` no cubre volumen, filtros o rendimiento |
| H3-D-006 | Rechazada para H3 | ChromaDB como store inicial | Facil de usar, pero introduce una capa mas opinada y no esta aprobada en `DECISIONS.md` | No se adopta sin decision nueva |
| H3-D-007 | Rechazada para H3 | FAISS como store inicial | Eficiente, pero persistencia, filtros y manejo operativo requieren mas codigo propio para el MVP | Puede considerarse para indices especializados futuros |
| H3-D-008 | Aceptada | No mezclar embeddings de modelos o dimensiones distintas en una misma coleccion | Evita resultados corruptos o incomparables | Cambio de modelo crea nuevo indice o exige reindexacion completa |
| H3-D-009 | Aceptada | SQLite mantiene manifest, estado de indexacion y almacenamiento vectorial inicial | H2 ya usa SQLite como fuente de verdad; `sqlite-vec` permite conservar el MVP en un unico archivo local | Las tablas vectoriales pueden borrarse y reconstruirse desde chunks H2 |
| H3-D-010 | Aceptada | Recuperacion hibrida inicial con keyword local simple | Mejora busquedas de identificadores, nombres de tablas, procedimientos y literales | BM25/rerankers quedan preparados, no implementados como dependencia obligatoria inicial |
| H3-D-011 | Aceptada | Context builder propio y determinista | Evita adoptar frameworks RAG grandes y facilita depuracion local | El pipeline RAG queda explicito: retrieve, assemble, generate, ground |
| H3-D-012 | Aceptada | No persistir memoria conversacional en H3 | El objetivo es preguntas tecnicas reproducibles con evidencia | Conversaciones complejas se difieren a hitos posteriores |
| H3-D-013 | Aceptada | Respuestas en espanol con citas obligatorias | Consistente con `D-013` y el principio de evidencia antes que elocuencia | `ask` debe declarar evidencia insuficiente si no recupera fuentes |
| H3-D-014 | Aceptada | Tests con proveedores fake por defecto | Mantiene suite rapida, offline y reproducible | Las pruebas reales de Ollama y `sqlite-vec` se marcan como integracion condicionada cuando dependan de binarios locales |
| H3-D-015 | Aceptada | Crear `symbol_occurrences` como tabla reservada para H4 | Permite compatibilidad futura sin convertir H3 en ingenieria inversa | H3 solo la puebla si H2 ya expone metadata simple; no implementa extraccion avanzada |

## 3. Evaluacion de modelos de embeddings

| Familia | Evaluacion | Decision H3 |
|---|---|---|
| `nomic-embed-text` via Ollama | Buen equilibrio local, multilingue y disponible con interfaz estable | Modelo por defecto configurable |
| BGE small | Bajo consumo y buena calidad general; puede usarse via sentence-transformers u Ollama si esta disponible | Alternativa soportable por adaptador futuro |
| BGE base | Mejor calidad esperada, mayor costo de memoria/latencia | No default; valido para reindexacion si hardware lo permite |
| sentence-transformers | Ecosistema maduro, pero agrega dependencia ML pesada al runtime | No proveedor inicial; posible adaptador posterior |
| Modelos GGUF compatibles | Alineados con ejecucion local, pero la compatibilidad depende del runner | Preparar interfaz; no requerir en H3 |

## 4. Politica de cambio

Cambiar proveedor, modelo, dimension, normalizacion o vector store requiere:

1. registrar la decision;
2. actualizar configuracion de ejemplo;
3. crear una nueva version de embedding;
4. ejecutar `barbarion reindex --full` o equivalente;
5. validar recuperacion con el benchmark de evaluacion.

Qdrant no se elimina del diseno conceptual: queda como alternativa futura. Adoptarlo en H4 o despues requiere una decision nueva y evidencia de que `sqlite-vec` no satisface el volumen, los filtros o la latencia esperados.
