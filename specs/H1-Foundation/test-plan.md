# H1 — Foundation: Plan de pruebas

## 1. Objetivo

Verificar que H1 sea instalable, determinista, local, idempotente y seguro para extender. Las pruebas deben detectar fallos de configuración, filesystem, SQLite, logging y diagnóstico sin depender de servicios externos.

## 2. Estrategia

| Nivel | Propósito | Dependencias reales |
|---|---|---|
| Unitario | Validar módulos aislados | Filesystem y SQLite temporales |
| Integración local | Validar configuración–bootstrap–DB–doctor | `sqlite3`; Ollama simulado |
| Smoke CLI | Validar comandos como usuario | Paquete instalado; sin red |
| Aceptación manual | Confirmar documentación y salida | Python 3.12 limpio |

No se exige un porcentaje de cobertura. Se exige cobertura de todos los comportamientos Must y ramas de error relevantes.

## 3. Entorno

- CPython 3.12;
- instalación editable con extra de desarrollo;
- `pytest`;
- `tmp_path` y `monkeypatch`;
- SQLite estándar;
- probe Ollama sustituido por una función determinista.

Las pruebas no leen ni escriben los directorios reales del checkout.

## 4. Pruebas unitarias

### Configuración

| ID | Caso | Resultado | Requisito |
|---|---|---|---|
| UT-CFG-01 | Sin archivo ni variable | Defaults, origen `defaults` | H1-REQ-003 |
| UT-CFG-02 | Archivo del cwd | Carga y resuelve rutas desde su directorio | H1-REQ-003 |
| UT-CFG-03 | Variable de entorno | Precede al archivo del cwd | H1-REQ-003 |
| UT-CFG-04 | `--config` | Precedencia máxima | H1-REQ-003 |
| UT-CFG-05 | Ruta explícita ausente | `ConfigError`, exit `2` | H1-REQ-003, H1-REQ-010 |
| UT-CFG-06 | TOML inválido | Mensaje sin traceback | H1-REQ-003 |
| UT-CFG-07 | Clave desconocida | Configuración rechazada | H1-REQ-003 |
| UT-CFG-08 | Timeout fuera de rango | Configuración rechazada | H1-REQ-003 |
| UT-CFG-09 | Nivel de log inválido | Configuración rechazada | H1-REQ-007 |
| UT-CFG-10 | URL con credenciales | Configuración rechazada | H1-NFR-001 |

### Directorios

| ID | Caso | Resultado | Requisito |
|---|---|---|---|
| UT-DIR-01 | Directorios ausentes | Se crean todos | H1-REQ-006 |
| UT-DIR-02 | Segunda inicialización | Sin error ni pérdida | H1-REQ-006 |
| UT-DIR-03 | Ruta ocupada por archivo | `FAIL` con ruta | H1-REQ-006 |
| UT-DIR-04 | Rutas duplicadas | Una comprobación por ruta | H1-REQ-006 |
| UT-DIR-05 | Escritura denegada | `FAIL` sin traceback | H1-REQ-006 |

Si permisos no pueden simularse de forma fiable en una plataforma, se cubre la rama con monkeypatch.

### Logging

| ID | Caso | Resultado | Requisito |
|---|---|---|---|
| UT-LOG-01 | Nivel INFO | Consola y archivo reciben INFO | H1-REQ-007 |
| UT-LOG-02 | Nivel ERROR | Filtra INFO, conserva ERROR | H1-REQ-007 |
| UT-LOG-03 | Reconfiguración | No duplica handlers/líneas | H1-REQ-007 |
| UT-LOG-04 | Unicode | Archivo UTF-8 legible | H1-REQ-007 |
| UT-LOG-05 | Handler configurado sin emitir | El archivo aún no existe por `delay=True` | H1-REQ-007 |

### SQLite

| ID | Caso | Resultado | Requisito |
|---|---|---|---|
| UT-DB-01 | Base ausente | DB y migración `1` | H1-REQ-008 |
| UT-DB-02 | Segunda inicialización | Una fila de migración | H1-REQ-008 |
| UT-DB-03 | Health check | `SELECT 1`, FK activas, versión `1` | H1-REQ-008 |
| UT-DB-04 | Versión futura `X` | Falla sin modificar DB y muestra `Database schema version X is newer than this Barbarion version supports.` | H1-REQ-008 |
| UT-DB-05 | Ruta no utilizable | Error accionable | H1-REQ-008 |
| UT-DB-06 | Error durante migración | Rollback sin versión parcial | H1-REQ-008 |

### Imports

| ID | Caso | Resultado | Requisito |
|---|---|---|---|
| UT-IMP-01 | Importar cada módulo desde un cwd temporal | No crea archivos ni directorios | H1-NFR-004 |
| UT-IMP-02 | Importar con `sqlite3.connect` y `urllib.request.urlopen` reemplazados por funciones que fallan | Ninguna función es invocada | H1-NFR-004 |
| UT-IMP-03 | Comparar handlers antes y después de importar | Root logger y logger `barbarion` no cambian | H1-NFR-004 |

Estas pruebas se ejecutan en un subproceso limpio para evitar falsos positivos por la caché de imports.
### Doctor

| ID | Caso | Resultado | Requisito |
|---|---|---|---|
| UT-DOC-01 | Checks disponibles | `PASS`, exit `0` | H1-REQ-009 |
| UT-DOC-02 | Ollama inaccesible | `WARN`, exit `0` | H1-REQ-009 |
| UT-DOC-03 | Ollama timeout | `WARN`, exit `0` | H1-REQ-009, H1-NFR-001 |
| UT-DOC-04 | Ollama responde | `PASS` | H1-REQ-009 |
| UT-DOC-05 | Directorio falla | `FAIL`, exit `1` | H1-REQ-009, H1-REQ-010 |
| UT-DOC-06 | SQLite falla | `FAIL`, exit `1` | H1-REQ-009, H1-REQ-010 |
| UT-DOC-07 | Orden | Coincide con diseño | H1-REQ-009 |
| UT-DOC-08 | Resumen | Conteos correctos | H1-REQ-009 |

## 5. Smoke tests

### SMK-01 — Ayuda

`barbarion --help`

- exit `0`;
- contiene `doctor` y `config`;
- no crea recursos.

### SMK-02 — Versión

`barbarion --version`

- exit `0` y muestra `0.1.0`;
- no crea recursos.

### SMK-03 — Configuración

`barbarion --config barbarion.toml config show`

- exit `0`;
- muestra origen y rutas normalizadas;
- no crea recursos.

### SMK-04 — Primer diagnóstico

`barbarion --config barbarion.toml doctor`

- crea `data/`, `output/`, `logs/` y SQLite;
- exit `0` aunque Ollama no esté disponible;
- Ollama muestra `WARN` y no hay `FAIL`.

### SMK-05 — Diagnóstico repetido

Repetir SMK-04:

- exit `0`;
- no duplica migración;
- no elimina un archivo centinela en `data/`;
- no duplica handlers de log.

### SMK-06 — Configuración ausente explícita

`barbarion --config missing.toml doctor`

- exit `2`;
- mensaje indica archivo ausente;
- sin traceback ni recursos creados.

## 6. Aceptación manual

1. Crear entorno virtual con Python 3.12.
2. Instalar proyecto editable con dependencias dev.
3. Copiar `barbarion.example.toml` como `barbarion.toml` en un temporal.
4. Ejecutar SMK-01 a SMK-06.
5. Ejecutar `python -m pytest`.
6. Confirmar que Git no muestra configuración, logs, SQLite ni datos locales.
7. Repetir el flujo siguiendo solo README.

## 7. Trazabilidad

| Requisito | Evidencia |
|---|---|
| H1-REQ-001 | SMK-01, SMK-02 |
| H1-REQ-002 | SMK-01, SMK-02 |
| H1-REQ-003 | UT-CFG-01..08, SMK-03, SMK-06 |
| H1-REQ-004 | SMK-03, aceptación manual |
| H1-REQ-005 | SMK-03 |
| H1-REQ-006 | UT-DIR-01..05, SMK-04, SMK-05 |
| H1-REQ-007 | UT-LOG-01..05, SMK-01..03, SMK-05 |
| H1-REQ-008 | UT-DB-01..06, SMK-04, SMK-05 |
| H1-REQ-009 | UT-DOC-01..08, SMK-04 |
| H1-REQ-010 | SMK-04, SMK-06 |
| H1-REQ-011 | Suite `pytest` |
| H1-REQ-012 | Aceptación desde README |
| H1-NFR-001 | UT-DOC-02..04; suite sin red |
| H1-NFR-002 | Config/directorios con `tmp_path` |
| H1-NFR-003 | Revisión de estructura y dependencias |
| H1-NFR-004 | UT-IMP-01..03; smoke tests sin efectos |

## 8. Criterios de éxito

- todos los tests pasan con `python -m pytest`;
- SMK-01 a SMK-06 cumplen códigos y efectos;
- segunda ejecución de `doctor` es idempotente;
- Ollama ausente no causa fallo global;
- no hay red durante pruebas;
- no se escribe fuera de rutas configuradas;
- Git no incluye configuración, logs, datos ni SQLite;
- no existen módulos o dependencias excluidas;
- importar cualquier módulo no crea recursos ni activa logging, SQLite o red;
- README permite repetir la verificación desde cero.

## 9. Evidencia de cierre

Registrar versión de Python, resumen de `pytest`, salida de comandos, confirmación de idempotencia, limitaciones justificadas y cualquier nueva decisión incorporada a `docs/DECISIONS.md`.
