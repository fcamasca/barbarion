# Barbarion — Roadmap del MVP

> **Estado del documento:** registro histórico del plan original de 12 semanas para H1-H5. Los hitos fueron ejecutados y las decisiones posteriores pueden sustituir componentes previstos aquí. La arquitectura vigente se documenta en [`ARCHITECTURE.md`](ARCHITECTURE.md), las sustituciones en [`DECISIONS.md`](DECISIONS.md) y las evoluciones posteriores en [`EVOLUTION.md`](EVOLUTION.md).

## 1. Horizonte y capacidad

El plan asume **12 semanas**, con una dedicación aproximada de **2 horas por día, de lunes a viernes**: unas **120 horas** en total.

| Hito | Semanas | Presupuesto | Resultado principal |
|---|---:|---:|---|
| H1 — Foundation | 1–2 | 18 h | CLI instalable, configuración, persistencia y pruebas base |
| H2 — Ingestion | 3–5 | 26 h | Corpus autorizado inventariado, fragmentado e incremental |
| H3 — RAG | 6–8 | 28 h | Consultas locales con recuperación y fuentes |
| H4 — Reverse Engineering | 9–11 | 30 h | Inventarios, relaciones e impacto técnico básico |
| H5 — Spec Mode | 12 | 12 h | Specs Markdown trazables, validadas técnicamente |
| Reserva transversal | Durante todo el plan | 6 h | Ajustes, documentación y contingencias |
| **Total** | **12** | **120 h** | **MVP evaluable de extremo a extremo** |

La reserva no debe convertirse en un hito adicional. Se utiliza para corregir defectos que impidan cumplir los criterios de aceptación.

El MVP se valida inicialmente sobre un dominio legacy real, pero ese dominio no forma parte del diseño público ni limita la arquitectura de Barbarion.

## 2. Reglas de ejecución

- Cada hito termina con una demostración desde CLI y evidencia de pruebas.
- El corpus inicial debe ser pequeño, representativo y autorizado; crecer solo cuando el flujo sea estable.
- Una tarea nueva entra al hito únicamente si es necesaria para un criterio de aceptación.
- Los hallazgos deseables pero no esenciales se registran como backlog.
- Los criterios se validan con un corpus autorizado de un sistema legacy real, no solo con ejemplos artificiales.
- No se inicia el siguiente hito si el flujo crítico del anterior no es repetible.

## 3. H1 — Foundation

**Objetivo:** establecer una aplicación Python local, simple y comprobable sobre la que se puedan construir los demás hitos.

### Entregables

- proyecto Python con gestión reproducible de dependencias;
- CLI con comandos de ayuda, versión, diagnóstico y configuración visible;
- modelo de configuración para rutas locales, dominio, Ollama y almacenamiento;
- inicialización de directorios de datos y esquema SQLite versionado;
- logging local con mensajes accionables;
- pruebas unitarias y una prueba de humo de la CLI;
- README con instalación, ejecución y límites del entorno;
- corpus de prueba mínimo, sintético y sin información sensible.

### Criterios de aceptación

- una instalación limpia permite ejecutar `barbarion --help` y `barbarion doctor` siguiendo el README;
- la aplicación valida configuración y reporta claramente rutas o servicios ausentes;
- SQLite se inicializa de forma idempotente;
- las pruebas se ejecutan con un solo comando y el flujo de humo pasa;
- ninguna operación requiere internet durante el uso normal, salvo la descarga inicial explícita de dependencias y modelos;
- no existen secretos ni rutas personales versionados.

### Riesgos

- incompatibilidades entre Python, Ollama o el sistema operativo objetivo;
- dedicar demasiado tiempo a empaquetado, configuración o abstracciones;
- no contar aún con hardware o modelos locales adecuados.

### Dependencias

- versión de Python acordada;
- instalación local de Ollama o decisión documentada para simularlo en pruebas;
- repositorio Git y política de manejo de datos sensibles.

### No hacer todavía

- FastAPI, servidor persistente o UI;
- sistema de plugins;
- contenedores de producción;
- autenticación, roles o telemetría remota;
- abstracción para múltiples proveedores de LLM.

## 4. H2 — Ingestion

**Objetivo:** transformar un conjunto controlado de fuentes del sistema legacy objetivo en fragmentos trazables, metadata consultable e índice incremental.

### Entregables

- escáner con inclusiones, exclusiones y límites configurables;
- huella de contenido para detectar altas, cambios y archivos sin modificación;
- clasificadores por extensión y parser de texto como fallback;
- extracción heurística inicial para PLSQL y exports PowerBuilder;
- chunking por unidades reconocibles y, cuando no sea posible, por bloques con solapamiento limitado;
- persistencia en SQLite de archivo, fragmento, tipo, objeto, líneas, checksum y estado;
- comando de ingesta con resumen de procesados, omitidos y fallidos;
- pruebas con fixtures de Oracle, PowerBuilder y Markdown;
- reporte de cobertura y errores de ingesta.

### Criterios de aceptación

- todos los archivos compatibles del corpus acordado quedan inventariados o marcados con un error explícito;
- cada fragmento puede rastrearse al archivo original y, cuando aplique, a líneas y objeto;
- repetir la ingesta sin cambios no reprocesa contenido;
- modificar o eliminar un archivo actualiza su metadata sin duplicados huérfanos;
- un archivo inválido no detiene la ingesta de los demás;
- una revisión manual de muestras confirma que los chunks conservan contexto útil.

### Riesgos

- exports PowerBuilder heterogéneos o con codificaciones antiguas;
- objetos PLSQL grandes y difíciles de segmentar con heurísticas;
- documentación binaria que amplíe prematuramente el alcance;
- ingestión accidental de credenciales o datos sensibles.

### Dependencias

- H1 aceptado;
- corpus autorizado y representativo del sistema legacy objetivo;
- reglas mínimas de exclusión y clasificación de información.

### No hacer todavía

- parser formal completo de PLSQL o PowerBuilder;
- OCR, imágenes, hojas de cálculo o todos los formatos Office;
- observación automática del filesystem;
- colas, procesamiento distribuido o paralelismo sofisticado;
- normalización exhaustiva de toda la historia del sistema.

## 5. H3 — RAG

**Objetivo:** responder preguntas técnicas utilizando contexto local recuperado, con fuentes y comportamiento explícito cuando la evidencia sea insuficiente.

### Entregables

- generación local de embeddings mediante Ollama;
- colección vectorial local en Qdrant, sincronizada con la metadata SQLite (previsión original reemplazada por SQLite + sqlite-vec mediante D-014);
- búsqueda semántica con filtros básicos por dominio, tipo y ruta;
- comando de búsqueda que muestre resultados antes de involucrar al LLM;
- comando de pregunta con prompt controlado, contexto acotado y citas;
- formato uniforme de respuesta: conclusión, evidencia, supuestos y limitaciones;
- conjunto de 10 preguntas de evaluación con fuentes esperadas;
- medición simple de recuperación y registro de latencia.

### Criterios de aceptación

- al menos 8 de 10 preguntas recuperan una fuente relevante dentro del top 5;
- una respuesta factual cita archivo y fragmento o declara evidencia insuficiente;
- el usuario puede inspeccionar los fragmentos enviados al modelo;
- filtros de metadata reducen resultados irrelevantes en casos de prueba definidos;
- la reindexación actualiza vectores modificados y elimina los obsoletos;
- el flujo funciona completamente en local con modelos y dependencias ya instalados.

### Riesgos

- modelo de embeddings inadecuado para código y español técnico;
- chunks demasiado grandes, pequeños o sin contexto;
- alucinaciones pese a recuperar fuentes correctas;
- latencia o memoria insuficiente en el hardware disponible.

### Dependencias

- H2 aceptado y corpus estable;
- Ollama y modelos seleccionados disponibles localmente;
- Qdrant en modo local y espacio de disco suficiente (dependencia original reemplazada por SQLite + sqlite-vec mediante D-014);
- preguntas de evaluación revisadas por alguien que conozca el sistema analizado.

### No hacer todavía

- agentes con múltiples pasos autónomos;
- reranking complejo, mezcla de muchos retrievers o ajuste fino;
- memoria conversacional persistente;
- evaluación con una plataforma externa;
- escalamiento multiusuario o servidor de inferencia distribuido.

## 6. H4 — Reverse Engineering

**Objetivo:** producir documentación técnica útil y un análisis de impacto básico a partir del inventario, relaciones heurísticas y evidencia recuperada.

### Entregables

- extractores de símbolos y referencias comunes de Oracle/PLSQL;
- extractores básicos de ventanas, eventos, DataWindows, SQL embebido y llamadas en PowerBuilder;
- catálogo consultable de objetos y relaciones con tipo, origen y confianza;
- consultas de dependencias entrantes y salientes hasta una profundidad limitada;
- comandos para describir un componente y analizar impacto;
- plantillas Markdown para inventario, ficha de componente y análisis de impacto;
- al menos 3 casos del dominio de validación revisados manualmente;
- sección de evidencia, inferencias y puntos no confirmados en cada documento.

### Criterios de aceptación

- cada relación reportada señala el archivo y el fragmento del que fue extraída;
- el análisis distingue relaciones detectadas de inferencias del LLM;
- ciclos o referencias faltantes no bloquean la generación;
- los documentos son Markdown válido, estables y aptos para versionarse;
- en 3 casos representativos, al menos 2 son considerados útiles por una persona conocedora del sistema sin repetir desde cero toda la investigación;
- los falsos positivos conocidos y limitaciones del parser quedan visibles.

### Riesgos

- llamadas dinámicas o SQL construido en tiempo de ejecución;
- nombres ambiguos y dependencias implícitas;
- sobreconfianza en relaciones extraídas heurísticamente;
- expansión del alcance hacia un grafo de conocimiento completo.

### Dependencias

- H3 aceptado;
- ejemplos reales de flujos Oracle–PowerBuilder;
- disponibilidad puntual de una persona experta en el sistema legacy objetivo para validar resultados.

### No hacer todavía

- grafo avanzado o base de datos de grafos;
- análisis estático completo y resolución semántica universal;
- modificación automática de código;
- diagramas exhaustivos de todo el sistema legacy objetivo;
- soporte genérico para cualquier versión o estilo PowerBuilder.

## 7. H5 — Spec Mode

**Objetivo:** convertir evidencia y análisis validados en una spec pequeña, revisable y orientada a implementación con Codex.

### Entregables

- comando para iniciar una spec desde una consulta o análisis existente;
- estructura estándar con `requirements.md`, `design.md`, `tasks.md` y `test-plan.md`;
- plantillas con fuentes, supuestos, decisiones, riesgos y criterios de aceptación;
- identificadores trazables entre requisitos, diseño y tareas;
- validaciones simples de estructura y referencias;
- una spec piloto del caso de validación lista para revisión humana.

### Criterios de aceptación

- una ejecución genera los cuatro documentos sin sobrescribir contenido existente sin confirmación;
- cada requisito tiene criterios de aceptación verificables;
- diseño y tareas referencian los requisitos que atienden;
- la spec conserva las fuentes técnicas utilizadas y separa hechos de supuestos;
- una persona puede editar y versionar los archivos sin herramientas especiales;
- la spec piloto pasa validación técnica y deja explícita cualquier revisión humana pendiente.

### Riesgos

- documentos extensos pero poco accionables;
- automatizar decisiones que requieren validación funcional;
- confundir generación de una spec con aprobación del cambio;
- intentar convertir Spec Mode en un workflow autónomo completo.

### Dependencias

- H4 aceptado;
- convención de specs acordada;
- caso piloto real, pequeño y autorizado.

### No hacer todavía

- ejecución automática de tareas;
- creación automática de branches, commits o pull requests;
- orquestación multiagente;
- workflow de aprobación empresarial;
- sincronización con herramientas externas de gestión.

## 8. Cadencia de validación

Al final de cada semana se recomienda reservar los últimos 20–30 minutos para registrar:

- qué flujo puede demostrarse;
- qué criterio de aceptación avanzó;
- qué supuesto fue invalidado;
- qué riesgo requiere una decisión;
- qué trabajo se descarta o mueve al backlog.

Cada hito produce una etiqueta o commit identificable. La demostración final ejecuta el recorrido completo: diagnóstico → ingesta → búsqueda → pregunta → análisis de impacto → generación de spec.

### Evoluciones implementadas después del plan original

- **H1.1 — Gestión y Evaluación de Modelos Locales:** completada y aceptada técnicamente. Incorpora administración explícita de modelos Ollama, validación de generación y benchmark sintético reproducible. La comparación real entre al menos dos modelos aptos quedó pendiente por condiciones del entorno de aceptación y no bloquea el cierre técnico.
- **H1.2 — Inferencia Remota con Anthropic:** completada y aceptada técnica y funcionalmente. Incorpora Anthropic como único backend remoto actual para la generación final, mantiene Ollama como default y conserva local ingesta, embeddings, retrieval, conocimiento y validación.
- **H4.1 — Configuraciones Data-Driven:** completada y aceptada técnicamente.
- **H3.1 — Optimización de contexto RAG:** implementación iniciada; H3.1-T01 a H3.1-T11 completadas. La regresión integral califica `optimized_v1` como candidato a default sin promoverlo todavía; `baseline_v1` continúa vigente. La operación y las decisiones están consolidadas en [`H31-RAG-CONTEXT.md`](H31-RAG-CONTEXT.md).

El detalle y la evidencia de estas evoluciones se conservan en [`EVOLUTION.md`](EVOLUTION.md) y sus specs. La aceptación final de H1.2 está registrada en [`../specs/H1.2-RemoteInference/acceptance.md`](../specs/H1.2-RemoteInference/acceptance.md).

## 9. Decisión posterior al MVP

Solo después de medir utilidad y uso se decidirá si corresponde incorporar una extensión de VS Code, más formatos, un segundo dominio o una API local. Si las métricas de recuperación o utilidad no se cumplen, la prioridad será mejorar el corpus y la calidad de evidencia, no añadir interfaces.
