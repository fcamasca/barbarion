# H3.2-T12.1 - Production Registry Refresh

Fecha: 2026-08-07

Implementado el comando `barbarion privacy refresh`.

- URL oficial fija: `https://aiprovidertrust.com/data.json`.
- Único método: HTTP GET, con `Accept: application/json` y User-Agent estático.
- Timeout: 20 segundos.
- Límite de respuesta: 10 MiB.
- Status HTTP y JSON se validan antes de tocar la cache.
- La normalización se delega al adaptador T05 y la escritura al cache T06.
- El refresh no recibe ni envía query, modelo, corpus o identificadores de usuario.
- Fallos de red/schema preservan la snapshot anterior.
- `ask` no invoca este fetcher ni hace refresh automático.
- Ctrl+C se propaga al manejador CLI y devuelve 130.

Verificación:

- Endpoint real: `AI Provider Trust Registry`, generado `2026-08-07`, 16 offerings.
- Pruebas T12.1: 5 passed.
- Regresión focal T03/T08/T11/T12.1: 29 passed.
- Suite completa posterior a la corrección de offering Anthropic: 1061 passed,
  14 skipped.
