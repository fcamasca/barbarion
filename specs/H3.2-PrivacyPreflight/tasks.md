# H3.2 - Privacy Preflight para inferencia remota: Plan de tareas

## 1. Reglas

- Implementar en orden y mantener el gate fail-closed desde su activacion.
- Cada tarea es pequeña, verificable e incluye pruebas asociadas.
- No modificar retrieval, H3.1, prompts, budgets ni `CitationValidator`.
- No agregar gateways, fallback ni tablas de politicas por modelo.
- No implementar un account verifier sin API fiable y fixtures contractuales.
- Registry y verifier nunca reciben contenido ni hashes del corpus.
- Fixtures y reportes son exclusivamente sinteticos/publicables.
- No crear `acceptance.md` hasta H3.2-T13.
- Estados iniciales: `pendiente`.

Estado actual del hito: implementacion iniciada. H3.2-T01 a H3.2-T09
completadas; T10-T13 pendientes.

## 2. Tareas

### H3.2-T01 - Caracterizar fronteras y regresion previa

**Estado:** completada.  
**Objetivo:** congelar el comportamiento anterior al gate.  
**Archivos/componentes esperados:** tests de `AskService`, factoria LLM,
Anthropic/Ollama HTTP fakes, prompts H3.1 y salidas CLI.  
**Descripcion:** demostrar primera llamada generativa, generation/repair,
`--no-llm`, evidencia insuficiente, budgets, CitationValidator y cero fallback.  
**Pruebas:** H3.2-TP-001, TP-002, INT-001.  
**Dependencias:** H1.2 y H3.1 aceptados.  
**Checkpoint:** hashes/golden de prompts y conteo de requests sin cambios de
`src/`.

**Evidencia:** `tests/unit/test_h32_privacy_preflight_baseline.py`,
`tests/integration/test_h32_privacy_preflight_cli_baseline.py` y
`reports/h32/t01-baseline.md`. La suite focal aprobo 136 pruebas; generation
valida realiza una solicitud, repair reutiliza el mismo provider como segunda y
ultima solicitud, y `--no-llm`/evidencia insuficiente realizan cero. No se
modifico ningun archivo bajo `src/`.

### H3.2-T02 - Modelar identidad, estados y politica

**Estado:** completada.  
**Objetivo:** crear contratos puros sin IO.  
**Archivos/componentes esperados:** `domain/privacy.py`, unit tests de modelos.  
**Descripcion:** implementar `InferenceTarget`, restricciones, estados,
evidencia, policy strict, resultado y autorizacion con invariantes inmutables.  
**Pruebas:** H3.2-TP-003..006.  
**Dependencias:** T01.  
**Checkpoint:** `CONDITIONAL` no existe; remoto no acepta `NOT_APPLICABLE`.

**Evidencia:** `src/barbarion/domain/privacy.py`,
`tests/unit/test_h32_privacy_domain.py` y `reports/h32/t02-domain.md`. El dominio
puro modela target, constraints, evidencia, policy, resultado y autorizacion sin
configuracion ni IO. La regresion focal aprobo 168 pruebas. No se modificaron
`config.py`, `AskService`, CLI, registry, cache ni adaptadores.

### H3.2-T03 - Resolver configuracion efectiva local/remota

**Estado:** completada.  
**Objetivo:** derivar Ollama local, Ollama cloud y Anthropic directo.  
**Archivos/componentes esperados:** `config.py`, composicion CLI, TOML temporal,
tests de config/factoria.  
**Descripcion:** derivar `execution`/`platform` desde provider y endpoint; agregar
solo `llm.execution` como override opcional ante transporte Ollama ambiguo. No
agregar aun `[privacy]`, offering, registry, cache ni evaluacion strict.  
**Pruebas:** H3.2-TP-007..009, INT-002.  
**Dependencias:** T02.  
**Checkpoint:** ningun nombre de modelo decide execution o politica.

**Evidencia:** `src/barbarion/application/privacy.py`, extension compatible de
`LlmSettings`, `tests/unit/test_h32_inference_target_resolution.py`,
`tests/integration/test_h32_inference_target_config.py` y
`reports/h32/t03-target-resolution.md`. La suite completa aprobo 953 pruebas con
14 skips. T03 no consulta politicas, registry, cache ni integra el gate en
`AskService`.

### H3.2-T04 - Implementar evaluadores puros strict

**Estado:** completada.  
**Objetivo:** decidir cada restriccion sin IO ni puntajes.  
**Archivos/componentes esperados:** `application/privacy.py`, unit tests
parametrizados.  
**Descripcion:** evaluar no-training, retencion y ubicacion; resolver evidencia
construida en memoria, incondicional, condicional, conflictiva y expirada. No
consultar cuentas, registry, cache ni red.  
**Pruebas:** H3.2-TP-010..019.  
**Dependencias:** T02.  
**Checkpoint:** toda combinacion remota que contenga FAIL/UNKNOWN bloquea.

**Evidencia:** evaluadores puros en `src/barbarion/application/privacy.py`,
matriz `tests/unit/test_h32_privacy_evaluation.py` y
`reports/h32/t04-strict-evaluation.md`. Las 27 combinaciones remotas fueron
probadas y la suite completa aprobo 1006 pruebas con 14 skips. No se agregaron
IO, registry, cache, HTTP ni integracion con `AskService`.

### H3.2-T05 - Definir adaptador y normalizacion del registry

**Estado:** completada.
**Objetivo:** desacoplar formato externo de evidencia de dominio.  
**Archivos/componentes esperados:** `PrivacyPolicySource`, adaptador inicial,
schemas/fixtures sinteticos, errores tipados.  
**Descripcion:** investigar una fuente machine-readable concreta, documentar su
licencia/autoridad y mapear solo datos estructurados; si no satisface el contrato,
entregar adaptador fake y dejar seleccion productiva bloqueada, sin inventar
evidencia.  
**Pruebas:** H3.2-TP-020..024.  
**Dependencias:** T02, T04.  
**Checkpoint:** payload observado contiene solo identidad publica.

**Evidencia:** `PrivacyPolicySource` y resultado normalizado en
`src/barbarion/domain/privacy.py`, adaptador puro en
`src/barbarion/infrastructure/privacy_registry.py`, fixture sintetico y matriz
`tests/unit/test_h32_privacy_registry.py`, y
`reports/h32/t05-registry-normalization.md`. Se verifico la fuente real y se
concluyo que indexa capabilities del offering: `training_on_customer_data =
yes_public` puede respaldar no-training cuando el scope coincide, pero
`retention_zdr` y `data_residency` nunca demuestran por si solos configuracion
efectiva. El adaptador no interpreta texto libre ni realiza red, cache o refresh.

### H3.2-T06 - Implementar cache atomica y refresh explicito

**Estado:** completada.
**Objetivo:** permitir evaluacion offline con vigencia segura.  
**Archivos/componentes esperados:** cache bajo `data_dir/privacy`, adaptador de
refresh, comando/servicio de refresh, tests de reloj y filesystem temporal.  
**Descripcion:** implementar snapshot, schema/version/integridad, TTL efectivo,
escritura atomica, estados de lectura valid/missing/expired/invalid y resultado
separado del comando refresh.  
**Pruebas:** H3.2-TP-025..032, INT-003.  
**Dependencias:** T05.  
**Checkpoint:** `ask` nunca refresca; cache expirada o refresh fallido nunca produce PASS.

**Evidencia:** cache local y servicio de refresh explicito en
`src/barbarion/infrastructure/privacy_cache.py`, pruebas TP-025..032 en
`tests/unit/test_h32_privacy_cache.py` y reporte
`reports/h32/t06-privacy-cache.md`. T06 entrega un `PrivacyPolicySource` solo
para snapshots `valid`; `missing`, `expired` e `invalid` no exponen evidencia.
No decide PASS/BLOCK, no implementa cliente HTTP ni modifica `AskService`.

### H3.2-T07 - Reservar contrato minimo de verificacion de cuenta

**Estado:** completada.
**Objetivo:** mantener separada la configuracion efectiva sin anticipar IO.  
**Archivos/componentes esperados:** protocolo minimo `AccountPrivacyVerifier`,
resultado `unavailable` y fake contractual sin credenciales ni red.  
**Descripcion:** modelar observaciones estructuradas minimas y precedencia para
una evolucion futura; no implementar adaptador productivo ni resolver
credenciales en v1.  
**Pruebas:** H3.2-TP-033..037.  
**Dependencias:** T04, T05.  
**Limite tajante:** T07 incluye exclusivamente interface, modelo de resultado,
implementacion `unavailable` y fake in-memory para demostrar extensibilidad. No
incluye API de provider, credenciales, HTTP ni deteccion de configuracion real.  
**Checkpoint:** `ZDR available` sin garantia incondicional sigue UNKNOWN; el diff
de T07 no contiene clientes HTTP, resolvers de secretos ni adaptadores de cuenta.

**Evidencia:** contrato y estados en `src/barbarion/domain/privacy.py`,
implementaciones `UnavailableAccountPrivacyVerifier` e
`InMemoryAccountPrivacyVerifier` en `src/barbarion/application/privacy.py`,
pruebas TP-033..037 en `tests/unit/test_h32_account_privacy_verifier.py` y
reporte `reports/h32/t07-account-verifier-contract.md`. Produccion retorna
siempre `unavailable`; no se agregaron HTTP, credenciales, configuracion,
deteccion de cuenta ni logica de proveedor.

### H3.2-T08 - Integrar el gate en AskService

**Estado:** completada.
**Objetivo:** bloquear antes del primer egress generativo.  
**Archivos/componentes esperados:** composicion de `PrivacyPreflightService`,
`AskService`, errores de dominio/aplicacion, tests con spies.  
**Descripcion:** evaluar tras returns locales y antes del prompt/request;
producir autorizacion por operation ID y requerirla en el wrapper comun.  
**Pruebas:** H3.2-TP-038..043, INT-004..007.  
**Dependencias:** T03, T04, T06, T07.  
**Checkpoint:** BLOCK implica exactamente cero llamadas a `generate()`.

**Evidencia:** `PrivacyPreflightService` en
`src/barbarion/application/privacy.py`, gate y autorizacion obligatoria en
`src/barbarion/application/rag.py`, composicion desde cache local en
`src/barbarion/cli.py`, matriz TP-038..043 en
`tests/unit/test_h32_privacy_preflight_ask.py`, integracion segura en
`tests/integration/test_h32_privacy_preflight_gate.py` y reporte
`reports/h32/t08-ask-gate.md`. BLOCK ocurre antes de `PromptBuilder.build`, logs
LLM y `generate()`; los returns `--no-llm` e insuficiencia permanecen antes del
preflight.

### H3.2-T09 - Blindar repair y cambios de identidad

**Estado:** completada.
**Objetivo:** impedir bypass o reutilizacion indebida.  
**Archivos/componentes esperados:** guard de autorizacion, tests generation y
repair.  
**Descripcion:** reutilizar la autorizacion solo dentro del ask y validar target
y policy fingerprints; negar autorizacion ausente, de otra operacion o target.  
**Pruebas:** H3.2-TP-044..047, INT-008.  
**Dependencias:** T08.  
**Checkpoint:** generation y repair pasan por el mismo guard; un solo preflight.

**Evidencia:** validacion determinista en `PrivacyAuthorization.is_valid_for`,
guard comun en `AskService._generate_with_observability`, matriz TP-044..047 en
`tests/unit/test_h32_privacy_authorization_guard.py` y reporte
`reports/h32/t09-authorization-guard.md`. Generation y repair reutilizan una
autorizacion emitida por un unico preflight; operation, target o policy distintos
fallan antes de logs y `generate()`.

### H3.2-T10 - Exponer CLI, debug y observabilidad segura

**Estado:** pendiente.  
**Objetivo:** explicar decisiones sin contenido ni secretos.  
**Archivos/componentes esperados:** render CLI text/JSON/debug, logging, config
show, errores/codigos.  
**Descripcion:** agregar salida compacta, detalle debug, eventos estructurados y
mensajes de cache/registry/verifier; aplicar redaccion/canarios.  
**Pruebas:** H3.2-TP-048..053, INT-009.  
**Dependencias:** T08, T09.  
**Checkpoint:** scanner no encuentra pregunta, chunks, paths ni credenciales.

### H3.2-T11 - Ejecutar seguridad y regresion completa

**Estado:** pendiente.  
**Objetivo:** demostrar compatibilidad y cero egress no autorizado.  
**Archivos/componentes esperados:** integration/smoke tests, scanner de
privacidad, reportes sinteticos.  
**Descripcion:** cubrir Ollama local/cloud, Anthropic, no-llm, cache, registry,
verifier, generation, repair, H3.1, H4.1, H4/H5 y suite completa.  
**Pruebas:** H3.2-INT-010..014, matriz de seguridad y regresion.  
**Dependencias:** T10.  
**Checkpoint:** suite offline pasa y todo BLOCK tiene cero requests LLM.

### H3.2-T12 - Documentar operacion y decisiones

**Estado:** pendiente.  
**Objetivo:** alinear documentacion una vez estabilizados los contratos.  
**Archivos/componentes esperados:** `barbarion.example.toml`, README, CLI,
ARCHITECTURE, DECISIONS, ROADMAP, EVOLUTION y guia de privacy/cache.  
**Descripcion:** documentar `strict = ZDR`, ubicacion conocida, allowlist
opcional, refresh explicito, offline, egress directo,
limitaciones de evidencia y ausencia de garantias legales.  
**Pruebas:** H3.2-TP-054 y links/docs tests.  
**Dependencias:** T11.  
**Checkpoint:** ejemplos sinteticos, sin afirmar soporte/verificacion inexistente.

### H3.2-T13 - Aceptacion tecnica y funcional

**Estado:** pendiente.  
**Objetivo:** producir evidencia final y decision humana.  
**Archivos/componentes esperados:** `acceptance.md` creado en esta tarea,
reportes finales y checklist de revision.  
**Descripcion:** ejecutar test-plan, registrar versiones/skips, revisar fuente
externa/licencia, privacidad, operaciones offline/proxy y realizar validacion
manual sintetica autorizada cuando exista conectividad.  
**Pruebas:** plan completo y puertas de la seccion 10 de `test-plan.md`.  
**Dependencias:** T12.  
**Checkpoint:** aprobacion explicita; pendientes externos no se presentan como
PASS.

## 3. Orden de implementacion

```text
T01 -> T02 -> T03
          -> T04 -> T05 -> T06
                    \-> T07
T03 + T04 + T06 + T07 -> T08 -> T09 -> T10 -> T11 -> T12 -> T13
```

T06 y T07 pueden desarrollarse en paralelo despues de estabilizar contratos,
pero T08 no comienza hasta que ambos comportamientos esten definidos.

## 4. Trazabilidad

| Tarea | Requisitos principales | Pruebas principales |
|---|---|---|
| T01 | REQ-010, REQ-013, REQ-014 | TP-001..002, INT-001 |
| T02 | REQ-001, REQ-007, REQ-008 | TP-003..006 |
| T03 | REQ-001 | TP-007..009, INT-002 |
| T04 | REQ-003, REQ-006..008 | TP-010..019 |
| T05 | REQ-004, REQ-005, REQ-011 | TP-020..024 |
| T06 | REQ-009 | TP-025..032, INT-003 |
| T07 | REQ-006, REQ-007 | TP-033..037 |
| T08 | REQ-002, REQ-008, REQ-010, REQ-013 | TP-038..043, INT-004..007 |
| T09 | REQ-010, REQ-014 | TP-044..047, INT-008 |
| T10 | REQ-012, REQ-015 | TP-048..053, INT-009 |
| T11 | REQ-011, REQ-014; NFR-001..008 | INT-010..014 |
| T12 | REQ-016 | TP-054 |
| T13 | todos | plan completo |
