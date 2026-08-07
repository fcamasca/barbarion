# H3.2-T10 - CLI y observabilidad segura

## Salida normal

Un preflight autorizado no agrega texto a la respuesta normal. Emite un evento
local `privacy_preflight` de nivel INFO con campos publicos y estados.

Un bloqueo produce exit code 1 y salida compacta:

```text
Privacy preflight: BLOCKED

no_training : PASS
retention   : UNKNOWN
location    : PASS

No se envio contexto al proveedor remoto.
```

No hay traceback esperado ni intento de provider.

## Debug seguro

`--debug` agrega exclusivamente:

- decision y `execution/provider/platform/offering/model` publicos;
- perfil strict y allowlist configurada;
- estado por restriccion y `reason_code`;
- `source_kind`, `source_id`, scope y timestamps de referencias estructuradas;
- `source_version` y `cache_status`;
- estado del account verifier.

El evento de log contiene un subconjunto compacto: decision, target publico,
estados, cache, verifier y procedencia. No incluye operation ID.

## Saneamiento del debug historico

El renderer CLI de `ask --debug` dejo de imprimir:

- pregunta/query;
- paths, source IDs, chunk IDs y contenido recuperado;
- prompt de generation o repair;
- respuesta LLM y respuesta rechazada;
- claims/reasons textuales de validacion.

Se conservan metricas agregadas de retrieval, contexto, presupuestos,
composicion, tokens, validacion y repair. Los componentes del prompt muestran
tipo y tamanos, sin source ID ni texto.

## Codigos operacionales

- configuracion invalida: 2;
- privacy block/error operativo: 1;
- interrupcion: 130;
- exito: contrato previo sin cambios.

`--no-llm` y evidencia insuficiente mantienen sus retornos anteriores al
preflight.

## Limite

T10 no modifica evaluadores, emision o validacion de autorizaciones. Tampoco
agrega refresh, HTTP del registry, configuracion nueva ni adaptadores de cuenta.

## Pruebas

- TP-048: salida BLOCK exacta y accionable.
- TP-049: target, policy, reasons, evidencia, cache y verifier seguros.
- TP-050: scanner de canarios sobre debug y evento.
- TP-051..053: exit codes y retornos locales conservados por regresion.
- Suite completa: 1051 aprobadas, 14 omitidas.
- Focal final de CLI, seguridad, prompts y observabilidad: 109 aprobadas.
