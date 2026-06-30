# Registro de decisiones técnicas

Este documento conserva las decisiones que delimitan el MVP de Barbarion. Se usa un registro liviano en lugar de una colección formal de ADR mientras el proyecto sea pequeño.

## Estados

- **Aceptada:** guía la implementación actual.
- **Propuesta:** requiere validación antes de implementarse.
- **Reemplazada:** se conserva como contexto histórico e indica su sucesora.

## Decisiones

| ID | Fecha | Estado | Decisión | Motivo | Consecuencia |
|---|---|---|---|---|---|
| D-001 | 2026-06-23 | Aceptada | Operación on-premise y local | El corpus puede contener código e información sensible | El uso normal no dependerá de servicios cloud |
| D-002 | 2026-06-23 | Aceptada | El MVP usará un único dominio legacy configurado | Se prioriza profundidad y validación real | El caso de validación no forma parte del diseño público; otros dominios requieren una decisión y una spec posterior |
| D-003 | 2026-06-23 | Aceptada | CLI como primera interfaz | Reduce costo y permite validar los casos de uso centrales | VS Code y UI web quedan fuera del MVP |
| D-004 | 2026-06-23 | Aceptada | Aplicación Python modular de un solo proceso | Es suficiente para un usuario local y evita complejidad operativa | No se crearán microservicios ni Kubernetes |
| D-005 | 2026-06-23 | Aceptada | SQLite como fuente de verdad de metadata | Es transaccional, local e inspeccionable | El esquema evolucionará mediante migraciones pequeñas |
| D-006 | 2026-06-23 | Reemplazada por D-014 | Qdrant en modo local para vectores | Aporta búsqueda vectorial y filtros, pero agrega un componente operativo adicional para el MVP local | Qdrant queda como alternativa futura y no como dependencia inicial |
| D-007 | 2026-06-23 | Aceptada | Ollama para embeddings e inferencia | Mantiene modelos y datos dentro del entorno local | Los modelos concretos se elegirán por configuración y hardware |
| D-008 | 2026-06-23 | Aceptada | Markdown como formato de entregables y specs | Es legible, editable y versionable | La generación debe usar plantillas y no sobrescribir trabajo humano por defecto |
| D-009 | 2026-06-23 | Aceptada | FastAPI se difiere | La CLI no necesita una API HTTP para validar el MVP | Solo se reconsiderará ante un cliente real que la necesite |
| D-010 | 2026-06-23 | Aceptada | Parsers heurísticos con fallback de texto | Permiten entregar valor antes de construir analizadores formales | Toda extracción debe conservar evidencia y declarar limitaciones |
| D-011 | 2026-06-23 | Aceptada | Registro liviano de decisiones en un único archivo | El volumen actual no justifica una estructura completa de ADR | Se migrará a ADR individuales si el historial deja de ser manejable |
| D-012 | 2026-06-23 | Aceptada | Se pospone un comando explícito `barbarion init` | H1 necesita un flujo mínimo y ya cuenta con diagnóstico operativo | En H1, `barbarion doctor` también realiza el bootstrap idempotente de directorios y SQLite; `init` se reconsiderará si separar ambos comportamientos aporta valor |
| D-013 | 2026-06-23 | Aceptada | La comunicación de Barbarion con el usuario será en español | Favorece claridad y consistencia para sus usuarios iniciales | Ayuda, mensajes CLI, errores, diagnósticos, logs, comentarios y docstrings se escriben en español; identificadores, claves de configuración, APIs y códigos técnicos estables pueden permanecer en inglés |
| D-014 | 2026-06-29 | Aceptada | SQLite + sqlite-vec como vector store inicial del MVP | Mantiene metadata y vectores en un único archivo local, reduce operación y conserva el índice reconstruible desde chunks H2 | H3 usa SQLite + sqlite-vec; Qdrant se reevalúa en H4 o posterior si volumen, filtros o latencia lo requieren |
| D-015 | 2026-06-30 | Aceptada | Las tablas permanentes de reverse engineering no usan prefijo de hito | El catálogo técnico ya forma parte del modelo de datos permanente de Barbarion, igual que `files`, `documents` y `chunks` | El esquema usa `analysis_runs`, `symbols`, `symbol_references`, `relations`, `relation_candidates` y `generated_artifacts`; se evita `references` por ser problemático en SQLite |

## Cómo añadir una decisión

1. Asignar el siguiente identificador `D-NNN`.
2. Registrar la alternativa elegida, el motivo y su consecuencia práctica.
3. No reescribir decisiones históricas: marcar como reemplazada y enlazar la nueva decisión.
4. Si la decisión modifica alcance, arquitectura o planificación, actualizar también el documento maestro correspondiente.
