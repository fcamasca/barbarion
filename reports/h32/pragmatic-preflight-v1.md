# H3.2 - Ajuste pragmático v1

Fecha: 2026-08-07

La decisión remota queda reducida a una obligación y una advertencia:

- `no_training=FAIL/UNKNOWN` -> `BLOCK`, sin confirmación y cero `generate()`.
- `no_training=PASS` + `retention=PASS` -> `PASS`.
- `no_training=PASS` + `retention=FAIL/UNKNOWN` -> `WARNING` y confirmación
  explícita antes de construir el prompt.
- `data_location` sigue evaluándose y mostrándose, pero no decide el gate.

La aceptación `S` emite una autorización inmutable marcada
`risk_accepted=True` y `privacy_decision=user_accepted_risk`; generation y
repair reutilizan esa autorización. `N` no construye prompt ni llama al LLM.

Para `ollama/ollama_cloud`, `OllamaOfficialPolicySource` aporta evidencia
uniforme para cualquier modelo desde la política oficial de Ollama:
`https://ollama.com/privacy`. No hay reglas por modelo ni IO durante `ask`.

Verificación focal: 81 passed. Suite completa final: 1064 passed, 14 skipped.
