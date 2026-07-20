# H1.1 - Gestion y Evaluacion de Modelos Locales: Requisitos

## 1. Proposito

H1.1 incorpora capacidades locales para descubrir, instalar, seleccionar,
validar y comparar los modelos LLM generativos disponibles en Ollama. El hito
permite elegir el modelo de `[llm].model` con evidencia reproducible, sin
modificar el pipeline RAG, la arquitectura del conocimiento, la ingenieria
inversa ni Spec Mode.

La evaluacion usa un corpus y casos sinteticos versionados, congela el contexto
recuperado para todos los modelos y reutiliza los contratos vigentes de prompt,
respuesta, citas y validacion. No evalua ni cambia el modelo de embeddings.

## 2. Alcance

### Incluido

- descubrimiento de modelos instalados mediante Ollama local;
- consulta de metadata disponible sin asumir una familia concreta;
- instalacion explicita de modelos por identificador aceptado por Ollama;
- seleccion segura del LLM generativo activo en `[llm].model`;
- validacion de existencia y generacion minima del modelo seleccionado;
- comandos CLI agrupados bajo `barbarion models`;
- dataset sintetico versionado para evaluar respuestas RAG;
- benchmark reproducible de dos o mas modelos instalados;
- metricas deterministas de calidad, instrucciones, groundedness, contexto,
  citas, validador, latencia y tokens cuando Ollama los informe;
- reporte comparativo Markdown y resultado JSON inspeccionable;
- fakes deterministas para la suite normal y prueba manual opcional con Ollama.

### Excluido

- proveedores, modelos o evaluadores cloud;
- descarga desde registries distintos de Ollama;
- entrenamiento, fine-tuning, cuantizacion o conversion de modelos;
- administracion del proceso o instalacion de Ollama;
- eliminacion automatica de modelos;
- seleccion o comparacion de modelos de embeddings;
- cambio de chunking, retrieval, ranking, ensamblado de contexto o prompts RAG;
- cambio de extractores H4/H4.1 o generadores H5;
- benchmark con codigo, prompts, contexto o datos reales;
- ranking universal o recomendacion independiente del hardware evaluado;
- UI, API HTTP, telemetria remota, plugins o multiples proveedores.

## 3. Actores

- **Desarrollador:** descubre, instala, valida y selecciona un modelo local.
- **Lider tecnico:** compara resultados y revisa limites antes de adoptar un
  modelo.
- **Validador humano:** revisa muestras y confirma que la recomendacion es util
  para el entorno evaluado.

## 4. Supuestos y dependencias

- MVP v0.6.0, H1, H2, H3, H4, H4.1 y H5 estan completados.
- Ollama expone su API local configurada en `ollama_url`.
- `[llm].model` sigue siendo la fuente de verdad del modelo generativo activo.
- El modelo de embeddings, el indice sqlite-vec y SQLite no cambian en H1.1.
- El benchmark usa el mismo contexto congelado para cada modelo de una corrida.
- La suite automatica no requiere Ollama, red ni modelos reales.
- Los nombres y capacidades concretas dependen de Ollama y no se codifican en
  reglas de negocio.
- Los fixtures y reportes versionables contienen solo informacion sintetica.

## 5. Convenciones

- **Must:** obligatorio para aceptar H1.1.
- **Should:** requerido salvo limitacion documentada.
- Mensajes CLI, errores y documentacion de usuario en espanol.
- Identificadores, claves TOML, JSON y APIs internas pueden estar en ingles.
- `modelo activo` significa exclusivamente el valor efectivo de `[llm].model`.
- `instalado` significa reportado por la instancia Ollama configurada.
- `available` significa que la instancia Ollama configurada responde.
- `installed` significa que Ollama reporta el nombre exacto localmente.
- `generation_ready` significa que el modelo completa la sonda minima; no
  acredita citas, groundedness ni adecuacion funcional.
- `benchmark_eligible` significa que el modelo esta `generation_ready` y puede
  participar en la comparacion; el benchmark determina su adecuacion funcional.
- Una metrica no disponible se representa como `null`/`no disponible`, nunca
  como cero.
- Ningun score sustituye la revision humana ni se presenta como verdad universal.

## 6. Requisitos funcionales

### H1.1-RF-001 - Descubrir modelos instalados

**Descripcion:** Consultar la instancia Ollama configurada y mostrar los modelos
locales disponibles.

**Prioridad:** Must.

**Criterios de aceptacion:**

- `barbarion models list` consulta el endpoint local configurado;
- muestra nombre/tag exacto y, cuando Ollama lo informe, tamano, fecha y metadata
  util sin depender de campos opcionales;
- identifica el modelo LLM activo y si esta instalado;
- soporta `--format text|json` con orden estable por nombre;
- una respuesta con campos desconocidos no rompe el comando;
- Ollama no disponible produce un error accionable sin traceback.

**Diseno:** H1.1-DD-001, H1.1-DD-003.  
**Pruebas:** H1.1-TP-001, H1.1-TP-002.  
**Tareas:** H1.1-T01, H1.1-T03.

### H1.1-RF-002 - Inspeccionar un modelo

**Descripcion:** Consultar la metadata que Ollama expone para un modelo local
sin inferir capacidades por su nombre.

**Prioridad:** Should.

**Criterios de aceptacion:**

- `barbarion models show <modelo>` exige un nombre exacto no vacio;
- presenta solo metadata devuelta por Ollama y marca campos ausentes;
- no imprime blobs, plantillas completas ni informacion potencialmente extensa
  por defecto;
- `--format json` conserva los campos normalizados y una seccion acotada de
  metadata adicional segura;
- un modelo ausente se diferencia de Ollama no disponible.

**Diseno:** H1.1-DD-001, H1.1-DD-003.  
**Pruebas:** H1.1-TP-003.  
**Tareas:** H1.1-T01, H1.1-T03.

### H1.1-RF-003 - Instalar un modelo

**Descripcion:** Solicitar explicitamente a Ollama la instalacion de un modelo
por el identificador que Ollama acepta, sin atribuirle adecuacion funcional.

**Prioridad:** Must.

**Criterios de aceptacion:**

- `barbarion models install <modelo>` usa solamente la instancia Ollama local;
- `--dry-run` valida conectividad y estado instalado, informa si solicitaría el
  pull y no inicia descarga ni cambia configuracion;
- la operacion no se inicia desde `list`, `show`, `validate`, `select` ni
  `benchmark`;
- muestra progreso acotado cuando Ollama lo proporciona y soporta Ctrl+C;
- valida el nombre como dato, sin construir comandos shell;
- verifica al final que el modelo aparezca instalado;
- reintentar una instalacion ya satisfecha es seguro e informa el estado;
- errores de espacio, red de Ollama, timeout o respuesta invalida son
  accionables y no cambian la configuracion activa.
- si el usuario interrumpe, CLI informa que Barbarion dejo de esperar pero
  Ollama podria continuar la descarga localmente; el codigo 130 no afirma que el
  modelo haya quedado ausente.

**Diseno:** H1.1-DD-001, H1.1-DD-004.  
**Pruebas:** H1.1-TP-004, H1.1-TP-005.  
**Tareas:** H1.1-T01, H1.1-T04.

### H1.1-RF-004 - Seleccionar el modelo activo

**Descripcion:** Cambiar de forma segura el valor de `[llm].model` en el TOML
activo, conservando la configuracion existente.

**Prioridad:** Must.

**Criterios de aceptacion:**

- `barbarion models select <modelo>` exige que el modelo este instalado y pase
  validacion antes de escribir;
- actualiza solamente la asignacion unica `model` de la seccion `[llm]` del
  archivo de configuracion efectivo;
- usa escritura temporal y reemplazo atomico en el mismo directorio;
- vuelve a cargar y validar el TOML antes del reemplazo;
- preserva comentarios, orden, encoding UTF-8 y las demas secciones;
- `--dry-run` muestra archivo y cambio sin escribir ni invocar generacion;
- configuracion por defaults, seccion ausente, asignacion duplicada o archivo no
  escribible producen instrucciones accionables sin crear un segundo origen;
- una falla deja intacto el archivo original;
- la seleccion no instala modelos implicitamente ni cambia embeddings.

**Diseno:** H1.1-DD-002, H1.1-DD-005.  
**Pruebas:** H1.1-TP-006, H1.1-TP-007, H1.1-TP-008.  
**Tareas:** H1.1-T02, H1.1-T06.

### H1.1-RF-005 - Validar disponibilidad y funcionamiento

**Descripcion:** Comprobar que un modelo instalado puede atender la generacion
minima requerida por Barbarion.

**Prioridad:** Must.

**Criterios de aceptacion:**

- `barbarion models validate [<modelo>]` usa el modelo indicado o el activo;
- valida conectividad, instalacion y una generacion sintetica minima con timeout;
- la sonda no incluye corpus, prompt real ni contexto del usuario;
- la respuesta se valida por un marcador determinista, no por conocimiento;
- informa por separado `available`, `installed`, `generation_ready` y
  `benchmark_eligible`;
- soporta `--format text|json` y no muestra razonamiento interno del modelo;
- `doctor` puede reutilizar el chequeo de existencia del activo sin convertir
  una sonda generativa costosa en requisito del diagnostico base.

**Diseno:** H1.1-DD-003, H1.1-DD-006.  
**Pruebas:** H1.1-TP-009, H1.1-TP-010.  
**Tareas:** H1.1-T05.

### H1.1-RF-006 - Dataset sintetico versionado

**Descripcion:** Definir un conjunto reproducible de casos que mida capacidades
relevantes para respuestas RAG sin usar ningun dominio real.

**Prioridad:** Must.

**Criterios de aceptacion:**

- el dataset tiene version de esquema e identificador/hash estable;
- incluye al menos 8 casos repartidos entre respuesta factual, evidencia
  insuficiente, instrucciones de formato, ambiguedad y citas multiples;
- cada caso define pregunta, contexto sintetico numerado, hechos esperados,
  afirmaciones prohibidas, instrucciones verificables y citas permitidas;
- ningun caso depende de nombres funcionales, sistemas o datos reales;
- el loader rechaza IDs duplicados, citas inexistentes, rubricas vacias, claves
  desconocidas y pesos invalidos;
- los casos no contienen prompts productivos completos: usan el constructor
  vigente de Barbarion para formar la solicitud final.

**Diseno:** H1.1-DD-007, H1.1-DD-008.  
**Pruebas:** H1.1-TP-011, H1.1-TP-012.  
**Tareas:** H1.1-T07.

### H1.1-RF-007 - Ejecutar benchmark reproducible

**Descripcion:** Evaluar dos o mas modelos instalados bajo las mismas entradas y
condiciones registradas.

**Prioridad:** Must.

**Criterios de aceptacion:**

- `barbarion models benchmark --models <m1> <m2> [...]` exige al menos dos modelos
  instalado y no cambia el activo;
- valida todos los modelos antes de iniciar y no instala faltantes;
- ejecuta temperatura `0` y exactamente una generacion medida por caso/modelo
  en H1.1;
- usa exactamente la misma pregunta, contexto congelado y configuracion RAG por
  caso para todos los modelos de una corrida;
- rota de forma determinista el orden de modelos por caso para reducir sesgo
  termico y registra el orden real;
- cada salida pasa por el validador de citas/respuesta vigente;
- Ctrl+C escribe un resultado parcial simple marcado `interrupted`, sin
  reanudacion automatica ni presentarlo como comparacion completa;
- una falla de un modelo/caso queda registrada y no invalida resultados ya
  confirmados;
- `--dataset`, `--timeout` y `--output` se validan y acotan;
- no modifica SQLite de conocimiento ni los artefactos H2-H5.

**Diseno:** H1.1-DD-006, H1.1-DD-008, H1.1-DD-009.  
**Pruebas:** H1.1-TP-013, H1.1-TP-014, H1.1-TP-015.  
**Tareas:** H1.1-T08, H1.1-T09.

### H1.1-RF-008 - Calcular metricas objetivas

**Descripcion:** Calcular por caso y modelo metricas transparentes derivadas de
la rubrica sintetica y del resultado del pipeline.

**Prioridad:** Must.

**Criterios de aceptacion:**

- calidad de respuesta mide cobertura de hechos esperados y penaliza
  afirmaciones prohibidas mediante reglas declaradas por caso;
- cumplimiento mide instrucciones estructurales verificables declaradas;
- groundedness mide afirmaciones evaluables soportadas por el contexto y
  penaliza contradicciones conocidas, sin usar un LLM juez;
- uso de contexto mide referencias correctas a hechos y fragmentos necesarios;
- citas mide presencia, validez y cobertura usando IDs entregados;
- registra aceptacion/rechazo y diagnostics del validador existente;
- registra tiempo total y, si Ollama los informa, carga, prompt y generacion;
- registra `prompt_eval_count` y `eval_count` cuando existan, como consumo
  aproximado de tokens;
- campos ausentes son `null` y no afectan silenciosamente denominadores;
- formulas, pesos y redondeo estan versionados en el reporte;
- el validador tiene peso predominante en el score agregado; el reporte muestra
  componentes y fallas sin presentar el score como verdad ni sustituto de
  revision humana.

**Diseno:** H1.1-DD-010.  
**Pruebas:** H1.1-TP-016, H1.1-TP-017, H1.1-TP-018.  
**Tareas:** H1.1-T10.

### H1.1-RF-009 - Generar reporte comparativo

**Descripcion:** Producir artefactos locales que permitan comparar modelos y
seleccionar uno para el hardware y dataset evaluados.

**Prioridad:** Must.

**Criterios de aceptacion:**

- cada corrida crea por defecto
  `<output_dir>/model-benchmarks/<run-id>/model-benchmark.json` y
  `model-benchmark.md`; `--output` cambia el directorio padre;
- imprime en stdout un resumen comparativo y la ruta absoluta de artefactos;
- incluye version, fecha UTC, dataset/hash, modelos exactos, metadata Ollama,
  plataforma, opciones, contexto/hash, orden, fallas y metricas por caso;
- compara promedios y mediana de latencia; H1.1 no calcula percentil 95;
- destaca compromisos entre calidad, validacion, latencia y tokens;
- propone `candidato recomendado` solo si la corrida esta completa y explica la
  regla determinista; empates o datos insuficientes quedan explicitos;
- no cambia automaticamente el modelo activo;
- `run-id` combina fecha UTC y sufijo corto; una colision aborta sin sobrescribir
  y la salida debe quedar en un directorio permitido;
- no incluye prompts completos, contexto fuera del dataset ni rutas personales;
- el Markdown tiene estructura y orden estables.

**Diseno:** H1.1-DD-011, H1.1-DD-012.  
**Pruebas:** H1.1-TP-019, H1.1-TP-020.  
**Tareas:** H1.1-T11.

### H1.1-RF-010 - Observabilidad y errores

**Descripcion:** Hacer diagnosticables las operaciones de modelos sin exponer
contenido sensible.

**Prioridad:** Must.

**Criterios de aceptacion:**

- cada comando informa etapa, modelo, resultado y duracion relevante;
- errores esperados no muestran traceback y distinguen configuracion, Ollama,
  modelo ausente, incompatibilidad, timeout, escritura y dataset invalido;
- logs no vuelcan respuestas completas, prompts ni contexto por defecto;
- codigos de salida son `0` exito, `1` error operativo o benchmark incompleto,
  `2` argumentos/configuracion/dataset invalido y `130` interrupcion;
- JSON de salida mantiene codigos tecnicos estables.

**Diseno:** H1.1-DD-003, H1.1-DD-013.  
**Pruebas:** H1.1-TP-021, H1.1-TP-022.  
**Tareas:** H1.1-T03..H1.1-T11.

## 7. Requisitos no funcionales

### H1.1-RNF-001 - Operacion local y privacidad

Solo se permite filesystem local, SQLite vigente y la instancia Ollama
configurada. Barbarion no envia modelos, codigo, prompts ni contexto a servicios
externos. La descarga iniciada por `install` es responsabilidad de Ollama y es
la unica operacion que puede requerir acceso externo explicito.

### H1.1-RNF-002 - Compatibilidad

Configuraciones existentes siguen siendo validas; `[llm].model` conserva
significado y precedencia. Los comandos H1-H5 mantienen comportamiento y la
suite normal sigue funcionando sin Ollama.

### H1.1-RNF-003 - No modificar RAG ni conocimiento

H1.1 reutiliza constructores, validadores y contratos existentes. No cambia
retrieval, contexto, prompts productivos, tablas de conocimiento, embeddings,
ingenieria inversa ni Spec Mode.

### H1.1-RNF-004 - Reproducibilidad honesta

Cada corrida registra entradas, hashes, parametros, versiones y hardware
observable. La reproducibilidad significa mismas condiciones declaradas; no
promete texto identico entre versiones de Ollama, drivers o hardware.

### H1.1-RNF-005 - Seguridad de escritura

La seleccion y los reportes usan escritura atomica cuando corresponde, no
siguen rutas fuera del alcance permitido y no sobrescriben sin autorizacion.

### H1.1-RNF-006 - Extensibilidad simple

Nuevos modelos se incorporan por nombre desde Ollama y por datos del
dataset, sin clases, plugins ni ramas por familia de modelo.

### H1.1-RNF-007 - Rendimiento acotado

Casos, timeout, tamano de respuestas y cantidad de modelos tienen limites
tecnicos acotados por la implementacion. No hay repeticiones configurables ni
paralelismo en H1.1; la ejecucion secuencial reduce contencion y hace comparables
las mediciones. El limite superior no forma parte del contrato funcional.

### H1.1-RNF-008 - Determinismo documental

JSON y Markdown usan orden canonico, IDs estables, clock fake en tests y formulas
de score versionadas.

### H1.1-RNF-009 - Compatibilidad Windows y Python 3.12

La implementacion conserva Python `>=3.12,<3.13`, rutas portables y no depende de
scripts shell para invocar Ollama.

### H1.1-RNF-010 - Mantenibilidad

Se mantiene el monolito modular: casos de uso en `application`, modelos puros en
`domain`, HTTP Ollama y filesystem en `infrastructure`, y CLI como adaptador. No
se agrega framework de benchmarking ni abstraccion multiproveedor.

### H1.1-RNF-011 - Pruebas sin modelos reales

La suite normal usa un cliente Ollama fake, clock fake y respuestas controladas.
Las pruebas con Ollama real son manuales o marcadas y no bloquean la regresion.

### H1.1-RNF-012 - Trazabilidad de evaluacion

Todo score se rastrea al caso, regla, respuesta validada y evidencia sintetica.
Los fallos y valores no disponibles permanecen visibles.

## 8. Casos de uso

### CU-01 - Descubrir y validar

1. El usuario ejecuta `barbarion models list`.
2. Barbarion muestra modelos instalados e identifica el activo.
3. El usuario ejecuta `barbarion models validate`.
4. Barbarion valida el modelo activo con una entrada sintetica minima.

### CU-02 - Instalar y seleccionar

1. El usuario ejecuta `barbarion models install <modelo>`.
2. Ollama instala y Barbarion verifica la presencia local.
3. El usuario ejecuta `barbarion models select <modelo> --dry-run`.
4. Tras revisar, repite sin `--dry-run`; Barbarion valida y actualiza el TOML.

### CU-03 - Comparar modelos

1. El usuario ejecuta `barbarion models benchmark --models <m1> <m2>`.
2. Barbarion valida dataset, modelos y condiciones.
3. Ejecuta casos sinteticos con contexto identico y valida cada respuesta.
4. Genera JSON y Markdown con metricas, fallas, compromisos y candidato.
5. El usuario decide si ejecuta posteriormente `models select`.

## 9. Fuera de alcance

H1.1 no administra embeddings, no elimina modelos, no instala Ollama, no usa
cloud, no evalua datos reales, no modifica RAG/H2/H4/H4.1/H5 y no selecciona un
modelo automaticamente.

## 10. Riesgos

- las respuestas y telemetria de Ollama pueden variar entre versiones;
- caches, temperatura del hardware y carga local afectan latencia;
- reglas lexicales no capturan toda la calidad semantica;
- modelos pueden obedecer el formato pero producir afirmaciones sutilmente
  incorrectas;
- editar TOML preservando comentarios exige limitarse a una asignacion unica;
- nombres instalados pueden incluir tags o digests no previstos;
- un dataset sintetico pequeno puede no representar todos los usos reales;
- una descarga grande puede consumir tiempo, red y disco fuera de Barbarion.
- una unica ejecucion por caso no caracteriza variabilidad estadistica; las
  repeticiones quedan para una evolucion posterior.

## 11. Matriz inicial de trazabilidad

| Requisito | Diseno | Pruebas | Tareas |
|---|---|---|---|
| H1.1-RF-001 | DD-001, DD-003 | TP-001, TP-002 | T01, T03 |
| H1.1-RF-002 | DD-001, DD-003 | TP-003 | T01, T03 |
| H1.1-RF-003 | DD-001, DD-004 | TP-004, TP-005 | T01, T04 |
| H1.1-RF-004 | DD-002, DD-005 | TP-006..008 | T02, T06 |
| H1.1-RF-005 | DD-003, DD-006 | TP-009, TP-010 | T05 |
| H1.1-RF-006 | DD-007, DD-008 | TP-011, TP-012 | T07 |
| H1.1-RF-007 | DD-006, DD-008, DD-009 | TP-013..015 | T08, T09 |
| H1.1-RF-008 | DD-010 | TP-016..018 | T10 |
| H1.1-RF-009 | DD-011, DD-012 | TP-019, TP-020 | T11 |
| H1.1-RF-010 | DD-003, DD-013 | TP-021, TP-022 | T03..T11 |
