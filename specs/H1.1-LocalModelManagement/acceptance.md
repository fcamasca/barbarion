# Aceptacion H1.1 - Gestion y Evaluacion de Modelos Locales

## Estado

**Estado tecnico y funcional:** aprobado con comparacion real pendiente por
condiciones del entorno.

H1.1 queda completado: administracion de modelos, validacion, dataset sintetico,
runner, scoring, agregacion y reportes fueron verificados mediante suite completa,
smoke instalado, integraciones con fakes y comprobaciones manuales contra Ollama
local. No se declara un modelo recomendado porque el entorno no permite una
comparacion real valida.

La limitacion externa no bloquea la aceptacion tecnica: solo existe un LLM
generativo instalado y ese modelo no supera actualmente la sonda exacta de
`generation_ready`. No se instalo otro modelo, no se falsearon resultados y no se
uso el modelo de embeddings como competidor.

## Version y entorno

- Fecha: 2026-07-20.
- Sistema operativo: Microsoft Windows 11 Pro `10.0.26200`.
- Rama: `feature/H1.1-LocalModelManagementAndEvaluation`.
- Revision evaluada: `c4caa9e` mas el cierre documental de T12.
- Barbarion: `0.6.0`, instalacion editable desde `.venv`.
- Python: `3.12.10`.
- Pytest: `8.4.2`.
- SQLite: `3.49.1`.
- Ollama: `0.32.1`.
- CPU: Intel Core i5-1035G1.
- RAM observable: 11.8 GB.
- GPU observable: Intel UHD Graphics.

No se registran hostname, usuario, variables de entorno, rutas personales ni
identificadores de hardware.

## Suite completa y regresion

Comando:

```powershell
.venv\Scripts\python.exe -m pytest --basetemp .pytest-tmp\h11-acceptance
```

Resultado:

```text
713 passed, 3 skipped in 104.98s
```

La corrida incluye unitarias, integraciones, golden files, smoke instalado y
regresion de H1-H5/H4.1. Las tres omisiones corresponden a condiciones opcionales
del entorno; no hubo fallas funcionales.

Smoke del entry point instalado, repetido de forma independiente:

```powershell
.venv\Scripts\python.exe -m pytest tests/smoke/test_cli_smoke.py --basetemp .pytest-tmp\h11-acceptance-smoke
```

Resultado:

```text
10 passed in 31.94s
```

La regresion demuestra que H1.1 no modifica retrieval, prompts productivos,
validador de citas, embeddings, SQLite de conocimiento, ingenieria inversa ni
Spec Mode.

## Cobertura funcional automatizada

La suite confirma:

- listado y detalle con metadata Ollama allowlist;
- instalacion idempotente, `--dry-run`, progreso, verificacion final y Ctrl+C;
- seleccion con preflight, validacion, escritura atomica y conservacion de
  `[embeddings].model`;
- estados separados `available`, `installed`, `generation_ready` y
  `benchmark_eligible`;
- dataset cerrado de ocho casos neutrales en cinco categorias;
- hash canonico independiente del formato superficial del JSON;
- contexto congelado y reutilizacion exacta de `ContextBuilder`, `PromptBuilder`
  y `CitationValidator`;
- rotacion determinista y una generacion medida por caso/modelo;
- continuacion tras fallas unitarias y parcial `interrupted` no reanudable;
- scoring lexical v1, pesos renormalizados y `null` preservados;
- peso individual predominante del validador (`0.25`);
- exclusion de respuestas rechazadas del score de recomendacion;
- agregacion de calidad, aceptacion, latencia y tokens con cobertura;
- recomendacion determinista solo para corridas completas y aceptacion `>= 0.90`;
- JSON y Markdown sin respuestas, prompts ni contexto completos;
- colision de `run-id` rechazada sin sobrescritura;
- candidato informativo sin seleccion automatica.

## Validacion manual contra Ollama real

Modelos observados:

| Modelo | Uso | Tamano aproximado | Estado |
|---|---|---:|---|
| `llama3.1:8b` | LLM generativo | 4.9 GB | instalado y activo |
| `nomic-embed-text:latest` | embeddings | 274 MB | instalado; excluido del benchmark generativo |

`models list --format json` marco el activo como instalado. `models show
llama3.1:8b --format json` devolvio exclusivamente metadata acotada: formato
`gguf`, familia `llama`, tamano de parametros `8.0B`, cuantizacion `Q4_K_M` y
capacidades `completion`/`tools`.

`models install llama3.1:8b --dry-run` informo `ya instalado`, no solicito pull y
confirmo presencia final.

`models select llama3.1:8b --dry-run` mostro el archivo efectivo y un cambio
nulo. No ejecuto generacion ni escribio. El SHA-256 del TOML fue identico antes y
despues:

```text
D44F4B479BDE325A8B48EAC1227E7BE76EEA9C05FB32E6D86749D664EB6D8B4B
```

La configuracion efectiva permanecio:

```text
llm.model = llama3.1:8b
embeddings.model = nomic-embed-text
```

## Sonda real y benchmark real

Comando de sonda:

```powershell
.venv\Scripts\barbarion.exe --config barbarion.toml models validate llama3.1:8b --format json --timeout 120
```

Resultado observado:

```text
available = true
installed = true
generation_ready = false
benchmark_eligible = false
diagnostic_code = MODEL_NOT_GENERATION_READY
duration_ms = 39827
```

La respuesta completa del modelo no se imprimio ni se persistio. El diagnostico
indica unicamente que la generacion termino sin devolver el marcador exacto.

No se ejecuto un benchmark real porque:

1. H1.1 exige al menos dos LLM generativos distintos;
2. solo hay uno instalado;
3. el unico LLM no supera la sonda previa;
4. el modelo de embeddings no es un sustituto valido para completar la matriz.

La matriz, rotacion, fallas parciales, scoring, reportes y codigos de salida si
quedaron aceptados mediante fakes deterministas. No se generaron metricas reales
ni candidato recomendado.

## Privacidad y seguridad

El scan del dataset operativo y su fixture no encontro URLs, correos, rutas
externas, nombres de tecnologias del dominio existente ni vocabulario funcional
real. Los ocho casos usan exclusivamente componentes, modulos, elementos,
piezas, objetos y fuentes sinteticas.

Tambien se verifico que:

- no se construyen comandos shell para administrar Ollama;
- solo se usa la URL Ollama configurada;
- no se envian datos a servicios cloud;
- reportes y logs omiten respuestas completas, prompt y contexto;
- el benchmark no cambia el modelo activo;
- `models select` no cambia embeddings;
- la recomendacion nunca ejecuta seleccion automatica.

## Limites aceptados

- El scoring es lexical y determinista; orienta, no sustituye revision humana.
- La sonda exacta acredita generacion minima, no calidad RAG.
- H1.1 usa una ejecucion por caso/modelo y no calcula p95 ni variabilidad.
- La telemetria de tokens queda `null` cuando Ollama no la informa.
- Una corrida interrumpida produce un parcial simple con `resumable: false`.
- No hay historico JSONL, checkpoint reanudable, respuestas persistidas, LLM juez
  ni soporte cloud.
- La recomendacion solo aplica al dataset, versiones, opciones y hardware
  registrados y requiere adopcion humana mediante `models select`.

## Decision final

**H1.1 se acepta tecnicamente y T12 queda completada.**

No quedan defectos funcionales conocidos que impidan integrar el hito. Queda
pendiente, como validacion operativa no bloqueante, repetir `models validate` y
ejecutar `models benchmark` cuando existan al menos dos LLM generativos instalados
que sean `generation_ready`. Hasta entonces no existe evidencia para recomendar
ni seleccionar un ganador real.

