# H3.2 - Privacy Preflight para inferencia remota: Plan de pruebas

## 1. Objetivo

Demostrar con datos sinteticos que ninguna inferencia remota ocurre sin evidencia
estructurada, vigente y suficiente para `strict`; que un `PASS` mantiene la
llamada directa y el pipeline vigente; y que registry, cache, observabilidad y
verificadores nunca reciben ni filtran contenido del corpus.

## 2. Principios de validacion

- La propiedad central es negativa: todo `BLOCK` implica cero requests LLM.
- `UNKNOWN` bloquea igual que `FAIL`, pero conserva una razon distinta.
- Capability y account configuration se prueban por separado.
- La suite normal bloquea Internet y usa relojes, registry, account y LLM fakes.
- Los prompts H3.1 se comparan byte a byte antes/despues de un PASS.
- Ninguna prueba usa corpus, consultas, rutas o identificadores reales.

## 3. Alcance

Incluye modelos de dominio, configuracion, resolucion de target, tres evaluadores,
registry, cache/TTL, refresh, verifier, AskService, generation/repair, CLI, logs,
errores, seguridad, compatibilidad y regresion.

Excluye auditoria legal, veracidad del proveedor, DLP/PII, attestation,
rendimiento del LLM, scraping web, gateways y proveedores no implementados.

## 4. Ambientes y fakes

- Python y plataformas soportadas por el proyecto, filesystem temporal;
- reloj UTC inyectable en limites de TTL;
- `SyntheticPrivacyPolicySource` que registra todos sus argumentos;
- snapshot valido, expirado, corrupto, conflictivo y con excepcion de modelo;
- fake contractual futuro `SyntheticAccountPrivacyVerifier` y resultado v1
  `unavailable`, sin adaptador productivo;
- fake Ollama local, fake Ollama cloud y fake Anthropic HTTP;
- interceptor que falla ante cualquier red no loopback/autorizada;
- canarios distintos para pregunta, chunk, path, simbolo, formula, business ID,
  API key y respuesta rechazada.

## 5. Fixtures sinteticos

Identidad base:

```text
provider=synthetic-ai
platform=direct_api
offering=standard
model=new-model-v99
allowed_regions=[region-a]  # fixture opcional; tambien se prueba omision
```

Evidencias:

- no-training incondicional y opt-out condicional;
- retention 0, 7 dias y `zdr_available=true`;
- region fija `region-a`, region `region-b` y region configurable desconocida;
- verifier que confirma ZDR/region, contradice capability o no esta disponible;
- modelo nuevo sin excepcion y una excepcion explicitamente publicada.

Corpus minimo: archivos virtuales `src/module_a.sql` y `ui/window_b.sru` con
identificadores `SYN_RULE_A`, fuentes F1/F2 y hechos abstractos sin dominio real.

## 6. Pruebas unitarias

### H3.2-TP-001 - Frontera generativa vigente

Caracteriza que generation y repair llaman al wrapper comun y al mismo provider.

### H3.2-TP-002 - Prompt y presupuestos baseline

Congela prompt generation/repair, contexto 4500, presupuesto H3.1 opcional,
seleccion, IDs y CitationValidator.

### H3.2-TP-003 - Estados validos

Acepta PASS/FAIL/UNKNOWN/NOT_APPLICABLE y rechaza estados libres/CONDITIONAL.

### H3.2-TP-004 - Resultado agregado

Local agrega NOT_APPLICABLE; remoto solo agrega PASS con tres PASS; cualquier
FAIL/UNKNOWN agrega BLOCK.

### H3.2-TP-005 - Autorizacion inmutable

Fingerprint depende solo de target/policy y operation ID, nunca de contenido.

### H3.2-TP-006 - Invariantes remotas

Rechaza autorizacion remota con NOT_APPLICABLE, evidencia vencida o identidad
incompleta.

### H3.2-TP-007 - Ollama local declarado

Un transporte Ollama ambiguo con `execution=local` resuelve
local/local_runtime sin usar el nombre del modelo. Sin override, incluso
loopback resuelve `unknown` porque el daemon puede offloadear al cloud.

### H3.2-TP-008 - Ollama cloud

Config explicita resuelve remote/ollama_cloud y activa preflight para cualquier
modelo, incluido uno nuevo.

### H3.2-TP-009 - Anthropic directo

Siempre resuelve remote/direct_api; declarar local se rechaza.

### H3.2-TP-010 - Politica strict igual a ZDR

Valida que strict exija no-training, retencion efectiva cero y ubicacion
conocida. Sin allowlist, ubicacion conocida pasa; con allowlist, se exige
pertenencia; ubicacion desconocida bloquea en ambos casos.

### H3.2-TP-011 - No-training PASS

Declaracion incondicional aplicable a inputs/outputs produce PASS.

### H3.2-TP-012 - No-training FAIL

Uso confirmado para entrenamiento produce FAIL.

### H3.2-TP-013 - No-training UNKNOWN

Opt-out disponible, scope ambiguo o evidencia ausente produce UNKNOWN.

### H3.2-TP-014 - Retention PASS

Retencion efectiva cero, incluida confirmacion fiable de cuenta, produce PASS.

### H3.2-TP-015 - Retention FAIL

Retencion positiva efectiva produce FAIL.

### H3.2-TP-016 - Retention UNKNOWN

ZDR disponible sin confirmacion, dato ausente o condicional produce UNKNOWN.

### H3.2-TP-017 - Location PASS

Ubicacion efectiva conocida produce PASS sin allowlist; con allowlist, la region
canonica incluida produce PASS.

### H3.2-TP-018 - Location FAIL

Region efectiva fuera de allowed_regions produce FAIL.

### H3.2-TP-019 - Location UNKNOWN

Region configurable no resuelta o dato ausente produce UNKNOWN. Una allowlist
omitida no convierte ubicacion desconocida en PASS.

### H3.2-TP-020 - Normalizacion de registry

Mapea schema versionado a evidencia de dominio sin conservar campos libres.

### H3.2-TP-021 - Provider/platform/offering

Resuelve scopes de mas especifico a general y marca ambiguedad/conflicto UNKNOWN.

### H3.2-TP-022 - Modelo nuevo sin cambio de codigo

`new-model-v99` usa evidencia del offering conocido sin branch/lista de modelo.

### H3.2-TP-023 - Excepcion de modelo publicada

Solo una excepcion presente en el snapshot puede sobreescribir offering; ausencia
de excepcion no dispara lookup distinto.

### H3.2-TP-024 - Lookup minimo

Spy confirma que solo provider/platform/offering y, cuando corresponde, model
publico llegan a la fuente; todos los canarios de contenido estan ausentes.

### H3.2-TP-025 - Refresh explicito con registry disponible

Refresh valido escribe snapshot atomico y la evaluacion usa su version/timestamps.

### H3.2-TP-026 - Cache valida offline

`ask` con registry inaccesible y cache vigente permite decidir sin intentar red.

### H3.2-TP-027 - Cache inexistente

`ask` con cache ausente produce UNKNOWN/BLOCK e instruccion de refresh, sin
intentar contactar el registry.

### H3.2-TP-028 - Cache expirada

Entrada exactamente en/despues de expires_at no autoriza; `ask` produce BLOCK
sin refresh automatico. El comando refresh fallido no reemplaza la cache.

### H3.2-TP-029 - TTL y expiracion de fuente

Expiracion efectiva es el minimo de TTL local y expiracion publicada.

### H3.2-TP-030 - Cache invalida

Schema, version, reloj futuro, integridad o identidad invalidos producen BLOCK.

### H3.2-TP-031 - Escritura atomica

Interrupcion/fallo conserva la ultima cache valida y no deja un snapshot parcial.

### H3.2-TP-032 - Ask sin correlacion ni refresh

Dos asks distintos usan el mismo snapshot y realizan cero requests al registry;
solo el comando refresh envia metadata, sin IDs/hashes de contenido.

### H3.2-TP-033 - Contrato futuro confirma configuracion

El fake in-memory construye una observacion sintetica de ZDR y region; los
evaluadores demuestran que el modelo admite scope account. No hay provider API,
credenciales, HTTP ni deteccion real.

### H3.2-TP-034 - Verifier v1 no disponible

La composicion v1 retorna unavailable sin credenciales ni IO; evidencia
incondicional aun puede decidir propiedades que no requieren cuenta.

### H3.2-TP-035 - ZDR disponible no habilitado

Capability `available=true` sin observacion account produce retention UNKNOWN.

### H3.2-TP-036 - Conflicto de evidencia

Un resultado fake sintetico que contradice capability produce FAIL o UNKNOWN
segun valor, nunca seleccion optimista. Esta es una prueba pura del evaluador,
no una comprobacion de cuenta.

### H3.2-TP-037 - Fake futuro con error seguro

El fake devuelve un error tipado sin transporte ni body; el contrato produce
UNKNOWN/BLOCK y no alcanza al LLM. V1 no contiene resolucion de credenciales,
HTTP, provider API, deteccion real ni adaptador productivo.

**Limite comun TP-033..037:** estas pruebas solo ejercitan interface, modelo de
resultado, `unavailable`, fake in-memory y funciones puras de precedencia. La
presencia de red, credenciales o codigo especifico de proveedor hace fallar el
alcance de T07.

### H3.2-TP-038 - Local no aplica

No invoca fuente/verifier y permite el provider local con NOT_APPLICABLE.

### H3.2-TP-039 - Remoto todo PASS

Emite autorizacion y permite exactamente una llamada generation directa.

### H3.2-TP-040 - No-training FAIL/UNKNOWN bloquea

Ambos estados producen cero llamadas LLM y razones diferenciadas.

### H3.2-TP-041 - Retention FAIL/UNKNOWN bloquea

Ambos estados producen cero llamadas LLM.

### H3.2-TP-042 - Location FAIL/UNKNOWN bloquea

Region no permitida y no conocida producen cero llamadas LLM.

### H3.2-TP-043 - Provider/plataforma desconocidos

Evidencia ausente produce UNKNOWN/BLOCK, no fallback ni branch de modelo.

### H3.2-TP-044 - Generation protegida

Provider remoto rechaza invocacion del wrapper sin autorizacion coincidente.

### H3.2-TP-045 - Repair protegido

Respuesta invalida activa repair con la misma autorizacion y sin segundo lookup.

### H3.2-TP-046 - Autorizacion no reutilizable

Otro operation ID, target o policy invalida el permiso antes de generate.

### H3.2-TP-047 - Repair bloqueado sin permiso

Una llamada directa/accidental al stage repair sin permiso produce cero HTTP.

### H3.2-TP-048 - Salida BLOCK compacta

Muestra estados y `No se envio contexto...` sin prompt/chunks.

### H3.2-TP-049 - Debug explicable

Muestra fuente, scope, reason, timestamps, cache y verifier seguros.

### H3.2-TP-050 - Logs seguros

Canarios de pregunta, codigo, rutas, simbolos, formula, respuesta y key no
aparecen en exito, bloqueo, error, debug ni Ctrl+C.

### H3.2-TP-051 - Errores y exit codes

Config=2, bloqueo/error operativo=1, interrupcion=130, sin traceback esperado.

### H3.2-TP-052 - `--no-llm`

No consulta registry/verifier/credencial/provider y conserva salida actual.

### H3.2-TP-053 - Evidencia insuficiente

Retorna localmente antes del preflight y conserva metricas/estado actuales.

### H3.2-TP-054 - Documentacion

Verifica enlaces, `strict = ZDR`, allowlist opcional, refresh explicito, llamada directa, fail-closed,
limitaciones y ausencia de afirmaciones/provider policies hardcodeadas.

### H3.2-TP-055 - Politica pragmatica v1

`no_training` FAIL/UNKNOWN bloquea; retention FAIL/UNKNOWN muestra WARNING y
requiere confirmacion antes del prompt; data_location no bloquea. Ollama Cloud
puede usar la politica oficial de Ollama como evidencia secundaria uniforme,
sin reglas por modelo. `N` mantiene cero llamadas LLM y `S` marca
`user_accepted_risk`.

## 7. Pruebas de integracion

### H3.2-INT-001 - Baseline H3.1

Ask sintetico confirma prompts, contexto, seleccion, budgets, citas y repair
anteriores.

### H3.2-INT-002 - Matriz de targets

CLI/config deriva Ollama local, Ollama cloud y Anthropic directo; ambiguedad sin
override bloquea.

### H3.2-INT-003 - Refresh y offline

Comando CLI refresca snapshot fake; un proceso `ask` separado reinicia sin red y
decide con cache valida. Cache ausente/expirada bloquea sin refresh automatico.

### H3.2-INT-004 - Remoto PASS end-to-end

Retrieval local, preflight PASS, prompt identico, HTTP directo al provider fake,
citas validas y salida vigente.

### H3.2-INT-005 - Remoto FAIL end-to-end

Cada restriccion FAIL bloquea antes de credencial/provider y muestra diagnostico.

### H3.2-INT-006 - Remoto UNKNOWN end-to-end

Provider desconocido, cache ausente y verifier unavailable bloquean sin red al registry.

### H3.2-INT-007 - Local end-to-end

Ollama local no consulta privacy IO y conserva request/respuesta vigente.

### H3.2-INT-008 - Generation y repair

Respuesta inicial con cita invalida produce exactamente un preflight y dos
requests directos autorizados; repair invalido conserva rechazo seguro.

### H3.2-INT-009 - CLI text/JSON/debug/logs

PASS/BLOCK/NOT_APPLICABLE y errores tienen contrato estable y pasan scanner.

### H3.2-INT-010 - Cero datos al registry

Interceptor inspecciona request completo y niega todos los canarios de corpus,
query, paths, symbols, formulas, business IDs y hashes derivados.

### H3.2-INT-011 - Cero LLM en BLOCK

Matriz completa FAIL/UNKNOWN/cache/error/Ctrl+C mantiene contador HTTP LLM en 0.

### H3.2-INT-012 - Llamada directa en PASS

Unico destino generativo es el endpoint del provider configurado; registry no
recibe prompt y no existe gateway/OpenRouter.

### H3.2-INT-013 - `--no-llm` y consumidores

Ask no-llm, H4/H5 y rutas sin generacion conservan contratos y cero privacy IO
cuando no transmiten contexto.

### H3.2-INT-014 - Regresion completa

Suite H1-H5, H1.1, H1.2, H3.1, H4.1, golden y smoke instalado pasan.

## 8. Matriz de escenarios obligatorios

| # | Escenario | Prueba | Esperado |
|---|---|---|---|
| 1 | local | TP-038, INT-007 | NOT_APPLICABLE, inferencia |
| 2 | remoto + todo PASS | TP-039, INT-004 | inferencia directa |
| 3 | no_training FAIL | TP-040 | BLOCK |
| 4 | no_training UNKNOWN | TP-040 | BLOCK |
| 5 | retention FAIL | TP-041 | BLOCK |
| 6 | retention UNKNOWN | TP-041 | BLOCK |
| 7 | ubicacion no permitida | TP-042 | BLOCK |
| 8 | registry disponible durante refresh | TP-025 | snapshot/evaluacion posterior |
| 9 | registry inaccesible + cache valida | TP-026 | ask usa cache, cero red |
| 10 | registry inaccesible + sin cache | TP-027 | BLOCK sin refresh automatico |
| 11 | cache expirada | TP-028 | BLOCK |
| 12 | modelo nuevo/provider conocido | TP-022 | sin cambio codigo |
| 13 | provider/platform desconocido | TP-043 | BLOCK |
| 14 | ZDR disponible no confirmado | TP-035 | UNKNOWN/BLOCK |
| 15 | contrato futuro confirma | TP-033 | precedencia probada con fake |
| 16 | verifier no disponible | TP-034 | no finge verificacion |
| 17 | generation protegida | TP-044 | requiere permiso |
| 18 | repair protegido | TP-045, INT-008 | mismo permiso |
| 19 | cero corpus al registry | TP-024, INT-010 | scanner limpio |
| 20 | `--no-llm` | TP-052 | operativo, cero IO |
| 21 | compatibilidad | TP-002, INT-014 | sin regresion |

## 9. Seguridad y privacidad

1. Inyectar canarios unicos en cada categoria sensible.
2. Ejecutar PASS, cada FAIL/UNKNOWN, refresh explicito, cache corrupta, verifier error,
   generation, repair, debug y Ctrl+C.
3. Capturar argumentos de puertos, requests, stdout, stderr, logs, cache, SQLite
   y archivos temporales.
4. Confirmar que registry/cache solo contienen metadata publica.
5. Confirmar que v1 no resuelve credenciales ni hace IO de cuenta; el fake del
   contrato futuro recibe solo el target sintetico.
6. Confirmar que provider LLM solo recibe prompt despues de PASS.
7. Escanear workspace temporal por canarios fuera de los fixtures controlados.

Cualquier canario sensible observado por registry/cache/logs o cualquier request
LLM durante BLOCK es P0 y bloquea aceptacion.

## 10. Puertas de aceptacion

- 100 % de escenarios obligatorios pasan con fixtures sinteticos;
- cero requests LLM para todo FAIL, UNKNOWN, error y cache invalida;
- cero contenido/canarios enviados al registry;
- cache valida opera offline; `ask` nunca refresca; cache expirada nunca autoriza;
- ZDR disponible sin account verification nunca pasa retention strict;
- modelo nuevo hereda offering sin cambios de codigo;
- generation y repair requieren una unica autorizacion por ask;
- prompt, budgets, retrieval, seleccion y CitationValidator no cambian;
- Ollama local, Ollama cloud remoto, Anthropic y no-llm estan cubiertos;
- suite completa y smoke pasan, con skips explicados;
- documentacion no afirma garantias legales ni verificadores inexistentes;
- revision humana aprueba fuente, TTL, UX y mensajes antes de crear acceptance.

## 11. Matriz requisito-prueba

| Requisito | Pruebas principales |
|---|---|
| REQ-001 | TP-007..009, INT-002 |
| REQ-002 | TP-038, INT-007 |
| REQ-003 | TP-010, TP-017..019 |
| REQ-004 | TP-020..024 |
| REQ-005 | TP-022..023 |
| REQ-006 | TP-033..037 |
| REQ-007 | TP-011..019 |
| REQ-008 | TP-004, TP-039..043, INT-011 |
| REQ-009 | TP-025..032, INT-003 |
| REQ-010 | TP-044..047, INT-008 |
| REQ-011 | TP-024, TP-032, INT-010 |
| REQ-012 | TP-048..050, INT-009 |
| REQ-013 | TP-052..053, INT-013 |
| REQ-014 | TP-001..002, INT-001, INT-014 |
| REQ-015 | TP-027..031, TP-037, TP-051 |
| REQ-016 | TP-054 |

## 12. Evidencia esperada para aceptacion

- version/hash del dataset y snapshots sinteticos;
- matriz por restriccion con razones y fuentes;
- contadores de lookup, preflight, generation y repair;
- captura saneada del lookup minimo y de la llamada LLM directa;
- casos cache valida/ausente/expirada/corrupta y refresh interrumpido;
- scanner de canarios limpio;
- hashes de prompts y resultados de budgets/citas antes/despues;
- suite completa, smoke instalado, duracion y skips;
- revision de la fuente externa, licencia, vigencia y limites;
- validacion manual sintetica autorizada o pendiente explicita;
- `acceptance.md` creado unicamente en H3.2-T13.
