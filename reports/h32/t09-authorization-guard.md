# H3.2-T09 - Blindaje de PrivacyAuthorization

## Vinculacion

Una autorizacion solo es valida cuando coinciden simultaneamente:

- `operation_id` normalizado;
- `InferenceTarget.fingerprint`;
- `PrivacyPolicy.fingerprint`.

Los fingerprints existentes usan JSON canonico, claves ordenadas y SHA-256.
Incluyen toda la identidad tecnica del target y el perfil/regiones de policy,
pero nunca pregunta, prompt, contenido, query ni evidencia del corpus.

`PrivacyAuthorization.is_valid_for()` compara esa vinculacion dentro del
proceso. No pretende autenticidad criptografica frente a un actor que controle
el runtime.

## Guard generativo

`AskService._generate_with_observability()` requiere explicitamente:

```text
authorization
operation_id
target efectivo
policy efectiva
```

El guard valida los cuatro valores antes de calcular metricas, emitir logs LLM o
llamar al provider. Ausencia, tipo falso o mismatch lanza
`InvalidPrivacyAuthorizationError`.

`ask()` crea un operation ID opaco una vez, ejecuta un unico preflight y pasa la
misma autorizacion, operation ID, target y policy a generation y al unico repair.

## Casos demostrados

| Caso | Resultado | Llamadas provider |
|---|---|---:|
| generation con vinculacion exacta | permitida | 1 |
| generation + repair, misma operacion | permitidas, un preflight | 2 |
| authorization ASK-001 usada por ASK-002 | rechazo | 0 |
| Anthropic/direct usada contra Ollama Cloud | rechazo | 0 |
| allowed_regions A usada con policy B | rechazo | 0 |
| `authorization=None` | rechazo | 0 |
| objeto que copia campos de authorization | rechazo por tipo | 0 |
| authorization local NOT_APPLICABLE usada contra remoto | rechazo | 0 |
| intento de emitir authorization desde BLOCK | constructor lo impide | 0 |

La construccion cerrada y el chequeo de tipo protegen bypasses y errores de
programacion ordinarios. Manipulacion deliberada mediante primitivas internas de
Python queda fuera del threat model, tal como corresponde a H3.2.

## Verificacion

- Pruebas focales T09 junto al gate/dominio: 30 aprobadas.
- Baseline de prompts y repair H3.1: 4 aprobadas.
- Suite completa: 1048 aprobadas, 14 omitidas.
