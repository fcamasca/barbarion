# H1 — Foundation: Evidencia de aceptación

## 1. Resultado

**Fecha:** 2026-06-23  
**Estado:** aceptado  
**Versión:** `0.1.0`

H1 cumple los requisitos Must y puede cerrarse. La aceptación se ejecutó en un entorno virtual temporal creado desde cero y eliminado al finalizar.

## 2. Entorno validado

- CPython `3.12.13`;
- instalación editable mediante `python -m pip install -e ".[dev]"`;
- Windows como plataforma de aceptación local;
- Ollama no disponible durante la ejecución manual;
- cero dependencias runtime de terceros.

La portabilidad de rutas y filesystem está cubierta por pruebas automatizadas. La ejecución manual en Linux y macOS queda pendiente para una futura matriz CI; no bloquea el MVP local actual.

## 3. Suite automatizada

```text
79 passed in 13.36s
```

La suite incluye pruebas unitarias, integración CLI y smoke contra el entry point instalado. Los smoke tests usan un endpoint Ollama falso en loopback y no requieren internet.

## 4. Comandos de aceptación

| Comando | Código esperado | Resultado |
|---|---:|---|
| `barbarion --help` | `0` | Aprobado; ayuda en español y sin efectos secundarios |
| `barbarion --version` | `0` | Aprobado; mostró `barbarion 0.1.0` |
| `barbarion --config barbarion.toml config show` | `0` | Aprobado; configuración efectiva y rutas normalizadas |
| `barbarion --config barbarion.toml doctor` | `0` | Aprobado; `6 PASS`, `1 WARN`, `0 FAIL` |
| Segunda ejecución de `doctor` | `0` | Aprobado; comportamiento idempotente |
| `barbarion --config missing.toml doctor` | `2` | Aprobado; error controlado y cero recursos creados |

La advertencia correspondió a Ollama no disponible. Es una dependencia opcional en H1 y no afecta el éxito cuando todos los checks requeridos pasan.

## 5. Idempotencia y persistencia

- `data/`, `output/` y `logs/` se crearon dentro de las rutas configuradas;
- SQLite quedó en la versión de esquema `1`;
- `schema_migrations` conservó una única fila después de dos ejecuciones;
- un archivo centinela existente en `data/` permaneció intacto;
- el log registró una entrada de inicio por ejecución, sin handlers duplicados;
- no se habilitó WAL en H1.

## 6. Trazabilidad

- requisitos definidos: `16`;
- requisitos sin referencia en tareas o pruebas: `0`;
- tareas previas a aceptación completadas: `11 de 11`;
- imports sin efectos secundarios: aprobado;
- `git diff --check`: aprobado;
- configuración, datos, salida, logs, `.venv` y SQLite: ignorados por Git;
- rutas personales, nombres internos o información sensible en documentación pública: no detectados.

## 7. Auditoría de alcance

Los únicos módulos de aplicación presentes son:

```text
__init__.py
__main__.py
bootstrap.py
cli.py
config.py
database.py
doctor.py
logging_config.py
```

No se implementaron RAG, embeddings, Qdrant, parsers de código legacy, FastAPI, VS Code, reverse engineering, generación Markdown, specs automáticas, multiusuario, plugins ni autenticación.

## 8. Decisiones

No fue necesaria una decisión arquitectónica adicional durante la aceptación. Siguen vigentes las decisiones registradas en [`docs/DECISIONS.md`](../../docs/DECISIONS.md), incluida la postergación de `barbarion init` y la comunicación con el usuario en español.

## 9. Conclusión

H1 proporciona una base local, pequeña, probada y suficiente para iniciar la especificación e implementación de H2 — Ingestion. Las limitaciones conocidas están documentadas y ninguna exige ampliar H1.
