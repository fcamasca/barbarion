# H1.2 - Inferencia Remota con Anthropic: Plan de pruebas

## 1. Objetivo

Verificar que H1.2 selecciona Anthropic como backend remoto de generacion final
sin cambiar los contratos, prompts, retrieval, citas, formatos, conocimiento
local, `--no-llm`, timeout, cancelacion o benchmark Ollama H1.1.

## 2. Alcance

Incluye:

- validacion compatible de `[llm]`;
- factoria cerrada Ollama/Anthropic;
- adaptador HTTP Anthropic Messages API con opener fake;
- credencial solo desde `ANTHROPIC_API_KEY`;
- payload, respuesta, stop reason y errores HTTP/red;
- generacion y reparacion RAG con el mismo validador;
- sintesis H4 opcional por el puerto existente;
- `--no-llm` sin credencial ni red;
- timeout y Ctrl+C;
- privacidad, egress y ausencia de persistencia;
- compatibilidad de comandos/benchmark H1.1;
- regresion H1-H5/H4.1/H1.1;
- validacion manual Anthropic opcional y sintetica.

Excluye:

- pruebas de otros proveedores;
- embeddings/retrieval cloud;
- benchmark Anthropic-Ollama;
- streaming, tools, batches, vision, caching o SDK;
- rotacion de secretos y costos reales;
- uso de corpus o prompts productivos en servicios externos.

## 3. Estrategia

- pruebas de caracterizacion antes de cambiar composicion;
- unit tests para config, factory, request, parser y errores;
- integration tests con servidor/opener fake sin internet;
- pruebas parametrizadas para estados HTTP y payloads variables;
- golden/contract tests para salida RAG y benchmark H1.1;
- key canario para detectar filtraciones en todos los canales;
- snapshots de SQLite/manifests antes y despues;
- bloqueo de conexiones salvo loopback en suite;
- regresion completa y smoke instalado;
- prueba real manual solo tras autorizacion y con datos sinteticos.

Prioridad:

- **P0 - Must:** secreto, destino fijo, payload, mismo prompt, citas, no-llm,
  timeout, Ctrl+C, no persistencia, benchmark intacto y regresion.
- **P1 - Defensiva:** campos desconocidos, request-id invalido, redirects,
  respuestas parciales y HTTP menos frecuentes.

La cantidad de tests no es una meta; se priorizan invariantes y riesgos.

## 4. Ambientes

- Windows local como ambiente principal;
- Python `>=3.12,<3.13`;
- TOML, entorno, logs y filesystem temporales;
- SQLite/sqlite-vec reales solo para regresion local;
- suite normal sin internet, Anthropic real ni API key valida;
- endpoint fake loopback u opener in-memory;
- Ollama fake para H1.1 y embeddings cuando corresponda;
- Anthropic real opcional con autorizacion;
- `pytest --basetemp .pytest-tmp/h12` recomendado.

## 5. Fixtures y datos

### Configuraciones

- Ollama legacy sin `max_output_tokens`;
- Ollama completa con `think` y `num_ctx`;
- Anthropic minima y completa;
- Anthropic con campos Ollama incompatibles;
- proveedor desconocido;
- key ausente, vacia y key canario
  `sk-ant-test-NEVER-LOG-H12-0123456789`.

### Fake Anthropic

Debe observar:

- URL, metodo, headers y timeout;
- JSON del request sin conservarlo fuera del test;
- uno/varios bloques text;
- campos y bloques desconocidos;
- texto vacio, JSON invalido y UTF-8 invalido;
- `end_turn`, `max_tokens`, stop reason nulo/desconocido;
- HTTP 400, 401, 402, 403, 404, 409, 413, 429, 500, 504 y 529;
- `request-id` valido, ausente, largo y con caracteres invalidos;
- DNS/URL/TLS/timeout simulado;
- `KeyboardInterrupt` durante apertura y lectura.

### Contexto sintetico

Reutilizar objetos abstractos y citas F1..Fn de H1.1. No usar nombres de
dominio, codigo real, rutas personales, secretos o contenido de clientes.

## 6. Pruebas unitarias

### H1.2-TP-001 - Config Ollama compatible

Config sin claves H1.2 conserva settings, provider, payload Ollama y salida.
Config Ollama que declara `max_output_tokens` se rechaza para evitar una clave
sin efecto.

### H1.2-TP-002 - Config Anthropic valida

Acepta provider/model/timeout/temperature/max output; `config show` presenta solo
valores no sensibles.

### H1.2-TP-003 - Config Anthropic incompatible

Rechaza `think`, `num_ctx`, max output fuera de rango, modelo vacio y proveedor
desconocido con codigo/config error accionable.

### H1.2-TP-004 - Factoria cerrada

Compone exactamente Ollama o Anthropic; no hay registry/import dinamico y el
tipo retornado satisface `LlmProviderPort`.

### H1.2-TP-005 - Key desde entorno

Solo `ANTHROPIC_API_KEY` llega al header; TOML y CLI no admiten credenciales.

### H1.2-TP-006 - Key ausente tardia

Construir settings/servicio funciona; `generate` falla antes de opener con key
ausente/vacia.

### H1.2-TP-007 - Key no observable

Key canario no aparece en repr, str(error), logs, stdout/stderr, debug, objetos
serializados ni archivos temporales.

### H1.2-TP-008 - Request Messages API

POST usa URL/version fijas, headers exactos, timeout recibido y body con modelo,
max tokens, temperatura y un unico mensaje user.

### H1.2-TP-009 - Request minimo

No contiene system, tools, thinking, files, metadata, beta, stream activo,
endpoint configurable ni propiedades Ollama.

### H1.2-TP-010 - Respuesta textual

Un bloque y varios bloques text se concatenan en orden; whitespace externo se
normaliza solo segun contrato vigente.

### H1.2-TP-011 - Respuesta extensible

Campos/bloques desconocidos se ignoran sin imprimirlos; content ausente, vacio o
invalido produce `ANTHROPIC_RESPONSE_INVALID`.

### H1.2-TP-012 - Truncamiento

`stop_reason=max_tokens` produce error tipado y nunca retorna texto parcial como
respuesta completa.

### H1.2-TP-013 - Prompt identico entre proveedores

Misma pregunta/contexto produce exactamente el mismo texto desde `PromptBuilder`
antes de entrar al adaptador y antes de cualquier serializacion Ollama o
Anthropic. No se comparan los requests HTTP completos.

### H1.2-TP-014 - Respuesta y citas validas

Fake Anthropic con respuesta controlada pasa exactamente el validador vigente y
produce mismo `AnswerResult`/formato que fake Ollama.

### H1.2-TP-015 - Reparacion por mismo proveedor

Respuesta con citas invalidas genera una unica reparacion mediante Anthropic;
prompt y validacion coinciden con comportamiento vigente.

### H1.2-TP-016 - Reparacion fallida

Citas aun invalidas producen la misma respuesta segura, status y exit code; no
hay fallback Ollama ni tercer request.

### H1.2-TP-017 - Evidencia insuficiente

Sin contexto se retorna localmente sin acceder a key ni proveedor.

### H1.2-TP-018 - Timeout exacto

Opener recibe exactamente `llm.timeout_seconds`; socket, URL y HTTP 504 se
normalizan sin traceback.

### H1.2-TP-019 - Ctrl+C

Interrupcion en apertura/lectura cierra recursos, propaga y termina 130 sin
registrar consulta completada.

### H1.2-TP-020 - Sin retry ni fallback

Cada `generate` realiza como maximo un POST; 429/500/529 no disparan segunda
llamada. Reparacion solo ocurre tras respuesta valida pero citas invalidas.

### H1.2-TP-021 - Autenticacion y permisos

401/402/403 se distinguen y sugieren key, billing o permisos sin body remoto.

### H1.2-TP-022 - Request y modelo

400/404/409/413 se mapean a request/modelo/tamaño y conservan exit 1.

### H1.2-TP-023 - Disponibilidad

429/500/504/529, DNS, TLS y conexion se distinguen con error seguro.

### H1.2-TP-024 - Request ID

Solo request-id acotado aparece en diagnostico; headers restantes y valores
invalidos/largos se omiten.

### H1.2-TP-025 - Ask `--no-llm`

Con Anthropic activo y sin key devuelve contexto vigente, sin opener ni lectura
del secreto.

### H1.2-TP-026 - Otros modos sin LLM

Describe, impact, spec y rutas keyword/no-llm mantienen salida y cero red.

### H1.2-TP-027 - Conocimiento inmutable

Hash/conteos de archivos, documentos, chunks, manifests, vectores, simbolos,
referencias y relaciones permanecen iguales tras generacion Anthropic.

### H1.2-TP-028 - Egress minimo

El request contiene solo campos de API y prompt vigente; no contiene ruta de DB,
TOML, variables, vectors, manifests ni archivo completo ajeno al contexto.

### H1.2-TP-029 - Sin persistencia nueva

No hay migracion/tablas/cache/reportes H1.2 y respuesta/key/request-id no quedan
en SQLite o filesystem.

### H1.2-TP-030 - Models Ollama con Anthropic activo

List/show/install/benchmark usan solo Ollama, no leen key y mantienen contratos.

### H1.2-TP-031 - Select protegido

`models select` con provider Anthropic aborta sin editar TOML; con Ollama conserva
edicion atomica vigente. La prueba registra que el bloqueo es una limitacion
temporal del unico `[llm].model` asociado al proveedor activo.

### H1.2-TP-032 - Validate protegido

Validate sin modelo con Anthropic activo explica alcance local; con nombre
Ollama explicito conserva sonda H1.1.

### H1.2-TP-033 - Benchmark identico

Dataset/hash, matriz, scoring, reportes/golden, candidato y exit codes H1.1 no
cambian y no admiten Anthropic como competidor.

### H1.2-TP-034 - Documentacion y ejemplos

Tests/enlaces verifican proveedor, egress, key de entorno, embeddings locales,
default Ollama y ausencia de otros proveedores o secretos.

### H1.2-TP-035 - Unicode de extremo a extremo

Una pregunta y corpus con `¿Dónde`, `configuración`, `adquisición`, `días`,
`cupón`, `último` y `cálculo` conservan exactamente sus code points en CLI,
SQLite, `PromptBuilder`, bytes UTF-8 del request, respuesta UTF-8, validacion de
citas, formatos text/JSON/Markdown, debug, stdout, stderr y logs permitidos. La
prueba de proceso Windows ejecuta el entrypoint instalado, captura bytes sin
`StringIO`, decodifica con UTF-8 estricto y distingue streams redirigidos de la
consola interactiva. Se prohibe `errors="replace"`.

### H1.2-TP-036 - Uso Anthropic real y parcial

`usage.input_tokens` y `usage.output_tokens` producen el total por suma y se
acumulan entre generacion y reparacion. Ausencia parcial/total, timeout,
truncamiento, error y Ctrl+C no inventan consumo. El estimador previo Anthropic
se etiqueta `prompt_tokens_est_local`; Ollama conserva `prompt_tokens_est`.

## 7. Pruebas de integracion

### INT-H1.2-01 - Ask Anthropic completo

CLI carga TOML temporal, recupera fixture local, envia prompt a fake HTTP,
valida citas y conserva formato/codigo.

### INT-H1.2-02 - Reparacion Anthropic

Fake devuelve cita invalida y luego valida; se observan exactamente dos POST con
prompts vigentes y mismo modelo.

### INT-H1.2-03 - Key ausente

Generacion falla 1 antes de HTTP; config show y no-llm terminan sin secreto.

### INT-H1.2-04 - Errores remotos

Matriz HTTP/red produce mensajes provider-specific, no traceback/body/key.

### INT-H1.2-05 - Timeout e interrupcion

Fake bloqueado confirma timeout; KeyboardInterrupt devuelve 130 y no reintenta.

### INT-H1.2-06 - Describe con LLM

Construccion H4 queda local y solo prompt de sintesis llega al fake Anthropic.

### INT-H1.2-07 - Impact con LLM y fallback

Exito usa texto remoto; error conserva resumen determinista y limitacion vigente,
sin fallback Ollama.

### INT-H1.2-08 - Todos los `--no-llm`

Ask/describe/impact/spec funcionan con provider Anthropic, key ausente y red
bloqueada.

### INT-H1.2-09 - Embeddings permanecen Ollama

Index/search semantic/hybrid invocan fake Ollama de embeddings y nunca Anthropic.

### INT-H1.2-10 - H1.1 permanece Ollama

Todos los comandos models usan fake Ollama; guards select/validate protegen
provider Anthropic.

### INT-H1.2-11 - Sin cambio SQLite

Snapshot antes/despues de ask/describe/impact Anthropic demuestra que solo las
metricas RAG existentes pueden cambiar como hoy y no hay schema/contenido nuevo.

### INT-H1.2-12 - Red acotada

Interceptor demuestra que el unico destino externo posible es el endpoint fijo
Anthropic; redirects no reciben key/contexto en otro host.

### INT-H1.2-13 - Compatibilidad Ollama

Suite HTTP Ollama y comportamiento existente pasan con config legacy.

### INT-H1.2-14 - Config show y logs

Muestran provider/model/limites y metricas seguras, nunca key/header/body.

### INT-H1.2-15 - Unicode y usage en CLI

Ask completo con fake Anthropic comprueba pregunta, contexto, prompt, payload,
respuesta, citas, text/JSON/Markdown, debug, logs UTF-8 y metricas reales
`10,198 + 612 = 10,810`, sin key ni conexiones externas.

## 8. Pruebas CLI

- `barbarion config show` con Ollama y Anthropic;
- `barbarion ask "pregunta"` con fake Anthropic;
- `barbarion ask "pregunta" --no-llm` sin key;
- `barbarion ask` con respuesta que requiere reparacion;
- `barbarion describe OBJETO --with-llm`;
- `barbarion impact OBJETO --with-llm`;
- provider desconocido y campos incompatibles;
- key ausente, 401, 403, 404, 429, 500, 504, 529;
- timeout y Ctrl+C;
- `models list/show/install/benchmark` con Anthropic activo;
- `models select/validate` protegidos;
- mismos formatos text/JSON/Markdown y codigos 0/1/2/130.

## 9. Golden y pruebas de contrato

No se crean nuevos golden de contenido remoto productivo. Se conservan:

- respuestas RAG existentes con fake provider;
- salidas de evidencia insuficiente y citas invalidas;
- Markdown describe/impact/spec;
- benchmark H1.1 completo/incompleto/sin candidato;
- JSON normalizado existente.

Si se agrega un golden Anthropic, contiene solo modelo y datos sinteticos,
clock/duracion fake, ningun request body completo, ruta o key.

## 10. Casos negativos

| Caso | Esperado |
|---|---|
| provider desconocido | config invalida, 2, cero red |
| Anthropic con `think/num_ctx` | config invalida y accionable |
| key ausente/vacia | 1 antes de HTTP; no-llm funciona |
| key en TOML | clave desconocida; no se carga |
| endpoint en TOML | clave desconocida; destino fijo |
| modelo vacio | config invalida |
| max output 0/excesivo | config invalida |
| 401/402/403 | auth/billing/permiso diferenciados |
| 404 | modelo/recurso no encontrado |
| 413 | request demasiado grande |
| 429 | rate limit, sin retry |
| 500/529 | error/sobrecarga, sin retry/fallback |
| 504/socket timeout | timeout accionable |
| redirect externo | no reenvia key/contexto |
| JSON invalido | response invalid, sin body |
| content vacio | response invalid |
| bloque desconocido | ignorado; requiere al menos texto |
| stop max_tokens | truncado, no salida parcial |
| Ctrl+C | 130; estado remoto no afirmado |
| cita inventada | reparacion/resultado seguro vigente |
| reparacion invalida | error vigente, sin tercer request |
| no context | insuficiencia local, cero HTTP |
| `--no-llm` | cero key/HTTP |
| `models select` con Anthropic | no edita proveedor/modelo |
| benchmark con nombre Claude | sigue semantica Ollama, no cloud |

## 11. Pruebas de regresion

La aceptacion final ejecuta:

- H1 configuracion, doctor, bootstrap y CLI;
- H1.1 list/show/install/validate/select/benchmark;
- H2 ingesta e incrementalidad;
- H3 index/search/ask, citas, repair y benchmark retrieval;
- H4 analyze/inventory/describe/impact;
- H4.1 Data-Driven y retrieval estructurado;
- H5 spec create/validate;
- golden files;
- smoke test instalado.

Adicionalmente:

- config legacy produce el mismo `OllamaLlmProvider` y payload;
- prompts de Ask/repair no cambian bytes;
- `CitationValidator` no cambia reglas;
- manifests/embeddings no dependen de `llm.provider`;
- no se agregan imports ni cambios Anthropic a application/domain;
- no se agrega dependencia runtime nueva.

## 12. Pruebas de seguridad y privacidad

1. Inyectar key canario unica.
2. Ejecutar exito, errores HTTP, timeout, JSON invalido, debug y Ctrl+C.
3. Capturar stdout, stderr y logs.
4. Inspeccionar repr/excepciones y archivos temporales/output.
5. Consultar SQLite y manifests.
6. Escanear workspace de prueba por key completa y fragmentos distintivos.
7. Confirmar que solo el header del request fake la recibio.
8. Confirmar que redirects no la reenvian.
9. Confirmar que no-llm no consulta el entorno ni el opener.

Un fallo de este scan es P0 y bloquea aceptacion.

## 13. Pruebas de rendimiento y costo

Con fakes se mide overhead de serializacion/parseo, sin SLA. En validacion real
opcional se registra, sin contenido:

- wall-clock por generacion y reparacion;
- timeout configurado;
- `prompt_chars` y `prompt_tokens_est_local` como aproximacion previa;
- response chars;
- stop reason;
- input/output tokens reales devueltos por Anthropic y total matematicamente
  demostrable, sin llamada previa a `/v1/messages/count_tokens`;
- numero exacto de solicitudes.

No se ejecutan cargas, paralelismo o benchmarks de costo. Una solicitud real
puede generar costo y requiere autorizacion previa.

## 14. Validacion manual con Anthropic real

Opcional y separada de la suite:

1. obtener autorizacion de egress/costo;
2. provisionar `ANTHROPIC_API_KEY` sin escribirla;
3. usar config temporal y modelo autorizado;
4. ejecutar un caso sintetico con cita unica;
5. ejecutar un caso sintetico que requiera multiples citas;
6. comprobar formato, validacion y request-id no sensible;
7. ejecutar `--no-llm` tras retirar la key;
8. escanear logs/output por secretos y contenido no previsto;
9. destruir config/logs temporales segun politica del entorno;
10. registrar limites sin copiar prompt/respuesta completa.

Si no hay key, red, presupuesto o autorizacion, se registra pendiente. No se usa
corpus real ni se inventan resultados.

## 15. Matriz requisito-prueba

| Requisito | Pruebas principales |
|---|---|
| H1.2-RF-001 | TP-001..004, INT-13, INT-14 |
| H1.2-RF-002 | TP-005..007, INT-03, seguridad |
| H1.2-RF-003 | TP-008..012, INT-01 |
| H1.2-RF-004 | TP-013..017, INT-01, INT-02 |
| H1.2-RF-005 | TP-018..020, INT-05 |
| H1.2-RF-006 | TP-021..024, INT-04 |
| H1.2-RF-007 | TP-025, TP-026, INT-08 |
| H1.2-RF-008 | TP-027..029, INT-09, INT-11, INT-12 |
| H1.2-RF-009 | TP-030..033, INT-10, INT-13 |
| H1.2-RF-010 | TP-034 |
| H1.2-RNF-001 | TP-005..007, TP-028, seguridad |
| H1.2-RNF-002 | TP-001, TP-013..017, INT-13 |
| H1.2-RNF-003 | TP-004, revision de imports |
| H1.2-RNF-004 | TP-013..017, TP-027, regresion |
| H1.2-RNF-005 | TP-005..007, seguridad |
| H1.2-RNF-006 | TP-008, TP-028, INT-12 |
| H1.2-RNF-007 | TP-012, TP-018..020, rendimiento |
| H1.2-RNF-008 | TP-019, INT-05 |
| H1.2-RNF-009 | fake suite, bloqueo de red |
| H1.2-RNF-010 | TP-035, INT-15, smoke Windows |
| H1.2-RNF-011 | TP-007, TP-024, TP-036, INT-14, INT-15 |
| H1.2-RNF-012 | TP-004, revision de alcance/dependencias |

## 16. Evidencia esperada para aceptacion

- suite completa, duracion y skips explicados;
- smoke instalado y regresion H1-H5/H4.1/H1.1;
- configs sinteticas Ollama/Anthropic;
- payload fake y endpoint/version comprobados;
- key canario ausente de todos los canales;
- matriz de errores y codigos CLI;
- hashes/prompts equivalentes antes del adaptador;
- casos de cita valida, repair valido e invalido;
- no-llm sin key/red;
- timeout y Ctrl+C sin retry/fallback;
- snapshot de conocimiento local;
- benchmark H1.1 sin cambios;
- bloqueo de destinos externos no autorizados;
- documentacion principal alineada;
- Unicode preservado de CLI a HTTP y de HTTP a todas las salidas;
- usage real acumulado, estimacion local diferenciada y cero conteo remoto previo;
- validacion real sintetica si fue autorizada, o pendiente explicita;
- revision humana de privacidad y decision final.

## 17. Criterios para declarar H1.2 listo para aceptacion

- todos los requisitos Must tienen pruebas pasando;
- Ollama continua como default y config legacy no cambia;
- Anthropic satisface el puerto sin cambiar su firma;
- API key solo proviene del entorno y no aparece en ningun canal;
- endpoint/version son fijos y payload no incorpora capacidades fuera de scope;
- retrieval, prompt, repair, citas, formatos y codigos permanecen iguales;
- todo conocimiento e indices permanecen locales;
- egress se limita al prompt de generacion/reparacion solicitado;
- no-llm funciona sin key ni red;
- timeout, Ctrl+C y ausencia de retries/fallback estan demostrados;
- H1.1 sigue Ollama-only y su benchmark pasa sin cambios;
- no hay soporte ni abstraccion para otro proveedor cloud;
- suite normal es offline y no contiene datos reales;
- documentacion explicita egress y limita afirmaciones on-premise;
- `acceptance.md` se crea solo durante H1.2-T08 y despues de aprobacion.
