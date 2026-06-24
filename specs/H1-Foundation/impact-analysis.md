# H1 — Foundation: Análisis de impacto

## 1. Resumen

H1 crea las convenciones operativas que heredarán los hitos siguientes: arranque, configuración, filesystem, logging, SQLite, diagnóstico, packaging y pruebas. No entrega análisis legacy, pero una base defectuosa multiplicaría retrabajo y ocultaría fallos posteriores.

## 2. Componentes afectados

| Componente | Impacto de H1 |
|---|---|
| Repositorio | Packaging Python, configuración de ejemplo y pruebas |
| CLI | Entry point, árbol de comandos y códigos de salida |
| Configuración | Precedencia, validación y rutas efectivas |
| Filesystem | Creación segura de `data/`, `output/` y `logs/` |
| SQLite | Conexión, health check y migración versión `1` |
| Operación | Logging y diagnóstico reproducible |
| Documentación | Instrucciones reales de instalación y verificación |

No se procesa ningún corpus legacy.

## 3. Dependencias futuras

### H2 — Ingestion

Depende de packaging, CLI, configuración, `data_dir`, SQLite versionado, logging, códigos de salida y pruebas. H2 añade sus tablas mediante migración `2`; no modifica la migración `1`.

### H3 — RAG

Depende del diagnóstico de Ollama, configuración, CLI, logging y errores estables. H1 solo comprueba disponibilidad: no fija modelos, prompts, embeddings ni cliente definitivo.

### H4 — Reverse Engineering

Depende de CLI/configuración, SQLite evolucionable, errores reproducibles y pruebas aisladas. H1 no define símbolos, relaciones ni algoritmos.

### H5 — Spec Mode

Depende de `output_dir`, CLI, configuración, logging y pruebas de escritura segura. H1 no crea templates ni genera Markdown.

## 4. Contratos a mantener

- ejecutable `barbarion` y opción global `--config`;
- precedencia de configuración;
- códigos `0`, `1`, `2` y `130`;
- rutas configurables y sin valores personales codificados;
- tabla `schema_migrations` y versiones crecientes;
- `doctor` seguro y repetible;
- comandos informativos sin efectos secundarios;
- importar módulos sin tocar filesystem, logging, SQLite o red.

La representación interna puede cambiar si conserva estos comportamientos.

## 5. Riesgos

| Riesgo | Consecuencia futura | Mitigación H1 |
|---|---|---|
| Configuración ambigua | Escrituras en ubicaciones inesperadas | Precedencia y rutas explícitas |
| Side effects al importar | Archivos accidentales y tests frágiles | Inicialización solo desde `doctor` |
| Migraciones no transaccionales | Metadata corrupta en H2 | Transacción e idempotencia |
| Códigos inconsistentes | Automatización no detecta fallos | Contrato probado |
| Logging global/duplicado | Salida ruidosa | Logger nombrado y handlers gestionados |
| Dependencia dura de Ollama | Desarrollo bloqueado | Check opcional y doble de prueba |
| Rutas codificadas | Falta de portabilidad o exposición | TOML, `pathlib` y `tmp_path` |
| Abstracciones anticipadas | Alto costo de cambio | Módulos directos y cero interfaces genéricas |
| Reparación destructiva | Pérdida de datos locales | Nunca recrear SQLite ante error |

## 6. Decisiones que no corresponden a H1

- modelos o librería de embeddings;
- diseño de Qdrant;
- chunking, parsers o esquema de ingesta;
- framework RAG o agentes;
- templates y formatos generados;
- API HTTP o VS Code;
- multiusuario, autenticación, permisos o plugins;
- múltiples dominios productivos;
- contenedores, microservicios o Kubernetes;
- DDD completo, Clean Architecture estricta o repositorios genéricos.

Si una tarea necesita alguna de estas decisiones, excede H1 y debe simplificarse.

## 7. Compatibilidad futura

No existe aplicación previa que migrar. H1 establece el primer contrato. Los hitos futuros deben:

- añadir claves con defaults compatibles cuando sea posible;
- añadir comandos sin alterar los existentes;
- evolucionar SQLite con migraciones nuevas;
- mantener dependencias opcionales como `WARN` hasta ejecutar una capacidad que las requiera;
- documentar rupturas deliberadas en `docs/DECISIONS.md`.

## 8. Evaluación

El impacto técnico de H1 es alto porque define fundamentos, pero su alcance funcional es deliberadamente bajo. La aceptación valora previsibilidad y capacidad de prueba, no cantidad de módulos o patrones.
