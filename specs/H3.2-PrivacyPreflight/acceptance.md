# H3.2 - Aceptación técnica y funcional

Fecha: 2026-08-07

## Decisión

**Aceptada técnicamente para H3.2 v1**, con las limitaciones explícitas de esta
acta. El preflight protege la frontera generativa sin introducir gateway,
proxy, políticas por modelo ni cambios en retrieval, presupuestos o
`CitationValidator`.

## Evidencia ejecutada

- Suite completa offline: **1067 passed, 14 skipped**.
- Focal CLI/privacy: **85 passed** (`tests/unit/test_cli.py`).
- Matriz pragmática: bloqueo obligatorio de `no_training`, warning confirmable
  de retention, ubicación informativa y fuente oficial uniforme para Ollama
  Cloud.
- `BLOCK` ocurre antes de construir prompt y conserva cero llamadas a
  `generate()`.
- `S` produce autorización `risk_accepted=True`; generation y repair comparten
  esa autorización. `N` no produce egress generativo.
- `--debug` mantiene metadata técnica; salida normal muestra solo el resumen
  humano de privacidad.
- `barbarion privacy refresh` valida el JSON oficial, normaliza T05 y escribe
  mediante la cache atómica T06; `ask` no refresca.

## Fuentes y límites

- Fuente principal: **AI Provider Trust Registry**, snapshot machine-readable
  con licencia de uso y atribución.
- Fuente secundaria exclusiva de Ollama Cloud: [Ollama Privacy Policy](https://ollama.com/privacy),
  aplicada a `provider=ollama / platform=ollama_cloud`, nunca al nombre del
  modelo.
- La evidencia pública no demuestra el cumplimiento contractual interno de un
  proveedor ni una configuración privada de cuenta.
- `AccountPrivacyVerifier` continúa siendo contrato futuro; en v1 permanece
  `unavailable`, sin credenciales ni HTTP.
- No se realizó una comprobación productiva de cuenta Anthropic/AWS. Por tanto,
  retención efectiva de una cuenta concreta puede quedar en WARNING/UNKNOWN.
- La validación manual con corpus real y credenciales queda fuera de esta
  aceptación automatizada; las pruebas de provider usan datos sintéticos/fakes.

## Checklist

- [x] Fail-closed para `no_training` FAIL/UNKNOWN.
- [x] Retention no PASS requiere confirmación explícita.
- [x] `data_location` no decide H3.2 v1.
- [x] Ollama local no usa privacy IO.
- [x] Ollama Cloud remoto no se clasifica por nombre de modelo.
- [x] Anthropic directo mantiene egress directo.
- [x] Registry separado del corpus RAG.
- [x] Cache inválida/ausente/expirada bloquea remoto.
- [x] Salida normal sin contenido sensible ni enums internos.
- [x] Suite completa verde.

## Pendientes fuera de alcance

Una futura versión puede añadir verificación real de cuenta, nuevas fuentes
oficiales o una política de regiones efectiva. Ninguno de esos pendientes se
presenta como PASS en H3.2 v1.
