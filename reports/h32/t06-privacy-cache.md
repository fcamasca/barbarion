# H3.2-T06 - Evidencia local vigente y confiable

## Resultado

T06 implementa persistencia local y refresh explicito sin evaluar la politica.
La salida de lectura es uno de cuatro estados:

| Estado | Fuente local disponible |
|---|---|
| `valid` | si, `PrivacyPolicySource` normalizado por T05 |
| `missing` | no |
| `expired` | no |
| `invalid` | no |

Ninguno de estos estados representa `PASS`, `BLOCK` o una autorizacion. T04/T08
seran responsables de consumir la evidencia y decidir posteriormente.

## Snapshot

La cache vive en `data_dir/privacy/registry-snapshot.json` y conserva:

- version del schema de cache;
- identidad y version de la fuente;
- `fetched_at` y expiracion efectiva;
- payload publico reducido a provider/platform/offering, dimensiones relevantes
  y excepciones de modelo publicadas;
- `value`, `confidence`, `source` y `verified` por celda;
- SHA-256 del envelope canonico.

No conserva `summary`, `notes`, `evidence`, `caveat`, preguntas, prompts,
chunks, rutas, credenciales, hashes del corpus, modelos consultados ni historial
de operaciones.

## Vigencia e integridad

La expiracion efectiva es `min(fetched_at + TTL, source_expires_at)` cuando la
fuente publica expiracion. El instante `now == expires_at` ya es expirado. Se
rechazan schema desconocido, identidad o version inconsistente, integridad
incorrecta, timestamps invalidos, reloj futuro y evidencia verificada despues
de `fetched_at`.

El refresh valida y normaliza todo antes de escribir. Usa un temporal en el
mismo directorio, `flush`, `fsync` y `os.replace`. Si fetch, validacion,
escritura o replace fallan, la ultima cache valida permanece intacta y el
temporal se elimina.

## Separacion operacional

`PrivacyRegistryFetcher.fetch()` no recibe argumentos: el refresh explicito
obtiene el snapshot publico completo sin identidad de una consulta. Las lecturas
posteriores son locales y nunca invocan el fetcher. T06 no agrega cliente HTTP,
CLI, configuracion, evaluadores ni integracion con `AskService`.

## Verificacion

- Pruebas focales T04/T05/T06: 71 aprobadas.
- Suite completa: 1024 aprobadas, 14 omitidas.
- TP-025..032 cubren refresh, lectura offline, missing, expiracion, TTL,
  corrupcion, reloj futuro, atomicidad y ausencia de correlacion.
