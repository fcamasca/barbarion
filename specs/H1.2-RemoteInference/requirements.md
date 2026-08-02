# H1.2 - Inferencia Remota con Anthropic: Requisitos

## 1. Proposito

H1.2 permite usar Anthropic Claude como backend remoto de generacion final sin
trasladar la construccion de conocimiento fuera de Barbarion. Ingesta,
inventario, embeddings, SQLite/sqlite-vec, busqueda keyword/semantica/hibrida,
ensamblado de contexto, reverse engineering y validacion de citas permanecen
locales y conservan sus contratos actuales.

H1.2 implementa inferencia remota mediante Anthropic como solucion concreta al
problema de rendimiento local. No establece que Anthropic sea el unico
proveedor remoto futuro; cualquier proveedor posterior requerira su propia
evolucion y una decision explicita de alcance.

La evolucion reutiliza `LlmProviderPort.generate(prompt, timeout_seconds)` y la
composicion existente. Ollama continua siendo el proveedor predeterminado y el
unico proveedor de embeddings y de administracion/benchmark de modelos H1.1.
Anthropic se incorpora solo como segundo backend de generacion, no como una
plataforma multiproveedor cloud.

## 2. Analisis CREAR

### Contexto

Barbarion es un monolito Python CLI-first. H3 construye localmente el contexto
RAG y entrega un prompt controlado a `LlmProviderPort`; H4 puede usar el mismo
puerto para una sintesis final opcional. Hoy la composicion concreta siempre
crea `OllamaLlmProvider`, aunque el puerto ya separa la aplicacion del adaptador.
H1.1 administra y evalua modelos instalados en Ollama mediante un contrato local
distinto, `LocalModelProvider`.

La dependencia exclusiva del hardware local puede impedir o degradar la
generacion, aun cuando el conocimiento local, retrieval y validacion funcionen.
H1.2 debe permitir que solo el prompt final se procese en Anthropic, haciendo
explicita esa salida de datos y sin convertir el resto del sistema en cloud.

### Rol

El diseno actua como arquitecto y mantenedor de Foundation. Debe introducir el
adaptador remoto mas pequeno posible, conservar los puertos y casos de uso
vigentes y proteger la frontera entre conocimiento local y generacion externa.
No redefine H2, H3, H4, H4.1 ni H5.

### Especificaciones

- `[llm].provider` acepta exactamente `ollama` o `anthropic`.
- `[llm].model` identifica el modelo del proveedor seleccionado.
- `ANTHROPIC_API_KEY` es el unico origen admitido para la credencial Anthropic.
- El adaptador usa la Messages API directa de Anthropic con endpoint y version
  controlados por Barbarion.
- El prompt construido por Barbarion se envia como un unico mensaje de usuario;
  no se agregan herramientas, memoria, retrieval remoto ni prompts alternativos.
- La respuesta textual vuelve al mismo validador de citas y al mismo flujo de
  reparacion existentes.
- Timeout, Ctrl+C, codigos de salida, formatos text/JSON/Markdown y `--no-llm`
  conservan su comportamiento publico.
- El benchmark y los comandos `barbarion models` de H1.1 siguen operando contra
  Ollama y no se convierten en administracion cloud.

### Accion

Definir configuracion compatible, adaptador HTTP Anthropic, seleccion concreta
en la raiz de composicion, errores tipados y pruebas de caracterizacion,
integracion y regresion. La implementacion posterior debe demostrar que el mismo
prompt y la misma salida validada funcionan con Ollama o Anthropic sin cambios en
los servicios RAG/reverse engineering.

### Restricciones

- No implementar OpenAI, Bedrock, Gemini, Groq, Vertex AI ni gateways.
- No crear plugins, registro dinamico, SDK multiproveedor, API HTTP propia ni
  arquitectura paralela.
- No enviar corpus completo, base SQLite, vectores, inventario ni artefactos; el
  unico egress productivo es la solicitud generativa construida por el flujo
  actual cuando `provider = "anthropic"`.
- No almacenar, imprimir, registrar, serializar ni aceptar la API key en TOML,
  argumentos CLI, SQLite, reportes o archivos de salida.
- No modificar retrieval, ranking, chunking, embeddings, prompts productivos,
  formato de respuesta, reparacion ni reglas del validador de citas.
- No agregar fallback automatico entre Anthropic y Ollama, retries ocultos,
  streaming, herramientas, batches, cache de prompts ni historial remoto.
- No crear `acceptance.md` durante la definicion de la spec.

## 3. Alcance

### Incluido

- seleccion explicita `ollama|anthropic` mediante `[llm].provider`;
- seleccion de modelo mediante `[llm].model`;
- limite configurable y acotado de salida para la Messages API;
- lectura exclusiva de `ANTHROPIC_API_KEY` desde el entorno del proceso;
- adaptador Anthropic que satisface `LlmProviderPort`;
- generacion y reparacion de citas de `ask` mediante el proveedor seleccionado;
- sintesis LLM opcional de `describe` e `impact` mediante el mismo proveedor,
  sin cambiar sus casos de uso;
- errores accionables para credencial, autenticacion, permisos, modelo,
  rate limit, sobrecarga, timeout, red, truncamiento y respuesta invalida;
- cancelacion por Ctrl+C sin reintento ni fallback automaticos;
- logs provider-neutral sin prompt, respuesta ni secreto;
- fakes HTTP y suite normal completamente offline;
- validacion manual opt-in con Anthropic usando solo datos sinteticos;
- regresion de H1-H5, H4.1 y H1.1.

### Excluido

- embeddings remotos o embeddings Anthropic;
- almacenamiento, retrieval, reranking o knowledge base cloud;
- soporte para un segundo proveedor cloud;
- API compatible con OpenAI o abstraccion universal de mensajes;
- administracion, listado, instalacion o descubrimiento de modelos Anthropic;
- benchmark comparativo Ollama-Anthropic o cambios al benchmark H1.1;
- streaming, tool use, vision, archivos, web search, MCP, prompt caching,
  batches o conversaciones multi-turn;
- rotacion, vault, helper, archivo `.env` o gestor de secretos;
- configuracion de endpoint/base URL Anthropic, proxy o version API por usuario;
- calculo o control de costos, cuotas o billing;
- fallback automatico a Ollama o a `--no-llm`;
- modificaciones funcionales a H2, H3, H4, H4.1 o H5.

## 4. Actores

- **Desarrollador:** elige proveedor/modelo y ejecuta consultas existentes.
- **Operador local:** provisiona `ANTHROPIC_API_KEY` fuera del repositorio y
  autoriza la salida del prompt al seleccionar Anthropic.
- **Lider tecnico o responsable de datos:** valida que el corpus y la politica
  del entorno permiten enviar el contexto seleccionado al proveedor remoto.
- **Validador humano:** revisa citas, utilidad y limites de una prueba sintetica
  real antes de aceptar H1.2.

## 5. Supuestos y dependencias

- Barbarion `0.6.0` y H1-H5, H4.1 y H1.1 estan completados.
- `LlmProviderPort` conserva `provider`, `model` y
  `generate(prompt, timeout_seconds) -> str`.
- Ollama continua disponible localmente para embeddings semanticos; seleccionar
  Anthropic no elimina esa dependencia para `index`, busqueda semantica o modo
  hibrido.
- El modo keyword y los flujos `--no-llm` pueden operar sin generacion remota.
- El usuario que selecciona Anthropic cuenta con autorizacion para enviar la
  pregunta, instrucciones y fragmentos de contexto que formen el prompt.
- La API directa de Anthropic acepta mensajes, modelo, `max_tokens` y
  temperatura mediante HTTPS.
- La suite automatica no dispone de API key real ni acceso a internet.
- Los nombres y disponibilidad de modelos Claude no se codifican como una lista
  cerrada; la API es la autoridad operacional.

## 6. Convenciones

- **Must:** obligatorio para aceptar H1.2.
- **Should:** requerido salvo limitacion documentada y aprobada.
- `proveedor de generacion` significa el valor efectivo de `[llm].provider`.
- `modelo generativo` significa el valor efectivo de `[llm].model` para ese
  proveedor.
- `local` describe construccion y persistencia del conocimiento; con Anthropic,
  el prompt final y la respuesta cruzan explicitamente la frontera de red.
- `sin LLM` significa que no se construye ninguna solicitud generativa ni se
  requiere credencial, aunque retrieval local pueda ejecutarse.
- La credencial se referencia solo por el nombre estable
  `ANTHROPIC_API_KEY`; su valor siempre se trata como secreto.
- Mensajes CLI, errores y documentacion de usuario se escriben en espanol.
- Identificadores de codigo, claves TOML y codigos tecnicos pueden permanecer en
  ingles.
- Un error remoto nunca implica fallback o reintento salvo accion posterior
  explicita del usuario.

## 7. Requisitos funcionales

### H1.2-RF-001 - Seleccionar proveedor y modelo

**Descripcion:** Resolver el backend generativo desde la configuracion efectiva
sin alterar la CLI ni los casos de uso.

**Prioridad:** Must.

**Criterios de aceptacion:**

- `[llm].provider` acepta exactamente `ollama` y `anthropic`;
- configuraciones existentes sin cambios continúan resolviendo `ollama`;
- `[llm].model` sigue siendo obligatorio, no vacio y es interpretado por el
  proveedor seleccionado;
- `[llm].timeout_seconds` y `[llm].temperature` conservan significado;
- `max_output_tokens` solo es interpretado cuando el proveedor efectivo es
  Anthropic, limita su salida y usa un default de 4096 si se omite;
- configurar explicitamente `max_output_tokens` con Ollama se rechaza con un
  mensaje accionable para no aceptar una propiedad silenciosamente inutil;
- `think` y `num_ctx` siguen aplicando solo a Ollama; si se configuran con
  Anthropic se rechaza la configuracion con un mensaje accionable, no se ignoran;
- un proveedor desconocido falla al cargar configuracion antes de cualquier red;
- `config show` muestra proveedor, modelo y limite no secreto, nunca la API key.

**Diseno:** H1.2-DD-002, H1.2-DD-004.  
**Pruebas:** H1.2-TP-001..004.  
**Tareas:** H1.2-T01, H1.2-T02.

### H1.2-RF-002 - Resolver credencial exclusivamente desde el entorno

**Descripcion:** Autenticar la API Anthropic sin introducir secretos en la
configuracion persistente.

**Prioridad:** Must.

**Criterios de aceptacion:**

- solo se consulta `ANTHROPIC_API_KEY` cuando el proveedor efectivo es
  Anthropic y se intenta generar;
- la carga de settings, `config show`, comandos locales y `--no-llm` no exigen
  que la variable exista;
- una variable ausente, vacia o solo con espacios produce un error operativo
  accionable antes de abrir una conexion;
- TOML rechaza claves `api_key`, `token`, `secret` o equivalentes no admitidas;
- la credencial no aparece en `repr`, excepciones, logs, debug, stdout, stderr,
  payloads de prueba persistidos ni artefactos;
- no se admite pasar la credencial por CLI ni por un archivo `.env` gestionado
  por Barbarion.

**Diseno:** H1.2-DD-003, H1.2-DD-004, H1.2-DD-011.  
**Pruebas:** H1.2-TP-005..007.  
**Tareas:** H1.2-T02, H1.2-T03, H1.2-T06.

### H1.2-RF-003 - Generar mediante Anthropic Messages API

**Descripcion:** Implementar un adaptador HTTP directo que satisfaga el puerto
LLM vigente y devuelva texto utilizable por el pipeline actual.

**Prioridad:** Must.

**Criterios de aceptacion:**

- envia un `POST` HTTPS exclusivamente al endpoint directo controlado por
  Barbarion para crear mensajes;
- usa headers `content-type`, `x-api-key` y `anthropic-version` sin exponer sus
  valores sensibles;
- envia el modelo configurado, el prompt como mensaje `user`, `max_tokens`,
  temperatura y `stream=false` o su equivalente no streaming;
- no envia herramientas, archivos, system prompt adicional, metadata de usuario
  ni campos beta;
- concatena en orden solo bloques de contenido textual reconocidos;
- rechaza cuerpo invalido, contenido textual vacio y truncamiento por limite de
  tokens con errores tipados;
- campos adicionales y bloques desconocidos no rompen el parser ni se imprimen;
- retorna `str` y no modifica `LlmProviderPort` ni el resultado de los servicios.

**Diseno:** H1.2-DD-001, H1.2-DD-003, H1.2-DD-006.  
**Pruebas:** H1.2-TP-008..012.  
**Tareas:** H1.2-T01, H1.2-T03.

### H1.2-RF-004 - Conservar el pipeline RAG y la validacion

**Descripcion:** Cambiar solo el adaptador de generacion, manteniendo retrieval,
prompt, reparacion, formato y validacion de citas.

**Prioridad:** Must.

**Criterios de aceptacion:**

- para una misma pregunta/contexto, se compara el texto generado por
  `PromptBuilder` antes de cualquier serializacion especifica del proveedor y
  ese texto no cambia al seleccionar Ollama o Anthropic;
- `AskService` ejecuta igual generacion, validacion y como maximo un intento de
  reparacion con ambos proveedores;
- la reparacion se envia al mismo proveedor configurado y pasa por el mismo
  `CitationValidator`;
- citas validas, faltantes, inventadas, contradicciones y evidencia insuficiente
  producen los mismos estados, formatos y codigos de salida;
- formatos text/JSON/Markdown y debug conservan su estructura publica;
- no cambian retrieval, ranking, contexto, prompts ni metricas SQLite RAG.

**Diseno:** H1.2-DD-001, H1.2-DD-005, H1.2-DD-008.  
**Pruebas:** H1.2-TP-013..017.  
**Tareas:** H1.2-T01, H1.2-T04.

### H1.2-RF-005 - Preservar timeout y cancelacion segura

**Descripcion:** Aplicar el timeout vigente y permitir que el usuario interrumpa
la espera sin crear trabajo local parcial ni una segunda solicitud.

**Prioridad:** Must.

**Criterios de aceptacion:**

- cada solicitud Anthropic usa exactamente `settings.llm.timeout_seconds`;
- timeouts de socket, API o transporte se normalizan como error operativo
  distinguible;
- Ctrl+C propaga `KeyboardInterrupt` hasta la CLI, cierra la respuesta/stream si
  existe y devuelve 130;
- no hay retry automatico, fallback a Ollama ni segundo intento fuera de la
  reparacion de citas ya existente;
- la CLI informa que Barbarion dejo de esperar, sin afirmar que Anthropic no
  proceso o facturo la solicitud;
- resultados RAG no se marcan completados si la generacion fue interrumpida.

**Diseno:** H1.2-DD-007.  
**Pruebas:** H1.2-TP-018..020.  
**Tareas:** H1.2-T03, H1.2-T04.

### H1.2-RF-006 - Mapear errores remotos de forma accionable

**Descripcion:** Diferenciar fallas esperadas de Anthropic sin filtrar payloads
ni acoplar los casos de uso a HTTP.

**Prioridad:** Must.

**Criterios de aceptacion:**

- distingue credencial ausente, autenticacion, permiso, modelo/recurso ausente,
  request invalido o grande, rate limit, billing, conflicto, timeout, sobrecarga,
  error de servidor, red, truncamiento y respuesta invalida;
- conserva un `request-id` acotado para diagnostico cuando el servidor lo
  informa, sin exponer headers restantes;
- errores 4xx/5xx desconocidos se convierten en un error estable y seguro;
- mensajes CLI y sugerencias nombran el proveedor efectivo y no recomiendan
  ejecutar Ollama cuando el proveedor es Anthropic;
- errores esperados no muestran traceback y mantienen exit code 1;
- configuracion invalida mantiene exit code 2 y Ctrl+C mantiene 130.

**Diseno:** H1.2-DD-006, H1.2-DD-011.  
**Pruebas:** H1.2-TP-021..024.  
**Tareas:** H1.2-T03, H1.2-T04.

### H1.2-RF-007 - Preservar `--no-llm`

**Descripcion:** Garantizar que los modos sin generacion no dependan de
Anthropic ni provoquen egress.

**Prioridad:** Must.

**Criterios de aceptacion:**

- `ask --no-llm`, `describe --no-llm`, `impact --no-llm` y Spec Mode
  conservan comportamiento, salida y codigos;
- seleccionar Anthropic sin `ANTHROPIC_API_KEY` no rompe ningun flujo
  `--no-llm`;
- no se construye request, no se abre conexion y no se lee ni registra la API
  key en esos flujos;
- keyword search y operaciones deterministas siguen disponibles sin Ollama
  generativo ni Anthropic;
- el resultado continua indicando `no_llm` de la misma forma actual.

**Diseno:** H1.2-DD-009.  
**Pruebas:** H1.2-TP-025, H1.2-TP-026.  
**Tareas:** H1.2-T04, H1.2-T05.

### H1.2-RF-008 - Mantener local el conocimiento

**Descripcion:** Limitar el cambio de frontera al prompt generativo y evitar que
Anthropic participe en construccion o persistencia de conocimiento.

**Prioridad:** Must.

**Criterios de aceptacion:**

- `ingest`, `inventory`, `index`, embeddings, sqlite-vec, `search`, `analyze`,
  reasoning/context package y validacion de citas no invocan Anthropic;
- seleccionar Anthropic no cambia `[embeddings]`, manifests, dimensiones,
  tablas, chunks, simbolos, relaciones ni artefactos previos;
- la solicitud remota contiene solo el prompt ya construido por el flujo
  vigente; nunca contiene la base, vectores, archivos completos o configuracion;
- logs explican proveedor/modelo, tamaño estimado y etapa sin contenido;
- no se crea persistencia nueva para prompts, respuestas, uso o credenciales.

**Diseno:** H1.2-DD-005, H1.2-DD-012.  
**Pruebas:** H1.2-TP-027..029.  
**Tareas:** H1.2-T04, H1.2-T05, H1.2-T06.

### H1.2-RF-009 - Preservar administracion y benchmark H1.1

**Descripcion:** Mantener `barbarion models` como capacidad local Ollama y
evitar que una configuracion Anthropic corrompa la seleccion local.

**Prioridad:** Must.

**Criterios de aceptacion:**

- `models list/show/install/benchmark` siguen usando solo `ollama_url` y no
  consultan Anthropic ni requieren su API key;
- el dataset, scoring, reportes, orden y elegibilidad del benchmark H1.1 no
  cambian;
- mientras `[llm].model` represente el modelo del proveedor activo,
  `models select` no modifica ese valor cuando `[llm].provider = "anthropic"`;
  esta limitacion temporal evita reemplazar accidentalmente el modelo Claude y
  exige cambiar primero el proveedor de forma explicita en TOML;
- `models validate` sin modelo no intenta validar un Claude remoto como modelo
  Ollama; informa que el comando pertenece a H1.1 local;
- validacion con un modelo Ollama explicito y los comandos de catalogo continúan
  disponibles aun si el proveedor generativo efectivo es Anthropic;
- con `provider = "ollama"` todos los comportamientos H1.1 permanecen iguales.

**Diseno:** H1.2-DD-010.  
**Pruebas:** H1.2-TP-030..033.  
**Tareas:** H1.2-T01, H1.2-T05.

### H1.2-RF-010 - Documentar operacion y egress antes de aceptar

**Descripcion:** Hacer visible la diferencia entre conocimiento local y
generacion remota sin modificar documentacion durante la fase de spec.

**Prioridad:** Must para aceptacion, no para aprobar la spec.

**Criterios de aceptacion:**

- durante implementacion se actualizan ejemplo TOML, CLI/README, arquitectura,
  vision, decisiones y evolucion solo despues de estabilizar contratos;
- la documentacion indica que pregunta, prompt y contexto seleccionado se
  envian a Anthropic cuando el proveedor se activa;
- incluye configuracion por variable de entorno sin mostrar valores reales;
- conserva Ollama como default y explica que embeddings permanecen locales;
- no afirma soporte para otros proveedores ni recomienda version/modelo sin
  evidencia de aceptacion;
- `acceptance.md` se crea exclusivamente en la ultima tarea tras aprobacion.

**Diseno:** H1.2-DD-004, H1.2-DD-005.  
**Pruebas:** H1.2-TP-034.  
**Tareas:** H1.2-T07, H1.2-T08.

## 8. Requisitos no funcionales

### H1.2-RNF-001 - Privacidad y consentimiento explicito

Anthropic solo se usa cuando `[llm].provider = "anthropic"`. Esa seleccion es
la autorizacion tecnica explicita para enviar el prompt generativo; la
organizacion sigue siendo responsable de autorizar el corpus. No hay deteccion,
routing o fallback automaticos.

### H1.2-RNF-002 - Compatibilidad hacia atras

Ollama sigue siendo el default. Configuraciones existentes, comandos, formatos,
codigos y contratos Python vigentes conservan comportamiento. La nueva clave de
limite de salida tiene default solo para Anthropic y no vuelve obligatoria
ninguna edicion en configuraciones Ollama existentes.

### H1.2-RNF-003 - Arquitectura existente

Se conserva el monolito modular y `LlmProviderPort`. La seleccion concreta vive
en la raiz de composicion; Anthropic es un adaptador de `infrastructure`. No se
agrega una capa, servicio, proceso o paquete raiz paralelo.

### H1.2-RNF-004 - No modificar conocimiento ni RAG

No cambian H2, H3, H4, H4.1 ni H5, salvo el cableado existente que recibe el
mismo puerto LLM. Prompt builders, validadores, modelos de salida y SQLite se
protegen mediante pruebas de caracterizacion.

### H1.2-RNF-005 - Seguridad de secretos

La API key existe solo en memoria del proceso y se enmascara aun si aparece en
una excepcion inesperada. No se persiste, serializa ni presenta. La suite incluye
un scan del valor canario por todos los canales observables.

### H1.2-RNF-006 - Red acotada

El adaptador solo puede llamar al host y ruta directos de Anthropic definidos en
codigo por HTTPS. Modelo, prompt o configuracion no pueden alterar el destino.
No se admite base URL configurable en H1.2.

### H1.2-RNF-007 - Rendimiento y costo acotados

Cada etapa generativa produce una solicitud no streaming y tiene timeout y
limite de salida. No hay concurrencia, retries, precarga ni solicitudes de
conteo. H1.2 no promete SLA ni costo universal.

### H1.2-RNF-008 - Cancelacion honesta

Ctrl+C detiene la espera local y devuelve 130. La documentacion y mensajes no
prometen cancelacion transaccional en Anthropic ni ausencia de consumo remoto.

### H1.2-RNF-009 - Pruebas offline

La suite normal usa opener/servidor fake, entorno temporal y bloqueo de red. Una
API key o llamada real es manual, opt-in y solo con datos sinteticos.

### H1.2-RNF-010 - Compatibilidad Windows y Python 3.12

La implementacion conserva Python `>=3.12,<3.13`, `urllib` y rutas portables. No
requiere shell, `curl`, daemon adicional ni SDK nativo.

### H1.2-RNF-011 - Observabilidad segura

Logs registran proveedor, modelo, etapa, timeout, tamaños, duracion, resultado y
codigo tecnico. No registran API key, headers, prompt, respuesta ni fragmentos.

### H1.2-RNF-012 - Alcance cerrado

Incorporar otro proveedor, endpoint alternativo, gateway, streaming, retry o
secret backend requiere una spec posterior. No se generaliza anticipadamente.

## 9. Casos de uso

### CU-01 - Consultar con Anthropic

1. El operador exporta `ANTHROPIC_API_KEY` en el entorno seguro.
2. Configura `[llm].provider = "anthropic"` y un modelo Claude autorizado.
3. Ejecuta `barbarion ask` sin cambiar opciones CLI.
4. Barbarion recupera y ensambla contexto localmente.
5. Envia el prompt final a Anthropic y valida localmente la respuesta/citas.
6. Presenta el mismo formato y codigo de salida que con Ollama.

### CU-02 - Consultar sin LLM con Anthropic configurado

1. El archivo selecciona Anthropic, pero la API key puede estar ausente.
2. El usuario ejecuta `barbarion ask ... --no-llm`.
3. Barbarion recupera contexto local, no lee credencial ni abre red remota.
4. Devuelve la salida `no_llm` vigente.

### CU-03 - Sintetizar descripcion o impacto

1. El usuario ejecuta `describe` o `impact` con la opcion LLM vigente.
2. El caso de uso construye localmente evidencia y resumen determinista.
3. El mismo puerto envia solo el prompt de sintesis a Anthropic.
4. Ante falla, se conserva la politica determinista vigente del caso de uso.

### CU-04 - Administrar modelos Ollama con Anthropic activo

1. `[llm].provider` permanece en `anthropic`.
2. El usuario puede listar, inspeccionar, instalar o benchmarkear modelos Ollama.
3. `models select` aplica la limitacion temporal y no altera el modelo Claude ni
   cambia el proveedor mientras exista un unico `[llm].model` activo.
4. Para volver a Ollama, el usuario edita explicitamente proveedor/modelo en
   TOML y luego puede usar la seleccion local H1.1.

## 10. Fuera de alcance consolidado

H1.2 no crea una estrategia multi-cloud, no mueve conocimiento a cloud, no
cambia embeddings, retrieval, citas o artefactos, no administra modelos Claude,
no compara proveedores y no modifica la interfaz publica. Solo incorpora
Anthropic como adaptador alternativo de generacion final.

## 11. Riesgos

- el prompt contiene contexto autorizado pero potencialmente sensible;
- una configuracion Anthropic accidental puede producir egress y costo;
- limites, modelos y errores Anthropic pueden cambiar con el tiempo;
- `max_output_tokens` insuficiente puede truncar una respuesta con citas;
- una solicitud interrumpida localmente puede haber sido procesada/facturada;
- rate limits, billing, permisos o disponibilidad remota afectan generacion;
- diferencias de estilo pueden activar la reparacion de citas con distinta
  frecuencia aunque el contrato sea igual;
- sugerencias CLI Ollama-specific existentes deben hacerse provider-neutral sin
  cambiar formatos;
- `models select` podria corromper una configuracion Anthropic si no se protege;
- conservar `think`/`num_ctx` en un TOML al migrar a Anthropic debe fallar de
  forma explicita y puede requerir edicion manual;
- un fake no demuestra politicas, costos ni comportamiento de un modelo real;
- la vision on-premise actual requiere una decision documental explicita antes
  de aceptar la evolucion.

## 12. Matriz inicial de trazabilidad

| Requisito | Diseno | Pruebas | Tareas |
|---|---|---|---|
| H1.2-RF-001 | DD-002, DD-004 | TP-001..004 | T01, T02 |
| H1.2-RF-002 | DD-003, DD-004, DD-011 | TP-005..007 | T02, T03, T06 |
| H1.2-RF-003 | DD-001, DD-003, DD-006 | TP-008..012 | T01, T03 |
| H1.2-RF-004 | DD-001, DD-005, DD-008 | TP-013..017 | T01, T04 |
| H1.2-RF-005 | DD-007 | TP-018..020 | T03, T04 |
| H1.2-RF-006 | DD-006, DD-011 | TP-021..024 | T03, T04 |
| H1.2-RF-007 | DD-009 | TP-025, TP-026 | T04, T05 |
| H1.2-RF-008 | DD-005, DD-012 | TP-027..029 | T04..T06 |
| H1.2-RF-009 | DD-010 | TP-030..033 | T01, T05 |
| H1.2-RF-010 | DD-004, DD-005 | TP-034 | T07, T08 |
