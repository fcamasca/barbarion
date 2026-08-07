# H3.2-T02 - Dominio puro de Privacy Preflight

## Estado

Completada el 2026-08-07 sobre la baseline H3.2-T01.

## Alcance implementado

Un unico modulo puro, `barbarion.domain.privacy`, incorpora:

- `InferenceTarget` e `InferenceExecution` (`local`, `remote`, `unknown`);
- `PrivacyConstraint` (`no_training`, `retention`, `data_location`);
- `EvaluationState` (`pass`, `fail`, `unknown`, `not_applicable`);
- `PrivacyEvidence` con valores escalares inmutables y vigencia UTC;
- `ConstraintEvaluation`;
- `PrivacyPolicy` con perfil `strict` y regiones opcionales;
- `PrivacyPreflightResult` con decision agregada derivada;
- `PrivacyAuthorization` inmutable y emitida solo desde un resultado permisivo.

No se implementaron configuracion, IO, registry, cache, CLI, composicion ni
integracion con `AskService`.

## Invariantes demostradas

```text
local
  todas las restricciones = NOT_APPLICABLE
  decision = NOT_APPLICABLE

remote
  PASS + PASS + PASS = PASS
  cualquier FAIL o UNKNOWN = BLOCK
  NOT_APPLICABLE = invalido

unknown
  decision = BLOCK
  no puede emitir PrivacyAuthorization
```

Un `PASS` remoto exige evidencia estructurada vigente para las tres
restricciones. Evidencia expirada o aun no vigente no puede producir permiso.

`PrivacyAuthorization` no tiene constructor publico normal. Se emite mediante
`PrivacyAuthorization.issue()` y queda vinculada exclusivamente a:

```text
operation_id
target_fingerprint
policy_fingerprint
```

Los fingerprints SHA-256 usan JSON canonico de la identidad tecnica o politica.
No incluyen pregunta, prompt, query, chunks, contenido ni evidencia del corpus.

## Pruebas

La suite focal incluyo dominio base, H3.2-T01, H3/H3.1, providers HTTP y CLI:

```text
168 passed in 16.99s
```

Las pruebas H3.2-T02 cubren TP-003..006: estados cerrados, agregacion local y
remota, inmutabilidad/fingerprints, bloqueo unknown, evidencia expirada,
identidad incompleta y modelos incoherentes.

## Checkpoint de alcance

- archivos productivos nuevos: `src/barbarion/domain/privacy.py`;
- configuracion modificada: no;
- `AskService` modificado: no;
- IO, HTTP, registry o cache: no;
- credenciales o provider APIs: no;
- T03 puede derivar targets sobre estos contratos sin alterar T02.
