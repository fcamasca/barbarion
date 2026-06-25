# H2 — Ingestion

**Estado:** aprobado para implementación.

Transformar un corpus autorizado de artefactos Oracle/PLSQL, exportaciones textuales de PowerBuilder y documentación técnica en documentos y chunks normalizados, incrementales y trazables.

El alcance inicial está en [ROADMAP.md](../../docs/ROADMAP.md#4-h2--ingestion). H2 depende de H1-Foundation, ya completado y aceptado.

## Documentos

- [Requisitos](requirements.md)
- [Diseño](design.md)
- [Plan de tareas](tasks.md)
- [Análisis de impacto](impact-analysis.md)
- [Plan de pruebas](test-plan.md)
- [Evidencia de aceptación](acceptance.md)

## Decisiones principales

- procesamiento local, CLI-first y secuencial;
- componentes ubicados en `application/`, `domain/` e `infrastructure/` según la arquitectura maestra;
- SQLite como fuente de verdad del corpus normalizado;
- WAL activado y verificado antes de escribir metadata de ingesta;
- parsers heurísticos mediante interfaz, `LogicalUnit.confidence` y registro interno explícito;
- ingesta incremental basada en identidad, metadata, SHA-256 y firma de procesamiento;
- chunks deterministas y neutrales respecto de ChromaDB, Qdrant u otro vector store;
- inventario consultable desde SQLite sin reescanear filesystem;
- duplicación de almacenamiento aceptada para privilegiar simplicidad y trazabilidad;
- ninguna dependencia de embeddings, Ollama o RAG.

La implementación debe seguir estos documentos. Cualquier cambio de alcance o contrato debe reflejarse primero en la spec.
