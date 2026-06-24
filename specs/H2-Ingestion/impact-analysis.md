# H2 — Ingestion: Análisis de impacto

## 1. Resumen

H2 convierte la base operativa de H1 en el primer pipeline de datos de Barbarion, respetando la separación ligera `application/`, `domain/` e `infrastructure/` de la arquitectura maestra. Introduce lectura de corpus, dos dependencias runtime documentales, un nuevo esquema SQLite y contratos que serán consumidos directamente por H3, H4 y H5.

El impacto se mantiene acotado a un proceso CLI local. No se incorporan servidores, vector stores, modelos, plugins dinámicos ni conexiones a sistemas legacy.

## 2. Componentes afectados

| Componente | Cambio | Compatibilidad esperada |
|---|---|---|
| `pyproject.toml` | dependencias `pypdf` y `python-docx` | instalación H1 sigue válida con nuevas dependencias locales |
| `barbarion.example.toml` | sección `[ingestion]` | claves planas H1 se conservan |
| `config.py` | settings y validación H2 | precedencia y side effects de H1 no cambian |
| `cli.py` | comando `ingest` | doctor/config/version mantienen contratos |
| `database.py` | migración v2, FK y WAL | DB v1 migra; versión futura sigue fallando seguro |
| `logging_config.py` | contexto run/stage | formato y destinos H1 se mantienen |
| `application/`, `domain/`, `infrastructure/` | componentes de ingesta ubicados en las capas existentes | no se crea una estructura paralela `src/barbarion/ingestion/` |
| `tests/` | fixtures y suites H2 | no reemplaza pruebas H1 |
| `data/barbarion.db` | inventario, texto y chunks | local y excluido de Git |

## 3. Contratos de H1 que no deben romperse

- Python `>=3.12,<3.13`;
- `barbarion --help`, `--version`, `doctor` y `config show`;
- precedencia de `--config`, variable, archivo local y defaults;
- `config show` sin efectos secundarios;
- `doctor` como bootstrap vigente;
- creación idempotente de directorios y SQLite;
- mensaje seguro ante schema version futura;
- logging UTF-8 con `delay=True`;
- mensajes orientados al usuario en español;
- imports sin efectos secundarios;
- `.gitignore` para configuración, datos, logs y DB.

## 4. Dependencias futuras

### H3 — RAG

Depende de H2 para:

- enumerar chunks vigentes sin reabrir archivos;
- consultar inventario agregado —archivos, documentos, chunks y tipos— sin reescanear filesystem;
- usar `chunks.id` como identidad del vector;
- detectar altas, cambios y bajas mediante IDs y hashes;
- construir citas desde rutas, líneas, páginas y objetos;
- filtrar solo documentos cuyo SHA coincide con el archivo procesado;
- obtener metadata tecnológica sin conocer parsers.

Una mala identidad de chunk obligaría a reindexar innecesariamente o dejar vectores obsoletos. Por eso H2 versiona parser/chunker y define IDs deterministas.

H2 no debe elegir ChromaDB o Qdrant. Esa decisión corresponde a H3 y no modifica el contrato SQLite.

### H4 — Reverse Engineering

Depende de:

- nombres y tipos de objetos Oracle/PowerBuilder;
- unidades lógicas con rangos confiables;
- texto completo preservado como evidencia;
- parser/versiones para interpretar calidad de metadata;
- capacidad de reingesta cuando evolucionen heurísticas.

H2 no modela relaciones, dependencias ni call graph. H4 podrá añadir tablas propias sin alterar documentos y chunks H2.

### H5 — Spec Mode

Depende de:

- trazabilidad al corpus autorizado;
- contenido reproducible y hashes;
- citas técnicas;
- estado incremental consistente;
- distinción entre metadata exacta y heurística.

H5 no debe inferir que un objeto heurístico es exacto si H2 lo marcó incierto.

## 5. Impacto del modelo de datos

### Migración

- H1 posee schema v1 con `schema_migrations`.
- H2 agrega schema v2; no edita ni reejecuta v1.
- una DB nueva aplica v1 y v2 en orden;
- una DB v1 se actualiza transaccionalmente;
- una DB superior a la soportada falla sin escritura.

### WAL

WAL se traslada deliberadamente a H2 porque aparece el primer workload de escrituras repetidas. Implicaciones:

- la DB debe estar en filesystem local;
- aparecen archivos auxiliares `-wal` y `-shm`;
- backup/copia en caliente debe considerar esos archivos;
- una unidad de red o sincronizada puede no ofrecer locks fiables;
- si SQLite no confirma `wal`, la ingesta no empieza.

### Crecimiento

Se acepta la duplicación de almacenamiento para privilegiar simplicidad y trazabilidad. H2 almacena texto normalizado y chunks, por lo que la DB puede ser mayor que el corpus textual por duplicación parcial y overlap. Mitigaciones:

- límites por archivo y extracción;
- overlap moderado;
- no almacenar embeddings en SQLite;
- mantener consultas agregadas de inventario sobre metadata e índices, no sobre reescaneo del filesystem;
- no conservar versiones históricas de documentos/chunks;
- medir el corpus de validación antes de diseñar compresión o GC.

## 6. Impacto de dependencias

`pypdf` y `python-docx` son las únicas dependencias runtime nuevas previstas. Deben:

- ser open source y compatibles con uso on-premise;
- fijarse en rangos reproducibles;
- soportar Python 3.12;
- no realizar red;
- tratar documentos como datos no confiables;
- estar cubiertas por fixtures de regresión.

No se agrega PyYAML porque H2 ingiere YAML como texto. No se agrega detector probabilístico de encoding para conservar determinismo.

## 7. Riesgos

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---:|---:|---|
| Encodings PowerBuilder heterogéneos | Alta | Alta | fallback configurable, warning Latin-1, fixtures cp1252 |
| Heurística PL/SQL delimita mal | Media | Alta | preservar texto, validar rangos y fallback por objeto/archivo |
| Exports PB varían por versión | Alta | Media | parser tolerante, warnings y corpus variado |
| PBL se interpreta como texto | Media | Alta | clasificación binaria y skip explícito |
| PDF sin capa de texto | Alta | Media | error recuperable; OCR fuera de alcance |
| PDF/DOCX consume recursos | Media | Alta | límites de bytes, páginas y caracteres |
| Fast path omite cambio con mismo size/mtime | Baja | Media | `--full`; evaluar always-SHA futuro |
| WAL falla en filesystem sincronizado | Media | Alta | exigir filesystem local y verificar antes del run |
| Roots solapadas duplican archivos | Media | Media | paths resueltos y deduplicados |
| Reconciliación borra por discovery incompleto | Baja | Alta | solo roots completas; nunca tras interrupción |
| Fallo de parser deja dato stale | Media | Alta | vigencia por status + SHA |
| DB crece por duplicación/overlap | Media | Media | decisión aceptada para MVP, default 50 MB por archivo, límites y medición real |
| Logs filtran corpus | Baja | Alta | no loguear contenido; tests de seguridad |
| Chunks no optimizan RAG | Media | Media | versión/configuración y reingesta posterior |

## 8. Decisiones que no deben tomarse en H2

- ChromaDB frente a Qdrant;
- modelo de embeddings o LLM;
- API de plugins externos;
- parser formal de Oracle o PowerBuilder;
- descompilador PBL;
- OCR;
- FTS5 o búsqueda híbrida;
- concurrencia y workers;
- retención histórica de contenido;
- formato final de exportación del inventario;
- múltiples dominios simultáneos;
- API web o extensión VS Code;
- abstracción para otras bases de datos.

## 9. Compatibilidad y rollback

- H2 es aditivo para CLI y configuración.
- La migración SQLite no requiere downgrade automático.
- Antes de migrar una DB real debe existir backup operativo documentado.
- Si falla la migración, la transacción se revierte y H1 debe poder diagnosticar el archivo, aunque no usar funciones H2.
- Remover H2 del código no revierte schema v2; una versión antigua debe rechazar la DB como más nueva.
- Los archivos fuente nunca se modifican, por lo que rollback del corpus no aplica.

## 10. Seguridad y privacidad

- solo se leen roots autorizadas;
- symlinks no amplían el scope;
- no se ejecuta contenido;
- rutas absolutas permanecen en metadata local y no deben publicarse;
- fixtures públicos no contienen datos internos;
- archivos de configuración, DB, logs y outputs siguen ignorados por Git;
- H2 no hace llamadas de red;
- errores y logs evitan fragmentos de contenido.

## 11. Inventario exportable

H2 debe dejar suficiente metadata para obtener, sin acceso al filesystem fuente, el número de archivos vigentes, documentos vigentes, chunks vigentes y tipos de artefactos. Esto impacta positivamente a H3 y H5 porque permite reportes, auditoría y sincronización futura desde SQLite. No implica agregar un comando nuevo ni definir formatos de exportación en H2.

## 12. Evaluación

El impacto es **medio y controlado**: H2 amplía configuración, CLI y SQLite, e introduce parsing de archivos no confiables. Los principales puntos de riesgo son integridad incremental, seguridad de documentos y calidad de trazabilidad. La mitigación consiste en procesamiento secuencial, límites explícitos, transacciones por archivo, fallbacks conservadores y pruebas con fixtures sintéticos.
