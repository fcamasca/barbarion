# Barbarion

[![CI](https://github.com/fcamasca/barbarion/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/fcamasca/barbarion/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/fcamasca/barbarion)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue)](pyproject.toml)

Barbarion es un agente de IA con conocimiento on-premise para análisis, documentación e ingeniería inversa asistida de sistemas legacy **Oracle/PL/SQL + PowerBuilder**.

Está pensado para equipos que necesitan comprender sistemas existentes manteniendo local el corpus, los índices y la evidencia técnica. La generación puede ejecutarse con Ollama o, de forma explícita, enviar únicamente el prompt final a Anthropic; las rutas `--no-llm` no requieren key ni red.

El MVP mantiene una arquitectura deliberadamente simple: aplicación Python modular de un solo proceso, CLI-first, SQLite + sqlite-vec, parsers heurísticos, Ollama para embeddings y una factoría generativa cerrada Ollama/Anthropic.

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

Los comandos operan sobre archivos locales y SQLite. Ollama se usa para embeddings y como backend generativo predeterminado. Si `[llm].provider = "anthropic"`, solo la generación final usa Anthropic; ingesta, inventario, embeddings, SQLite, búsqueda híbrida, ingeniería inversa, Reasoning Package y validación de citas continúan localmente. Varias rutas de diagnóstico, ingesta, análisis, búsqueda keyword y salidas `--no-llm` no requieren un modelo generativo ni acceso remoto.

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
- Operación: conocimiento on-premise; inferencia remota opcional

### Evolución posterior al MVP

- H4.1 Configuraciones Data-Driven: completada y aceptada técnicamente.
- Suite oficial H4.1: `581 passed, 2 skipped`.
- Evidencia: [`specs/H4.1-DataDrivenConfigurations/acceptance.md`](specs/H4.1-DataDrivenConfigurations/acceptance.md).
- H1.1 Gestión y Evaluación de Modelos Locales: completada y aceptada
  técnicamente, con comparación real entre modelos pendiente por condiciones del
  entorno de aceptación.
- Suite oficial H1.1: `713 passed, 3 skipped`; smoke instalado: `10 passed`.
- Evidencia: [`specs/H1.1-LocalModelManagement/acceptance.md`](specs/H1.1-LocalModelManagement/acceptance.md).

H1.1 no selecciona automáticamente un modelo ni declara un candidato sin una
corrida real elegible. La aceptación confirma la capacidad; la elección operativa
continúa siendo explícita y requiere revisión humana.

- H1.2 Inferencia Remota con Anthropic: implementación técnica y documentación
  completadas; aceptación pendiente.
- Alcance: Anthropic es el único proveedor remoto implementado. Ollama sigue
  siendo el default y el único proveedor de embeddings.
- Spec: [`specs/H1.2-RemoteInference/`](specs/H1.2-RemoteInference/).

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
- Ollama local para embeddings, administración H1.1 y generación predeterminada;
- `ANTHROPIC_API_KEY` en el entorno únicamente si se configura generación Anthropic.

Las pruebas automatizadas no requieren un Ollama real, una key válida ni acceso a servicios externos: bloquean conexiones no-loopback y usan adaptadores o endpoints falsos controlados.

## Comandos disponibles

| Comando | Resultado | Efectos secundarios |
|---|---|---|
| `barbarion --help` | Muestra ayuda en español | Ninguno |
| `barbarion --version` | Muestra la versión instalada | Ninguno |
| `barbarion config show` | Valida y muestra la configuración efectiva | Ninguno |
| `barbarion doctor` | Inicializa recursos y diagnostica el entorno | Crea directorios, SQLite y log si faltan |
| `barbarion models list/show/validate` | Consulta modelos Ollama locales y readiness de generacion | Ninguno |
| `barbarion models install MODELO` | Solicita explicitamente un pull a Ollama | Descarga local; no cambia el modelo activo |
| `barbarion models select MODELO` | Valida y cambia solamente `[llm].model` con Ollama activo | Edita atomicamente el TOML efectivo; se bloquea con Anthropic |
| `barbarion models benchmark --models M1 M2` | Compara modelos con un dataset sintetico | Escribe JSON y Markdown locales; no selecciona candidato |
| `barbarion ingest` | Ejecuta ingesta incremental del corpus configurado | Lee corpus y escribe metadata/chunks en SQLite |
| `barbarion index` | Indexa chunks vigentes para RAG | Escribe manifests, estados y vectores locales |
| `barbarion search "consulta"` | Recupera evidencia RAG | Registra métricas de consulta |
| `barbarion ask "pregunta"` | Responde con evidencia y citas usando el proveedor configurado | Registra métricas de consulta/contexto; con Anthropic envía el prompt final |
| `barbarion analyze` | Actualiza símbolos y relaciones de reverse engineering | Escribe catálogo técnico y runs en SQLite |
| `barbarion inventory` | Consulta inventario técnico persistido | Ninguno |
| `barbarion describe OBJETO` | Genera ficha técnica de un componente | Con `--with-llm`, usa el proveedor configurado y conserva fallback determinista |
| `barbarion impact OBJETO` | Analiza impacto técnico desde relaciones persistidas | Con `--with-llm`, usa el proveedor configurado y conserva fallback determinista |
| `barbarion spec create "REQUERIMIENTO"` | Genera una spec Markdown H5 desde evidencia H3/H4 | Escribe cuatro archivos Markdown si Review y validación pasan |
| `barbarion spec validate RUTA` | Valida una spec Markdown existente | Ninguno |
| `barbarion stats` | Muestra estadísticas de ingesta, RAG y reverse engineering | Ninguno |
| `barbarion generate-report` | Genera evidencia técnica RAG en `reports/rag` | Escribe reportes locales |

La referencia completa de la CLI está en [`docs/CLI.md`](docs/CLI.md).

## Configuración

El archivo versionado [`barbarion.example.toml`](barbarion.example.toml) documenta las claves disponibles para rutas locales, ingesta, RAG, Ollama, Anthropic, SQLite y salida.

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

### Inferencia remota con Anthropic

H1.2 permite seleccionar Anthropic sin cambiar retrieval, prompts, citas,
formatos ni persistencia. Sustituye el bloque `[llm]` por una configuración como:

```toml
[llm]
provider = "anthropic"
model = "modelo-claude-autorizado"
timeout_seconds = 120.0
temperature = 0.1
max_output_tokens = 4096
```

`max_output_tokens` pertenece únicamente a Anthropic. `think` y `num_ctx`
pertenecen únicamente a Ollama; combinar campos incompatibles produce un error
de configuración antes de cualquier red.

La credencial nunca se admite en TOML ni por argumento CLI. Debe existir solo en
el entorno del proceso que solicita generación:

```powershell
$secret = Read-Host "ANTHROPIC_API_KEY" -AsSecureString
$env:ANTHROPIC_API_KEY = [System.Net.NetworkCredential]::new("", $secret).Password
Remove-Variable secret
barbarion ask "¿Dónde se calcula order_total?" --mode hybrid
```

En CI o shells distintos, usa el mecanismo seguro de secretos del entorno y
evita guardar el valor en historial, scripts o archivos versionados.

H1.2 usa `POST` no streaming a Messages API con endpoint y versión fijos. No
realiza retries, fallback a Ollama ni cálculo de costos. Cuando Anthropic informa
uso, la CLI muestra `Input tokens`, `Output tokens`, `Total tokens` y tiempo
transcurrido; no los denomina créditos ni aplica tablas de precios.

El egress remoto contiene el modelo, límites de generación y el mismo texto
producido por `PromptBuilder`. No se envían la base SQLite, vectores, manifests,
configuración, variables de entorno ni archivos completos fuera del contexto
RAG seleccionado. Prompts, respuestas, key, request-id y métricas de uso no se
persisten en SQLite ni en artefactos nuevos.

## Modelos locales y benchmark

La administracion de modelos usa exclusivamente la instancia Ollama configurada.
No ejecuta comandos shell ni envia prompts, contexto o respuestas a servicios
cloud.

```bash
barbarion models list
barbarion models show modelo-local:tag
barbarion models install modelo-local:tag --dry-run
barbarion models validate modelo-local:tag
barbarion models select modelo-local:tag --dry-run
barbarion models benchmark --models modelo-a:tag modelo-b:tag
```

`models validate` solo acredita generacion minima. La adecuacion funcional se
evalua con `models benchmark`, que usa ocho casos sinteticos, temperatura cero,
una ejecucion por caso/modelo y rotacion secuencial determinista. Por defecto
crea:

```text
output/model-benchmarks/<run-id>/model-benchmark.json
output/model-benchmarks/<run-id>/model-benchmark.md
```

El reporte compara calidad lexical, instrucciones, groundedness, uso de contexto,
citas, validador, latencia y tokens cuando Ollama los informa. Los datos ausentes
permanecen `null`; no se calcula p95 en H1.1. Un candidato solo aparece si la
corrida esta completa, todos sus casos terminaron y la aceptacion es al menos
0.90. Es una recomendacion para revision humana: Barbarion nunca cambia el modelo
activo desde el benchmark: el benchmark nunca cambia el modelo activo. Para
adoptarlo, ejecuta despues `models select` de
forma explicita.

Con Anthropic activo, los comandos de catálogo, instalación y benchmark siguen
apuntando exclusivamente a Ollama. `models validate` requiere entonces un nombre
Ollama explícito. `models select` se bloquea para no reemplazar accidentalmente
el modelo Claude mientras `[llm].model` represente el modelo del proveedor
activo; esta es una limitación temporal del modelo de configuración actual.

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

- conocimiento, embeddings, retrieval y persistencia locales por diseño;
- generación local por defecto y Anthropic remoto solo por configuración explícita;
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

Las evoluciones posteriores H4.1, H1.1 y H1.2 se registran en
[`docs/EVOLUTION.md`](docs/EVOLUTION.md). H1.2 está implementada y su aceptación
formal permanece pendiente.

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
- [Spec H1.2 de inferencia remota](specs/H1.2-RemoteInference/)
- [Specs por hito](specs/)
- [Spec aprobada de H1](specs/H1-Foundation/)

## Licencia

Barbarion se distribuye bajo la [licencia MIT](LICENSE).
