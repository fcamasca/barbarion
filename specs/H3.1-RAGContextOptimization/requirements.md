# H3.1 - Optimizacion de contexto RAG: Requisitos

## 1. Proposito

H3.1 debe hacer medible y optimizable el contexto que Barbarion entrega al LLM
sin degradar recuperacion, evidencia, trazabilidad, citas ni calidad funcional.
La evolucion parte del consumo real observado durante H1.2: una consulta reporto
`10,198` tokens de entrada Anthropic frente a una estimacion local de `6,190`.
Ese valor es una observacion valida, no un defecto demostrado ni un objetivo de
reduccion por si mismo.

H1.2 permanece cerrado. H3.1 actua sobre contratos H3 independientes del
proveedor y comienza con instrumentacion y baseline antes de optimizar.

## 2. Alcance

### Incluido

- reconstruccion medible de retrieval, seleccion, contexto y prompt de `ask`;
- desglose estructural de instrucciones, pregunta, metadata, evidencia y formato;
- distincion entre caracteres, estimaciones locales y uso real del proveedor;
- diagnostico de duplicados exactos, redundancia y solapamiento parcial;
- presupuesto configurable para el input completo controlado por Barbarion;
- politicas deterministas y conservadoras de seleccion de evidencia;
- comparacion reproducible antes/despues sobre corpus sintetico o publico;
- compatibilidad con Ollama, Anthropic, `--no-llm` y evidencia insuficiente;
- observabilidad segura, CLI y documentacion operativa necesarias;
- evaluacion de retrieval, seleccion, citas y calidad funcional.

### Excluido

- cambios dentro de H1.2 o de los adaptadores Anthropic/Ollama salvo consumo de
  contratos de observabilidad ya existentes;
- nuevos proveedores, routing, fallback o plataforma multi-LLM;
- cambio de embeddings, vector store, chunking H2 o persistencia del corpus;
- reranker neuronal, framework RAG externo o servicio remoto de evaluacion;
- resumen generativo de chunks antes de responder;
- fijar un objetivo universal de tokens sin baseline;
- persistir prompts, respuestas, preguntas en claro o contenido de fuentes;
- benchmarks, ejemplos o fixtures con informacion privada o propietaria;
- `acceptance.md` durante la fase de especificacion.

## 3. Evidencia de partida

- `SearchService` recupera hasta `candidate_k` por canal y entrega como maximo
  `top_k` despues de ranking o fusion.
- El modo hibrido combina por `chunk_id`, normaliza scores vector/keyword y usa
  pesos configurables; no existe un reranker separado.
- `AskService` antepone evidencia estructurada H4.1, agrega chunks H3 sin repetir
  `chunk_id` y vuelve a limitar a `top_k`.
- `ContextBuilder` aplica threshold, deduplicacion exacta por `chunk_id` o
  prefijo de `content_sha256`, orden documental estable, limite por chunk y
  presupuesto global estimado.
- El estimador local vigente es `ceil(caracteres / 4)`.
- `context_token_budget=6000` limita el contexto renderizado, no el prompt
  completo ni los tokens reales de un tokenizer de proveedor.
- `PromptBuilder` agrega instrucciones, IDs permitidos, pregunta, contexto y
  formato de salida. Un intento de reparacion vuelve a enviar pregunta y contexto
  e incorpora la respuesta rechazada.
- H1.2 conservo para la ejecucion real solo `prompt_tokens_est_local=6,190`,
  `usage.input_tokens=10,198` y `usage.output_tokens=529`; no existe desglose
  historico suficiente para atribuir exactamente los `10,198` por componente.

## 4. Convenciones

- **Must:** obligatorio para aceptar H3.1.
- **Should:** requerido salvo evidencia documentada que justifique diferirlo.
- **Metrica estructural:** calculada localmente sin tokenizer ni proveedor.
- **Estimacion local:** aproximacion etiquetada, nunca presentada como uso real.
- **Uso real:** contador retornado por el proveedor para una solicitud completada.
- **Baseline:** medicion congelada del comportamiento anterior a optimizaciones.
- **Evidencia seleccionada:** fuentes que entran al contexto final.
- **Evidencia citada:** subconjunto referenciado por una respuesta valida.

## 5. Requisitos funcionales

### H3.1-REQ-001 - Baseline antes de optimizar (Must)

H3.1 debe capturar una baseline reproducible del pipeline vigente antes de
activar cualquier politica de reduccion.

Criterios:

- usa configuracion, version de dataset y version de algoritmo identificables;
- registra retrieval, seleccion, contexto, prompt, citas y resultado funcional;
- puede ejecutarse sin proveedor remoto y sin red;
- ninguna optimizacion se habilita antes de aprobar el reporte baseline;
- los `10,198` historicos se conservan como observacion, no como fixture fingida.

### H3.1-REQ-002 - Desglose del input controlado (Must)

Barbarion debe medir por solicitud los componentes que controla:

- instrucciones base;
- pregunta;
- lista de IDs y reglas de citacion;
- metadata y encabezados de fuentes;
- contenido de evidencias;
- plantilla/formato de salida;
- otros componentes explicitos que incorpore el pipeline.

Cada componente expone como minimo caracteres, bytes UTF-8 y estimacion local.
La suma debe reconciliar exactamente caracteres y bytes con el prompt enviado.

### H3.1-REQ-003 - Taxonomia de tokens (Must)

- los contadores reales se etiquetan `provider_input_tokens`,
  `provider_output_tokens` y `provider_total_tokens`;
- las estimaciones incluyen metodo/version y el sufijo `_est_local`;
- las metricas estructurales no se denominan tokens;
- `null` permanece `null`; no se convierte en cero ni se infiere;
- una diferencia estimacion/real se reporta, no se corrige retroactivamente;
- generacion y reparacion se miden como solicitudes distintas y como total de run.

### H3.1-REQ-004 - Observabilidad segura (Must)

Las mediciones deben estar disponibles en memoria, debug y reportes de benchmark
sin persistir contenido sensible.

- logs y SQLite no guardan pregunta, prompt, respuesta ni contenido de chunks;
- los registros persistibles usan conteos, razones, hashes no reversibles y
  versiones de configuracion/dataset;
- `--debug` conserva la politica vigente para contenido efimero explicito;
- Ollama, Anthropic y `--no-llm` no requieren capacidades nuevas de red.

### H3.1-REQ-005 - Diagnostico de redundancia (Must)

La instrumentacion debe distinguir:

- duplicado de `chunk_id`;
- contenido exactamente duplicado;
- solapamiento parcial entre chunks del mismo documento;
- metadata repetida por fuente;
- evidencia recuperada, seleccionada pero no citada.

Los umbrales y metodos deben ser deterministas, explicables y probados. Una
coincidencia aproximada es diagnostico, no autorizacion automatica para eliminar
evidencia.

La redundancia lexical aproximada entre documentos distintos es **Should** y,
si se evalua, comienza exclusivamente como `report-only`. No es requisito de
aceptacion construir un detector general de similitud textual.

### H3.1-REQ-006 - Trazabilidad de seleccion (Must)

Cada candidato debe terminar con una decision observable: seleccionado,
truncado u omitido, junto con una razon estable como threshold, duplicado exacto,
solapamiento, limite por fuente, presupuesto o top-k. La fuente seleccionada
conserva `chunk_id`, archivo, lineas/paginas, scores y procedencia estructurada.

### H3.1-REQ-007 - Presupuesto provider-agnostic del input (Must)

Debe existir un presupuesto configurable aplicado al input completo construido
por Barbarion, no solo al contenido de chunks.

- se reserva primero el costo local estimado de instrucciones, pregunta,
  metadata obligatoria y formato;
- el remanente se asigna a evidencia;
- se conserva compatibilidad con `context_token_budget` mediante migracion o
  precedencia documentada;
- el presupuesto usa un estimador local intercambiable, no APIs de proveedores;
- configuracion invalida falla temprano y muestra valores efectivos;
- no se promete que el presupuesto estimado iguale tokens reales.

### H3.1-REQ-008 - Seleccion conservadora de evidencia (Must)

La politica optimizada debe priorizar relevancia antes que orden de documento y
evitar gastar presupuesto en duplicados u overlap demostrable. Debe ser
determinista y permitir comparacion con la politica baseline. No puede eliminar
la unica evidencia de un hecho esperado solo para reducir tamano. Cobertura y
diversidad se miden en el benchmark, pero no forman parte del algoritmo inicial
salvo que evidencia posterior justifique una evolucion.

### H3.1-REQ-009 - Retrieval y ranking sin regresion (Must)

- semantic, keyword e hybrid mantienen contratos y filtros;
- `candidate_k`, `top_k`, threshold y pesos siguen siendo configurables;
- se documenta que la fusion hibrida vigente es ranking, no cross-encoder;
- H3.1 mide candidatos por canal, fusionados, estructurados, finales y omitidos;
- cualquier cambio de orden o seleccion debe quedar cubierto por benchmark.

### H3.1-REQ-010 - Citas y evidencia insuficiente (Must)

- IDs de fuente permanecen consecutivos y validables;
- rangos y contenido citado corresponden a la evidencia realmente enviada;
- reduccion o truncado no deja citas huerfanas;
- si el presupuesto no admite evidencia suficiente, el sistema declara
  evidencia insuficiente sin llamar al LLM cuando corresponda;
- la reparacion de citas respeta el mismo presupuesto y se mide por separado.

### H3.1-REQ-011 - Benchmark publicable (Must)

El benchmark debe usar exclusivamente corpus sintetico creado para Barbarion o
fuentes publicas con licencia/procedencia documentada. Debe incluir:

- preguntas literales, semanticas, multi-fuente, ambiguas e insuficientes;
- chunks con overlap controlado, duplicados y distractores;
- fuentes Oracle/PLSQL, PowerBuilder y documentales sinteticas;
- expected chunks/facts/citations versionados;
- configuracion baseline y optimizada reproducibles;
- ejecucion sin LLM obligatoria y generacion con fake deterministico;
- proveedores reales solo como validacion manual opt-in, nunca requisito normal.

### H3.1-REQ-012 - Metricas comparables (Must)

Por caso y agregadas se deben reportar, cuando apliquen:

- recall@5, recall@10 y MRR de retrieval;
- recall de evidencia seleccionada y cobertura de hechos esperados;
- fuentes recuperadas/seleccionadas/citadas;
- precision y recall de citas, citas invalidas y tasa de reparacion;
- caracteres/bytes/estimacion local por componente y total;
- uso real del proveedor y cobertura de esa metrica;
- duplicado exacto, overlap, evidencia no citada y, como metrica Should
  `report-only`, redundancia lexical aproximada;
- truncamientos, omisiones y razones;
- latencia de retrieval, seleccion, contexto y LLM;
- variacion baseline/optimizada, sin declarar mejora solo por reducir tamano.

### H3.1-REQ-013 - Comparacion y puertas de calidad (Must)

La aceptacion debe definir las puertas a partir de la baseline aprobada. Como
minimo, la configuracion optimizada no puede empeorar los criterios H3 vigentes
de retrieval, debe mantener citas validas y no reducir cobertura funcional de
los casos Must. Una reduccion de input solo se acepta si pasa esas puertas.

### H3.1-REQ-014 - Compatibilidad operativa (Must)

- configuraciones existentes siguen cargando con comportamiento documentado;
- Ollama y Anthropic reciben el mismo prompt para igual pregunta/configuracion;
- `--no-llm` produce contexto y metricas sin crear proveedor ni requerir key;
- evidencia insuficiente no llama al LLM;
- formatos text, JSON y Markdown conservan compatibilidad salvo campos aditivos;
- Windows y Linux mantienen salida UTF-8 conforme a contratos vigentes.

### H3.1-REQ-015 - Documentacion y decision final (Must)

La documentacion debe explicar fronteras de presupuesto, significado de cada
metrica, limitaciones del estimador, como reproducir benchmark y como comparar
runs. `acceptance.md` se crea solo en la ultima tarea con evidencia real.

## 6. Requisitos no funcionales

### H3.1-NFR-001 - Privacidad

Ningun artefacto versionado o persistido contiene informacion privada. Una
prueba automatica inspecciona fixtures, reportes y persistencia generada.

### H3.1-NFR-002 - Determinismo

Con dataset, configuracion y fakes iguales, seleccion, razones y metricas
estructurales son identicas entre ejecuciones.

### H3.1-NFR-003 - Rendimiento

La instrumentacion y deteccion de overlap deben operar sobre el conjunto acotado
de candidatos de una consulta y evitar comparaciones contra todo el corpus.

### H3.1-NFR-004 - Mantenibilidad

Se reutilizan `SearchService`, `ContextBuilder`, `PromptBuilder`,
`CitationValidator`, `AnswerResult` y puertos existentes. Una abstraccion nueva
requiere una frontera medible que esos contratos no puedan expresar.

### H3.1-NFR-005 - Reproducibilidad

El benchmark se ejecuta con un comando documentado, sin internet, secretos,
Ollama o Anthropic obligatorios y produce JSON/Markdown comparables.

### H3.1-NFR-006 - Honestidad metrica

Toda metrica documenta unidad, fuente, disponibilidad y limitacion. No se
mezclan estimaciones locales con contadores reales ni se inventan costos.

## 7. Criterio de listo para implementacion

H3.1 esta listo para implementacion cuando los requisitos Must tienen decisiones,
tareas y pruebas trazadas; la composicion actual esta documentada desde codigo;
el benchmark propuesto es publicable; las puertas de calidad se derivan de una
baseline futura y no de un numero arbitrario; y no existe `acceptance.md`.
