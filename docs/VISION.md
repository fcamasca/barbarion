# Barbarion — Visión del producto

> Agente AI con conocimiento on-premise para analizar, documentar y asistir la ingeniería inversa de sistemas legacy Oracle/PLSQL + PowerBuilder.

## 1. Propósito

Barbarion busca convertir el conocimiento técnico disperso de un sistema legacy objetivo —código, documentación, convenciones y experiencia del equipo— en una base consultable y trazable que ayude a entender el sistema antes de modificarlo.

El producto construye y conserva on-premise el conocimiento técnico, y entrega resultados útiles para el desarrollo: explicaciones con fuentes, inventarios técnicos, análisis de dependencias e impacto, y documentos Markdown orientados por especificaciones. La generación usa Ollama por defecto y puede delegarse explícitamente a Anthropic sin trasladar ingesta, embeddings, retrieval, relaciones, validación ni persistencia.

Barbarion no pretende sustituir el criterio del desarrollador ni ejecutar cambios de forma autónoma. Su función es reducir el trabajo de exploración, hacer explícitos los supuestos y preservar conocimiento que hoy depende de búsquedas manuales o de pocas personas.

## 2. Problema que resuelve

Los sistemas Oracle/PLSQL + PowerBuilder suelen acumular años de evolución y presentan varias dificultades:

- reglas de negocio distribuidas entre base de datos, pantallas, eventos y DataWindows;
- documentación incompleta, desactualizada o separada del código;
- dependencias difíciles de rastrear entre objetos PowerBuilder y objetos Oracle;
- análisis de impacto lento y dependiente del conocimiento tácito;
- incorporación costosa de nuevos integrantes;
- restricciones para enviar código o documentación sensible a servicios cloud;
- resultados de asistentes generalistas sin suficiente contexto ni evidencia.

El problema central no es la falta de un chatbot. Es la falta de una representación local, navegable y verificable del sistema real.

## 3. Visión del MVP

El MVP demostrará, sobre un corpus autorizado, acotado y representativo de un sistema Oracle/PowerBuilder real, que un desarrollador puede:

1. ingestar código PLSQL, exports de PowerBuilder y documentación Markdown o texto;
2. consultar ese conocimiento mediante una CLI local;
3. recibir respuestas apoyadas en fragmentos recuperados y referencias a archivos;
4. obtener una vista técnica básica de componentes y dependencias;
5. generar documentación Markdown reproducible;
6. crear una spec pequeña a partir de un análisis, manteniendo requisitos, diseño y tareas separados.

El MVP será una herramienta para análisis asistido. No será todavía una plataforma corporativa ni un agente autónomo de implementación.

El MVP se valida inicialmente sobre un dominio legacy real, pero ese dominio no forma parte del diseño público ni limita la arquitectura de Barbarion.

## 4. Usuarios objetivo

### Usuario principal

Desarrollador o analista técnico que mantiene el sistema legacy objetivo y necesita comprender código existente, investigar un incidente o preparar un cambio.

### Usuarios secundarios

- líder técnico que revisa impacto, riesgos y alcance;
- especialista funcional/técnico que valida reglas de negocio identificadas;
- nuevo integrante que necesita orientarse en el sistema;
- arquitecto o responsable de mantenimiento que busca preservar conocimiento.

El MVP se optimizará para uno o pocos usuarios técnicos trabajando localmente, no para concurrencia masiva.

## 5. Alcance del MVP

### Dentro del alcance

- construcción local del conocimiento y ejecución sin servicios externos por defecto;
- inferencia remota opcional mediante Anthropic, limitada al prompt final construido desde el contexto seleccionado;
- un único dominio legacy configurado para la validación inicial;
- interfaz CLI;
- configuración simple por archivo y variables de entorno;
- escaneo incremental de carpetas y archivos;
- ingesta de `.sql`, `.pks`, `.pkb`, `.srw`, `.sru`, `.srd` y documentos de texto/Markdown;
- extracción heurística de objetos y referencias comunes;
- metadata e inventario local en SQLite;
- embeddings y búsqueda vectorial local;
- inferencia mediante Ollama o Anthropic, seleccionada explícitamente por configuración;
- RAG con citas a archivo, objeto y líneas cuando estén disponibles;
- generación de Markdown para inventarios, explicaciones, impacto y specs;
- logs locales y comandos básicos de diagnóstico;
- pruebas sobre un corpus autorizado del sistema legacy objetivo.

### Fuera del alcance

- extensión de VS Code, UI web o aplicación de escritorio;
- soporte simultáneo o productivo para múltiples dominios;
- edición o despliegue autónomo de código;
- autenticación corporativa, roles o multiusuario;
- microservicios, Kubernetes o infraestructura distribuida;
- base de datos empresarial;
- grafo avanzado de conocimiento;
- parser completo o semánticamente perfecto de PowerBuilder;
- cobertura total de formatos documentales en la primera versión;
- entrenamiento o fine-tuning de modelos;
- workflows automáticos complejos;
- múltiples proveedores cloud, routing dinámico o fallback entre proveedores;
- garantía de exactitud sin revisión humana.

## 6. Principios de diseño

1. **Conocimiento local primero.** Código, índices, embeddings, metadata y relaciones permanecen dentro del entorno controlado. Con Anthropic activo, solo el prompt final y su respuesta cruzan la frontera declarada; Ollama y `--no-llm` conservan el flujo completamente local.
2. **Evidencia antes que elocuencia.** Una respuesta sin fuentes o con evidencia insuficiente debe declararlo.
3. **Profundidad antes que amplitud.** Un dominio legacy real se valida antes de incorporar otro dominio.
4. **CLI primero.** La capacidad central debe funcionar sin depender de una interfaz gráfica o servidor web.
5. **Incrementos verificables.** Cada hito debe producir un flujo demostrable y pruebas repetibles.
6. **Heurísticas honestas.** Los parsers iniciales pueden ser incompletos, pero deben conservar el texto original e indicar sus límites.
7. **Una aplicación modular.** Separación interna clara sin distribuir prematuramente el sistema.
8. **Configuración explícita.** Rutas, modelos, límites y colecciones no deben quedar ocultos en el código.
9. **Artefactos legibles.** Markdown, JSON y SQLite deben permitir inspección y diagnóstico sin herramientas propietarias.
10. **Spec antes de cambios complejos.** El análisis debe poder convertirse en requisitos, diseño y tareas revisables.
11. **Humano responsable.** Barbarion propone y documenta; una persona valida las conclusiones y decide los cambios.

## 7. Valor esperado

- reducir el tiempo invertido en localizar código y documentación relevante;
- hacer visibles dependencias Oracle–PowerBuilder que hoy se investigan manualmente;
- mejorar la calidad de los análisis mediante fuentes y supuestos explícitos;
- producir documentación consistente y versionable;
- disminuir la dependencia de conocimiento tácito;
- establecer una base técnica reutilizable para futuros dominios e interfaces, sin construirlas antes de necesitarlas.

## 8. Hipótesis que debe validar el MVP

1. Un índice local de tamaño manejable puede devolver contexto útil del dominio configurado con latencia aceptable.
2. Parsers heurísticos son suficientes para aportar valor antes de construir analizadores formales.
3. La combinación de búsqueda semántica, filtros de metadata y referencias explícitas mejora la confianza frente a un chat sin RAG.
4. Los documentos generados reducen trabajo real si tienen estructura estable y permanecen editables.
5. El equipo puede mantener la solución con una base Python pequeña y dependencias limitadas.

## 9. Definición de éxito del MVP

El MVP se considera exitoso cuando, en una demostración reproducible sobre un corpus autorizado del sistema legacy objetivo:

- el 100 % de los archivos compatibles se inventaría y cada error de ingesta queda registrado sin abortar todo el proceso;
- una segunda ingesta sin cambios evita reprocesar archivos sin modificaciones;
- al menos 8 de 10 preguntas de un conjunto de evaluación recuperan una fuente relevante entre los primeros 5 resultados;
- todas las respuestas factuales de la demostración incluyen referencias verificables o declaran que no existe evidencia suficiente;
- Barbarion genera un inventario, un análisis de componente, un análisis de impacto y una spec en Markdown;
- al menos 3 análisis representativos son revisados por una persona conocedora del sistema analizado y 2 resultan útiles sin rehacer la investigación desde cero;
- el flujo completo puede ejecutarse localmente con Ollama o `--no-llm` desde instrucciones versionadas y repetirse en una instalación limpia;
- no se requiere una extensión de editor, microservicio ni infraestructura empresarial; Anthropic es una opción explícita para desacoplar la generación del hardware local, no una dependencia del conocimiento.

Estas métricas son una puerta de decisión, no una promesa de precisión universal. Si no se cumplen, se mejora el corpus, la ingesta o la recuperación antes de ampliar el producto.

## 10. Resultado al finalizar

Al cerrar el MVP, Barbarion debe ser una base pequeña pero real: instalable, demostrable, evaluada con casos del dominio de validación y preparada para evolucionar mediante specs. La siguiente inversión se decidirá con evidencia de uso, no por anticipación arquitectónica.
