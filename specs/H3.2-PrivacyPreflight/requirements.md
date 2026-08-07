# H3.2 - Privacy Preflight para inferencia remota: Requisitos

## 1. Proposito

H3.2 impide que `barbarion ask` transmita una pregunta, instrucciones o contexto
RAG a un destino remoto cuya privacidad no pueda demostrarse con evidencia
estructurada suficiente para la politica exigida por Barbarion.

La evolucion agrega un gate local, explicable y fail-closed entre la seleccion
del contexto y la primera invocacion generativa. No agrega un proxy: despues de
un `PASS`, `LlmProviderPort` continua llamando directamente al proveedor
configurado. Una fuente externa solo puede recibir identificadores publicos del
destino (`provider`, `platform`, `offering`) y nunca contenido del corpus.

H3.2 distingue tres planos:

1. **Provider capability:** lo que una fuente estructurada declara para el
   proveedor, plataforma u offering.
2. **Account configuration:** lo efectivamente habilitado en la cuenta, solo si
   una API fiable permite comprobarlo.
3. **Execution:** la llamada directa que realiza el adaptador LLM vigente.

No se interpreta `ZDR available` como `ZDR enabled`. Una propiedad obligatoria
no demostrada queda `UNKNOWN` y bloquea la inferencia remota.

## 2. Alcance

### Incluido

- clasificacion explicita del destino como `local` o `remote`;
- identidad no sensible por `provider`, `platform` y `offering`, con excepcion
  de modelo solo cuando la evidencia estructurada la declare;
- perfil inicial `strict` para `no_training`, `retention` y `data_location`;
- ubicacion de procesamiento conocida como requisito obligatorio y una lista
  organizacional opcional de regiones permitidas;
- fuente desacoplada de politicas machine-readable;
- cache local con procedencia, verificacion y expiracion;
- contrato minimo futuro para configuracion de cuenta, sin verificador
  productivo ni verificaciones ficticias en v1;
- una evaluacion inmutable por operacion `ask`, reutilizada por generation y
  repair;
- bloqueo previo a toda invocacion LLM remota;
- salida compacta, debug explicable y logs sin contenido;
- pruebas offline con registry, cuentas, providers y corpus sinteticos;
- documentacion de operacion y una tarea final separada de aceptacion.

### Excluido

- proxy, gateway, OpenRouter o routing de prompts por terceros;
- fallback automatico a otro proveedor local o remoto;
- seleccion automatica del proveedor mas seguro;
- tabla manual de politicas por modelo;
- scraping libre de paginas legales o interpretacion legal mediante LLM;
- deteccion de mentiras, auditoria contractual o garantia criptografica;
- DLP, PII, secretos, clasificacion del corpus o confidential computing;
- remote attestation, motor GRC o compliance generico;
- cambios a retrieval, ranking, H3.1, prompts, token budgets,
  `CitationValidator` o la regla de no entregar respuestas sin grounding;
- persistencia de preguntas, prompts, respuestas, chunks o decisiones con
  contenido;
- implementacion dentro de esta spec.

## 3. Evidencia de partida

- `AskService.ask()` ejecuta retrieval, seleccion y presupuesto local antes de
  construir el prompt.
- La primera frontera de egress de `ask` es
  `AskService._generate_with_observability()` ->
  `LlmProviderPort.generate()`; repair recorre la misma funcion.
- La factoria vigente selecciona `OllamaLlmProvider` o
  `AnthropicLlmProvider`; el nombre de modelo vive en configuracion.
- Ollama es el default, pero el identificador `ollama` por si solo no demuestra
  que la ejecucion sea local: un modelo o servicio Ollama cloud tambien requiere
  preflight.
- Anthropic usa su API directa y no tiene fallback. `--no-llm` retorna antes de
  construir una solicitud generativa.
- H3.1 conserva `baseline_v1`, `optimized_v1`, presupuesto de contexto 4500 y
  un presupuesto opcional e independiente para generation y repair.
- Los logs actuales registran proveedor, modelo, etapa y tamaños, sin persistir
  prompts ni respuestas.

## 4. Convenciones

- **Must:** obligatorio para aceptar H3.2.
- **Should:** requerido salvo limitacion documentada y aprobada.
- **Politica requerida:** condicion que debe resultar `PASS` para permitir una
  inferencia remota.
- **Evidencia valida:** registro estructurado, no expirado, aplicable a la
  identidad efectiva y con procedencia/verificacion conservadas.
- **Evidencia de cuenta:** dato obtenido por una API fiable del proveedor para
  la cuenta efectiva; una capacidad comercial no la sustituye.
- Los estados por restriccion son `PASS`, `FAIL`, `UNKNOWN` y
  `NOT_APPLICABLE`. No se agrega `CONDITIONAL`: una condicion se resuelve con
  evidencia de cuenta a `PASS`/`FAIL`, o queda `UNKNOWN`.
- El resultado agregado es `PASS`, `BLOCK` o `NOT_APPLICABLE`.
- Mensajes al usuario en espanol; IDs, claves TOML y codigos tecnicos en ingles.

## 5. Requisitos funcionales

### H3.2-REQ-001 - Identificar la frontera efectiva de inferencia (Must)

Antes de evaluar politicas, Barbarion debe resolver un descriptor inmutable con
`execution`, `provider`, `platform`, `offering` y modelo informativo. Barbarion
deriva `execution` y `platform` del adaptador, endpoint y metadata operativa
fiable siempre que sea posible; no son campos ordinariamente exigidos al
usuario. No se infiere privacidad del nombre del modelo. Anthropic directo se
resuelve como remoto. Ollama local/cloud se distingue mediante metadata del
runtime o transporte, no con una tabla de modelos. Solo ante una ambiguedad que
el runtime no pueda resolver se admite un override explicito; sin derivacion ni
override seguro, el destino queda desconocido y se bloquea.

### H3.2-REQ-002 - Omitir el preflight remoto para ejecucion local (Must)

Un destino demostrado como local produce restricciones `NOT_APPLICABLE`,
resultado agregado `NOT_APPLICABLE` y continua sin consultar registry ni
verificador de cuenta. Esta omision no altera retrieval, contexto o generacion.

### H3.2-REQ-003 - Configurar lo que Barbarion exige (Must)

La configuracion describe requisitos, no afirmaciones sobre el proveedor. La
primera version admite `remote_inference = "strict"` y `allowed_regions`
opcional. Se decide explicitamente que **`strict` significa ZDR efectivo**:
no-training aplicable, retencion efectiva cero y ubicacion efectiva conocida.
Si `allowed_regions` se configura, la ubicacion debe pertenecer a la lista; si
se omite, cualquier ubicacion estructurada y verificada satisface
`data_location`, pero una ubicacion desconocida siempre bloquea. No se exponen
inicialmente booleanos independientes ni perfiles permisivos.

### H3.2-REQ-004 - Obtener capability desde una fuente estructurada (Must)

La aplicacion debe depender de un contrato `PrivacyPolicySource`, no del JSON o
endpoint de un registry concreto. El lookup solo recibe la identidad publica del
destino. Debe devolver evidencia normalizada, version, procedencia,
`verified_at`, `expires_at` y, si existe, alcance/excepcion de modelo declarada
por la propia fuente. La ausencia, ambiguedad o conflicto se normaliza como
`UNKNOWN`; una pagina libre o inferencia de un LLM no es evidencia.

### H3.2-REQ-005 - No hardcodear politicas por modelo (Must)

La resolucion normal se realiza por `provider/platform/offering`. Un modelo
nuevo bajo el mismo offering hereda la evidencia aplicable sin cambios de
codigo. Solo se consulta una excepcion de modelo si el registry la publica de
forma explicita. Barbarion no contiene `if model == ...` ni un catalogo manual
de politicas.

### H3.2-REQ-006 - Verificar configuracion efectiva cuando sea posible (Must)

Se reserva un contrato minimo y futuro `AccountPrivacyVerifier` capaz de aportar
observaciones estructuradas de cuenta. H3.2 v1 no implementa ni invoca un
verificador productivo hasta identificar una API fiable y documentada. Si no
existe o una propiedad no es observable, el estado es `unavailable` y la
restriccion se decide con evidencia suficiente restante. Una capability
condicional (`ZDR available`) sin confirmacion de cuenta produce `UNKNOWN`, no
`PASS`.

Esta consecuencia es intencional: Anthropic/direct API u otro destino que solo
publique disponibilidad de ZDR queda `retention=UNKNOWN` y se bloquea. En cambio,
si la evidencia estructurada del offering concreto garantiza ZDR de manera
incondicional, `retention=PASS` puede resolverse sin verifier de cuenta.

### H3.2-REQ-007 - Evaluar las tres restricciones con semantica propia (Must)

- `no_training`: `PASS` solo si evidencia aplicable declara que inputs y outputs
  no se usan para entrenamiento bajo el offering efectivo; opt-out disponible
  sin confirmacion efectiva queda `UNKNOWN`.
- `retention`: `PASS` bajo `strict` solo con ZDR/retencion efectiva cero; ZDR
  disponible pero no habilitado queda `UNKNOWN`; retencion positiva confirmada
  es `FAIL`.
- `data_location`: `PASS` solo si la ubicacion efectiva esta verificada; cuando
  existe `allowed_regions`, ademas debe pertenecer a la lista. Ubicacion
  verificada no permitida es `FAIL`; ubicacion no determinada es `UNKNOWN`.

La evaluacion conserva evidencia y razon por restriccion. No usa un estado
`CONDITIONAL` publico.

### H3.2-REQ-008 - Aplicar decision agregada fail-closed (Must)

Para un destino remoto, las tres restricciones obligatorias deben ser `PASS`.
Cualquier `FAIL` o `UNKNOWN` produce `BLOCK`. El bloqueo ocurre antes de llamar
`generate()` y garantiza cero requests generativos, sin fallback automatico.
Un error o indisponibilidad del propio preflight nunca se convierte en permiso.

### H3.2-REQ-009 - Usar cache local con vigencia demostrable (Must)

El registry se consume como snapshot/registro cacheable, evitando una consulta
por cada `ask`. La cache conserva identidad, payload normalizado o snapshot,
version, fuente, `verified_at`, `fetched_at`, `expires_at` e integridad. En v1,
`ask` solo consume cache local y nunca refresca el registry. Sin cache valida la
evidencia queda `UNKNOWN`, se bloquea y se indica ejecutar la operacion explicita
de refresh. Una cache expirada nunca autoriza inferencia. El refresh separado
facilita proxies, sincronizacion controlada y ausencia de correlacion temporal.

### H3.2-REQ-010 - Proteger generation y repair con una evaluacion (Must)

`ask` debe evaluar una vez despues de resolver el proveedor y seleccionar el
contexto, pero antes de la primera llamada LLM. Un `PASS` inmutable y acotado a
la operacion autoriza generation y su unico repair con la misma identidad y
politica. Si identidad o politica cambian, el permiso no es reutilizable. Repair
no realiza su propio lookup ni puede invocar el proveedor sin un permiso valido.

### H3.2-REQ-011 - Mantener privada la consulta de preflight (Must)

Registry, cache updater y el futuro account verifier reciben solo los campos minimos que
su contrato exige. Nunca reciben pregunta, prompt, respuesta rechazada, chunks,
codigo, rutas, IDs de fuentes, simbolos, formulas, business IDs, hashes derivados
del contenido, DB ni configuracion completa. Las pruebas deben observar y negar
esos campos.

### H3.2-REQ-012 - Explicar sin filtrar contenido (Must)

Modo normal muestra resultado agregado y, al bloquear, los tres estados y la
garantia `No se envio contexto al proveedor remoto`. `--debug` agrega identidad
publica, razones, tipo de fuente, version, timestamps, estado de cache y
disponibilidad del verificador; no muestra payloads libres, secretos ni contenido
del corpus. Logs estructurados contienen los mismos metadatos seguros.

### H3.2-REQ-013 - Preservar `--no-llm` y evidencia insuficiente (Must)

`ask --no-llm` y una respuesta local de evidencia insuficiente no consultan
registry, account verifier, credenciales ni proveedor LLM. Conservan formatos,
estado y codigos actuales.

### H3.2-REQ-014 - Preservar el pipeline H3/H3.1 (Must)

No cambian retrieval, ranking, merge H4.1, seleccion, IDs F1..Fn, prompts,
presupuestos de 4500 ni `input_token_budget_est`, generation, repair,
`CitationValidator`, formatos o persistencia RAG. Tras `PASS`, el mismo prompt se
envia al mismo adaptador directo actual. Las respuestas rechazadas siguen sin
entregarse.

### H3.2-REQ-015 - Errores seguros y accionables (Must)

Configuracion invalida falla antes de red. Refresh inaccesible, cache ausente o
expirada, evidencia conflictiva, provider desconocido y futuro verifier fallido se
presentan mediante codigos estables sin traceback ni contenido. Un bloqueo de
politica se distingue de un fallo del proveedor y usa exit code operativo
documentado. Ctrl+C durante refresh conserva 130 y no llama al LLM.

### H3.2-REQ-016 - Documentar y aceptar separadamente (Must)

La implementacion posterior actualiza configuracion de ejemplo, CLI, README,
arquitectura, decisiones, roadmap/evolucion y operacion de cache. Todos los
ejemplos son sinteticos. `acceptance.md` solo se crea en la ultima tarea, despues
de ejecutar el plan de pruebas y obtener revision humana.

## 6. Requisitos no funcionales

### H3.2-NFR-001 - Privacidad por construccion

El preflight se ejecuta localmente y su unico egress opcional son identificadores
publicos de proveedor. No persiste ni registra contenido de usuario o corpus.

### H3.2-NFR-002 - Fail-closed determinista

La misma politica, identidad, evidencia y hora de evaluacion producen la misma
decision. Errores, ambiguedad y ausencia de evidencia nunca elevan confianza.

### H3.2-NFR-003 - Desacoplamiento minimo

El contrato de fuente y la extension futura de verificacion pertenecen al
dominio/aplicacion; formatos HTTP y cache al adaptador de infraestructura. No se
crea un framework de plugins, GRC ni un segundo pipeline generativo.

### H3.2-NFR-004 - Disponibilidad offline

Una cache valida permite operar sin Internet. La indisponibilidad con evidencia
invalida bloquea de forma rapida y explicable, sin degradacion insegura.

### H3.2-NFR-005 - Rendimiento

El camino con cache valida agrega solo lectura local y evaluacion acotada. No hay
lookup remoto por generation y repair ni consulta por cada chunk/modelo.

### H3.2-NFR-006 - Trazabilidad

Cada estado referencia tipo de evidencia, fuente, alcance y vigencia. No se
presenta capability como configuracion efectiva ni estimacion como verificacion.

### H3.2-NFR-007 - Compatibilidad

Se preservan Ollama local, Ollama cloud derivado como remoto, Anthropic,
`--no-llm`, H3, H3.1, H4.1 y la factoria cerrada. Las configuraciones legacy
siguen cargando, pero un daemon Ollama ambiguo resuelve `unknown` hasta declarar
el override minimo; no se sacrifica fail-closed para conservar una suposicion
historica de localidad.

### H3.2-NFR-008 - Datos publicables

Tests, fixtures, logs esperados y documentos solo contienen providers/evidencia
sinteticos o metadata publica, nunca nombres, rutas, formulas o codigo privados.

## 7. Criterio de listo para implementacion

- los cuatro documentos del spec son coherentes y trazables;
- la identidad local/remota no depende del nombre de modelo;
- `strict` y sus tres evaluadores tienen semantica no ambigua;
- cache valida/ausente/expirada y fallo del refresh explicito tienen resultado definido;
- capability y account configuration no se confunden;
- generation y repair quedan detras de una unica autorizacion por operacion;
- ninguna ruta de bloqueo puede llamar al proveedor;
- no se propone gateway, fallback ni cambios a H3.1/CitationValidator;
- no existe `acceptance.md` en esta fase.
