# H3.2-T03 - Resolucion de la frontera de inferencia

## Estado

Completada el 2026-08-07 sobre el dominio puro H3.2-T02.

## Resultado

La funcion pura `resolve_inference_target(settings)` produce:

| Transporte/configuracion demostrable | execution | platform |
|---|---|---|
| Anthropic directo | `remote` | `direct_api` |
| Ollama `https://ollama.com` | `remote` | `ollama_cloud` |
| Ollama ambiguo + `llm.execution = "local"` | `local` | `local_runtime` |
| Ollama ambiguo + `llm.execution = "remote"` | `remote` | `ollama_cloud` |
| Ollama ambiguo sin override | `unknown` | `null` |

La deteccion del endpoint cloud exige esquema HTTPS y hostname exacto
`ollama.com`; subdominios impostores, HTTP y otros hosts no se promueven a
`remote/ollama_cloud` automaticamente.

## Decision sobre Ollama local y cloud

La documentacion oficial confirma dos caminos cloud:

- acceso directo mediante `https://ollama.com/api`;
- offload automatico desde el daemon local para modelos cloud.

Referencias publicas:

- https://docs.ollama.com/cloud
- https://docs.ollama.com/api/authentication
- https://docs.ollama.com/api-reference/show-model-details

`/api/show` no documenta un campo estructurado que demuestre si la ejecucion
sera local o cloud. Por ello, una URL loopback solo demuestra que Barbarion habla
con un daemon local, no donde ese daemon ejecutara el prompt. Clasificar loopback
como local seria inseguro.

El override `llm.execution` es opcional y solo necesario ante esa ambiguedad. No
se solicita `platform`: Barbarion la deriva de provider, endpoint y override.

## Invariante de modelo

El resolver nunca inspecciona `settings.llm.model` para decidir execution o
platform. Las pruebas parametrizadas demuestran que:

```text
localhost + "ordinary-local-name" -> unknown
localhost + "obvious:cloud"       -> unknown

execution=local + cualquier nombre -> local/local_runtime
https://ollama.com + cualquier nombre -> remote/ollama_cloud
```

Esto evita una tabla por modelo y tambien evita depender de sufijos como
`:cloud`, que son nombres y no evidencia estable de transporte.

## Configuracion y compatibilidad

`LlmSettings.execution` admite `local`, `remote` o ausencia (`auto`).
`config show` expone el valor efectivo no sensible. Anthropic rechaza una
declaracion local contradictoria; un endpoint directo de Ollama Cloud tambien
rechaza `execution=local` durante resolucion.

Las configuraciones legacy siguen cargando y los providers conservan su
comportamiento. Como el preflight aun no se integra, T03 no bloquea ni modifica
ninguna llamada LLM existente.

## Pruebas

Suite focal de configuracion, CLI, factory y resolucion:

```text
201 passed in 42.59s
```

Suite completa:

```text
953 passed, 14 skipped in 190.25s
```

## Checkpoint de alcance

- politicas/evaluadores strict: no;
- registry o cache: no;
- IO adicional o probes Ollama: no;
- cambios en `AskService`: no;
- inferencia por nombre de modelo: no;
- T04 puede consumir `InferenceTarget` sin reabrir la resolucion de frontera.
