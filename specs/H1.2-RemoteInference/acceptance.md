# Aceptacion H1.2 - Inferencia Remota con Anthropic

## Estado

**Estado tecnico y funcional:** aceptado y cerrado.

**Estado de H1.2-T08:** completada por aprobacion explicita del usuario el
2026-08-03.

H1.2 incorpora Anthropic como segundo adaptador generativo, conserva Ollama
como proveedor predeterminado y mantiene locales retrieval, embeddings,
conocimiento, indices y persistencia. La aceptacion cubre configuracion,
credencial, request HTTP, generacion, reparacion, citas, errores, cancelacion,
privacidad, observabilidad, Unicode, uso real de tokens y regresion completa.

La decision combina dos evidencias honestamente separadas:

- una solicitud Anthropic real previa valido el flujo remoto y los contadores
  devueltos por el proveedor;
- la correccion final de Unicode se valido despues, sin nueva llamada remota,
  mediante bytes reales del entrypoint instalado, UTF-8 estricto, suite offline
  y smoke Windows.

El usuario acepta expresamente este cierre sin repetir una solicitud con costo.

## Version y entorno

- Fecha: 2026-08-03.
- Sistema operativo: Microsoft Windows 11 Pro `10.0.26200`, build `26200`.
- PowerShell: `5.1.26100.8875`.
- Rama: `feature/H1.2-RemoteInference`.
- Revision base evaluada: `a01c895` mas los cambios locales de H1.2-T08-PRE y
  este cierre documental.
- Barbarion: `0.6.0`, instalacion editable desde `.venv`.
- Python: `3.12.10`.
- Pytest: `8.4.2`.

No se registran API keys, hostname, usuario, variables de entorno completas ni
contenido remoto integral.

## Suite completa y regresion

Comando de aceptacion:

```powershell
.venv\Scripts\python.exe -m pytest --basetemp .pytest-tmp\h12-acceptance -q
```

Resultado:

```text
856 passed, 3 skipped in 117.55s
```

Las tres omisiones corresponden a pruebas de symlinks que el entorno Windows no
permite crear. No son omisiones de Anthropic, Unicode ni de los contratos H1.2.

Smoke independiente del entrypoint instalado:

```powershell
.venv\Scripts\python.exe -m pytest tests\smoke --basetemp .pytest-tmp\h12-acceptance-smoke -q
```

Resultado:

```text
11 passed in 30.93s
```

La corrida cubre regresion de H1-H5, H4.1 y H1.1, unitarias, integraciones,
golden files, seguridad offline y el proceso Windows instalado. La fixture
global bloquea conexiones externas salvo loopback; ninguna prueba de aceptacion
contacto Anthropic.

## Validacion Anthropic real

La validacion real autorizada anterior uso el adaptador Anthropic no streaming
y produjo contadores del proveedor consistentes:

| Metrica | Valor |
|---|---:|
| `prompt_tokens_est_local` | 6,190 |
| `usage.input_tokens` | 10,198 |
| `usage.output_tokens` | 529 |
| total calculado | 10,727 |

La igualdad comprobada es:

```text
10,198 + 529 = 10,727
```

`prompt_tokens_est_local` permanece identificado como estimacion local previa y
no se presenta como consumo remoto. No se llamo a
`/v1/messages/count_tokens`, no se calculo costo y no se inventaron contadores.

La llamada real revelo mojibake en la presentacion Windows. Ese hallazgo impidio
aceptar inicialmente T08 y origino H1.2-T08-PRE. La correccion de contadores se
considero validada; la correccion de Unicode se reabrio y se caracterizo por
separado antes de este cierre.

No se conserva request-id de esa ejecucion en esta acta y no se inventa uno. No
se realizo una segunda llamada Anthropic despues de la correccion final de
Unicode.

## Unicode en Windows PowerShell 5.1

La causa raiz era el uso de `GetConsoleOutputCP()` para reconfigurar tambien
streams redirigidos. El codepage de consola no define necesariamente el
contrato de un pipe de PowerShell, por lo que productor y consumidor podian
usar encodings distintos.

Caracterizacion del proceso redirigido:

| Momento | stdout/stderr | `isatty()` | Tipo concreto |
|---|---|---:|---|
| antes de la configuracion CLI | `cp1252` | `false` | `_io.TextIOWrapper` |
| implementacion anterior | `cp65001` tomado de consola | `false` | `_io.TextIOWrapper` |
| implementacion aceptada | `utf-8` estable | `false` | `_io.TextIOWrapper` |

Codepages observados durante la prueba:

- salida de consola: 65001;
- entrada de consola: 850;
- ANSI: 1252;
- OEM: 850.

La implementacion aceptada aplica por stream:

- redirigido: `encoding="utf-8"`, `errors="strict"`;
- interactivo: conserva el stream nativo de consola;
- sin `errors="replace"`, reemplazos manuales, ASCII, `chcp`, `PYTHONUTF8` ni
  `PYTHONIOENCODING` como requisito.

El smoke real solicitado termino con codigo cero:

```powershell
barbarion ask "variables de configuración usadas para calcular provisiones" --mode keyword --no-llm --debug
```

Los bytes de `configuración` contienen `c3 b3`, decodifican como UTF-8 estricto
y no contienen `ef bf bd`. El proceso conserva QUERY, debug y respuesta local
sin caracteres de reemplazo.

La prueba automatizada adicional ejecuta `barbarion.exe` instalado mediante
`subprocess`, usa pipes reales en lugar de `StringIO`, captura bytes y exige la
decodificacion UTF-8 estricta de:

```text
¿Configuración, provisión, días, cupón, último y cálculo?
```

## Funcionalidad aceptada

- seleccion cerrada entre Ollama y Anthropic sin registry dinamico;
- Ollama permanece como default y conserva sus opciones y payload;
- credencial Anthropic exclusivamente desde `ANTHROPIC_API_KEY` y resuelta de
  forma tardia;
- endpoint y version de Messages API fijos;
- request no streaming con payload minimo y timeout configurado;
- respuesta formada solo por bloques text reconocidos;
- rechazo tipado de JSON invalido, texto vacio y truncamiento por `max_tokens`;
- misma construccion de prompt, validacion de citas y unico intento de repair;
- mismo proveedor para generacion y reparacion, sin fallback Ollama;
- matriz HTTP, red, TLS y timeout normalizada sin body remoto ni traceback;
- Ctrl+C propagado y salida 130 sin declarar exito;
- `--no-llm` operativo sin key ni red;
- H4 opcional conserva su fallback determinista existente;
- comandos y benchmark H1.1 permanecen Ollama-only;
- input, output, total y duracion se publican solo cuando existen;
- contadores parciales o ausentes permanecen no disponibles;
- no se agregan migraciones, cache, tablas ni persistencia remota.

## Seguridad, privacidad y egress

Las pruebas con keys canario confirman que la credencial no aparece en
`repr`, excepciones, stdout, stderr, debug, logs, SQLite ni archivos generados.
Las cadenas `sk-ant-*` versionadas pertenecen exclusivamente a fixtures
declaradamente falsas y a sus aserciones.

El unico egress productivo agregado es el POST solicitado al endpoint Anthropic
fijo. El body contiene solo configuracion de API y el prompt vigente ya
construido por Barbarion. No se envian base SQLite, vectores, manifests, TOML,
archivos completos ajenos al contexto ni variables de entorno. Los redirects no
reciben key o contexto.

Activar Anthropic implica egress del prompt y requiere seleccion y credencial
explicitas. Ollama sigue siendo el comportamiento predeterminado. Embeddings,
retrieval y conocimiento permanecen locales.

## Requisitos aceptados

| Grupo | Resultado | Evidencia principal |
|---|---|---|
| RF-001..003 | Cumple | configuracion/factoria cerrada y adaptador HTTP probado |
| RF-004 | Cumple | prompts, citas, repair y formatos sin cambio |
| RF-005..006 | Cumple | timeout, Ctrl+C y matriz de errores |
| RF-007 | Cumple | `--no-llm` sin key ni red |
| RF-008 | Cumple | conocimiento e indices locales, sin migracion |
| RF-009 | Cumple | H1.1 y Ollama sin regresion |
| RF-010 | Cumple | README, CLI, spec y esta aceptacion |
| RNF-001..006 | Cumple | consentimiento, compatibilidad, arquitectura, secretos y egress |
| RNF-007..009 | Cumple | costo acotado, cancelacion y suite offline |
| RNF-010 | Cumple | Python 3.12 y proceso real Windows UTF-8 estricto |
| RNF-011 | Cumple | usage real honesto y observabilidad sin secretos |
| RNF-012 | Cumple | alcance de proveedor cerrado |

## Limites aceptados

- No hay streaming, tools, vision, batches, caching, SDK, retry automatico ni
  fallback entre proveedores.
- No se implementan otros proveedores cloud ni un registry extensible.
- La medicion de tokens depende del `usage` devuelto por Anthropic; no representa
  costos ni ejecuta conteo remoto previo.
- La validacion real cubrio una solicitud controlada. La correccion final de
  Unicode no se repitio contra Anthropic; se acepto mediante evidencia de
  frontera independiente, bytes reales y confirmacion humana.
- La consola interactiva queda a cargo del stream nativo de Python; el contrato
  UTF-8 estable aplica a streams redirigidos.
- La disponibilidad, latencia y calidad futura del servicio Anthropic dependen
  del proveedor y del modelo configurado.

## Decision final

**H1.2 se acepta tecnica y funcionalmente, H1.2-T08 queda completada y el hito
queda cerrado.**

No quedan defectos funcionales conocidos que bloqueen su integracion. La
separacion entre evidencia Anthropic real y verificacion Unicode posterior es
una limitacion conocida, documentada y aceptada expresamente, no una afirmacion
de una ejecucion que no ocurrio.
