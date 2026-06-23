# Specs de Barbarion

Las specs convierten cada hito del roadmap en trabajo pequeño, revisable y verificable.

## Hitos

| Hito | Objetivo | Estado |
|---|---|---|
| [H1-Foundation](H1-Foundation/) | Base Python, CLI, configuración y pruebas | Pendiente |
| [H2-Ingestion](H2-Ingestion/) | Ingesta incremental y metadata trazable | Pendiente |
| [H3-RAG](H3-RAG/) | Recuperación y respuestas locales con fuentes | Pendiente |
| [H4-ReverseEngineering](H4-ReverseEngineering/) | Relaciones e impacto técnico básico | Pendiente |
| [H5-SpecMode](H5-SpecMode/) | Generación guiada de specs Markdown | Pendiente |

## Estructura de una spec activa

Cada carpeta de hito incorporará estos documentos cuando comience su definición:

```text
requirements.md   # Qué debe resolver y cómo se acepta
design.md         # Cómo se resolverá y qué decisiones aplica
tasks.md          # Incrementos pequeños, ordenados y verificables
```

No se generarán los tres archivos con contenido ficticio. Se crearán al iniciar el hito correspondiente y se aprobarán antes de implementar.
