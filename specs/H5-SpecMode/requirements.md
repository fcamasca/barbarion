# H5 - SpecMode: Requisitos

## 1. Proposito

H5 convierte el conocimiento producido por H2, H3 y H4 en especificaciones Markdown pequenas, revisables y listas para iniciar trabajo de desarrollo sobre sistemas legacy Oracle/PLSQL y PowerBuilder.

El modo Spec permite que un analista describa un requerimiento funcional y que Barbarion construya una propuesta de especificacion sustentada por evidencia existente: chunks RAG, simbolos, referencias, relaciones, analisis de impacto y documentacion ingerida.

H5 no genera codigo, no aprueba cambios y no sustituye la validacion humana. Su objetivo es reducir el esfuerzo de analisis, hacer visibles supuestos y vacios, y producir una base editable para continuar el diseno funcional y tecnico.

## 2. Alcance

### Incluido

- comando CLI para crear una spec desde una descripcion de requerimiento;
- recuperacion de evidencia relevante usando RAG H3;
- uso de simbolos, referencias, relaciones y recorridos de impacto H4;
- identificacion de componentes potencialmente afectados;
- extraccion de reglas de negocio existentes cuando esten respaldadas por evidencia;
- registro explicito de riesgos, supuestos, vacios de informacion y preguntas abiertas;
- generacion de `requirements.md`, `design.md`, `tasks.md` y `test-plan.md`;
- trazabilidad entre conclusiones, requisitos, diseno, tareas, pruebas y fuentes;
- validacion estructural antes de escribir artefactos;
- escritura segura en `specs/<nombre>/` u otro directorio permitido;
- modo determinista sin LLM cuando sea posible y fakes para pruebas;
- evaluacion con una spec piloto revisada por una persona.

### Excluido

- generacion automatica de codigo;
- ejecucion automatica de tareas;
- creacion automatica de branches, commits o pull requests;
- aprobacion funcional o tecnica del cambio;
- workflow empresarial de aprobaciones;
- edicion interactiva tipo IDE;
- UI web, VS Code, API HTTP o microservicios;
- framework de agentes o planificacion multiagente;
- nuevas bases de datos, base de grafos o Qdrant;
- parser formal adicional de Oracle/PowerBuilder;
- soporte productivo para multiples dominios;
- sincronizacion con Jira, Azure DevOps u otras herramientas externas.

## 3. Actores

- **Analista funcional/tecnico:** describe el requerimiento, revisa la propuesta y completa definiciones.
- **Desarrollador legacy:** usa la spec para preparar el cambio y revisar impacto tecnico.
- **Lider tecnico:** valida alcance, riesgos, supuestos y trazabilidad.
- **Validador experto:** confirma si las conclusiones basadas en evidencia son utiles y correctas.

## 4. Supuestos y dependencias

- H1, H2, H3 y H4 estan aceptados.
- El corpus autorizado ya fue ingerido e indexado.
- `barbarion analyze` ya produjo simbolos y relaciones vigentes.
- SQLite es la fuente de verdad local para metadata, RAG y reverse engineering.
- SQLite + sqlite-vec sigue siendo el vector store del MVP.
- Ollama local puede no estar disponible; H5 debe ofrecer salida util sin LLM o error accionable.
- Las fuentes publicas, fixtures y specs piloto usan nombres sinteticos o anonimizados.
- El usuario es responsable de revisar, editar y aprobar la spec generada.

## 5. Convenciones

- **Must:** obligatorio para aceptar H5.
- **Should:** requerido salvo limitacion justificada.
- Mensajes CLI, errores y documentacion de usuario en espanol.
- Identificadores, opciones CLI, nombres de tablas y APIs internas pueden permanecer en ingles.
- Toda conclusion debe tener fuentes o declararse como evidencia insuficiente.
- Las afirmaciones se clasifican como `detectado`, `inferido`, `supuesto` o `por_confirmar`.
- Las citas usan IDs estables de evidencia, por ejemplo `[F1]`, y deben apuntar a fuentes recuperadas.
- El nombre publico del hito es `H5-SpecMode`.

## 6. Historias de usuario

### HU-01 - Crear spec desde requerimiento funcional

Como analista, quiero describir un requerimiento en lenguaje natural para obtener una spec inicial con requisitos, diseno, tareas y plan de pruebas sustentados por evidencia.

### HU-02 - Revisar evidencia y vacios

Como lider tecnico, quiero ver que fuentes respaldan cada conclusion y que informacion falta para decidir si el analisis es confiable.

### HU-03 - Identificar componentes afectados

Como desarrollador legacy, quiero conocer componentes Oracle, PowerBuilder y documentos relacionados para estimar alcance antes de modificar codigo.

### HU-04 - Continuar trabajo manualmente

Como equipo de mantenimiento, quiero que los archivos Markdown generados sean editables y versionables sin herramientas especiales.

### HU-05 - Operar sin LLM real en pruebas

Como mantenedor de Barbarion, quiero probar Spec Mode con fakes deterministas para no depender de Ollama ni de internet.

## 7. Requisitos funcionales

### H5-RF-001 - Comando de creacion de spec

**Descripcion:** Exponer un comando CLI para crear una spec a partir de un requerimiento textual.

**Prioridad:** Must.

**Criterios de aceptacion:**

- existe `barbarion spec create "REQUERIMIENTO"` o subcomando equivalente;
- permite indicar nombre de spec, salida, modo RAG, profundidad de impacto y uso/no uso de LLM;
- valida argumentos y muestra ayuda en espanol;
- no sobrescribe una spec existente salvo `--overwrite`;
- devuelve codigo `0` si genera la spec, `1` ante error operativo y `2` ante argumentos invalidos;
- no modifica codigo fuente ingerido ni ejecuta tareas.

**Diseno:** H5-DD-001, H5-DD-010.  
**Pruebas:** H5-TP-001, H5-TP-014.  
**Tareas:** H5-T01, H5-T08.

### H5-RF-002 - Comprension inicial del requerimiento

**Descripcion:** Transformar la descripcion del usuario en una representacion estructurada del problema, intencion, alcance tentativo, entidades mencionadas y terminos de busqueda.

**Prioridad:** Must.

**Criterios de aceptacion:**

- conserva el texto original del requerimiento;
- extrae terminos candidatos, componentes mencionados y acciones solicitadas;
- diferencia requerimiento funcional, restriccion tecnica, supuesto y pregunta abierta cuando sea posible;
- si el requerimiento es ambiguo, no inventa alcance y registra preguntas abiertas;
- funciona con un modo determinista basico sin LLM.

**Diseno:** H5-DD-002.  
**Pruebas:** H5-TP-002, H5-TP-015.  
**Tareas:** H5-T02.

### H5-RF-003 - Recuperacion de evidencia

**Descripcion:** Recuperar evidencia relevante desde H3 y H4 sin duplicar sus funcionalidades.

**Prioridad:** Must.

**Criterios de aceptacion:**

- usa `SearchService`/`ContextBuilder` o contratos equivalentes de H3;
- consulta simbolos, relaciones, dependencias e impacto H4 vigentes;
- combina evidencia documental y tecnica con orden estable;
- elimina duplicados por chunk, simbolo o relacion;
- registra fuentes usadas y fuentes candidatas descartadas por limite;
- declara evidencia insuficiente cuando no hay resultados utiles.

**Diseno:** H5-DD-003, H5-DD-004.  
**Pruebas:** H5-TP-003, H5-TP-004, H5-TP-016.  
**Tareas:** H5-T03, H5-T04.

### H5-RF-004 - Identificacion de componentes afectados

**Descripcion:** Proponer componentes afectados usando evidencia recuperada, simbolos y recorridos H4.

**Prioridad:** Must.

**Criterios de aceptacion:**

- lista componentes directos, consumidores, dependencias y posibles indirectos;
- separa Oracle, PowerBuilder, documentacion y desconocidos;
- no afirma impacto solo por similitud semantica;
- muestra referencias ambiguas, dinamicas o no resueltas como `por_confirmar`;
- registra profundidad, filtros y limites aplicados;
- cada componente afectado tiene al menos una fuente o una razon de incertidumbre.

**Diseno:** H5-DD-004, H5-DD-006.  
**Pruebas:** H5-TP-004, H5-TP-005.  
**Tareas:** H5-T04.

### H5-RF-005 - Sintesis de reglas y comportamiento existente

**Descripcion:** Extraer reglas de negocio, validaciones, flujos y restricciones existentes solamente cuando haya evidencia.

**Prioridad:** Must.

**Criterios de aceptacion:**

- cada regla propuesta cita fragmentos recuperados;
- separa regla observada de inferencia o supuesto;
- identifica contradicciones o evidencia parcial;
- no transforma nombres tecnicos en reglas funcionales sin sustento;
- registra vacios de informacion cuando no sea posible concluir.

**Diseno:** H5-DD-005, H5-DD-007.  
**Pruebas:** H5-TP-006, H5-TP-017.  
**Tareas:** H5-T05.

### H5-RF-006 - Generacion de documentos de spec

**Descripcion:** Generar cuatro documentos Markdown: `requirements.md`, `design.md`, `tasks.md` y `test-plan.md`.

**Prioridad:** Must.

**Criterios de aceptacion:**

- crea los cuatro archivos solicitados con secciones estables;
- `requirements.md` incluye objetivo, alcance, fuera de alcance, historias, requisitos, no funcionales y criterios por requisito;
- `design.md` incluye arquitectura funcional, integracion, flujo, componentes, responsabilidades, modelo de datos si aplica, CLI propuesta, pipeline, errores, decisiones y Mermaid;
- `tasks.md` contiene tareas pequenas con objetivo, descripcion, dependencias y resultado esperado;
- `tasks.md` concentra la aceptacion integral en una unica ultima tarea;
- `test-plan.md` incluye estrategia, unitarias, integracion, CLI, regresion, negativos y evidencia esperada;
- los documentos son editables, versionables y no contienen rutas personales.

**Diseno:** H5-DD-007, H5-DD-008.  
**Pruebas:** H5-TP-007, H5-TP-008, H5-TP-018.  
**Tareas:** H5-T06, H5-T07.

### H5-RF-007 - Trazabilidad interna de la spec

**Descripcion:** Mantener trazabilidad entre requerimiento, evidencia, requisitos, diseno, tareas y pruebas.

**Prioridad:** Must.

**Criterios de aceptacion:**

- cada requisito tiene ID estable `REQ-NNN` o equivalente;
- decisiones de diseno referencian requisitos;
- tareas referencian requisitos y decisiones cuando aplique;
- pruebas referencian requisitos;
- cada conclusion factual cita evidencia o aparece en supuestos/por confirmar;
- la validacion detecta citas inexistentes o no usadas.

**Diseno:** H5-DD-008, H5-DD-009.  
**Pruebas:** H5-TP-009, H5-TP-010.  
**Tareas:** H5-T07.

### H5-RF-008 - Validacion estructural y de citas

**Descripcion:** Validar la spec generada antes de escribirla o antes de marcarla como generada correctamente.

**Prioridad:** Must.

**Criterios de aceptacion:**

- valida presencia de documentos y secciones obligatorias;
- valida IDs duplicados o referencias rotas;
- valida que las citas `[F#]` existan en el bloque de evidencia;
- valida que no haya afirmaciones marcadas como detectadas sin fuente;
- falla con mensaje accionable si la estructura es invalida;
- puede ejecutarse sobre una carpeta existente con `barbarion spec validate`.

**Diseno:** H5-DD-009, H5-DD-010.  
**Pruebas:** H5-TP-010, H5-TP-011, H5-TP-014.  
**Tareas:** H5-T07, H5-T09.

### H5-RF-009 - Escritura segura y artefactos generados

**Descripcion:** Escribir specs en rutas permitidas, registrar metadata minima y evitar perdida de trabajo humano.

**Prioridad:** Must.

**Criterios de aceptacion:**

- resuelve la ruta de salida de forma segura;
- crea directorio solo si esta bajo `specs/`, `output/` o una ruta explicita validada;
- falla si el directorio existe y no se pasa `--overwrite`;
- usa nombres de archivo predecibles y sanitizados;
- registra plantilla, parametros, fecha, fuentes y advertencias;
- si se persiste en `generated_artifacts`, no requiere migracion nueva salvo necesidad justificada.

**Diseno:** H5-DD-008, H5-DD-011.  
**Pruebas:** H5-TP-012, H5-TP-018.  
**Tareas:** H5-T06, H5-T08.

### H5-RF-010 - Observabilidad y errores

**Descripcion:** Reportar progreso, fuentes, limites, advertencias y errores esperados sin traceback.

**Prioridad:** Must.

**Criterios de aceptacion:**

- muestra etapas: interpretacion, recuperacion, impacto, sintesis, render y validacion;
- informa cantidad de fuentes, componentes, requisitos, tareas y preguntas abiertas;
- reporta LLM no disponible con recomendacion accionable;
- reporta evidencia insuficiente sin fallar si la spec parcial puede generarse;
- logs no vuelcan contenido fuente completo salvo debug explicito;
- conserva compatibilidad con codigos de salida existentes.

**Diseno:** H5-DD-010, H5-DD-012.  
**Pruebas:** H5-TP-013, H5-TP-014.  
**Tareas:** H5-T08, H5-T10.

### H5-RF-011 - Evaluacion de calidad

**Descripcion:** Validar H5 con una spec piloto reproducible sobre un caso autorizado y pequeno.

**Prioridad:** Must.

**Criterios de aceptacion:**

- la spec piloto usa evidencia H2/H3/H4;
- una persona revisa utilidad, trazabilidad, vacios y accionabilidad;
- se registran limitaciones, falsos positivos y preguntas abiertas;
- se ejecutan suite, smoke y regresion H1-H4;
- la aceptacion integral se documenta solo en la ultima tarea.

**Diseno:** H5-DD-013.  
**Pruebas:** H5-TP-019, H5-TP-020.  
**Tareas:** H5-T11.

## 8. Requisitos no funcionales

### H5-RNF-001 - Operacion local y privacidad

H5 opera on-premise, usa filesystem, SQLite, sqlite-vec y Ollama local opcional. No envia corpus a servicios cloud.

### H5-RNF-002 - Evidencia obligatoria

Toda conclusion factual debe citar evidencia recuperada o declararse como supuesto, inferencia o informacion insuficiente.

### H5-RNF-003 - No sobrescritura por defecto

La generacion nunca debe reemplazar specs existentes sin una opcion explicita.

### H5-RNF-004 - Determinismo estructural

La estructura, secciones, IDs, orden de evidencia y nombres de archivo deben ser estables con fakes.

### H5-RNF-005 - Pruebas sin LLM real

La suite normal debe ejecutarse sin Ollama real mediante fakes deterministas.

### H5-RNF-006 - Compatibilidad Windows y Python 3.12

El hito conserva compatibilidad con Windows y Python `>=3.12,<3.13`.

### H5-RNF-007 - Mantenibilidad

H5 reutiliza las capas existentes `cli`, `application`, `domain` e `infrastructure`, sin microservicios ni framework de agentes.

### H5-RNF-008 - Seguridad de informacion

Fixtures, specs piloto, reportes y logs no deben contener secretos, rutas personales ni nombres reales del dominio de validacion.

### H5-RNF-009 - Compatibilidad con H1-H4

Los comandos y contratos aceptados de H1-H4 no deben romperse.

### H5-RNF-010 - Latencia razonable MVP

La generacion debe aplicar limites de fuentes, tokens, profundidad y nodos para evitar ejecuciones sin control.

## 9. Casos de uso

### CU-01 - Crear spec inicial

1. El usuario ejecuta `barbarion spec create "Agregar validacion de limite de credito" --name limite-credito`.
2. Barbarion interpreta el requerimiento y genera terminos de busqueda.
3. Recupera evidencia RAG y datos H4.
4. Genera los cuatro documentos Markdown.
5. Valida estructura y citas.
6. Informa fuentes, preguntas abiertas y ruta de salida.

### CU-02 - Crear spec sin LLM

1. El usuario ejecuta `barbarion spec create "..." --no-llm`.
2. Barbarion recupera evidencia y arma una spec determinista parcial.
3. Las secciones que requieren sintesis quedan como `por_confirmar` o `evidencia insuficiente`.

### CU-03 - Validar spec existente

1. El usuario ejecuta `barbarion spec validate specs/H5-SpecMode`.
2. Barbarion revisa documentos, secciones, IDs y citas.
3. Devuelve errores accionables o confirmacion de estructura valida.

### CU-04 - Requerimiento ambiguo

1. El requerimiento no menciona componentes ni reglas claras.
2. Barbarion recupera poca evidencia.
3. La spec se genera con alcance tentativo, supuestos minimos y preguntas abiertas.

## 10. Riesgos

- specs largas pero poco accionables;
- conclusiones funcionales basadas en evidencia tecnica parcial;
- requerimientos ambiguos que recuperan evidencia irrelevante;
- sobreconfianza en impactos inferidos por H4;
- degradacion si el corpus no esta actualizado;
- tentacion de convertir H5 en generador de codigo o workflow autonomo.

## 11. Matriz inicial de trazabilidad

| Requisito | Diseno | Pruebas | Tareas |
|---|---|---|---|
| H5-RF-001 | DD-001, DD-010 | TP-001, TP-014 | T01, T08 |
| H5-RF-002 | DD-002 | TP-002, TP-015 | T02 |
| H5-RF-003 | DD-003, DD-004 | TP-003, TP-004, TP-016 | T03, T04 |
| H5-RF-004 | DD-004, DD-006 | TP-004, TP-005 | T04 |
| H5-RF-005 | DD-005, DD-007 | TP-006, TP-017 | T05 |
| H5-RF-006 | DD-007, DD-008 | TP-007, TP-008, TP-018 | T06, T07 |
| H5-RF-007 | DD-008, DD-009 | TP-009, TP-010 | T07 |
| H5-RF-008 | DD-009, DD-010 | TP-010, TP-011, TP-014 | T07, T09 |
| H5-RF-009 | DD-008, DD-011 | TP-012, TP-018 | T06, T08 |
| H5-RF-010 | DD-010, DD-012 | TP-013, TP-014 | T08, T10 |
| H5-RF-011 | DD-013 | TP-019, TP-020 | T11 |

## 12. Criterio global

H5 queda listo para implementarse cuando estos requisitos, el diseno, el plan de pruebas y las tareas mantienen trazabilidad completa y respetan el alcance del MVP. H5 se aceptara durante la ultima tarea de implementacion, con evidencia real, revision humana y no regresion de H1-H4.
