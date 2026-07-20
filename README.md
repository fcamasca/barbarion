# Barbarion

[![CI](https://github.com/fcamasca/barbarion/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/fcamasca/barbarion/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/fcamasca/barbarion)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue)](pyproject.toml)

Barbarion es un agente de IA on-premise para análisis, documentación e ingeniería inversa asistida de sistemas legacy **Oracle/PL/SQL + PowerBuilder**.

Está pensado para equipos que necesitan comprender sistemas existentes sin enviar código, documentación ni contexto técnico a servicios cloud. Trabaja sobre un corpus local autorizado, lo transforma en evidencia consultable y genera salidas Markdown trazables.

El MVP mantiene una arquitectura deliberadamente simple: aplicación Python modular de un solo proceso, CLI-first, SQLite + sqlite-vec, parsers heurísticos y Ollama opcional según el comando.

## Problema que resuelve

En sistemas legacy Oracle/PL/SQL y PowerBuilder, la lógica de negocio suele estar repartida entre packages, triggers, ventanas, DataWindows, SQL embebido y documentación incompleta. Ubicar una regla, estimar impacto o preparar una especificación puede requerir revisar muchos archivos sin una ruta clara.

Barbarion reduce ese trabajo manual convirtiendo artefactos locales en un catálogo técnico consultable, con fuentes, relaciones y límites explícitos. No reemplaza la revisión humana: organiza evidencia para que esa revisión sea más rápida y verificable.

## ¿Qué puede hacer?

Barbarion convierte código y documentación legacy en un catálogo técnico consultable.

Puede:

- localizar donde se implementa una regla o identificador;
- relacionar componentes Oracle/PL/SQL y PowerBuilder;
- identificar dependencias e impacto técnico;
- responder preguntas con evidencia y citas;
- generar especificaciones Markdown para cambios controlados.

## Cómo funciona

```text
Corpus autorizado
      |
      v
barbarion ingest        H2: prepara documentos, chunks y metadata
      |
      v
barbarion index         H3: indexa evidencia recuperable con SQLite + sqlite-vec
      |
      v
barbarion analyze       H4: genera inventario, símbolos y relaciones
      |
      v
barbarion ask / describe / impact
      |
      v
barbarion spec create   H5: produce specs Markdown trazables
```

Los comandos operan sobre archivos locales y SQLite. Ollama se usa solo cuando el comando necesita embeddings o LLM local; varias rutas de diagnóstico, ingesta, análisis, búsqueda keyword y salidas `--no-llm` no requieren un modelo real.

## Ejemplo end-to-end

```bash
barbarion ingest
barbarion index
barbarion analyze
barbarion ask "Dónde se calcula order_total?" --mode hybrid
barbarion impact order_total --depth 2 --no-llm
barbarion spec create "Agregar validación de límite de crédito" --name limite-credito --mode keyword --no-llm
```

El ejemplo usa nombres sanitizados. En un corpus real, las respuestas incluyen rutas, fragmentos, citas y advertencias cuando la evidencia no alcanza para sostener una conclusión.

## Estado del MVP

- Versión actual: `0.6.0`
- Hitos completados: `5/5`
- Suite de aceptación del MVP: `502 passed, 2 skipped`
- Smoke tests instalados: `10 passed`
- Runtime validado: Python `3.12`
- Integración continua: GitHub Actions
- Operación: local y on-premise

### Evolución posterior al MVP

- H4.1 Configuraciones Data-Driven: completada y aceptada técnicamente.
- Suite oficial H4.1: `581 passed, 2 skipped`.
- Evidencia: [`specs/H4.1-DataDrivenConfigurations/acceptance.md`](specs/H4.1-DataDrivenConfigurations/acceptance.md).

La evidencia técnica está documentada en [`specs/H5-SpecMode/acceptance.md`](specs/H5-SpecMode/acceptance.md). Ese registro conserva además la nota de revisión humana pendiente para la spec piloto H5.

## Quick Start

Este recorrido deja el proyecto instalado y ejecuta el flujo principal sobre el corpus configurado en `barbarion.toml`.

```bash
git clone https://github.com/fcamasca/barbarion.git
cd barbarion
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
cp barbarion.example.toml barbarion.toml
barbarion doctor
barbarion ingest
barbarion index
barbarion analyze
barbarion ask "Dónde se calcula order_total?" --mode hybrid
```

En Windows PowerShell, activa el entorno con `.\.venv\Scripts\Activate.ps1` y copia la configuración con `Copy-Item barbarion.example.toml barbarion.toml`. Antes de ingestar, edita `barbarion.toml` para apuntar `[ingestion].paths` a una carpeta local autorizada.

Los detalles de instalación de Ollama, políticas de ejecución de PowerShell, modos `keyword`, `semantic` e `hybrid`, códigos de salida y ejemplos avanzados están en la [referencia CLI](docs/CLI.md).

## Demostración

Las capturas reproducibles deben mantenerse en `docs/images/`.

Capturas recomendadas:

- salida de `barbarion ask`;
- salida de `barbarion impact`;
- archivos generados por `barbarion spec create`.

<!--
Pendiente: agregar capturas reales en docs/images/ cuando exista una corrida pública reproducible.
No enlazar imágenes hasta que los archivos estén versionados.
-->

## Requisitos

- CPython `3.12` (`>=3.12,<3.13`);
- `pip`;
- Ollama local solo para comandos que usan embeddings o LLM.

Las pruebas automatizadas no requieren un Ollama real ni acceso a servicios externos: usan directorios temporales y un endpoint falso en loopback.

## Comandos disponibles

| Comando | Resultado | Efectos secundarios |
|---|---|---|
| `barbarion --help` | Muestra ayuda en español | Ninguno |
| `barbarion --version` | Muestra la versión instalada | Ninguno |
| `barbarion config show` | Valida y muestra la configuración efectiva | Ninguno |
| `barbarion doctor` | Inicializa recursos y diagnostica el entorno | Crea directorios, SQLite y log si faltan |
| `barbarion ingest` | Ejecuta ingesta incremental del corpus configurado | Lee corpus y escribe metadata/chunks en SQLite |
| `barbarion index` | Indexa chunks vigentes para RAG | Escribe manifests, estados y vectores locales |
| `barbarion search "consulta"` | Recupera evidencia RAG | Registra métricas de consulta |
| `barbarion ask "pregunta"` | Responde con evidencia y citas | Registra métricas de consulta/contexto |
| `barbarion analyze` | Actualiza símbolos y relaciones de reverse engineering | Escribe catálogo técnico y runs en SQLite |
| `barbarion inventory` | Consulta inventario técnico persistido | Ninguno |
| `barbarion describe OBJETO` | Genera ficha técnica de un componente | Ninguno |
| `barbarion impact OBJETO` | Analiza impacto técnico desde relaciones persistidas | Ninguno |
| `barbarion spec create "REQUERIMIENTO"` | Genera una spec Markdown H5 desde evidencia H3/H4 | Escribe cuatro archivos Markdown si Review y validación pasan |
| `barbarion spec validate RUTA` | Valida una spec Markdown existente | Ninguno |
| `barbarion stats` | Muestra estadísticas de ingesta, RAG y reverse engineering | Ninguno |
| `barbarion generate-report` | Genera evidencia técnica RAG en `reports/rag` | Escribe reportes locales |

La referencia completa de la CLI está en [`docs/CLI.md`](docs/CLI.md).

## Configuración

El archivo versionado [`barbarion.example.toml`](barbarion.example.toml) documenta las claves disponibles para rutas locales, ingesta, RAG, Ollama, SQLite y salida.

`barbarion.toml` está excluido de Git. No deben versionarse rutas personales, credenciales ni endpoints privados.

La configuración se resuelve en este orden:

1. opción global `--config RUTA`;
2. variable de entorno `BARBARION_CONFIG`;
3. `./barbarion.toml`;
4. valores predeterminados.

Para inspeccionar los valores efectivos:

```bash
barbarion config show
barbarion --config ruta/al/archivo.toml config show
```

## Configuraciones Data-Driven

H4.1 está completada. La capacidad integra configuraciones declaradas con el
catálogo técnico, inventario, impacto, RAG y Spec Mode, incluyendo recuperación
estructurada por conceptos naturales y relaciones hacia código asociado.

Barbarion puede tratar archivos `.sql` declarados como configuracion sin
ejecutar el DML. Para habilitarlo, configura `data_driven.enabled = true`, los
`file_patterns`, tablas, columnas de identidad y columnas semanticas en
`barbarion.toml`. El ejemplo completo y comentado esta en
[`barbarion.example.toml`](barbarion.example.toml).

Flujo operativo recomendado:

```bash
barbarion ingest
barbarion analyze --dry-run
barbarion analyze
barbarion inventory --technology configuration
barbarion stats --format json
```

`analyze --dry-run` informa archivos DML candidatos, sentencias soportadas,
omitidas o con error, registros, simbolos, referencias, estados de relacion,
advertencias por archivo/linea y duracion por etapa. No escribe conocimiento.
La ejecucion normal reconcilia el alcance y publica los resultados consistentes
en SQLite. `stats` agrega una seccion `reverse_engineering.data_driven` cuando
se solicita JSON.

Las sentencias no soportadas y los registros malformados se diagnostican sin
impedir que otros documentos validos del alcance sean procesados. Ante un
diagnostico, revisa `motivo`, ruta y rango de lineas; corrige el DML o ajusta la
declaracion TOML y vuelve a ejecutar `ingest` seguido de `analyze`.

## Directorios locales

Con la configuración predeterminada, `barbarion doctor` inicializa:

```text
data/
  barbarion.db
output/
logs/
  barbarion.log
```

`data/`, `output/`, `logs/`, `barbarion.toml`, bases SQLite y `.venv/` están excluidos de Git.

## Pruebas

Ejecutar toda la suite:

```bash
python -m pytest
```

Ejecutar únicamente los smoke tests contra el entry point instalado:

```bash
python -m pytest tests/smoke
```

## Alcance y principios

- local y on-premise por diseño;
- CLI-first;
- monolito Python modular de un solo proceso;
- SQLite + sqlite-vec;
- parsers heurísticos;
- evidencia antes que elocuencia;
- entregables Markdown pequeños y verificables;
- revisión humana de resultados.

No forman parte del MVP una extensión de VS Code, UI web, autenticación, microservicios, Kubernetes, base de datos empresarial ni grafo avanzado. [`docs/EVOLUTION.md`](docs/EVOLUTION.md) documenta ideas posteriores y no forma parte del alcance MVP.

## Roadmap

El MVP se ejecutó en cinco hitos incrementales, desde Foundation hasta Spec Mode:

1. `H1-Foundation`
2. `H2-Ingestion`
3. `H3-RAG`
4. `H4-ReverseEngineering`
5. `H5-SpecMode`

La estimación histórica de 12 semanas y 120 horas se conserva en [`docs/ROADMAP.md`](docs/ROADMAP.md) como registro del plan original.

## Documentación

- [Guía de documentación](docs/README.md)
- [Visión del producto](docs/VISION.md)
- [Roadmap del MVP](docs/ROADMAP.md)
- [Arquitectura](docs/ARCHITECTURE.md)
- [Decisiones técnicas](docs/DECISIONS.md)
- [Referencia CLI](docs/CLI.md)
- [Operación de ingesta H2](docs/INGESTION.md)
- [Aceptación H3](specs/H3-RAG/acceptance.md)
- [Aceptación H4](specs/H4-ReverseEngineering/acceptance.md)
- [Validación H5](specs/H5-SpecMode/acceptance.md)
- [Configuracion del analisis Data-Driven](docs/data-driven-configuration.md)
- [Specs por hito](specs/)
- [Spec aprobada de H1](specs/H1-Foundation/)

## Licencia

Barbarion se distribuye bajo la [licencia MIT](LICENSE).
