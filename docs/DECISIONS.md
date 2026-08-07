# Registro de decisiones técnicas

Este documento conserva las decisiones que delimitan el MVP de Barbarion. Se usa un registro liviano en lugar de una colección formal de ADR mientras el proyecto sea pequeño.

## Estados

- **Aceptada:** guía la implementación actual.
- **Acotada:** continúa vigente con una excepción definida por una decisión posterior.
- **Propuesta:** requiere validación antes de implementarse.
- **Reemplazada:** se conserva como contexto histórico e indica su sucesora.

## Decisiones

| ID | Fecha | Estado | Decisión | Motivo | Consecuencia |
|---|---|---|---|---|---|
| D-001 | 2026-06-23 | Acotada por D-019 | Operación on-premise y local | El corpus puede contener código e información sensible | El conocimiento y el flujo predeterminado permanecen locales; H1.2 permite enviar únicamente el prompt final a Anthropic cuando el usuario lo configura |
| D-002 | 2026-06-23 | Aceptada | El MVP usará un único dominio legacy configurado | Se prioriza profundidad y validación real | El caso de validación no forma parte del diseño público; otros dominios requieren una decisión y una spec posterior |
| D-003 | 2026-06-23 | Aceptada | CLI como primera interfaz | Reduce costo y permite validar los casos de uso centrales | VS Code y UI web quedan fuera del MVP |
| D-004 | 2026-06-23 | Aceptada | Aplicación Python modular de un solo proceso | Es suficiente para un usuario local y evita complejidad operativa | No se crearán microservicios ni Kubernetes |
| D-005 | 2026-06-23 | Aceptada | SQLite como fuente de verdad de metadata | Es transaccional, local e inspeccionable | El esquema evolucionará mediante migraciones pequeñas |
| D-006 | 2026-06-23 | Reemplazada por D-014 | Qdrant en modo local para vectores | Aporta búsqueda vectorial y filtros, pero agrega un componente operativo adicional para el MVP local | Qdrant queda como alternativa futura y no como dependencia inicial |
| D-007 | 2026-06-23 | Acotada por D-019 | Ollama para embeddings e inferencia | Mantiene modelos y datos dentro del entorno local | Ollama sigue siendo obligatorio para embeddings y el backend generativo predeterminado; H1.2 añade Anthropic solo para generación |
| D-008 | 2026-06-23 | Aceptada | Markdown como formato de entregables y specs | Es legible, editable y versionable | La generación debe usar plantillas y no sobrescribir trabajo humano por defecto |
| D-009 | 2026-06-23 | Aceptada | FastAPI se difiere | La CLI no necesita una API HTTP para validar el MVP | Solo se reconsiderará ante un cliente real que la necesite |
| D-010 | 2026-06-23 | Aceptada | Parsers heurísticos con fallback de texto | Permiten entregar valor antes de construir analizadores formales | Toda extracción debe conservar evidencia y declarar limitaciones |
| D-011 | 2026-06-23 | Aceptada | Registro liviano de decisiones en un único archivo | El volumen actual no justifica una estructura completa de ADR | Se migrará a ADR individuales si el historial deja de ser manejable |
| D-012 | 2026-06-23 | Aceptada | Se pospone un comando explícito `barbarion init` | H1 necesita un flujo mínimo y ya cuenta con diagnóstico operativo | En H1, `barbarion doctor` también realiza el bootstrap idempotente de directorios y SQLite; `init` se reconsiderará si separar ambos comportamientos aporta valor |
| D-013 | 2026-06-23 | Aceptada | La comunicación de Barbarion con el usuario será en español | Favorece claridad y consistencia para sus usuarios iniciales | Ayuda, mensajes CLI, errores, diagnósticos, logs, comentarios y docstrings se escriben en español; identificadores, claves de configuración, APIs y códigos técnicos estables pueden permanecer en inglés |
| D-014 | 2026-06-29 | Aceptada | SQLite + sqlite-vec como vector store inicial del MVP | Mantiene metadata y vectores en un único archivo local, reduce operación y conserva el índice reconstruible desde chunks H2 | H3 usa SQLite + sqlite-vec; Qdrant se reevalúa en H4 o posterior si volumen, filtros o latencia lo requieren |
| D-015 | 2026-06-30 | Aceptada | Las tablas permanentes de reverse engineering no usan prefijo de hito | El catálogo técnico ya forma parte del modelo de datos permanente de Barbarion, igual que `files`, `documents` y `chunks` | El esquema usa `analysis_runs`, `symbols`, `symbol_references`, `relations`, `relation_candidates` y `generated_artifacts`; se evita `references` por ser problemático en SQLite |
| D-016 | 2026-07-20 | Acotada por D-019 | Ollama es la fuente del catálogo de modelos y `[llm].model` es la única fuente de verdad del LLM generativo activo | Evita un registro paralelo y nuevas precedencias de configuración | Los modelos no se catalogan en SQLite; `models select` solo edita `[llm].model` cuando el proveedor activo es Ollama y no cambia `[embeddings].model` |
| D-017 | 2026-07-20 | Aceptada | La instalación y selección de modelos son acciones explícitas y separadas | Descargar, validar o evaluar un modelo no autoriza cambiar la configuración activa | `models install`, `models validate` y `models benchmark` nunca seleccionan un modelo; `models select` exige validación previa |
| D-018 | 2026-07-20 | Aceptada | La evaluación H1.1 usa un benchmark local, sintético y determinista con recomendación informativa | Permite comparar el LLM generativo sin exponer datos, alterar retrieval ni introducir un LLM juez | Los reportes son JSON y Markdown locales, no se persisten en SQLite y cualquier candidato requiere revisión humana y selección posterior explícita |
| D-019 | 2026-08-02 | Aceptada | H1.2 desacopla la generación mediante una factoría cerrada Ollama/Anthropic y conserva local toda la construcción de conocimiento | Permite evitar la dependencia del hardware local sin rediseñar RAG ni anticipar una plataforma multiproveedor | Ollama continúa como default y proveedor de embeddings; Anthropic usa Messages API con endpoint y versión fijos, key solo desde `ANTHROPIC_API_KEY`, sin streaming, retries ni fallback; no se persisten prompts, respuestas, uso, request-id o credenciales |
| D-020 | 2026-08-06 | Acotada por D-023 | H3.1 mantiene `baseline_v1` como default y califica `optimized_v1` como candidata opt-in | El benchmark inicial atribuyó la mejora material a selección relevance-first y midió overlap marginal | `optimized_v1` requiere `input_token_budget_est`; D-023 revisa mezcla de familias y overlap sin promover el default |
| D-021 | 2026-08-06 | Aceptada | `input_token_budget_est` es opt-in, sin default numérico, y `chars4_v1` permanece como estimación local | Cada corpus requiere su propia baseline y los contadores del proveedor no son intercambiables con una aproximación local | El prompt completo de generation y repair se presupuesta solo al configurar la clave; el contrato legacy permanece intacto y las métricas reales se etiquetan por separado |
| D-022 | 2026-08-06 | Reemplazada por D-023 | Diferir `trim_overlap_v1` y conservar el diagnóstico report-only | Los `27` caracteres o `7` tokens estimados de overlap medidos inicialmente eran marginales | La decisión se reabrió al aparecer evidencia material reproducible |
| D-023 | 2026-08-07 | Aceptada | Fusionar H3/H4.1 por rango relativo de familia y activar trim solo para overlap exacto y continuo | Los scores absolutos de ambas familias no comparten calibración y una validación midió `2,446` caracteres/`612` tokens estimados repetidos | El score original se conserva; `optimized_v1` usa rango relativo y solo recorta sufijo/prefijo exacto del mismo documento con continuidad de rangos |
| D-024 | 2026-08-07 | Aceptada | Usar rangos densos para empates y preservar coincidencias literales de identificadores en `optimized_v1` | El rango ordinal asignaba percentiles distintos a candidatos H4.1 con el mismo score y podía desplazar la identidad exacta solicitada | Los empates reales comparten `family_rank`/`relative_score`; una coincidencia exacta de identificador es una señal explícita y trazable, sin cambiar `top_k`, presupuesto ni `baseline_v1` |

## Cómo añadir una decisión

1. Asignar el siguiente identificador `D-NNN`.
2. Registrar la alternativa elegida, el motivo y su consecuencia práctica.
3. No reescribir decisiones históricas: marcar como reemplazada y enlazar la nueva decisión.
4. Si la decisión modifica alcance, arquitectura o planificación, actualizar también el documento maestro correspondiente.
