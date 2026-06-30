# H5 - SpecMode: Plan de pruebas

## 1. Objetivo

Verificar que H5 genera especificaciones Markdown trazables desde un requerimiento funcional, reutilizando RAG H3 y reverse engineering H4, sin inventar informacion, sin sobrescribir trabajo humano y sin depender de sintesis asistida real en la suite normal.

## 2. Alcance

Incluye:

- interpretacion del requerimiento;
- recuperacion de evidencia H3;
- integracion con simbolos, relaciones e impacto H4;
- sintesis de reglas, riesgos, supuestos y preguntas abiertas;
- Review automatico interno sobre `SpecDraft`;
- generacion de `requirements.md`, `design.md`, `tasks.md` y `test-plan.md`;
- validacion de estructura, IDs y citas;
- CLI `spec create` y `spec validate`;
- escritura segura;
- observabilidad, errores y regresion H1-H4;
- spec piloto con revision humana.

Excluye:

- generacion automatica de codigo;
- ejecucion automatica de tareas;
- workflows de aprobacion;
- API HTTP, UI, VS Code o agentes;
- pruebas contra Oracle productivo;
- precision funcional universal.

## 3. Estrategia

- unit tests para dominio, interpretacion, evidencia, sintesis, Review, validacion y rutas;
- integration tests con SQLite temporal, fixtures H2/H3/H4 y fakes de RAG/sintesis;
- CLI tests para `spec create` y `spec validate`;
- golden files Markdown para estructura estable;
- casos negativos de evidencia insuficiente, ambiguedad y citas invalidas;
- regresion H1-H4;
- smoke test del entry point instalado;
- validacion humana documentada en la ultima tarea.

## 4. Ambientes

- Windows local como ambiente principal;
- Python `>=3.12,<3.13`;
- SQLite local con schema vigente H4;
- sqlite-vec instalado para no romper H3;
- Ollama real opcional;
- fake determinista de sintesis por defecto;
- `pytest --basetemp .pytest-tmp/h5` recomendado en Windows.

## 5. Fixtures y datos

### Corpus sintetico H5

Debe reutilizar o extender fixtures H4 con nombres sinteticos:

- package Oracle con validacion de negocio;
- procedure que actualiza una tabla;
- trigger o view relacionado;
- PowerBuilder window/event que invoca logica Oracle;
- DataWindow con SQL embebido;
- documento Markdown con regla funcional parcial;
- referencia dinamica o ambigua;
- componente mencionado en requerimiento pero sin evidencia suficiente.

### Requerimientos de prueba

1. Requerimiento concreto con componentes conocidos.
2. Requerimiento funcional sin nombres tecnicos.
3. Requerimiento ambiguo con poca evidencia.
4. Requerimiento que cruza PowerBuilder y Oracle.
5. Requerimiento con impacto sobre referencia dinamica.

Los fixtures no deben incluir nombres reales, rutas personales ni datos privados.

## 6. Pruebas unitarias

### H5-TP-001 - Dominio Spec Mode

Valida modelos, IDs estables, clasificaciones, trace links y serializacion minima.

### H5-TP-002 - Interpretacion del requerimiento

Extrae texto original, terminos, entidades, acciones, restricciones, supuestos y preguntas; no inventa alcance ante ambiguedad.

### H5-TP-003 - Recuperacion RAG

Invoca H3 con modo, top-k y filtros; deduplica chunks; asigna `[F#]`; reporta evidencia insuficiente.

### H5-TP-004 - Integracion H4

Consulta simbolos y dependencias; respeta profundidad; incluye resolved, ambiguous, unresolved y dynamic.

### H5-TP-005 - Componentes afectados

Clasifica directos, consumidores, dependencias e indirectos; no declara impacto solo por similitud semantica.

### H5-TP-006 - Reglas existentes

Cada regla detectada cita evidencia; contradicciones y evidencia parcial quedan visibles.

### H5-TP-007 - Render de documentos

Genera los cuatro archivos con secciones obligatorias y estructura estable.

### H5-TP-008 - Review automatico

Review verifica consistencia entre documentos proyectados, evidencia por requisito, tareas/pruebas asociadas a requisitos, conclusiones dentro del alcance de la evidencia, citas validas y ausencia de contradicciones internas. Si falla, detiene generacion o degrada solo secciones afectadas.

### H5-TP-009 - Tareas y aceptacion unica

`tasks.md` contiene tareas implementables y una sola ultima tarea de validacion y aceptacion integral.

### H5-TP-010 - Trazabilidad

Requisitos, decisiones, tareas y pruebas se enlazan entre si y con evidencia.

### H5-TP-011 - Validacion de citas

Citas existentes pasan; citas inexistentes, duplicadas o no usadas generan issue.

### H5-TP-012 - Validacion estructural

Detecta documentos faltantes, secciones ausentes, IDs duplicados y requisitos sin criterios.

### H5-TP-013 - Rutas y no sobrescritura

Valida slug seguro, salida bajo ruta permitida, directorio existente sin `--overwrite` y nombres predecibles.

### H5-TP-014 - Observabilidad

Etapas, conteos, advertencias, limites y errores esperados se reportan sin traceback.

### H5-TP-015 - CLI argumentos y codigos

Help en espanol, argumentos invalidos codigo 2, errores operativos codigo 1, exitos codigo 0.

### H5-TP-016 - Modo sin sintesis asistida

Genera draft conservador, marca secciones inciertas y mantiene estructura valida.

### H5-TP-017 - Limites de evidencia

Cuando se alcanza `top-k`, presupuesto de contexto o limite de componentes, la spec lo declara.

### H5-TP-018 - Sintesis fake y validacion de salida

Salida del fake con citas validas pasa; salida con citas inventadas se rechaza o degrada.

### H5-TP-019 - Golden Markdown

Golden files no tienen rutas personales, ordenan fuentes de forma canonica y son estables con clock fake.

### H5-TP-020 - Validacion integral de spec piloto

La spec piloto se genera, pasa Review, pasa `spec validate`, conserva trazabilidad y queda lista para revision humana documentada en la ultima tarea.

## 7. Pruebas de integracion

### INT-H5-01 - Crear spec desde corpus completo sintetico

Ejecuta ingesta, indexacion fake o keyword, analyze H4 y `spec create` sobre un requerimiento concreto.

### INT-H5-02 - Spec con impacto PB-Oracle

Genera componentes afectados cruzando PowerBuilder y Oracle con evidencia de relaciones H4.

### INT-H5-03 - Evidencia insuficiente

Genera spec parcial con preguntas abiertas, sin inventar reglas ni componentes.

### INT-H5-04 - H4 no disponible

Si no hay catalogo H4, advierte y genera solo evidencia RAG cuando sea posible.

### INT-H5-05 - Sin sintesis asistida real

`spec create --no-llm` completa con salida util y validable.

### INT-H5-06 - Sintesis fake

`spec create` con fake produce contenido sintetizado, citas validas y salida determinista.

### INT-H5-07 - Validacion de spec editada

`spec validate` detecta roturas introducidas manualmente en IDs, secciones y citas.

### INT-H5-08 - Escritura segura

No sobrescribe carpeta existente; `--overwrite` funciona solo en ruta validada.

### INT-H5-09 - Registro de artifact

Si se reutiliza `generated_artifacts`, registra tipo, plantilla, parametros y fuentes sin migracion innecesaria.

### INT-H5-10 - Sin red externa

La suite con fakes no intenta internet ni servicios cloud.

## 8. Pruebas CLI

- `barbarion spec --help`;
- `barbarion spec create --help`;
- `barbarion spec validate --help`;
- `barbarion spec create "requerimiento" --name caso-piloto --mode keyword --no-llm`;
- `barbarion spec create "requerimiento" --mode hybrid --depth 2`;
- `barbarion spec create "requerimiento" --output output/specs/caso`;
- `barbarion spec create "requerimiento" --overwrite`;
- `barbarion spec validate specs/caso-piloto`;
- `barbarion spec validate specs/caso-piloto --format json`;
- requerimiento vacio;
- profundidad invalida;
- modo invalido;
- ruta existente sin overwrite;
- spec con citas rotas;
- sintesis asistida no disponible;
- base sin ingesta;
- base sin catalogo H4.

## 9. Golden files

Golden files minimos:

- `requirements-basic.md`;
- `design-basic.md`;
- `tasks-basic.md`;
- `test-plan-basic.md`;
- `requirements-insufficient-evidence.md`;
- `design-cross-stack.md`;
- `tasks-acceptance-single-final-task.md`;
- `validation-errors.json`.

Reglas:

- fechas fijadas con clock fake;
- IDs y fuentes ordenados de forma canonica;
- fake determinista de sintesis;
- Mermaid sintacticamente simple;
- sin rutas personales;
- secciones obligatorias siempre presentes.

## 10. Casos negativos

| Caso | Esperado |
|---|---|
| requerimiento vacio | codigo 2 y mensaje accionable |
| nombre de spec invalido | slug seguro o codigo 2 |
| carpeta existente sin overwrite | codigo 1, no modifica archivos |
| DB sin inicializar | sugerir `barbarion doctor` |
| corpus no ingerido | sugerir `barbarion ingest` |
| indice RAG no disponible | sugerir `barbarion index` o modo keyword |
| H4 sin analyze | advertir y sugerir `barbarion analyze` |
| sintesis asistida no disponible | salida estructurada basada en evidencia o mensaje accionable |
| citas inventadas por sintesis asistida | falla Review/validacion o degrada contenido |
| Review con tarea sin requisito | falla antes de render o degrada seccion afectada |
| Review con prueba sin requisito | falla antes de render o degrada seccion afectada |
| Review con contradiccion interna | falla antes de render con issue accionable |
| referencias ambiguas | quedan `por_confirmar`, no resueltas silenciosamente |
| evidencia insuficiente | spec parcial con vacios y preguntas |
| interrupcion | codigo 130 y no deja carpeta parcial como valida |

## 11. Pruebas de regresion

La validacion final debe ejecutar:

- suite H1 de configuracion, doctor y CLI base;
- suite H2 de ingesta, chunking e incrementalidad;
- suite H3 de index, search, ask, citas y benchmark donde aplique;
- suite H4 de analyze, inventory, describe e impact;
- smoke test instalado.

H5 no debe cambiar comportamiento existente de `ask`, `search`, `analyze`, `inventory`, `describe` ni `impact`.

## 12. Pruebas de rendimiento

Mediciones iniciales:

1. `spec create --no-llm` con modo keyword;
2. `spec create` con fake de sintesis;
3. recuperacion H3 con `top-k` default;
4. consulta H4 con profundidad 1;
5. Review de `SpecDraft`;
6. validacion de spec generada;
7. escritura de cuatro documentos.

Metricas:

- duracion total;
- duracion por etapa;
- fuentes recuperadas;
- fuentes usadas;
- componentes afectados;
- requisitos generados;
- tareas generadas;
- preguntas abiertas;
- limites alcanzados.

No se fija umbral duro sin baseline; H5-T11 registra medicion y criterio relativo para futuras iteraciones.

## 13. Evaluacion de calidad de la spec piloto

Para la spec piloto se debe revisar:

- claridad del objetivo;
- alcance y fuera de alcance;
- requisitos con criterios verificables;
- diseno consistente con evidencia;
- tareas pequenas e implementables;
- plan de pruebas accionable;
- trazabilidad completa;
- vacios y preguntas abiertas utiles;
- ausencia de afirmaciones sin fuente;
- utilidad para iniciar desarrollo sin rehacer todo el analisis.

Metricas iniciales:

- requisitos con criterio de aceptacion / requisitos totales;
- conclusiones factuales con fuente / conclusiones factuales totales;
- tareas trazadas a requisitos / tareas totales;
- pruebas trazadas a requisitos / pruebas totales;
- preguntas abiertas registradas;
- hallazgos corregidos por revision humana.

## 14. Validacion manual

La ultima tarea debe pedir revision humana de:

- los cuatro documentos generados;
- fuentes y citas;
- componentes afectados;
- reglas existentes propuestas;
- riesgos, supuestos y vacios;
- preguntas abiertas;
- accionabilidad para iniciar implementacion;
- falsos positivos o inferencias excesivas.

La evidencia se registra en `specs/H5-SpecMode/acceptance.md` solo durante H5-T11.

## 15. Matriz requisito-prueba

| Requisito | Pruebas principales |
|---|---|
| H5-RF-001 | TP-001, TP-015, CLI |
| H5-RF-002 | TP-002, TP-016 |
| H5-RF-003 | TP-003, TP-004, TP-017, INT-H5-01 |
| H5-RF-004 | TP-004, TP-005, INT-H5-02 |
| H5-RF-005 | TP-006, TP-018 |
| H5-RF-006 | TP-007, TP-008, TP-009, TP-019, golden files |
| H5-RF-007 | TP-010, TP-011 |
| H5-RF-008 | TP-008, TP-011, TP-012, INT-H5-07 |
| H5-RF-009 | TP-013, TP-019, INT-H5-08 |
| H5-RF-010 | TP-014, TP-015 |
| H5-RF-011 | INT-H5-01, calidad, validacion manual |
| H5-RNF-001 | INT-H5-10 |
| H5-RNF-002 | TP-006, TP-008, TP-010, TP-011 |
| H5-RNF-003 | TP-013, INT-H5-08 |
| H5-RNF-004 | TP-019, golden files |
| H5-RNF-005 | TP-016, INT-H5-05, INT-H5-06 |
| H5-RNF-006 | smoke Windows/Python 3.12 |
| H5-RNF-007 | revision estructural/imports |
| H5-RNF-008 | scan de fixtures/specs/reportes |
| H5-RNF-009 | regresion H1-H4 |
| H5-RNF-010 | TP-017, rendimiento |

## 16. Evidencia esperada para aceptacion

- comandos ejecutados;
- suite completa y duracion;
- smoke test instalado;
- spec piloto generada;
- resultado de Review automatico;
- salida de `spec validate`;
- conteos de requisitos, tareas, pruebas y fuentes;
- lista de preguntas abiertas;
- evidencia de modo `--no-llm`;
- evidencia con fake de sintesis;
- regresion H1-H4;
- scan de datos sensibles;
- revision humana;
- limitaciones conocidas;
- decision final: aceptado o pendiente de feedback.

## 17. Criterios para declarar H5 listo para aceptacion

- todos los Must tienen pruebas pasando;
- `spec create` genera los cuatro documentos sin sobrescribir por defecto;
- Review verifica `SpecDraft` antes de Markdown y detiene o degrada secciones afectadas;
- `spec validate` detecta problemas estructurales y de citas;
- cada conclusion factual tiene evidencia o queda marcada como supuesto/por confirmar;
- componentes afectados no se declaran solo por similitud semantica;
- `tasks.md` concentra aceptacion integral en una unica ultima tarea;
- modo `--no-llm` es util y testeado;
- fakes permiten suite normal sin Ollama real;
- golden files son estables;
- no hay codigo generado, agentes, API HTTP, UI, Qdrant ni base de grafos;
- no hay secretos, rutas personales ni datos sensibles en fixtures/reportes/spec piloto;
- suite completa no presenta regresiones H1-H4;
- la spec piloto es revisada por una persona y el resultado queda documentado.
