# Barbarion

[![CI](https://github.com/fcamasca/barbarion/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/fcamasca/barbarion/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/fcamasca/barbarion)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue)](pyproject.toml)

Barbarion es una herramienta CLI de IA para analizar, documentar y hacer ingeniería inversa asistida de sistemas legacy **Oracle/PL/SQL + PowerBuilder**. Convierte un corpus autorizado en evidencia técnica consultable, manteniendo local el conocimiento del proyecto.

## Problema que resuelve

En sistemas legacy, la lógica de negocio suele estar repartida entre packages, triggers, ventanas, DataWindows, SQL embebido y documentación incompleta. Ubicar una regla, estimar su impacto o preparar una especificación puede exigir la revisión manual de muchos archivos.

Barbarion organiza esos artefactos como un catálogo técnico con fuentes, relaciones y límites explícitos. No reemplaza la revisión humana: ayuda a que sea más rápida y verificable.

## Capacidades principales

- localizar dónde se implementa una regla o identificador;
- relacionar componentes Oracle/PLSQL y PowerBuilder;
- identificar dependencias e impacto técnico;
- responder preguntas con evidencia y citas;
- generar especificaciones Markdown para cambios controlados;
- operar sin generación mediante las rutas `--no-llm` disponibles.

## Cómo funciona

```text
Corpus autorizado
      |
      v
barbarion ingest       prepara documentos, chunks y metadatos
      |
      v
barbarion index        indexa evidencia en SQLite + sqlite-vec
      |
      v
barbarion analyze      genera inventario, símbolos y relaciones
      |
      v
ask / describe / impact / patterns / spec create
```

El corpus, los índices y la evidencia permanecen en el entorno local. La generación de respuestas se ejecuta mediante el proveedor configurado. Consulta la [arquitectura](docs/ARCHITECTURE.md) para conocer los componentes y contratos internos.

## Quick Start

El flujo principal usa Ollama y requiere CPython `3.12`, `pip` y una instancia local de Ollama disponible.

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
barbarion ask "¿Dónde se calcula order_total?" --mode hybrid
```

Antes de ingestar, edita `barbarion.toml` para que `[ingestion].paths` apunte a una carpeta local autorizada. En Windows PowerShell, activa el entorno con `.\.venv\Scripts\Activate.ps1` y copia la configuración con `Copy-Item barbarion.example.toml barbarion.toml`.

Los detalles de instalación de Ollama, modos de búsqueda, códigos de salida y ejemplos avanzados están en la [referencia CLI](docs/CLI.md).

> Para usar Anthropic como backend de generación, consulta [Configurar Anthropic](#configurar-anthropic).

## Configurar Anthropic

Ollama es el proveedor predeterminado. Anthropic es opcional y ejecuta únicamente la generación final.

El corpus, los embeddings, SQLite, la búsqueda, la ingeniería inversa y la validación de citas permanecen locales. Para generar la respuesta, la pregunta, las instrucciones y el contexto seleccionado sí se envían a Anthropic.

Configura el bloque `[llm]` de `barbarion.toml`:

```toml
[llm]
provider = "anthropic"
model = "MODELO_CLAUDE"
timeout_seconds = 120.0
temperature = 0.1
max_output_tokens = 4096
```

`think` y `num_ctx` son exclusivos de Ollama. `max_output_tokens` solo se interpreta con Anthropic.

La API key no debe escribirse en TOML ni versionarse. Defínela únicamente mediante la variable de entorno `ANTHROPIC_API_KEY`.

PowerShell:

```powershell
$env:ANTHROPIC_API_KEY = "TU_API_KEY"
barbarion ask "¿Dónde se calcula order_total?" --mode hybrid
```

Linux/macOS:

```bash
export ANTHROPIC_API_KEY="TU_API_KEY"
barbarion ask "¿Dónde se calcula order_total?" --mode hybrid
```

Los valores son ilustrativos. No guardes ni versiones la key en archivos, scripts o ejemplos reales.

Antes de consultar, puedes validar la configuración efectiva sin mostrar el secreto:

```bash
barbarion config show
```

`config show` no valida la API key remota. Anthropic no tiene fallback automático a Ollama. Las rutas `--no-llm` no requieren key ni red.

Cuando Anthropic devuelve métricas de uso, la CLI puede mostrar tokens de entrada, tokens de salida, total de tokens y tiempo transcurrido. Barbarion no denomina “créditos” a los tokens ni calcula costos.

Para los detalles técnicos y de seguridad, consulta la [arquitectura](docs/ARCHITECTURE.md), las [decisiones](docs/DECISIONS.md), la [guía de Privacy Preflight](docs/PRIVACY.md), la [referencia CLI](docs/CLI.md) y la [spec H1.2](specs/H1.2-RemoteInference/).

## Privacy Preflight (H3.2)

Antes de cualquier inferencia remota, Barbarion evalúa localmente la política de
privacidad aplicable. `no_training` es bloqueante; los riesgos de retención
requieren confirmación explícita. `ask` no refresca metadata de privacidad
durante una consulta. Consulta la [guía de privacidad](docs/PRIVACY.md) para
registry, cache, proveedores y contratos completos.

## Comandos principales

| Comando | Propósito |
|---|---|
| `barbarion config show` | Valida y muestra la configuración efectiva |
| `barbarion doctor` | Inicializa recursos y diagnostica el entorno |
| `barbarion ingest` | Ingiere el corpus configurado |
| `barbarion index` | Indexa los chunks vigentes para RAG |
| `barbarion search "consulta"` | Recupera evidencia |
| `barbarion ask "pregunta"` | Responde con evidencia y citas |
| `barbarion analyze` | Actualiza símbolos y relaciones |
| `barbarion inventory` | Consulta el inventario técnico |
| `barbarion patterns` | Calcula rankings descriptivos de patrones estructurales |
| `barbarion describe OBJETO` | Describe un componente |
| `barbarion impact OBJETO` | Analiza impacto técnico |
| `barbarion spec create "REQUERIMIENTO"` | Genera una spec Markdown |
| `barbarion spec validate RUTA` | Valida una spec existente |
| `barbarion stats` | Muestra estadísticas del repositorio analizado |
| `barbarion generate-report` | Genera evidencia técnica RAG |
| `barbarion models ...` | Administra y evalúa modelos Ollama |

`barbarion models` trabaja exclusivamente con Ollama. Su benchmark compara modelos, pero no cambia automáticamente el modelo activo. Consulta la [spec H1.1](specs/H1.1-LocalModelManagement/) para conocer el flujo y los criterios completos.

La sintaxis, opciones, efectos secundarios y códigos de salida están documentados en [`docs/CLI.md`](docs/CLI.md).

## Estado del proyecto

### MVP completado

```text
H1 Foundation → H2 Ingesta/Memoria → H3 RAG/Recuperación →
H4 Ingeniería inversa → H5 Spec Mode
```

### Evoluciones implementadas

| Evolución | Capacidad | Estado |
|---|---|---|
| H1.1 | Gestión y benchmark de modelos locales | Aceptada |
| H1.2 | Inferencia remota | Aceptada |
| H3.1 | Optimización de contexto RAG | Aceptada |
| H3.2 | Privacy Preflight | Aceptada |
| H3.3 | Graph-Aware Retrieval | Aceptada, opt-in |
| H4.1 | Configuraciones Data-Driven | Aceptada |
| H4.2 | Patrones técnicos | Aceptada, descriptiva |

El detalle conceptual, las decisiones, benchmarks y próximas evoluciones se
mantienen en [docs/EVOLUTION.md](docs/EVOLUTION.md) y en las specs.

- Versión actual: `0.6.0`
- MVP completado: `5/5` hitos
- Suite completa de T08: `1107 passed, 14 skipped`; las pruebas focalizadas
  finales de H4.2: `10 passed`
- Smoke tests instalados: `11 passed`
- Runtime validado: Python `3.12`
- Integración continua: GitHub Actions

La evidencia del cierre del MVP está en [`specs/H5-SpecMode/acceptance.md`](specs/H5-SpecMode/acceptance.md).

## Documentación

- [Guía de documentación](docs/README.md)
- [Visión del producto](docs/VISION.md)
- [Arquitectura](docs/ARCHITECTURE.md)
- [Decisiones técnicas](docs/DECISIONS.md)
- [Referencia CLI](docs/CLI.md)
- [Roadmap](docs/ROADMAP.md)
- [Evolución del producto](docs/EVOLUTION.md)
- [Contexto RAG y benchmark H3.1](docs/H31-RAG-CONTEXT.md)
- [Operación de ingesta](docs/INGESTION.md)
- [Configuración Data-Driven](docs/data-driven-configuration.md)
- [Specs por hito](specs/)

El archivo [`barbarion.example.toml`](barbarion.example.toml) contiene una configuración completa y comentada. `barbarion.toml`, las bases SQLite, `data/`, `output/`, `logs/` y `.venv/` son artefactos locales excluidos de Git.

## Licencia

Barbarion se distribuye bajo la [licencia MIT](LICENSE).
