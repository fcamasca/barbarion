# Barbarion

Barbarion es un agente AI on-premise para análisis, documentación e ingeniería inversa asistida de sistemas legacy **Oracle/PLSQL + PowerBuilder**.

Su objetivo es ayudar a desarrolladores y analistas técnicos a comprender código existente, localizar dependencias y producir documentación trazable sin enviar el corpus a servicios cloud.

> El MVP se valida inicialmente sobre un dominio legacy real, pero ese dominio no forma parte del diseño público ni limita la arquitectura de Barbarion.

## Estado

`H1-Foundation` está completado y aceptado en la versión `0.1.0`.
`H2-Ingestion` está completado y aceptado en la versión `0.2.0`.
`H3-RAG` está completado y aceptado en la versión `0.3.0`.
`H4-ReverseEngineering` está completado, revisado y aceptado en la versión `0.4.0`.

H3 incluye:

- paquete Python instalable;
- CLI local en español;
- configuración TOML validada;
- inicialización segura de directorios;
- logging local;
- SQLite versionado;
- diagnóstico reproducible mediante `barbarion doctor`;
- ingesta local incremental de corpus autorizado;
- parsers heurísticos para Oracle/PLSQL, PowerBuilder textual, Markdown, texto, configuración, PDF y DOCX;
- métricas, stats e inventario consultable desde SQLite;
- pruebas unitarias, de integración y smoke;
- indexación RAG local sobre SQLite + sqlite-vec;
- búsqueda `semantic`, `keyword` e `hybrid`;
- `ask` con contexto trazable, citas y modo `--no-llm`;
- benchmark RAG con `recall@5`, `recall@10`, `mrr`, latencia e historico local;
- reportes de cierre RAG en `reports/rag`.

Qdrant no es dependencia inicial de H3; queda diferido como alternativa futura. Ingeniería inversa profunda y generación de documentos pertenecen a hitos posteriores.

## Requisitos

- CPython `3.12` (`>=3.12,<3.13`);
- `pip`;
- Ollama es opcional para H1/H2 y para consultas H3 sin LLM.

Ollama no es necesario para instalar, probar ni ejecutar H2. En H3 se requiere para `index` real con embeddings Ollama y para `ask` con LLM; `index --dry-run`, `search --mode keyword` y `ask --no-llm --mode keyword` pueden ejecutarse sin modelo real. Cuando Ollama no está disponible, `doctor` informa `WARN` y conserva el código de salida `0` si todos los checks requeridos pasan.

## Quick Start

Este flujo deja una instalación local lista para hacer la primera consulta RAG sobre un corpus propio en pocos minutos.

### 1. Crear entorno virtual

```bash
git clone https://github.com/tu-org/barbarion.git
cd barbarion
python -m venv .venv
```

### 2. Activar entorno

**Windows PowerShell:**
```powershell
.\.venv\Scripts\Activate.ps1
```

Si PowerShell bloquea la ejecución de scripts con un error similar a:
```text
PSSecurityException: la ejecución de scripts está deshabilitada en este sistema
```

habilitar la ejecución únicamente para la sesión actual:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Este cambio no modifica la política del sistema de forma permanente y solo afecta la ventana actual de PowerShell.

**Linux o macOS:**
```bash
source .venv/bin/activate
```

### 3. Instalar Barbarion

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Comprobar la instalación:
```bash
barbarion --version
barbarion --help
```

### 4. Instalar Ollama

Descargarlo desde [ollama.com](https://ollama.com/) e iniciar el servicio local. Verificar:

```bash
ollama --version
```

### 5. Descargar modelos locales

```bash
ollama pull nomic-embed-text
ollama pull llama3.1:8b
ollama list
```

`nomic-embed-text` se usa para embeddings. `llama3.1:8b` es una opción local para `ask`; puedes cambiarlo en `[llm]`.

### 6. Configurar barbarion.toml

```bash
cp barbarion.example.toml barbarion.toml
```

```powershell
# Windows PowerShell
Copy-Item barbarion.example.toml barbarion.toml
```

Editar `barbarion.toml` y apuntar `[ingestion].paths` a una carpeta local autorizada, por ejemplo:

```toml
[ingestion]
paths = ["./sources"]
```

### 7. Ejecutar doctor

```bash
barbarion doctor
```

Salida esperada resumida:
```text
PASS  Python
PASS  Configuracion
PASS  Directorio de datos
PASS  Directorio de salida
PASS  Directorio de logs
PASS  Directorio de fuentes
PASS  SQLite
PASS  Ollama

Resumen: 8 PASS, 0 WARN, 0 FAIL
```

### 8. Ingestar documentos

```bash
barbarion ingest
```

### 9. Indexar

```bash
barbarion index --dry-run
barbarion index
```

### 10. Primera búsqueda

```bash
barbarion search "consulta" --mode hybrid
barbarion search "donde se calcula order_total" --mode hybrid
```

Si todavía no tienes embeddings o modelo disponible, puedes probar keyword:
```bash
barbarion search "calculate_discount" --mode keyword
```

Como regla practica:

- `--mode keyword`: coincidencia textual; usalo para nombres exactos de variables, tablas, procedimientos o codigos de negocio.
- `--mode semantic`: similitud por significado; usalo para explorar conceptos aunque no conozcas los nombres exactos.
- `--mode hybrid`: combina keyword y semantic; es el modo recomendado para preguntas naturales.

Salida esperada resumida:
```text
Busqueda RAG: hybrid
Query: 1
- score=0.842 chunk=... sources/oracle/orders.sql lineas=10-32
```

### 11. Primera pregunta

```bash
barbarion ask "pregunta" --mode hybrid
barbarion ask "que fuentes explican order_total?" --mode hybrid
```

Para inspeccionar contexto sin invocar LLM:
```bash
barbarion ask "que fuentes explican order_total?" --mode keyword --no-llm
```

Salida esperada resumida:
```text
## Conclusion
Respuesta basada en la evidencia recuperada. [F1]

## Evidencia
- [F1] ...

## Supuestos y limites
- ...
```

### 12. Primer analisis reverse engineering

```bash
barbarion analyze --dry-run
barbarion analyze
```

### 13. Inventario tecnico

```bash
barbarion inventory --format text
```

### 14. Ficha de componente

```bash
barbarion describe order_total --no-llm
```

### 15. Impacto tecnico

```bash
barbarion impact order_total --depth 2 --no-llm
```

### 16. Estadisticas locales

```bash
barbarion stats
```

## Configuración

El archivo versionado [`barbarion.example.toml`](barbarion.example.toml) documenta todas las claves disponibles para la base local, la ingesta H2 y la configuración base H3. Para crear una configuración local:

```powershell
# Windows PowerShell
Copy-Item barbarion.example.toml barbarion.toml
```

```bash
# Linux o macOS
cp barbarion.example.toml barbarion.toml
```

`barbarion.toml` está excluido de Git. No deben versionarse rutas personales, credenciales ni endpoints privados.

La configuración se resuelve en este orden:

1. opción global `--config RUTA`;
2. variable de entorno `BARBARION_CONFIG`;
3. `./barbarion.toml`;
4. valores predeterminados.

Las rutas relativas se resuelven desde el directorio del archivo TOML. Sin archivo, se resuelven desde el directorio de trabajo.

Para inspeccionar los valores efectivos sin crear recursos:

```bash
barbarion config show
barbarion --config ruta/al/archivo.toml config show
```

Las secciones H3 `[embeddings]`, `[vector_store]`, `[retrieval]`, `[rag]` y `[llm]` ya pueden validarse y mostrarse con `config show`. `vector_store.provider = "sqlite_vec"` es el valor soportado para el MVP; Qdrant queda diferido como alternativa futura.

## Comandos disponibles

| Comando | Resultado | Efectos secundarios |
|---|---|---|
| `barbarion --help` | Muestra ayuda en español | Ninguno |
| `barbarion --version` | Muestra la versión instalada | Ninguno |
| `barbarion config show` | Valida y muestra la configuración efectiva | Ninguno |
| `barbarion doctor` | Inicializa recursos y diagnostica el entorno | Crea directorios, SQLite y log si faltan |
| `barbarion ingest` | Ejecuta ingesta incremental del corpus configurado | Lee corpus y escribe metadata/chunks en SQLite |
| `barbarion index` | Indexa chunks vigentes para RAG con progreso por etapas | Escribe manifests, estados y vectores locales |
| `barbarion reindex` | Reconstruye total o parcialmente el indice RAG | Escribe estados y vectores locales |
| `barbarion search "consulta"` | Recupera evidencia RAG | Registra métricas de consulta |
| `barbarion ask "pregunta"` | Responde con evidencia y citas | Registra métricas de consulta/contexto |
| `barbarion embeddings` | Muestra manifests, versiones y conteos | Ninguno |
| `barbarion analyze` | Actualiza simbolos y relaciones de reverse engineering desde chunks vigentes | Escribe catalogo tecnico y runs en SQLite |
| `barbarion inventory` | Consulta inventario tecnico persistido | Ninguno |
| `barbarion describe OBJETO` | Genera ficha tecnica de un componente | Ninguno |
| `barbarion impact OBJETO` | Analiza impacto tecnico desde relaciones persistidas | Ninguno |
| `barbarion stats` | Muestra estadísticas de ingesta + RAG + reverse engineering | Ninguno |
| `barbarion generate-report` | Genera evidencia técnica RAG en `reports/rag` | Escribe reportes locales |

La referencia completa de la CLI esta en [`docs/CLI.md`](docs/CLI.md).

## Directorios y archivos locales

Con la configuración predeterminada, `barbarion doctor` inicializa:

```text
data/
└── barbarion.db
output/
logs/
└── barbarion.log
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

Las pruebas usan directorios temporales y un endpoint Ollama falso en loopback. No necesitan un Ollama real ni acceso a internet.

## Alcance y principios

- local y on-premise por diseño;
- CLI-first;
- monolito Python modular de un solo proceso;
- biblioteca estándar para el runtime de H1;
- evidencia antes que elocuencia;
- un solo dominio configurado durante la validación inicial;
- entregables pequeños y verificables;
- revisión humana de resultados futuros.

No forman parte del MVP una extensión de VS Code, UI web, autenticación, microservicios, Kubernetes, base de datos empresarial ni grafo avanzado. `docs/EVOLUTION.md` documenta ideas posteriores y no forma parte del alcance MVP.

## Roadmap

1. `H1-Foundation`
2. `H2-Ingestion`
3. `H3-RAG`
4. `H4-ReverseEngineering`
5. `H5-SpecMode`

El plan completo contempla aproximadamente 12 semanas y 120 horas de trabajo.

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
- [Specs por hito](specs/)
- [Spec aprobada de H1](specs/H1-Foundation/)

## Licencia

Barbarion se distribuye bajo la [licencia MIT](LICENSE).
