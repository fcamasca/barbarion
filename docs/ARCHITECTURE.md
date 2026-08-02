# Barbarion — Arquitectura del MVP

## 1. Objetivo arquitectónico

La arquitectura debe soportar un flujo local completo —ingestar, buscar, analizar y documentar— con la menor cantidad razonable de componentes. El MVP se valida inicialmente sobre un dominio legacy real, pero ese dominio no forma parte del diseño público ni limita la arquitectura de Barbarion. El MVP será una **aplicación Python modular de un solo proceso**, invocada desde CLI y respaldada por almacenamiento local.

La separación entre módulos existe para mantener el código comprensible y comprobable, no para desplegar servicios independientes.

## 2. Decisiones principales

| Área | Decisión del MVP | Motivo |
|---|---|---|
| Interfaz | CLI | Menor costo, fácil de automatizar y suficiente para validar valor |
| Backend | Python 3.12, una aplicación | Ecosistema sólido para parsing, RAG y modelos locales |
| API HTTP | No usar inicialmente | FastAPI no aporta al flujo CLI de un solo usuario; puede añadirse como adaptador futuro |
| Metadata | SQLite | Local, transaccional, inspeccionable y sin servidor |
| Vectores | SQLite + sqlite-vec | Mantiene metadata y vectores en el mismo archivo local y conserva el índice reconstruible |
| LLM y embeddings | Ollama | Inferencia local con una interfaz estable y modelos sustituibles por configuración |
| Entregables | Markdown | Legible, editable, versionable y adecuado para specs |
| Parsing | Heurísticas por tipo + fallback de texto | Valor temprano sin intentar compiladores completos |
| Arquitectura | Monolito modular con puertos pequeños | Evoluciona sin introducir distribución prematura |

Los nombres concretos de modelos se definirán en configuración y se validarán en el hardware objetivo. No forman parte del dominio ni deben quedar codificados en la lógica.

## 3. Contexto del sistema

```mermaid
flowchart LR
    U["Desarrollador del sistema legacy"] --> CLI["Barbarion CLI"]
    SRC["Código y documentación autorizados"] --> CLI
    CLI --> APP["Aplicación Python local"]
    APP --> SQL[("SQLite\nmetadata, relaciones y sqlite-vec")]
    APP --> OL["Ollama\nembeddings y LLM"]
    APP --> MD["Documentos Markdown"]
```

Todos los componentes se ejecutan dentro del entorno controlado. Barbarion no necesita conectarse a una base Oracle productiva: analiza artefactos exportados y documentación autorizada.

## 4. Flujo principal

```mermaid
flowchart TD
    A["Carpeta fuente autorizada"] --> B["Escaneo y checksum"]
    B --> C["Clasificación y decoding"]
    C --> D["Parser heurístico"]
    D --> E["Chunks + metadata + referencias"]
    E --> F[("SQLite")]
    E --> G["Ollama embeddings"]
    G --> F

    Q["Pregunta o comando"] --> R["Recuperación semántica + filtros"]
    F --> R
    R --> P["Construcción de contexto"]
    P --> L["Ollama LLM"]
    L --> V["Validación y formato"]
    V --> O["CLI o Markdown con fuentes"]
```

### Ingesta

1. El escáner aplica rutas incluidas, exclusiones y límites.
2. Se calcula un checksum para decidir si el archivo debe procesarse.
3. El decoder conserva información sobre encoding y registra sustituciones o fallos.
4. El parser extrae unidades lógicas y referencias conocidas; si falla, se usa texto segmentado.
5. SQLite guarda la identidad, procedencia, estado y relaciones.
6. Ollama genera embeddings y SQLite/sqlite-vec almacena cada vector con un identificador estable.
7. Una operación de sincronización retira metadata y vectores obsoletos.

### Consulta RAG

1. La consulta se convierte en embedding.
2. sqlite-vec recupera candidatos, opcionalmente filtrados por metadata.
3. SQLite aporta datos de archivo, objeto y relaciones simples.
4. Un ensamblador limita y ordena el contexto según presupuesto configurable.
5. El LLM responde bajo una plantilla que exige evidencia, supuestos y límites.
6. La salida valida que las referencias apunten a fragmentos recuperados.

La validación de referencias reduce afirmaciones no sustentadas, pero no convierte la salida del modelo en una verdad automática. La revisión humana sigue siendo obligatoria.

## 5. Componentes internos

### 5.1 CLI

Responsabilidades:

- interpretar comandos y opciones;
- cargar configuración;
- presentar progreso, resultados y errores;
- devolver códigos de salida útiles.

Comandos previstos, incorporados por hito:

```text
barbarion doctor
barbarion models list
barbarion models show <modelo>
barbarion models install <modelo>
barbarion models validate <modelo>
barbarion models select <modelo>
barbarion models benchmark --models <modelo-1> <modelo-2>
barbarion ingest <ruta>
barbarion status
barbarion search "consulta"
barbarion ask "pregunta"
barbarion describe <objeto>
barbarion impact <objeto>
barbarion spec create <nombre>
```

Los comandos expresan casos de uso. No deben contener lógica de parsing, recuperación ni generación.

### 5.2 Configuración

Un archivo local, por ejemplo `barbarion.toml`, define:

- identificador del único dominio configurado para la validación;
- rutas de entrada, salida y datos;
- inclusiones y exclusiones;
- URL local de Ollama y modelos seleccionados;
- tamaños y solapamiento de chunks;
- top-k y límites de contexto;
- ubicación de SQLite y configuración de sqlite-vec;
- nivel de logging.

Se versiona un archivo de ejemplo, no la configuración con rutas, secretos o datos reales. Los valores efectivos deben poder mostrarse con datos sensibles ocultos.

### 5.3 Ingesta y parsers

Se define un contrato pequeño para los parsers: reciben texto y contexto del archivo; devuelven fragmentos, símbolos, referencias, advertencias y posición de origen.

Parsers iniciales:

- **PLSQL:** detecta package, procedure, function, trigger, view y bloques; busca referencias frecuentes a tablas, vistas y llamadas a otros objetos;
- **PowerBuilder:** reconoce cabeceras exportadas, objetos, eventos, funciones, DataWindows, SQL embebido y llamadas comunes;
- **Markdown/texto:** segmenta por encabezados y bloques;
- **fallback:** divide texto por ventanas controladas cuando no reconoce estructura.

Reglas importantes:

- nunca descartar el contenido porque una heurística no lo entienda;
- conservar archivo, líneas y parser utilizado;
- distinguir símbolo declarado, referencia detectada e inferencia;
- registrar confianza o método, no inventar certeza;
- probar parsers con fixtures pequeños y casos reales anonimizados.

No se usará un AST universal ni una gramática completa durante el MVP.

### 5.4 Metadata en SQLite

Modelo conceptual mínimo:

```mermaid
erDiagram
    FILE ||--o{ DOCUMENT : normaliza
    DOCUMENT ||--o{ CHUNK : contiene
    FILE ||--o{ SYMBOL : declara
    CHUNK ||--o{ SYMBOL : ubica
    SYMBOL ||--o{ SYMBOL_REFERENCE : origen
    SYMBOL_REFERENCE ||--o{ RELATION : resuelve
    SYMBOL ||--o{ RELATION : origen
    SYMBOL ||--o{ RELATION : destino
    ANALYSIS_RUN ||--o{ SYMBOL : actualiza
    ANALYSIS_RUN ||--o{ SYMBOL_REFERENCE : actualiza
    ANALYSIS_RUN ||--o{ RELATION : actualiza

    FILE {
        string id
        string path
        string checksum
        string kind
        string status
    }
    DOCUMENT {
        string id
        string file_id
        string parser_id
    }
    CHUNK {
        string id
        string document_id
        int start_line
        int end_line
        string content_hash
    }
    SYMBOL {
        string id
        string file_id
        string name
        string kind
    }
    SYMBOL_REFERENCE {
        string id
        string source_symbol_id
        string normalized_target
        string resolution_status
    }
    RELATION {
        string source_symbol_id
        string target_symbol_id
        string target_key
        string kind
        string evidence_chunk_id
        float confidence
    }
    ANALYSIS_RUN {
        string id
        datetime started_at
        string status
    }
```

Este modelo puede evolucionar mediante migraciones pequeñas. Las tablas permanentes de reverse engineering usan nombres sin prefijo de hito: `analysis_runs`, `symbols`, `symbol_references`, `relations`, `relation_candidates` y `generated_artifacts`. `target_key` permite registrar una referencia aunque el destino aún no se haya resuelto.

### 5.5 Vector store local

sqlite-vec guarda en SQLite:

- ID estable del chunk;
- vector de embedding;
- metadata mínima para filtros: dominio, tipo, ruta y símbolo principal;
- hash del contenido y versión del modelo de embedding.

SQLite es la fuente de verdad de procedencia, estado y vectores. El índice vectorial es reconstruible desde `chunks` y los manifiestos de embeddings. Si cambia el modelo de embedding, se crea o reconstruye el manifiesto; no se mezclan dimensiones ni modelos silenciosamente.

Durante el MVP se usa SQLite + sqlite-vec. Qdrant queda como alternativa futura si aparecen límites reales de volumen, filtros, bloqueo o concurrencia.

### 5.6 RAG

El RAG básico tendrá cuatro pasos explícitos:

1. **retrieve:** similitud vectorial y filtros;
2. **assemble:** deduplicación, orden y límite de contexto;
3. **generate:** prompt con la pregunta y fragmentos numerados;
4. **ground:** comprobación de que las citas correspondan a los fragmentos entregados.

Formato recomendado de respuesta:

```markdown
## Conclusión
...

## Evidencia
- [F1] `ruta/archivo.sql`, objeto `...`, líneas 10–42

## Supuestos y límites
- ...
```

No se implementarán planificación multiagente, memoria conversacional compleja ni cadenas autónomas. Si una pregunta necesita varios pasos, el usuario los ejecutará como comandos explícitos.

### 5.7 Reverse engineering

La capa de análisis combina:

- símbolos y relaciones deterministas o heurísticas guardadas en SQLite;
- fragmentos recuperados por RAG;
- plantillas específicas para descripción e impacto;
- LLM para sintetizar, nunca para ocultar la procedencia.

Las relaciones se recorren con consultas SQL y profundidad limitada. Esto cubre los primeros casos sin introducir una base de grafos. Los documentos deben separar:

- **detectado:** respaldado directamente por código o metadata;
- **inferido:** conclusión razonable del modelo;
- **por confirmar:** falta evidencia o requiere validación funcional.

### 5.8 Generación de Markdown y Spec Mode

Los renderers reciben datos estructurados y producen archivos Markdown mediante plantillas versionadas. La generación debe ser determinista en estructura aunque el contenido sintetizado provenga del LLM.

Tipos iniciales:

- inventario técnico;
- ficha de componente;
- análisis de impacto;
- spec con `requirements.md`, `design.md`, `tasks.md` y `test-plan.md`.

Antes de escribir se valida la ruta de salida. Un archivo existente no se reemplaza sin una opción o confirmación explícita. Los artefactos incluyen fecha, versión de plantilla, fuentes y advertencias; no necesitan metadata propietaria.

Spec Mode coordina evidencia documental H3, impacto técnico H4, síntesis conservadora, Review de `SpecDraft`, render Markdown, `SpecValidator` y escritura segura. La CLI solo orquesta argumentos y presentación; no recalcula RAG/H4 ni reemplaza revisión humana.

### 5.9 Gestión y evaluación de modelos locales

H1.1 agrega una capacidad lateral al monolito y no modifica ingesta, retrieval, embeddings, conocimiento persistido, reverse engineering ni Spec Mode.

- Ollama es la fuente de verdad del catálogo de modelos instalados.
- `[llm].model` en la configuración efectiva es la única fuente de verdad del modelo generativo activo; `[embeddings].model` permanece independiente.
- Los servicios de aplicación listan, inspeccionan, instalan, validan y seleccionan modelos mediante un cliente pequeño de la API local de Ollama.
- La selección valida previamente el modelo y edita de forma atómica solo `[llm].model`; instalar, validar o ejecutar un benchmark no cambia la selección.
- El benchmark reutiliza el constructor de contexto, el prompt y el validador RAG existentes sobre un dataset sintético congelado. Ejecuta los modelos secuencialmente, aplica scoring determinista y produce JSON y Markdown locales.
- Los reportes del benchmark no se guardan en SQLite y una recomendación nunca selecciona automáticamente un modelo; la adopción requiere `models select` explícito y revisión humana.

## 6. Estructura de referencia

La siguiente estructura es un objetivo incremental. **No es necesario crear todas las carpetas hasta que el hito correspondiente las use.**

```text
Barbarion/
├── README.md
├── LICENSE
├── .gitattributes
├── .gitignore
├── pyproject.toml                 # H1
├── barbarion.example.toml        # H1
├── docs/
│   ├── README.md
│   ├── VISION.md
│   ├── ROADMAP.md
│   ├── ARCHITECTURE.md
│   ├── DECISIONS.md
│   └── references/                # Propuestas históricas
├── src/
│   └── barbarion/
│       ├── __init__.py
│       ├── cli.py                # Adaptador CLI
│       ├── config.py             # Configuración validada
│       ├── application/          # Casos de uso, sin detalles de CLI
│       │   ├── ingest.py
│       │   ├── local_models.py
│       │   ├── model_benchmark.py
│       │   ├── query.py
│       │   ├── analyze.py
│       │   └── specs.py
│       ├── domain/               # Modelos y reglas pequeñas
│       │   ├── models.py
│       │   └── ports.py
│       └── infrastructure/       # Adaptadores locales
│           ├── parsers/
│           │   ├── plsql.py
│           │   ├── powerbuilder.py
│           │   └── text.py
│           ├── sqlite.py
│           ├── ollama.py
│           ├── ollama_models.py
│           ├── model_config.py
│           └── markdown.py
├── templates/                    # Plantillas Markdown versionadas
├── tests/
│   ├── fixtures/                 # Corpus sintético/anonimizado
│   ├── unit/
│   └── integration/
├── specs/
│   ├── H1-Foundation/
│   ├── H1.1-LocalModelManagement/
│   ├── H2-Ingestion/
│   ├── H3-RAG/
│   ├── H4-ReverseEngineering/
│   └── H5-SpecMode/
├── data/                         # Local, ignorado por Git
│   ├── sqlite/
│   └── cache/
└── output/                       # Documentos generados; política por definir
```

La división `application/domain/infrastructure` debe mantenerse ligera. Si un archivo simple basta, no se crea una jerarquía adicional. Los archivos `__init__.py` se añaden solo cuando el paquete correspondiente exista.

## 7. Límites y dependencias

### Dependencias permitidas con intención clara

- una biblioteca CLI madura;
- validación de configuración;
- cliente de Ollama;
- acceso estándar o liviano a SQLite;
- sqlite-vec para búsqueda vectorial local;
- motor de plantillas Markdown;
- framework de pruebas y herramientas de calidad.

Se evitará adoptar un framework RAG grande al inicio. Las cuatro operaciones del RAG son suficientemente pequeñas para implementarlas de forma explícita, facilitar diagnóstico y limitar dependencias.

### Fronteras de seguridad

- solo se procesan rutas configuradas y autorizadas;
- se excluyen por defecto secretos, binarios, carpetas de build y control de versiones;
- logs y documentos no deben volcar prompts completos si contienen información sensible, salvo modo de diagnóstico explícito;
- no se ejecuta código fuente ingerido;
- no se conecta a Oracle productivo;
- las llamadas de modelo apuntan a endpoints locales permitidos.

## 8. Observabilidad y manejo de errores

Para un MVP local basta con:

- logs estructurados legibles con nivel configurable;
- ID de corrida de ingesta;
- conteos de procesados, omitidos, actualizados y fallidos;
- tiempos por etapa y latencia de consulta;
- comando `doctor` para rutas, SQLite, sqlite-vec y Ollama;
- mensajes de error con archivo y acción recomendada.

No se requiere una plataforma de métricas, trazas distribuidas ni telemetría remota.

## 9. Estrategia de pruebas

- **Unitarias:** chunking, checksums, parsers, filtros, renderers y validadores de citas.
- **Integración:** SQLite, sqlite-vec y Ollama sustituible por un fake estable.
- **Golden files:** Markdown esperado para entradas controladas.
- **Evaluación RAG:** conjunto versionado de preguntas, fuentes esperadas y métrica top-k.
- **Smoke test:** recorrido CLI mínimo sobre un corpus pequeño.
- **Validación humana:** tres casos del dominio configurado para utilidad y falsos positivos.

Las pruebas no deben depender siempre de descargar o ejecutar un modelo grande. La integración real con Ollama se prueba de forma separada y explícita.

## 10. Evolución futura sin implementarla ahora

Una extensión de VS Code puede añadirse después como un adaptador que invoque la CLI o una API local estable:

```mermaid
flowchart LR
    CLI["CLI actual"] --> UC["Casos de uso"]
    VSC["Extensión VS Code futura"] -.-> API["API local futura"]
    API -.-> UC
    UC --> CORE["Dominio + adaptadores locales"]
```

FastAPI solo se justificará cuando una interfaz futura necesite comunicación persistente o múltiples clientes. La lógica de negocio permanecerá fuera de la API, por lo que añadirla no exigirá reescribir el núcleo.

Otras evoluciones posibles —un segundo dominio, más formatos, Qdrant como alternativa vectorial o un grafo— requieren evidencia de necesidad, una spec propia y métricas que justifiquen el costo.

## 11. Criterios de calidad arquitectónica

La arquitectura se considera adecuada para el MVP si:

- el flujo completo puede ejecutarse desde CLI en una máquina local;
- cada fragmento y relación puede rastrearse a su fuente;
- el índice sqlite-vec puede reconstruirse desde chunks y manifiestos en SQLite;
- un fallo de parser o archivo no invalida toda la ingesta;
- modelos y rutas cambian por configuración;
- los módulos centrales pueden probarse sin ejecutar un LLM real;
- la generación no sobrescribe trabajo humano por defecto;
- agregar una interfaz futura no exige mover la lógica de aplicación;
- el repositorio sigue siendo comprensible para una persona sin operar infraestructura adicional.
