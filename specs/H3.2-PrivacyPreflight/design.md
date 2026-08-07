# H3.2 - Privacy Preflight para inferencia remota: Diseno

## 1. Comportamiento actual verificado

`AskService.ask()` recupera candidatos, integra evidencia H4.1, selecciona y
presupuesta contexto, y retorna localmente ante evidencia insuficiente o
`--no-llm`. Si continua, construye `PromptComposition` y llama a
`_generate_with_observability()`. Esa funcion es el unico camino de generation y
repair hacia `LlmProviderPort.generate()`.

```text
query
  -> SearchService
  -> merge/selection H3.1
  -> ContextBuilder + input budget
  -> insufficient / --no-llm (retorno local)
  -> PromptBuilder
  -> _generate_with_observability(generation)
  -> CitationValidator
  -> _generate_with_observability(repair, como maximo una vez)
```

La factoria cerrada crea Ollama o Anthropic. `provider` no expresa por si solo
la frontera: Anthropic directo es remoto, mientras Ollama puede representar
ejecucion local o una oferta cloud. El nombre del modelo tampoco es una señal de
privacidad estable.

## 2. Ubicacion exacta del gate

El preflight se incorpora en `AskService.ask()` despues de:

- resolver el `InferenceTarget` efectivo durante composicion;
- completar retrieval, seleccion y contexto;
- retornar los caminos locales de evidencia insuficiente y `--no-llm`.

Y antes de:

- construir o registrar el prompt de generation en debug;
- resolver credenciales del proveedor;
- ejecutar cualquier `LlmProviderPort.generate()`.

La implementacion recomendada obtiene un `PrivacyAuthorization` una vez y lo
entrega a `_generate_with_observability()`. La funcion exige autorizacion para
todo `InferenceTarget.remote`, por lo que repair no puede saltarse el gate.

```text
Query -> Retrieval -> Selection -> Context
                               |-> no-llm/insufficient -> local result
                               v
                    PrivacyPreflight.evaluate(target, policy)
                         | PASS              | BLOCK
                         v                   v
                 PromptBuilder        safe local error
                         v             zero LLM requests
                 direct provider
                         v
                validate -> repair
                          (same authorization)
```

El contexto ya existe en memoria, pero nunca se entrega al registry. Ejecutar el
gate antes de retrieval agregaria red incluso cuando no habra inferencia y no
conoce aun si la operacion necesita LLM.

## 3. Decisiones de diseno

| ID | Decision | Motivo | Requisitos |
|---|---|---|---|
| H3.2-DD-001 | Numerar la evolucion H3.2 | Es el siguiente gate del pipeline RAG despues de H3.1 | REQ-010, REQ-014 |
| H3.2-DD-002 | Derivar `InferenceTarget` del adaptador/transporte y usar override solo ante ambiguedad | Evita carga normal al usuario y no confunde modelo con frontera | REQ-001, REQ-005 |
| H3.2-DD-003 | Definir `strict` como ZDR efectivo, ubicacion conocida y `allowed_regions` opcional | Hace explicita la decision fuerte sin obligar a mantener una allowlist | REQ-003, REQ-007 |
| H3.2-DD-004 | Mantener cuatro estados por restriccion y omitir `CONDITIONAL` | Las condiciones se resuelven o quedan `UNKNOWN` | REQ-006, REQ-007 |
| H3.2-DD-005 | Exigir todos los `PASS` remotos | Implementa fail-closed sin score de confianza | REQ-008 |
| H3.2-DD-006 | Consultar un snapshot/cache, no el registry por cada `ask` | Reduce egress, latencia y dependencia de disponibilidad | REQ-009, NFR-004 |
| H3.2-DD-007 | Reservar un contrato minimo futuro `AccountPrivacyVerifier` sin implementacion productiva v1 | Separa capability y cuenta sin anticipar una API inexistente | REQ-004, REQ-006 |
| H3.2-DD-008 | Una autorizacion inmutable por operacion cubre generation y repair | Evita duplicacion y bypass manteniendo identidad/politica estables | REQ-010 |
| H3.2-DD-009 | Mantener el provider LLM y su llamada directa sin cambios de routing | El registry no debe ver prompts ni ejecutar inferencia | REQ-011, REQ-014 |
| H3.2-DD-010 | No persistir evaluaciones con contenido; cachear solo metadata publica | Conserva privacidad y trazabilidad suficiente | REQ-009, REQ-012 |
| H3.2-DD-011 | `ask` solo lee cache; refresh es explicito en v1 | Evita red y correlacion por consulta en el camino critico | REQ-009, REQ-011 |
| H3.2-DD-012 | Una cache expirada nunca es evidencia valida | Disponibilidad temporal no puede abrir el gate | REQ-008, REQ-009 |

## 4. Componentes y contratos

Los nombres son propuestos. Deben ubicarse siguiendo el monolito modular actual;
no requieren paquetes/plugin registries dinamicos.

```text
domain/privacy.py
  InferenceTarget
  PrivacyConstraint, EvaluationState
  PrivacyEvidence, ConstraintEvaluation
  PrivacyPolicy, PrivacyPreflightResult, PrivacyAuthorization
  PrivacyPolicySource (Protocol)
  AccountPrivacyVerifier (Protocol)

application/privacy.py
  PrivacyPreflightService
  PrivacyEvidenceResolver

infrastructure/privacy_registry.py
  adaptador del registry machine-readable
  snapshot/cache atomica

infrastructure/<provider>_privacy.py
  futuro; solo tras aprobar una API fiable en otra evolucion/tarea
```

Contrato minimo:

```text
InferenceTarget
  execution: local | remote | unknown
  provider: str
  platform: str
  offering: str | null
  model: str | null            # diagnostico/excepcion publicada; no lookup normal

PrivacyPolicy
  profile: strict
  allowed_regions: tuple[str, ...] | null

PrivacyEvidence
  constraint: no_training | retention | data_location
  value: structured value
  scope: provider | platform | offering | model_exception | account
  source_kind: external_registry | account_verifier | provider_configuration
  source_id: str
  verified_at: datetime
  expires_at: datetime
  conditional_on_account: bool

ConstraintEvaluation
  constraint: PrivacyConstraint
  state: PASS | FAIL | UNKNOWN | NOT_APPLICABLE
  reason_code: str
  evidence_refs: tuple[SafeEvidenceRef, ...]

PrivacyPreflightResult
  decision: PASS | BLOCK | NOT_APPLICABLE
  target: InferenceTarget
  evaluated_at: datetime
  policy_fingerprint: str       # solo politica/identidad, nunca contenido
  evaluations: tuple[ConstraintEvaluation, ...]
  cache_status: valid | missing | expired | invalid

PrivacyAuthorization
  operation_id: opaque local ID
  target_fingerprint: str
  policy_fingerprint: str
  result: PASS | NOT_APPLICABLE
```

`PrivacyPolicySource.lookup(target)` solo acepta `provider/platform/offering` y
el modelo cuando el snapshot ya declara una excepcion aplicable. El adaptador no
recibe `Settings`, `ContextBuildResult`, pregunta o prompt.

El contrato futuro `AccountPrivacyVerifier.verify(target)` devuelve un conjunto
minimo de observaciones estructuradas y disponibilidad por propiedad. V1 incluye
solo el protocolo y un resultado `unavailable`; no resuelve credenciales ni hace
IO de cuenta. Una implementacion futura requiere API fiable, pruebas de contrato
y una decision explicita. El verifier nunca decide la politica.

## 5. Resolucion provider/platform/offering

La raiz de composicion construye `InferenceTarget` junto al provider, derivando
los campos de contratos ya controlados por Barbarion:

| Señal efectiva | execution | provider | platform | offering |
|---|---|---|---|---|
| Ollama local legacy | local | ollama | local_runtime | null |
| Ollama cloud declarada | remote | ollama | ollama_cloud | valor configurado/opcional |
| Anthropic directo | remote | anthropic | direct_api | valor configurado/opcional |

Propuesta TOML minima:

```toml
[llm]
provider = "anthropic"
model = "modelo-autorizado"
# offering = "api_standard"  # solo si la fuente distingue ofertas

[privacy]
remote_inference = "strict"
allowed_regions = ["region-sintetica-1"]
registry_cache_ttl_hours = 24
```

`allowed_regions` puede omitirse. `execution` y `platform` no aparecen en la
configuracion normal: Anthropic se deriva de su adaptador directo y Ollama de la
metadata/endpoint efectivo. Un override avanzado se admite solo para destinos
ambiguos que no expongan metadata suficiente; queda marcado como declaracion del
operador, validado y visible en debug.

Compatibilidad:

- config Ollama existente deriva local/local_runtime cuando endpoint y runtime
  lo demuestran;
- Anthropic deriva remoto/direct API en composicion;
- Ollama cloud deriva remoto/ollama_cloud desde metadata operativa fiable, no
  desde el nombre del modelo;
- si no puede distinguirse la frontera, se usa un override avanzado o
  `execution=unknown` y BLOCK;
- combinaciones imposibles o destino remoto sin identidad suficiente fallan al
  cargar config;
- `offering` no es obligatorio si el registry tiene una politica inequívoca en
  plataforma; si existen offerings divergentes y no se puede resolver, el
  resultado es `UNKNOWN`.

No se mantiene una lista de modelos. `model` solo participa si la evidencia
recibida contiene una excepcion de modelo declarada.

## 6. Fuente externa y cache

### 6.1 Estrategia

Se prefiere descargar un snapshot machine-readable completo o particionado por
provider antes que consultar por cada `ask`. Esto evita correlacion temporal con
preguntas, permite validar esquema/integridad una vez y funciona offline.

Flujo de v1:

```text
privacy refresh -> descargar metadata -> validar -> escritura atomica

ask
  -> cache valida -> resolver localmente -> evaluar
  -> cache ausente/expirada/invalidada -> UNKNOWN + BLOCK + instruccion refresh
```

El refresh ocurre mediante un comando explicito (por ejemplo,
`barbarion privacy refresh`). `ask` no lo dispara de forma oportunista ni hace
red hacia el registry. Esto mantiene el camino generativo determinista y evita
correlacion temporal con una pregunta concreta.

### 6.2 Vigencia

- el snapshot contiene `source_version`, `verified_at` y, si la fuente lo
  aporta, `expires_at`;
- Barbarion calcula una expiracion efectiva como el minimo entre la expiracion
  de fuente y `fetched_at + registry_cache_ttl_hours`;
- TTL inicial configurable con default documentado de 24 horas; no puede
  extender una expiracion impuesta por la fuente;
- reloj futuro, esquema desconocido, identidad conflictiva, integridad fallida o
  evidencia vencida invalidan la entrada;
- stale-while-revalidate no se usa para autorizar.

### 6.3 Persistencia

La cache vive bajo `data_dir/privacy/`, fuera de SQLite RAG, con archivo temporal
y replace atomico. Contiene exclusivamente snapshot publico normalizado y
metadata de descarga. No contiene credenciales, pregunta, modelo consultado,
historial de asks ni decisiones por usuario. Permisos y proxy reutilizan
mecanismos estandar del proceso; no se agrega daemon.

## 7. Verificacion de cuenta y precedencia de evidencia

Cada restriccion combina hechos, no puntajes. Precedencia:

1. configuracion de cuenta fiable para propiedades efectivas, cuando exista un
   verifier futuro aprobado;
2. configuracion explicita controlada y verificable del proveedor;
3. capability del registry cuando aplica incondicionalmente al offering.

Una evidencia mas especifica puede confirmar o contradecir una general. Un
conflicto no resuelto produce `UNKNOWN`; una configuracion efectiva que viola la
politica produce `FAIL`. Ejemplos:

| Evidencia | Resultado strict |
|---|---|
| no-training incondicional para direct API | `PASS` para `no_training` |
| opt-out disponible, estado de cuenta desconocido | `UNKNOWN` |
| ZDR disponible, verifier ausente | `UNKNOWN` para `retention` |
| verifier futuro confirma ZDR habilitado | `PASS` para `retention` |
| verifier futuro confirma retencion de 7 dias | `FAIL` |
| offering concreto garantiza ZDR incondicionalmente | `PASS` para `retention` sin verifier de cuenta |
| offering declara ubicacion efectiva conocida | `PASS` para `data_location` sin allowlist |
| offering declara region fija permitida | `PASS` para `data_location` con allowlist |
| region configurable sin region efectiva | `UNKNOWN` |
| verifier futuro confirma region no permitida | `FAIL` |

La version inicial no incluye ningun verifier productivo. El contrato minimo
permite probar precedencia sin prometer soporte; `unavailable` se comunica hasta
que una API fiable sea investigada y aprobada.

Consecuencia intencional en v1:

```text
Anthropic/direct API + ZDR solo disponible, no garantizado para esta forma de consumo
  -> retention=UNKNOWN -> BLOCK

offering estructurado que garantiza ZDR incondicionalmente
  + no_training=PASS + data_location=PASS
  -> retention=PASS -> ALLOW
```

El primer resultado no es una carencia accidental del verifier: es la aplicacion
fail-closed de la diferencia entre capacidad ofrecida y garantia aplicable al
offering concreto.

## 8. Algoritmo de decision

```text
evaluate(target, policy, now):
  if target.execution == local:
    return NOT_APPLICABLE para las 3 restricciones

  evidence = source.lookup(target)       # cache local exclusivamente en v1
  account = unavailable                  # v1; contrato preparado para futuro

  no_training = evaluate_no_training(evidence, account, now)
  retention = evaluate_retention(evidence, account, now)
  location = evaluate_known_location(evidence, account, policy.allowed_regions, now)

  if all(state == PASS):
    return PASS + PrivacyAuthorization
  return BLOCK                           # FAIL o UNKNOWN
```

No se permite que `NOT_APPLICABLE` satisfaga una restriccion remota. Los
evaluadores son funciones puras y separadas porque entrenamiento, retencion y
ubicacion no tienen la misma semantica.

## 9. Integracion generation/repair

`AskService` recibe `privacy_preflight` y `inference_target` por inyeccion. Tras
los returns locales llama:

```text
authorization = privacy_preflight.authorize(target, strict_policy)
```

Si bloquea, registra metricas RAG locales existentes como operacion sin LLM y
retorna/eleva un error seguro tipado. Si pasa, generation recibe la autorizacion.
`_generate_with_observability(prompt, stage, authorization)` valida que:

- el target fingerprint coincide;
- la politica coincide;
- decision es `PASS` para remoto o `NOT_APPLICABLE` para local;
- pertenece al mismo operation ID.

Repair reutiliza exactamente el mismo objeto. No hay segundo registry lookup,
pero la autorizacion tampoco se guarda para otro `ask`. Si en el futuro un ask
cambia de provider a mitad de operacion, debe reautorizar antes del nuevo egress;
H3.2 no introduce tal cambio.

## 10. CLI y errores

Salida normal permitida:

```text
Privacy preflight: BLOCKED
no_training : PASS
retention   : UNKNOWN
location    : PASS
No se envio contexto al proveedor remoto.
```

En `PASS`, la salida normal puede limitarse a una linea solo cuando el usuario
solicita diagnostico; los logs conservan el evento. `--debug` agrega:

```text
privacy_preflight=PASS
execution=remote provider=synthetic platform=direct_api offering=standard
no_training=PASS source=external_registry verified_at=...
retention=PASS source=external_registry scope=offering verified_at=...
data_location=PASS source=provider_configuration region=region-sintetica-1
cache_status=valid source_version=...
```

Codigos propuestos:

- `PRIVACY_POLICY_BLOCKED`: evidencia `FAIL`;
- `PRIVACY_EVIDENCE_UNKNOWN`: evidencia insuficiente/ambigua;
- `PRIVACY_REGISTRY_UNAVAILABLE`: comando refresh no pudo obtener metadata;
- `PRIVACY_CACHE_INVALID` / `PRIVACY_CACHE_EXPIRED`;
- `PRIVACY_TARGET_INVALID`;
- `PRIVACY_ACCOUNT_VERIFICATION_FAILED`.

Todos resultan en cero requests LLM. La CLI usa exit code 1 para bloqueo/error
operativo, 2 para configuracion invalida y 130 para interrupcion, coherente con
H1.2. Nunca imprime cuerpos del registry/API, tokens o secretos.

## 11. Observabilidad y privacidad

Evento agregado `privacy_preflight_finished`:

```text
result=pass|block|not_applicable
execution=local|remote provider=... platform=... offering=...
no_training=... retention=... data_location=...
cache_status=... evidence_age_seconds=...
account_verifier=unavailable
```

Se omiten modelo por default en logs de privacidad si no es necesario, region
cuando la politica del entorno la considere sensible, URLs, payloads y valores
de credenciales. `--debug` puede mostrar solo IDs publicos ya aprobados. El
preflight nunca recibe `PromptComposition`; esta separacion se prueba con spies.

## 12. Impacto en componentes existentes

- `config.py`: settings y validacion minima de target/privacy.
- `domain/ports.py` o `domain/privacy.py`: contratos pequeños, sin HTTP.
- `application/privacy.py`: evaluacion y autorizacion.
- `application/rag.py`: un gate y un argumento de autorizacion en el wrapper de
  generacion; retrieval/contexto/validator permanecen iguales.
- `cli.py`: composicion, comando refresh explicito, errores y salida debug.
- infraestructura: registry/cache; verificadores quedan fuera de v1.
- `barbarion.example.toml`: requisitos, no afirmaciones del proveedor.

No se modifica la firma publica de `LlmProviderPort.generate()`: el guard vive
en aplicacion, antes del adaptador. Esto minimiza impacto y mantiene los providers
directos.

## 13. Riesgos y mitigaciones

| Riesgo | Mitigacion |
|---|---|
| Registry desactualizado o comprometido | TTL, version/integridad, fail-closed y fuente reemplazable |
| Confundir capability con cuenta | modelos y evaluadores separados; condicional -> `UNKNOWN` |
| Ollama cloud tratado como local | derivacion por metadata/transporte; ambiguedad -> override o BLOCK |
| Lookup correlacionado con una pregunta | snapshot completo/cache y cero contenido/query hashes |
| Indisponibilidad bloquea trabajo remoto | cache valida y refresh explicito; nunca stale permisivo |
| Repair evade el gate | autorizacion obligatoria en wrapper comun generation/repair |
| Abstracciones prematuras | dos puertos con responsabilidades distintas, sin plugin framework |
| Region demasiado simplificada | comparacion canonica exacta; sin jerarquias legales inferidas |
| Ruptura H3.1 | golden prompts, budgets y regresion completa |

## 14. Trade-offs y evoluciones futuras

- `strict = ZDR efectivo` es deliberadamente fuerte y puede bloquear la mayoria
  de cuentas sin evidencia suficiente. Perfiles adicionales requieren una spec
  posterior.
- TTL 24 h equilibra actualidad y operacion offline, pero sigue siendo politica
  configurable; nunca supera la expiracion de fuente.
- El snapshot completo usa mas disco que un lookup puntual, a cambio de menor
  correlacion y mayor disponibilidad.
- No se firma criptograficamente el snapshot salvo que la fuente ofrezca una
  cadena verificable; integridad local no demuestra veracidad legal.
- Verificadores de cuenta, contratos privados, DLP y attestation quedan para
  evoluciones separadas y solo con APIs/evidencia reales.
