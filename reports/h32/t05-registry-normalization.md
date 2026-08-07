# H3.2-T05 - Registry y normalizacion conservadora

## Fuente investigada

- Fuente: AI Provider Trust Registry (`https://aiprovidertrust.com/data.json`).
- Snapshot observado: `generated = 2026-08-07`.
- Formato: JSON machine-readable por offering y dimension.
- Uso declarado: gratuito con atribucion y enlace de regreso.
- Autoridad: indice de evidencia publica con fuente y fecha por celda; su propia
  metodologia aclara que no es una determinacion legal o de cumplimiento.

El payload real contiene las dimensiones estructuradas
`training_on_customer_data`, `retention_zdr` y `data_residency`, con `value`,
`confidence`, `source` y `verified`. Los campos libres `summary`, `notes`,
`evidence` y `caveat` no participan en la normalizacion.

## Decision de contrato

El registry describe principalmente capability del offering, no configuracion
efectiva de una cuenta o peticion. El adaptador aplica estas reglas cerradas:

| Celda estructurada | Evidencia normalizada | Evaluacion strict esperada |
|---|---|---|
| `training_on_customer_data=yes_public`, confianza alta y scope exacto | `no_training_guaranteed` | puede producir `PASS` |
| `retention_zdr=yes_public/yes_sales_gated/yes_platform_only` | `zdr_available`, condicional | `UNKNOWN` |
| `data_residency=yes_public/yes_sales_gated/yes_platform_only` | `data_residency_available`, condicional | `UNKNOWN` |

No se analizan `notes`, `evidence` o `caveat`, no se usa un LLM y no existen
heuristicas de texto. Valores parciales, ambiguos, conflictivos, de confianza no
alta o no reconocidos no inventan evidencia favorable.

La resolucion usa `provider/platform/offering` de mas especifico a general. Un
modelo nuevo hereda el offering sin cambios de codigo. Solo un bloque
estructurado `model_exceptions` publicado en el snapshot puede sobreescribirlo;
el snapshot real observado no publica actualmente ese bloque.

## Privacidad y alcance

`PrivacyPolicySource.lookup()` recibe exclusivamente `InferenceTarget`, que
contiene identidad tecnica publica. No recibe pregunta, prompt, chunks, paths,
credenciales ni hashes del corpus. La fixture de pruebas es sintetica y sus
canarios de texto libre se descartan.

T05 no implementa HTTP, descarga, cache, TTL, escritura atomica, refresh,
configuracion ni integracion con `AskService`. El adaptador recibe en memoria un
snapshot ya obtenido; T06 definira refresh explicito y persistencia offline.

## Verificacion

- Pruebas focales T02/T04/T05: 72 aprobadas.
- Suite completa: 1013 aprobadas, 14 omitidas.
- Resultado funcional intencional para Anthropic API con ZDR solo disponible:
  `no_training=PASS`, `retention=UNKNOWN`, `data_location=UNKNOWN`, por tanto
  inferencia remota bloqueada.
