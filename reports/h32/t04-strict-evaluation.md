# H3.2-T04 - Evaluadores puros strict

## Estado

Completada el 2026-08-07 sobre los contratos H3.2-T02 y el target H3.2-T03.

## Alcance implementado

Cuatro funciones puras operan exclusivamente sobre objetos en memoria:

```text
evaluate_no_training(evidence, evaluated_at)
evaluate_retention(evidence, evaluated_at)
evaluate_data_location(evidence, policy, evaluated_at)
aggregate_remote_result(target, policy, evaluated_at, evaluations)
```

No crean ni consultan configuracion, cuentas, registry, cache, filesystem, red,
HTTP, credenciales o `AskService`. Los tests construyen `PrivacyEvidence`
directamente.

## Reglas congeladas

### No training

| Evidencia aplicable | Estado |
|---|---|
| garantia incondicional de no-training | `PASS` |
| uso para training confirmado | `FAIL` |
| opt-out disponible | `UNKNOWN` |
| evidencia condicional, ausente, expirada, ambigua o conflictiva | `UNKNOWN` |

### Retention

| Evidencia aplicable | Estado |
|---|---|
| ZDR efectivo o retencion `0` | `PASS` |
| retencion positiva confirmada | `FAIL` |
| ZDR solo disponible | `UNKNOWN` |
| evidencia condicional, ausente, expirada, ambigua o conflictiva | `UNKNOWN` |

### Data location

| Evidencia aplicable | Estado |
|---|---|
| ubicacion unica conocida, sin allowlist | `PASS` |
| ubicacion unica incluida en allowlist | `PASS` |
| ubicacion conocida fuera de allowlist | `FAIL` |
| ubicacion ausente, condicional, expirada o conflictiva | `UNKNOWN` |

### Agregacion remota

```text
PASS + PASS + PASS -> PASS
cualquier otra combinacion de PASS/FAIL/UNKNOWN -> BLOCK
```

La matriz parametrizada ejecuta las 27 combinaciones. El agregador rechaza un
target local o unknown para evitar usar accidentalmente la funcion remota fuera
de su contrato.

## Semantica de evidencia

Los valores minimos reconocidos son:

```text
no_training_guaranteed
training_confirmed
opt_out_available
zdr
zdr_available
retention days como entero no negativo
region como string canonico
```

La evidencia `conditional_on_account=true` se conserva para explicacion, pero no
es aplicable para producir PASS en T04. Una futura evidencia efectiva de cuenta
debera llegar ya normalizada por el contrato correspondiente; T04 no la obtiene.

## Pruebas

Suite pura focal:

```text
78 passed in 0.40s
```

Suite completa:

```text
1006 passed, 14 skipped in 104.52s
```

## Checkpoint de alcance

- source de politicas: no;
- registry/cache: no;
- timestamps de descarga: no;
- HTTP/credenciales/provider APIs: no;
- cambios en `AskService`: no;
- decision remota distinta de all-PASS: no;
- T05 puede normalizar evidencia hacia estos valores sin cambiar la logica.
