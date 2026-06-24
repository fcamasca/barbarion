# H1 — Foundation: Requisitos

## 1. Propósito

H1 establece la base mínima, local y verificable de Barbarion. Al finalizar debe existir un paquete Python instalable, una CLI funcional, configuración explícita, logging, directorios de trabajo, una base SQLite inicial, diagnóstico del entorno y pruebas reproducibles.

H1 no incluye análisis de sistemas legacy ni funcionalidad de negocio. Su resultado es la plataforma mínima sobre la que se implementará H2 sin rehacer el arranque de la aplicación.

## 2. Alcance

### Incluido

- estructura inicial del paquete Python;
- CLI con ayuda, versión, diagnóstico y visualización de configuración;
- carga y validación de configuración TOML;
- inicialización idempotente de `data/`, `output/` y `logs/`;
- logging a consola y archivo local;
- creación y verificación de una base SQLite con esquema versionado;
- comprobación no destructiva de disponibilidad de Ollama;
- pruebas unitarias, de integración local y de humo;
- documentación mínima de instalación y uso.

### Excluido

- RAG, embeddings y Qdrant;
- parsers o ingesta de corpus;
- FastAPI, servidor HTTP y UI web;
- extensión de VS Code;
- ingeniería inversa o generación de Markdown;
- generación automática de specs;
- multiusuario, plugins y autenticación;
- conexión a Oracle o procesamiento de exports PowerBuilder;
- contenedores, microservicios o infraestructura distribuida.

## 3. Convenciones

- **Prioridad Must:** necesaria para aceptar H1.
- **Prioridad Should:** aporta operabilidad, pero no amplía el alcance.
- Los criterios se expresan en términos observables desde CLI, filesystem o pruebas.
- Los comandos `--help`, `--version` y `config show` no modifican el filesystem.
- `doctor` es el único comando de H1 autorizado a inicializar directorios y SQLite.

## 4. Requisitos funcionales

### H1-REQ-001 — Proyecto Python instalable

**Descripción:** El repositorio debe definir un paquete `barbarion` instalable en modo editable y un ejecutable de consola llamado `barbarion`.

**Prioridad:** Must.

**Criterios de aceptación:**

- `pyproject.toml` declara Python `>=3.12,<3.13`, metadata mínima y el entry point `barbarion`;
- `python -m pip install -e .` completa sin instalar dependencias runtime de terceros;
- `barbarion --help` y `python -m barbarion --help` invocan la misma CLI;
- el paquete no contiene módulos de RAG, parsing, vectores ni ingeniería inversa.

### H1-REQ-002 — Ayuda y versión

**Descripción:** La CLI debe exponer ayuda navegable y la versión instalada sin inicializar recursos locales.

**Prioridad:** Must.

**Criterios de aceptación:**

- `barbarion --help` finaliza con código `0` y muestra `doctor` y `config`;
- `barbarion config --help` muestra el subcomando `show`;
- `barbarion --version` finaliza con código `0` y muestra una versión compatible con la metadata del paquete;
- ninguno de estos comandos crea `data/`, `output/`, `logs/` ni SQLite.

### H1-REQ-003 — Resolución de configuración

**Descripción:** Barbarion debe cargar una configuración TOML única mediante una precedencia determinista.

**Prioridad:** Must.

**Criterios de aceptación:**

- la precedencia es: opción global `--config PATH`, variable `BARBARION_CONFIG`, archivo `./barbarion.toml`, valores predeterminados;
- una ruta explícita o indicada por variable que no existe produce un error de configuración y código `2`;
- la ausencia de `./barbarion.toml` no impide usar valores predeterminados;
- las rutas relativas se resuelven respecto del directorio del archivo TOML que las define; si no hay archivo, respecto del directorio de trabajo;
- claves desconocidas, tipos inválidos o valores vacíos obligatorios producen un mensaje accionable;
- el parser usa `tomllib` y no admite interpolación ni ejecución de contenido.

### H1-REQ-004 — Configuración de ejemplo

**Descripción:** El repositorio debe incluir `barbarion.example.toml` como contrato visible de la configuración de H1.

**Prioridad:** Must.

**Criterios de aceptación:**

- el ejemplo contiene exclusivamente `domain`, `data_dir`, `output_dir`, `logs_dir`, `database_path`, `log_level`, `ollama_url` y `ollama_timeout_seconds`;
- usa rutas relativas portables y valores no sensibles;
- copiarlo a `barbarion.toml` produce una configuración válida;
- `barbarion.toml` permanece ignorado por Git.

### H1-REQ-005 — Visualización de configuración

**Descripción:** `barbarion config show` debe mostrar la configuración efectiva y su origen sin modificar el entorno.

**Prioridad:** Must.

**Criterios de aceptación:**

- finaliza con código `0` para una configuración válida;
- muestra el origen (`archivo` o `defaults`) y todos los campos de H1 en orden estable;
- muestra rutas normalizadas absolutas para facilitar diagnóstico;
- no crea directorios, base de datos ni archivo de log;
- una configuración inválida finaliza con código `2` y no imprime traceback.

### H1-REQ-006 — Inicialización de directorios

**Descripción:** El arranque operativo de H1 debe asegurar la existencia de los directorios configurados.

**Prioridad:** Must.

**Criterios de aceptación:**

- `barbarion doctor` crea, si faltan, `data_dir`, `output_dir`, `logs_dir` y el directorio padre de `database_path`;
- repetir el comando no falla ni elimina contenido existente;
- una ruta ocupada por un archivo o sin permisos se reporta como `FAIL` con la ruta afectada;
- no se crean carpetas fuera de las rutas efectivas mostradas por `config show`.

### H1-REQ-007 — Logging local

**Descripción:** Las operaciones de `doctor` deben registrar eventos accionables en consola y en un archivo local.

**Prioridad:** Must.

**Criterios de aceptación:**

- se usa exclusivamente `logging` de la biblioteca estándar;
- consola escribe en `stderr` y el resultado de `doctor` en `stdout`;
- el archivo efectivo es `<logs_dir>/barbarion.log` y usa `encoding="utf-8"` y `delay=True`;
- el archivo no se crea hasta que se emite el primer registro;
- el nivel acepta `DEBUG`, `INFO`, `WARNING`, `ERROR` y `CRITICAL`, con `INFO` por defecto;
- se registra inicio, configuración utilizada, resultado global y errores, sin secretos ni contenido de corpus;
- cada configuración reemplaza handlers gestionados por Barbarion y no duplica mensajes.

### H1-REQ-008 — SQLite inicial y versionado

**Descripción:** H1 debe crear y verificar una base SQLite mínima, idempotente y preparada para migraciones posteriores.

**Prioridad:** Must.

**Criterios de aceptación:**

- `doctor` crea la base en `database_path` si no existe;
- el esquema versión `1` contiene únicamente `schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)`;
- la migración se ejecuta dentro de una transacción y se registra una sola vez;
- cada conexión habilita `PRAGMA foreign_keys = ON` y usa un timeout de 5 segundos;
- repetir la inicialización no cambia la versión ni agrega filas duplicadas;
- `SELECT 1` y la lectura de la versión comprueban salud;
- una versión de esquema futura se reporta exactamente como `Database schema version X is newer than this Barbarion version supports.`, sustituyendo `X` por la versión detectada;
- errores de apertura, bloqueo o versión futura desconocida se reportan sin borrar ni recrear la base.

### H1-REQ-009 — Diagnóstico del entorno

**Descripción:** `barbarion doctor` debe presentar un diagnóstico legible de recursos requeridos y opcionales.

**Prioridad:** Must.

**Criterios de aceptación:**

- reporta versión de Python, origen de configuración, directorios de datos/salida/logs, SQLite y Ollama;
- cada comprobación muestra `PASS`, `WARN` o `FAIL` y un detalle breve;
- Python menor a 3.12, configuración inválida, directorios no utilizables o SQLite no saludable son fallos requeridos;
- Ollama se comprueba con `GET <ollama_url>/api/tags` usando el timeout configurado;
- Ollama ausente, inaccesible o con respuesta no válida produce `WARN`, no bloquea H1 y no imprime traceback;
- el resumen final muestra conteos y estado global.

### H1-REQ-010 — Códigos de salida y errores

**Descripción:** La CLI debe distinguir éxito, diagnóstico fallido y uso/configuración inválidos.

**Prioridad:** Must.

**Criterios de aceptación:**

- código `0`: comando completado y checks requeridos aprobados; se permiten advertencias opcionales;
- código `1`: `doctor` completó, pero uno o más checks requeridos fallaron;
- código `2`: argumentos o configuración inválidos;
- `Ctrl+C` finaliza con código `130` y mensaje breve;
- errores esperados no muestran traceback ni mensajes crudos de librerías.

### H1-REQ-011 — Pruebas reproducibles

**Descripción:** H1 debe incluir pruebas rápidas que no dependan de internet, Ollama real ni rutas personales.

**Prioridad:** Must.

**Criterios de aceptación:**

- `python -m pytest` ejecuta todas las pruebas con un solo comando;
- las pruebas usan `tmp_path` para directorios y SQLite;
- Ollama se prueba con dobles locales o funciones inyectadas, sin red real;
- existe cobertura de configuración, directorios, logging, SQLite, diagnóstico y códigos de salida;
- existe un smoke test de los cuatro comandos esperados;
- todo pasa en una instalación limpia compatible con Python 3.12.

### H1-REQ-012 — Documentación operativa mínima

**Descripción:** Un desarrollador debe poder instalar, configurar, verificar y probar H1 desde el README público.

**Prioridad:** Should.

**Criterios de aceptación:**

- README documenta prerrequisitos, entorno virtual, instalación editable y comandos H1;
- explica cómo copiar y ajustar `barbarion.example.toml`;
- explica que Ollama es opcional para aceptar H1 y cómo interpreta `doctor` su ausencia;
- documenta códigos de salida y comando de pruebas;
- no incluye rutas personales, nombres internos, secretos ni presenta capacidades futuras como disponibles.

## 5. Requisitos no funcionales

### H1-NFR-001 — Operación local

**Descripción:** El uso normal de H1 debe funcionar sin acceso a internet.

**Prioridad:** Must.

**Criterios de aceptación:**

- no existe telemetría ni llamada remota distinta del endpoint de Ollama configurado;
- el timeout de Ollama limita el bloqueo al valor configurado;
- las pruebas no necesitan red.

### H1-NFR-002 — Portabilidad acotada

**Descripción:** La base debe usar APIs portables de Python 3.12 y `pathlib`.

**Prioridad:** Must.

**Criterios de aceptación:**

- no se codifican separadores, unidades de disco ni rutas de usuario;
- las pruebas pasan con rutas relativas y absolutas;
- la aplicación no ejecuta comandos dependientes del shell.

### H1-NFR-003 — Simplicidad estructural

**Descripción:** H1 debe evitar capas y contratos que todavía no tengan consumidores reales.

**Prioridad:** Must.

**Criterios de aceptación:**

- se usan módulos directos dentro de `src/barbarion/`;
- no se crean directorios `domain`, `application`, `infrastructure`, `services`, `repositories` ni `plugins`;
- no se introduce contenedor de dependencias ni framework de configuración, CLI, ORM o migraciones;
- las dependencias runtime de terceros son cero.

### H1-NFR-004 — Imports sin efectos secundarios

**Descripción:** Importar cualquier módulo de Barbarion debe ser una operación pura respecto del entorno.

**Prioridad:** Must.

**Criterios de aceptación:**

- importar cualquier módulo bajo `barbarion` no crea archivos ni directorios;
- no abre conexiones SQLite;
- no configura logging ni añade handlers;
- no realiza llamadas HTTP ni otras operaciones de red;
- toda inicialización ocurre únicamente al invocar explícitamente una función desde el flujo CLI correspondiente.

## 6. Criterio de finalización

H1 está completo cuando todos los requisitos Must y el test plan pasan, la documentación refleja el comportamiento real y una instalación limpia ejecuta:

```text
barbarion --help
barbarion --version
barbarion config show
barbarion doctor
python -m pytest
```

La ausencia de Ollama puede producir una advertencia, pero no impide aceptar H1.
