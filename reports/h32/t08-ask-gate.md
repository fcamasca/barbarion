# H3.2-T08 - Gate real en AskService

## Frontera integrada

El flujo efectivo queda:

```text
retrieval -> seleccion/budget H3.1
  -> insufficient/no-llm: return local
  -> resolve InferenceTarget
  -> PrivacyPreflightService.authorize
     -> BLOCK: error seguro
     -> PASS/NOT_APPLICABLE: PrivacyAuthorization
  -> PromptBuilder.build
  -> _generate_with_observability(authorization obligatoria)
```

La composicion de presupuesto H3.1 sigue usando `PromptBuilder.compose` para
medir candidatos antes del gate. El prompt productivo, su debug y sus logs solo
se crean despues de obtener autorizacion.

## PrivacyPreflightService

El servicio combina exclusivamente:

- `InferenceTarget` resuelto por T03;
- `PrivacyPolicySource` local valido de T06, cuando existe;
- evaluadores strict de T04;
- `UnavailableAccountPrivacyVerifier` de T07;
- `PrivacyPolicy` strict;
- `PrivacyAuthorization` de T02.

Local produce evaluaciones `NOT_APPLICABLE` sin consultar source ni verifier.
Unknown produce `BLOCK`. Remoto consulta la fuente local y combina observaciones
de cuenta; ausencia o error de cualquiera se degrada a evidencia vacia y nunca
autoriza.

## Invariantes demostradas

| Caso | Resultado | `PromptBuilder.build` | `generate` |
|---|---|---:|---:|
| local | `NOT_APPLICABLE` | 1 | 1 |
| remoto, tres PASS | autorizacion | 1 | 1 |
| no-training FAIL | `BLOCK` | 0 | 0 |
| retention UNKNOWN | `BLOCK` | 0 | 0 |
| location UNKNOWN | `BLOCK` | 0 | 0 |
| execution unknown | `BLOCK` | 0 | 0 |
| `--no-llm` | return local | 0 | 0 |
| evidencia insuficiente | return local | 0 | 0 |

`_generate_with_observability` exige un `PrivacyAuthorization` posicionalmente
obligatorio y valida su tipo antes de registrar metricas o llamar al provider.
Generation y repair reciben la misma autorizacion. T09 reforzara operation ID,
fingerprints, identidad y reglas de reutilizacion.

## Composicion y regresion

La composicion CLI lee `PrivacySnapshotCache` una vez y nunca refresca. Cache no
valida implica source ausente y bloqueo remoto. Produccion usa exclusivamente el
verifier `unavailable`. El bloqueo CLI retorna codigo operativo 1 con mensaje
seguro y sin traceback.

Las pruebas historicas de Anthropic que ejercitan HTTP posterior al gate
inyectan explicitamente una fuente PASS sintetica. Los baselines Ollama declaran
`execution=local`; no existe bypass o default permisivo en produccion.

## Fuera de alcance

T08 no agrega comando de refresh, HTTP del registry, configuracion `[privacy]`,
UX final, observabilidad detallada ni validacion completa de reutilizacion para
repair. Estos puntos permanecen en T09/T10.

## Pruebas

- TP-038..043 y retornos locales: 9 pruebas del flujo real.
- Integracion de bloqueo CLI: 1 prueba.
- Baseline T01/H3.1: prompts y comportamiento previo conservados.
- Suite completa: 1039 aprobadas, 14 omitidas.
