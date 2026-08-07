# Specs de Barbarion

Las specs convierten cada hito del roadmap en trabajo pequeño, revisable y verificable.

## Hitos

| Hito | Objetivo | Estado |
|---|---|---|
| [H1-Foundation](H1-Foundation/) | Base Python, CLI, configuración y pruebas | Completado |
| [H2-Ingestion](H2-Ingestion/) | Ingesta incremental y metadata trazable | Completado |
| [H3-RAG](H3-RAG/) | Recuperación y respuestas locales con fuentes | Completado |
| [H4-ReverseEngineering](H4-ReverseEngineering/) | Relaciones e impacto técnico básico | Completado |
| [H4.1-DataDrivenConfigurations](H4.1-DataDrivenConfigurations/) | Configuraciones persistidas integradas al conocimiento técnico | Completado |
| [H5-SpecMode](H5-SpecMode/) | Generación guiada de specs Markdown | Completado |
| [H1.1-LocalModelManagement](H1.1-LocalModelManagement/) | Gestión y evaluación reproducible de modelos Ollama locales | Completado; comparación real pendiente |
| [H1.2-RemoteInference](H1.2-RemoteInference/) | Generación remota opcional mediante Anthropic sin cambiar el conocimiento local | Completado y aceptado técnica y funcionalmente |
| [H3.1-RAGContextOptimization](H3.1-RAGContextOptimization/) | Medición y optimización provider-agnostic del contexto RAG | Implementación iniciada; T01-T09 completadas; observabilidad comparable |

## Estructura de una spec activa

Cada carpeta de hito incorporará estos documentos cuando comience su definición:

```text
requirements.md   # Qué debe resolver y cómo se acepta
design.md         # Cómo se resolverá y qué decisiones aplica
tasks.md          # Incrementos pequeños, ordenados y verificables
test-plan.md      # Cómo se verifican contratos, riesgos y regresión
acceptance.md     # Evidencia final; se crea únicamente durante la aceptación
```

No se generarán documentos con contenido ficticio. Requisitos, diseño, tareas y
plan de pruebas se crean y aprueban antes de implementar; `acceptance.md` se
elabora únicamente cuando se autoriza la aceptación del hito.
