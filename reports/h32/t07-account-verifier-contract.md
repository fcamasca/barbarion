# H3.2-T07 - Contrato futuro de verificacion de cuenta

## Alcance implementado

T07 reserva un contrato inmutable con cuatro resultados:

- `verified`: observaciones estructuradas disponibles;
- `partial`: solo algunas propiedades fueron observadas;
- `unavailable`: no existe observacion de cuenta;
- `error`: fallo tipado, sin evidencia ni cuerpo de transporte.

`AccountPrivacyVerificationResult` no decide politica. La evidencia aceptada
debe usar `scope=account` y `source_kind=account_verifier`. Los estados
`unavailable` y `error` no pueden contener evidencia; `verified` y `partial`
requieren al menos una observacion estructurada.

## Produccion v1

`UnavailableAccountPrivacyVerifier` es la unica implementacion productiva de
H3.2 v1. Siempre devuelve:

```text
status = unavailable
evidence = ()
reason_code = account_verifier_unavailable
```

No resuelve configuracion, credenciales o secretos y no realiza IO.

## Fake contractual

`InMemoryAccountPrivacyVerifier` devuelve un resultado construido en memoria y
registra solo el `InferenceTarget` publico observado. Existe para demostrar que
T04 puede combinar evidencia futura mas especifica:

| Capability | Observacion fake de cuenta | Resultado T04 |
|---|---|---|
| ZDR disponible | unavailable | retention `UNKNOWN` |
| ZDR disponible | ZDR habilitado | retention `PASS` |
| no-training garantizado | training confirmado | `UNKNOWN` por conflicto |
| cualquiera | error sin evidencia | restricciones `UNKNOWN`, agregado `BLOCK` |

El ajuste explicativo de T04 conserva capabilities condicionales en el reason:
`zdr_available_not_effective` y `training_opt_out_only`. No las convierte en
evidencia aplicable ni en `PASS`.

## Limite verificado

T07 no contiene:

- API de proveedor o adaptador productivo de cuenta;
- API keys, credenciales o resolucion de secretos;
- HTTP, AWS/Bedrock probes o logica Anthropic;
- configuracion del verifier;
- integracion con cache, CLI o `AskService`.

## Pruebas

- Contrato focal T02/T04/T07: 70 aprobadas.
- Suite completa: 1029 aprobadas, 14 omitidas.
- TP-033..037 cubren evidencia account sintetica, produccion unavailable,
  capability sin habilitacion, conflicto y error fail-closed.
