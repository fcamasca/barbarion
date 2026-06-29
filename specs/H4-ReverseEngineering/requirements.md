# H4 - ReverseEngineering: Requisitos

## 1. Proposito

H4 convierte la metadata, chunks, busqueda RAG y campos simbolicos preparados por H2/H3 en capacidades de ingenieria inversa tecnica: inventario consultable, catalogo de simbolos, relaciones trazables, navegacion de dependencias, descripcion de componentes, analisis de impacto basico y documentos Markdown estables.

El hito debe funcionar localmente, desde CLI, reutilizando SQLite como fuente de verdad y SQLite + sqlite-vec para recuperacion RAG. H4 no implementa H5 Spec Mode ni modifica codigo fuente ingerido.

## 2. Alcance

### Incluido

- inventario tecnico desde metadata persistida;
- catalogo persistido de simbolos tecnicos;
- extraccion heuristica de referencias Oracle/PLSQL y PowerBuilder;
- resolucion controlada de referencias contra simbolos conocidos;
- persistencia de relaciones con evidencia y estado de resolucion;
- consultas de dependencias entrantes, salientes y transitivas con profundidad limitada;
- comandos `inventory`, `describe` e `impact`;
- modo determinista sin LLM para `describe` e `impact`;
- generacion Markdown para inventario, ficha de componente e impacto;
- integracion incremental con ingesta y reanalisis/reconciliacion;
- observabilidad, pruebas y validacion manual sobre tres casos representativos.

### Excluido

- H5 Spec Mode y generacion automatica de specs de cambio;
- modificacion automatica de codigo;
- agentes autonomos, multiagente o workflows de aprobacion;
- API HTTP, FastAPI, UI web, VS Code o microservicios;
- base de datos de grafos o grafo empresarial;
- Qdrant como dependencia actual;
- parser formal completo de PLSQL o PowerBuilder;
- ejecucion de SQL, PowerScript o codigo ingerido;
- conexion a Oracle productivo;
- garantia de exactitud total sin revision humana.

## 3. Actores

- **Analista tecnico:** consulta inventario, dependencias y evidencia.
- **Desarrollador legacy:** describe componentes y evalua impacto antes de cambiar codigo.
- **Lider tecnico:** revisa riesgos, limitaciones y utilidad de los documentos.
- **Validador experto:** revisa tres casos representativos y registra falsos positivos o limites.

## 4. Supuestos y dependencias

- H1, H2 y H3 estan aceptados.
- SQLite esta en version 3 antes de migrar H4.
- H2 mantiene archivos, documentos y chunks vigentes con rangos trazables.
- H3 mantiene `search`, `ask --no-llm`, `ContextBuilder`, metricas y `symbol_occurrences` reservada.
- Ollama puede no estar disponible; los comandos deben tener salida util sin LLM.
- El corpus de validacion es autorizado y los fixtures versionados son sinteticos o anonimizados.
- Los documentos maestros vigentes estan en `docs/`, aunque el prompt los nombre en raiz.

## 5. Convenciones

- **Must:** obligatorio para aceptar H4.
- **Should:** requerido salvo limitacion justificada.
- Mensajes CLI, errores y documentacion de usuario en espanol.
- Identificadores, nombres de tablas, opciones y APIs internas pueden estar en ingles.
- Toda afirmacion debe clasificarse como `detectado`, `inferido` o `por_confirmar`.
- Ninguna referencia ambigua se resuelve silenciosamente.
- Profundidad por defecto: `1`; maximo permitido por configuracion: `5`.

## 6. Requisitos funcionales

### H4-RF-001 - Inventario tecnico

**Descripcion:** Consultar y exportar un inventario tecnico desde SQLite sin reescanear el filesystem.

**Prioridad:** Must.

**Criterios de aceptacion:**

- `barbarion inventory` lista archivos, objetos, simbolos y conteos vigentes;
- permite filtros por tecnologia, tipo, nombre, path, estado y confianza;
- la salida incluye procedencia minima: archivo, chunk y lineas si existen;
- marca componentes incompletos, ambiguos o desconocidos;
- soporta `--format text|json|markdown`;
- no ejecuta parsers ni accede al corpus fuente.

**Diseno:** H4-DD-004, H4-DD-008.  
**Pruebas:** H4-TP-001, H4-TP-014, H4-TP-020.  
**Tareas:** H4-T01, H4-T05, H4-T08.

### H4-RF-002 - Catalogo de simbolos

**Descripcion:** Persistir simbolos tecnicos con identidad estable, normalizacion, ubicacion, estado, metodo de extraccion y confianza.

**Prioridad:** Must.

**Criterios de aceptacion:**

- existe una tabla H4 para simbolos o una evolucion compatible de `symbol_occurrences`;
- cada simbolo conserva nombre original, nombre normalizado, tipo, tecnologia, archivo, chunk, rango y contenedor cuando existan;
- los IDs son deterministas para la misma evidencia y cambian cuando cambia la ubicacion o identidad de origen;
- estados minimos: `active`, `stale`, `deleted`, `ambiguous`;
- soporta simbolos Oracle, PowerBuilder, documentacion relacionada y desconocidos.

**Diseno:** H4-DD-001, H4-DD-002, H4-DD-005.  
**Pruebas:** H4-TP-002, H4-TP-013, H4-TP-017.  
**Tareas:** H4-T01, H4-T02, H4-T04.

### H4-RF-003 - Extraccion de referencias

**Descripcion:** Extraer referencias comunes Oracle/PLSQL y PowerBuilder mediante heuristicas conservadoras.

**Prioridad:** Must.

**Criterios de aceptacion:**

- Oracle detecta llamadas, packages, tablas/vistas en SQL, triggers, secuencias, sinonimos evidentes y SQL dinamico reconocible;
- PowerBuilder detecta `open`, llamadas a funciones/eventos, user objects, menus, DataWindows, SQL embebido y procedimientos almacenados;
- cada referencia conserva evidencia textual, archivo, chunk, lineas, metodo y confianza;
- comentarios y literales no se tratan como referencias directas salvo heuristica explicitamente marcada;
- referencias dinamicas se guardan con `resolution_status = dynamic` y `classification = por_confirmar`, no como resueltas.

**Diseno:** H4-DD-006, H4-DD-007.  
**Pruebas:** H4-TP-003, H4-TP-004, H4-TP-018.  
**Tareas:** H4-T03, H4-T04.

### H4-RF-004 - Resolucion controlada de relaciones

**Descripcion:** Resolver referencias contra simbolos conocidos aplicando normalizacion y reglas de ambiguedad.

**Prioridad:** Must.

**Criterios de aceptacion:**

- normaliza nombres case-insensitive y conserva el nombre original;
- distingue referencias calificadas y no calificadas;
- si hay un unico candidato razonable, marca `resolved`;
- si hay varios candidatos razonables, marca `ambiguous` y persiste candidatos;
- si no hay candidato, marca `unresolved`;
- no elimina referencias no resueltas por no poder resolverlas.

**Diseno:** H4-DD-007.  
**Pruebas:** H4-TP-005, H4-TP-006, H4-TP-007.  
**Tareas:** H4-T04.

### H4-RF-005 - Modelo de relaciones trazable

**Descripcion:** Persistir relaciones tecnicas con origen, destino, tipo, evidencia, metodo, confianza y estado.

**Prioridad:** Must.

**Criterios de aceptacion:**

- cada relacion tiene simbolo origen o archivo/chunk origen;
- el destino puede ser simbolo resuelto, clave textual, externo o desconocido;
- no almacena `direction`; la direccion `incoming`, `outgoing` o `both` se calcula al consultar desde un simbolo semilla;
- conserva tipo de relacion y clasificacion `detectado`, `inferido` o `por_confirmar`;
- conserva candidatos cuando la resolucion es ambigua;
- las eliminaciones de archivos/chunks no dejan relaciones vigentes huerfanas.

**Diseno:** H4-DD-002, H4-DD-005, H4-DD-007.  
**Pruebas:** H4-TP-008, H4-TP-013, H4-TP-017.  
**Tareas:** H4-T01, H4-T04.

### H4-RF-006 - Navegacion de dependencias

**Descripcion:** Consultar dependencias entrantes, salientes, directas y transitivas con profundidad limitada.

**Prioridad:** Must.

**Criterios de aceptacion:**

- soporta `incoming`, `outgoing`, `both` y profundidad `0..5`;
- detecta ciclos y los reporta sin bloquear;
- permite filtrar por tecnologia, tipo de relacion, estado y confianza minima;
- muestra referencias no resueltas y ambiguas;
- el recorrido tiene limite de nodos y mensaje cuando se alcanza.

**Diseno:** H4-DD-009.  
**Pruebas:** H4-TP-009, H4-TP-010.  
**Tareas:** H4-T06.

### H4-RF-007 - Descripcion de componentes

**Descripcion:** `barbarion describe <objeto>` produce una ficha tecnica desde metadata, simbolos, relaciones, RAG y LLM opcional.

**Prioridad:** Must.

**Criterios de aceptacion:**

- resuelve el objeto por nombre, tipo o identificador;
- ante multiples coincidencias muestra candidatos y no elige automaticamente;
- incluye identificacion, ubicacion, responsabilidades, dependencias, evidencia, inferencias, puntos por confirmar y limitaciones;
- `--no-llm` genera una ficha determinista util;
- si el LLM falla, se ofrece salida sin LLM o mensaje accionable;
- soporta salida `text|json|markdown` y escritura segura a archivo.

**Diseno:** H4-DD-010, H4-DD-012.  
**Pruebas:** H4-TP-011, H4-TP-015, H4-TP-020.  
**Tareas:** H4-T07, H4-T09.

### H4-RF-008 - Analisis de impacto basico

**Descripcion:** `barbarion impact <objeto>` analiza consumidores y dependencias con profundidad controlada.

**Prioridad:** Must.

**Criterios de aceptacion:**

- presenta componente analizado, alcance, dependencias directas, consumidores y posibles indirectos;
- separa cruces Oracle-PowerBuilder;
- no afirma impacto solo por similitud semantica;
- clasifica hallazgos en detectado, inferido y por confirmar;
- muestra referencias dinamicas, ambiguas y no resueltas;
- reporta ciclos, profundidad alcanzada y limites aplicados.

**Diseno:** H4-DD-011, H4-DD-012.  
**Pruebas:** H4-TP-012, H4-TP-015, H4-TP-021.  
**Tareas:** H4-T07, H4-T10.

### H4-RF-009 - Generacion Markdown versionada

**Descripcion:** Generar Markdown estable para inventario, ficha de componente e impacto.

**Prioridad:** Must.

**Criterios de aceptacion:**

- cada plantilla incluye version, fecha, parametros, fuentes, limitaciones y secciones estables;
- nombres de archivo son seguros, predecibles y sin rutas personales;
- no sobrescribe archivos existentes salvo `--overwrite`;
- valida que la salida quede dentro del directorio permitido o indicado;
- la estructura es determinista aunque el contenido sintetizado por LLM varie.

**Diseno:** H4-DD-012.  
**Pruebas:** H4-TP-015, H4-TP-016.  
**Tareas:** H4-T08, H4-T09, H4-T10.

### H4-RF-010 - Actualizacion incremental H4

**Descripcion:** Integrar simbolos y relaciones con el flujo incremental H2/H3 sin dejar estado ambiguo.

**Prioridad:** Must.

**Criterios de aceptacion:**

- un archivo nuevo genera o actualiza simbolos y referencias del archivo;
- un archivo modificado reemplaza simbolos y relaciones derivados de evidencia obsoleta;
- un archivo eliminado marca simbolos/relaciones como `deleted` o los elimina segun FK definida;
- una referencia no resuelta puede resolverse en una ejecucion posterior;
- una relacion resuelta vuelve a `unresolved` o `ambiguous` si cambia el destino;
- despues de actualizar simbolos, H4 re-resuelve referencias vigentes de archivos sin cambios cuando su `normalized_target`, contenedor o tipo coincide con simbolos creados, modificados o eliminados;
- `--full` re-resuelve todas las referencias vigentes;
- H4 publica resultados incrementalmente por archivo o scope confirmado;
- Ctrl+C deja un run `interrupted`; los archivos ya confirmados permanecen vigentes y el archivo/scope en curso se revierte;
- la reconciliacion global de eliminados solo se aplica cuando la seleccion de scope termina correctamente.

**Diseno:** H4-DD-003, H4-DD-013.  
**Pruebas:** H4-TP-017, H4-TP-019.  
**Tareas:** H4-T01, H4-T05.

### H4-RF-011 - Observabilidad y errores

**Descripcion:** Reportar conteos, duraciones, estados, limites y errores accionables.

**Prioridad:** Must.

**Criterios de aceptacion:**

- registra runs H4 con estado `running`, `completed`, `completed_with_errors`, `failed`, `interrupted`;
- informa simbolos detectados, relaciones detectadas, resueltas, no resueltas y ambiguas;
- informa archivos con advertencias, duracion por etapa, profundidad recorrida y limites alcanzados;
- errores esperados devuelven codigo de salida definido y no traceback;
- operaciones extensas reutilizan progreso por etapas compatible con H3 cuando aplique.

**Diseno:** H4-DD-013.  
**Pruebas:** H4-TP-019, H4-TP-020.  
**Tareas:** H4-T05, H4-T11.

### H4-RF-012 - Evaluacion de calidad

**Descripcion:** Validar H4 con una muestra pequena, controlada y reproducible.

**Prioridad:** Must.

**Criterios de aceptacion:**

- existen al menos tres casos: Oracle, PowerBuilder y cruce PowerBuilder-Oracle;
- la evaluacion mide exactitud de simbolos, relaciones, falsos positivos, falsos negativos conocidos, utilidad y trazabilidad;
- usa fakes para LLM en pruebas normales;
- no inventa porcentajes sin muestra definida;
- la ultima tarea registra evidencia, metricas, limitaciones y revision humana.

**Diseno:** H4-DD-014.  
**Pruebas:** H4-TP-021, H4-TP-022.  
**Tareas:** H4-T12.

## 7. Requisitos no funcionales

### H4-RNF-001 - Operacion local y privacidad

**Descripcion:** H4 opera on-premise y no envia corpus a servicios externos.

**Criterio:** solo usa SQLite, filesystem local y Ollama local configurado; pruebas normales no requieren internet.

**Diseno:** H4-DD-015.  
**Pruebas:** H4-TP-023.  
**Tareas:** H4-T07, H4-T12.

### H4-RNF-002 - Trazabilidad

**Descripcion:** Todo resultado debe poder rastrearse a evidencia o declararse como inferencia/por confirmar.

**Criterio:** relaciones, descripcion, impacto y Markdown incluyen fuentes o limitaciones.

**Diseno:** H4-DD-012, H4-DD-015.  
**Pruebas:** H4-TP-011, H4-TP-012, H4-TP-015.  
**Tareas:** H4-T07, H4-T09, H4-T10.

### H4-RNF-003 - Consistencia transaccional

**Descripcion:** Simbolos y relaciones se publican de forma atomica por archivo o scope confirmado, no por corrida completa.

**Criterio:** falla o interrupcion revierte el archivo/scope actual, conserva resultados ya confirmados y no deja relaciones vigentes huerfanas.

**Diseno:** H4-DD-003.  
**Pruebas:** H4-TP-017, H4-TP-019.  
**Tareas:** H4-T01, H4-T05.

### H4-RNF-004 - Idempotencia e incrementalidad

**Descripcion:** Repetir el analisis sin cambios no duplica simbolos, relaciones ni documentos.

**Criterio:** dos ejecuciones equivalentes conservan IDs, conteos y orden canonico.

**Diseno:** H4-DD-003, H4-DD-005.  
**Pruebas:** H4-TP-017.  
**Tareas:** H4-T05.

### H4-RNF-005 - Rendimiento MVP

**Descripcion:** El analisis no debe reparsear todo el corpus cuando no hay cambios.

**Criterio:** se mide full vs incremental en la muestra H4; si no hay linea base, la ultima tarea registra baseline y procedimiento.

**Diseno:** H4-DD-013, H4-DD-014.  
**Pruebas:** H4-TP-024.  
**Tareas:** H4-T05, H4-T12.

### H4-RNF-006 - Profundidad y ciclos acotados

**Descripcion:** Los recorridos de dependencias no deben crecer sin control.

**Criterio:** profundidad maxima, limite de nodos, deteccion de ciclos y mensaje de limite alcanzado.

**Diseno:** H4-DD-009.  
**Pruebas:** H4-TP-009, H4-TP-010.  
**Tareas:** H4-T06.

### H4-RNF-007 - Determinismo documental

**Descripcion:** La estructura Markdown y el orden de secciones deben ser estables.

**Criterio:** golden files pasan con fakes y orden canonico.

**Diseno:** H4-DD-012.  
**Pruebas:** H4-TP-015, H4-TP-016.  
**Tareas:** H4-T08, H4-T09, H4-T10.

### H4-RNF-008 - Compatibilidad Windows y Python 3.12

**Descripcion:** H4 debe conservar compatibilidad con Windows y Python `>=3.12,<3.13`.

**Criterio:** rutas persistidas usan `/`, tests usan temporales y no hay comandos shell obligatorios.

**Diseno:** H4-DD-015.  
**Pruebas:** H4-TP-023.  
**Tareas:** H4-T12.

### H4-RNF-009 - Mantenibilidad

**Descripcion:** Mantener monolito modular sin paquetes paralelos ni abstracciones especulativas.

**Criterio:** CLI orquesta, `application/` contiene casos de uso, `domain/` reglas, `infrastructure/` adaptadores; no se agregan microservicios, grafo, plugins ni frameworks RAG.

**Diseno:** H4-DD-001.  
**Pruebas:** H4-TP-025.  
**Tareas:** H4-T01, H4-T12.

### H4-RNF-010 - Seguridad de informacion

**Descripcion:** No versionar secretos, rutas personales ni datos sensibles en fixtures o reportes.

**Criterio:** fixtures H4 son sinteticos/anonimizados y logs no vuelcan contenido fuente completo.

**Diseno:** H4-DD-015.  
**Pruebas:** H4-TP-023, H4-TP-022.  
**Tareas:** H4-T12.

### H4-RNF-011 - Compatibilidad con H1/H2/H3

**Descripcion:** H4 no debe romper comandos, tablas ni contratos aceptados.

**Criterio:** suite H1-H3 continua pasando y comandos existentes conservan comportamiento.

**Diseno:** H4-DD-003, H4-DD-015.  
**Pruebas:** H4-TP-026.  
**Tareas:** H4-T12.

### H4-RNF-012 - Pruebas sin LLM real

**Descripcion:** La suite normal no depende de Ollama ni de un modelo real.

**Criterio:** descripciones e impactos con LLM usan fake determinista; modo `--no-llm` queda cubierto.

**Diseno:** H4-DD-010, H4-DD-011.  
**Pruebas:** H4-TP-011, H4-TP-012, H4-TP-020.  
**Tareas:** H4-T07, H4-T12.

## 8. Casos de uso

### CU-01 - Consultar inventario

1. El usuario ejecuta `barbarion inventory --type package --format text`.
2. Barbarion abre SQLite, consulta simbolos vigentes y muestra conteos.
3. Cada resultado incluye procedencia, confianza y estado.

**Alternativos:** base sin analisis H4, filtros sin resultados, formato Markdown.

### CU-02 - Describir componente

1. El usuario ejecuta `barbarion describe order_total --no-llm`.
2. Barbarion resuelve el componente o muestra candidatos.
3. Ensambla metadata, simbolos, relaciones y evidencia RAG.
4. Genera ficha determinista o sintetizada con LLM local.

**Alternativos:** objeto inexistente, ambiguo, sin evidencia, LLM no disponible, ciclos.

### CU-03 - Analizar impacto

1. El usuario ejecuta `barbarion impact process_customer --depth 2`.
2. Barbarion recorre relaciones entrantes/salientes con limites.
3. Muestra consumidores, dependencias, cruces y no resueltos.
4. Clasifica hallazgos y genera Markdown si se indica salida.

**Alternativos:** profundidad invalida, limite alcanzado, referencias dinamicas.

### CU-04 - Reconciliar analisis

1. El usuario ejecuta ingesta incremental.
2. H4 detecta cambios por documentos/chunks vigentes o por comando explicito `analyze`.
3. Simbolos y relaciones obsoletas se reemplazan sin duplicados.

**Alternativos:** interrupcion, archivo eliminado, referencia antes no resuelta ahora resuelta.

## 9. Fuera de alcance

H4 no crea specs H5, no propone cambios de codigo, no ejecuta codigo, no agrega API HTTP, no usa base de grafos, no conecta Oracle, no implementa parser perfecto y no garantiza impacto funcional completo.

## 10. Riesgos

- SQL dinamico y llamadas PowerBuilder dinamicas pueden generar falsos negativos.
- Nombres comunes o no calificados pueden producir ambiguedad frecuente.
- Documentacion maestra conserva referencias antiguas a Qdrant.
- `docs/ARCHITECTURE.md` describe Qdrant, pero DECISIONS y codigo vigente usan SQLite + sqlite-vec.
- `ROADMAP.md` todavia menciona Qdrant en H3, desactualizado frente a D-014.
- `README.md` lista documentos maestros en `docs/`, no en raiz como indica el prompt.
- La tabla `symbol_occurrences` actual es insuficiente para relaciones H4 completas y requiere migracion.
- Validacion manual puede retrasarse si no hay experto disponible.

## 11. Matriz inicial de trazabilidad

| Requisito | Diseno | Pruebas | Tareas |
|---|---|---|---|
| H4-RF-001 | DD-004, DD-008 | TP-001, TP-014, TP-020 | T01, T05, T08 |
| H4-RF-002 | DD-001, DD-002, DD-005 | TP-002, TP-013, TP-017 | T01, T02, T04 |
| H4-RF-003 | DD-006, DD-007 | TP-003, TP-004, TP-018 | T03, T04 |
| H4-RF-004 | DD-007 | TP-005, TP-006, TP-007 | T04 |
| H4-RF-005 | DD-002, DD-005, DD-007 | TP-008, TP-013, TP-017 | T01, T04 |
| H4-RF-006 | DD-009 | TP-009, TP-010 | T06 |
| H4-RF-007 | DD-010, DD-012 | TP-011, TP-015, TP-020 | T07, T09 |
| H4-RF-008 | DD-011, DD-012 | TP-012, TP-015, TP-021 | T07, T10 |
| H4-RF-009 | DD-012 | TP-015, TP-016 | T08, T09, T10 |
| H4-RF-010 | DD-003, DD-013 | TP-017, TP-019 | T01, T05 |
| H4-RF-011 | DD-013 | TP-019, TP-020 | T05, T11 |
| H4-RF-012 | DD-014 | TP-021, TP-022 | T12 |
| H4-RNF-001 | DD-015 | TP-023 | T07, T12 |
| H4-RNF-002 | DD-012, DD-015 | TP-011, TP-012, TP-015 | T07, T09, T10 |
| H4-RNF-003 | DD-003 | TP-017, TP-019 | T01, T05 |
| H4-RNF-004 | DD-003, DD-005 | TP-017 | T05 |
| H4-RNF-005 | DD-013, DD-014 | TP-024 | T05, T12 |
| H4-RNF-006 | DD-009 | TP-009, TP-010 | T06 |
| H4-RNF-007 | DD-012 | TP-015, TP-016 | T08, T09, T10 |
| H4-RNF-008 | DD-015 | TP-023 | T12 |
| H4-RNF-009 | DD-001 | TP-025 | T01, T12 |
| H4-RNF-010 | DD-015 | TP-022, TP-023 | T12 |
| H4-RNF-011 | DD-003, DD-015 | TP-026 | T12 |
| H4-RNF-012 | DD-010, DD-011 | TP-011, TP-012, TP-020 | T07, T12 |

## 12. Criterio global

H4 queda listo para implementarse cuando estos requisitos, el diseno, el plan de pruebas y las tareas mantienen trazabilidad completa. H4 se aceptara durante la ultima tarea de implementacion, no durante la elaboracion de este spec, con evidencia de suite completa, smoke test, tres casos representativos, metricas, limitaciones y no regresion de H1/H2/H3.
