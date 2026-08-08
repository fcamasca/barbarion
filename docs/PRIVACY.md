# Privacy Preflight y cache

H3.2 protege únicamente la decisión de enviar contexto a una inferencia
remota. Retrieval, embeddings, SQLite y la construcción de conocimiento siguen
siendo locales.

## Política

En remoto, `no_training` es obligatorio: FAIL o UNKNOWN produce `BLOCK` sin
override. `retention` es informativa: FAIL o UNKNOWN produce `WARNING` y exige
confirmación explícita antes de construir el prompt. `data_location` se evalúa
para diagnóstico, pero no decide H3.2 v1. En local, las restricciones son
`NOT_APPLICABLE`.

El registry público es un índice de evidencia estructurada sobre capacidades.
`yes_public`, `available`, `configurable` o `sales-gated` no prueban que la
configuración efectiva de una cuenta esté activa. Por tanto, ZDR disponible no
es ZDR efectivo. Barbarion no puede demostrar el cumplimiento contractual
interno de un proveedor.

## Cache y refresh

La snapshot se guarda en `data_dir/privacy/registry-snapshot.json`, separada de
SQLite y del corpus RAG. `barbarion privacy refresh` valida esquema, fuente,
vigencia e integridad y escribe de forma atómica únicamente metadata pública.
No incluye preguntas, prompts, chunks, paths, símbolos, fórmulas, respuestas,
API keys ni decisiones por operación.

`ask` consume la cache local. Nunca consulta ni refresca el registry durante una
pregunta. Una cache missing, expired o invalid bloquea la inferencia remota.
La descarga usa solo `GET`, no transmite query, modelo, corpus ni
identificadores de usuario, y conserva la snapshot anterior ante errores.

## Cuenta y egress

`AccountPrivacyVerifier` es un contrato preparado para una integración futura.
En v1 devuelve `unavailable`, sin credenciales, HTTP ni detección de cuenta.

Para `provider=ollama` y `platform=ollama_cloud`, la segunda fuente permitida es
la política oficial de Ollama (`https://ollama.com/privacy`). Declara que los
prompts/respuestas cloud se procesan transitoriamente y no se usan para
entrenamiento; la evidencia se aplica uniformemente a cualquier modelo, nunca
por nombre. Si la política dejara de demostrar no-training, el estado sería
`UNKNOWN` y el gate bloquearía.

Con PASS remoto, Barbarion llama directamente al proveedor configurado; no
hay gateway ni proxy de inferencia. `localhost` no implica local: Ollama Cloud
declarado remoto conserva el gate de privacidad.
