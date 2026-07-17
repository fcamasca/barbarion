# H4.1 - Configuraciones Data-Driven: Analisis de impacto

## 1. Resumen

H4.1 impacta principalmente configuracion, ingesta, parsing, reverse
engineering, persistencia, CLI, renderers y pruebas. El cambio debe ser
compatible hacia atras: con `data_driven.enabled=false`, Barbarion debe
comportarse como MVP `0.5.0`.

No se modifica codigo productivo durante la elaboracion de esta especificacion.

## 2. Documentos revisados

Orden solicitado:

1. `docs/VISION.md`
2. `docs/ARCHITECTURE.md`
3. `docs/DECISIONS.md`
4. `README.md`
5. `docs/ROADMAP.md`
6. `specs/H4-ReverseEngineering/`
7. `specs/H5-SpecMode/`
8. codigo y pruebas relacionados con ingesta, parsing, chunks, simbolos,
   referencias, relaciones, incrementalidad, inventario, descripcion,
   dependencias, impacto, persistencia y migraciones
9. `docs/EVOLUTION.md`

Hallazgos:

- los documentos maestros estan bajo `docs/`, salvo `README.md` raiz;
- `docs/EVOLUTION.md` ya identifica H4.1 como evolucion futura para
  configuraciones Data-Driven;
- H4 y H5 estan completados y aceptados/validados tecnicamente;
- el MVP `0.5.0` esta congelado;
- DECISIONS tiene precedencia ante menciones historicas a Qdrant;
- SQLite + sqlite-vec es el vector store vigente;
- H4 usa tablas permanentes sin prefijo de hito.

## 3. Decisiones previas condicionantes

| Decision | Impacto en H4.1 |
|---|---|
| D-001 Local/on-premise | No conexion a bases ni servicios cloud |
| D-003 CLI-first | Extender comandos existentes, sin UI |
| D-004 Python monolito modular | Mantener capas existentes |
| D-005 SQLite | Persistir en SQLite, no grafo externo |
| D-010 Parsers heuristicos | Parser DML acotado, no SQL universal |
| D-013 Espanol para usuario | Mensajes, docs y errores en espanol |
| D-014 SQLite + sqlite-vec | H3 integra por chunks/metadata existentes |
| D-015 Tablas H4 permanentes | No usar nombres `h41_*` |

## 4. Impacto por area

### Configuracion

Impacto:

- agregar `DataDrivenSettings`;
- validar nueva seccion `[data_driven]`;
- actualizar `barbarion.example.toml`;
- mantener rechazo de claves desconocidas.

Riesgo:

- romper configuraciones existentes si la nueva seccion no es opcional.

Mitigacion:

- default `enabled=false`;
- pruebas de regresion `test_config.py`.

### Ingesta H2

Impacto:

- clasificacion opcional de archivos `.sql` declarados como `configuration`;
- metadata adicional en documentos/chunks;
- no cambiar fingerprint ni chunking base salvo incluir firma Data-Driven en
  procesamiento cuando corresponda.

Riesgo:

- archivos `.sql` de codigo Oracle podrian clasificarse erroneamente.

Mitigacion:

- exigir conjuntamente `data_driven.enabled`, `file_patterns` y tabla declarada;
- no inferir por contenido general.

### Parsers

Impacto:

- nuevo parser/splitter DML acotado o helpers bajo `infrastructure/parsers`;
- no modificar OracleParser para convertir cualquier DML en configuracion;
- posible reutilizacion de masking de comentarios/literales.

Riesgo:

- crecer hacia parser SQL universal.

Mitigacion:

- limitar a `INSERT` y `UPDATE` definidos;
- pruebas negativas de variantes no soportadas.

### Dominio H4

Impacto:

- nuevos modelos puros para declaracion, registro, valor, token y diagnostico;
- ampliar compatibilidad de tipos de simbolo y referencia;
- tecnologia `configuration`.

Riesgo:

- mezclar semantica funcional no demostrada con hallazgos tecnicos.

Mitigacion:

- clasificacion `detectado`, `inferido`, `por_confirmar`;
- declaracion TOML minima obligatoria.

### Persistencia SQLite

Impacto:

- reutilizar tablas H4 existentes;
- metadata JSON mas rica;
- sin migracion nueva para registros Data-Driven.

Riesgo:

- consultas por JSON pueden ser suficientes al inicio pero incomodas despues.

Mitigacion:

- reutilizar `symbols`, `symbol_references`, `relations`,
  `relation_candidates` y `metadata_json`;
- detener la implementacion y actualizar el diseno si el modelo H4 existente no
  satisface un requisito obligatorio.

### Analyze H4

Impacto:

- integrar paso Data-Driven;
- calcular firma de declaracion y hashes;
- re-resolver referencias afectadas;
- reportar metricas.

Riesgo:

- duplicar pipelines de analisis.

Mitigacion:

- extender `AnalyzeService`;
- no crear comando nuevo.

### Inventory/Describe/Impact

Impacto:

- filtros y renderers para `configuration`;
- secciones de columnas, formulas, tokens, estado y vigencia;
- impacto cruzado configuration/oracle/powerbuilder.

Riesgo:

- salidas demasiado verbosas.

Mitigacion:

- mostrar valores declarados y resumen; valores extensos truncados con aviso.

### H3 RAG

Impacto:

- chunks DML indexables;
- filtros por `artifact_kind=configuration`;
- no cambiar ranking.

Riesgo:

- DML extenso puede ocupar presupuesto de contexto.

Mitigacion:

- chunking existente y limites de contexto H3.

### H5 Spec Mode

Impacto:

- componentes Data-Driven aparecen como afectados via H4;
- specs pueden citar configuraciones.

Riesgo:

- H5 podria sobreinterpretar reglas tecnicas como funcionales.

Mitigacion:

- evidencia obligatoria y `por_confirmar` cuando falte validacion funcional.

### CLI y documentacion

Impacto:

- help y mensajes para Data-Driven;
- docs operativas y README al cerrar implementacion.

Riesgo:

- confundir H4.1 con aceptacion del MVP.

Mitigacion:

- documentar como evolucion posterior.

## 5. Impacto sobre pruebas existentes

Pruebas que no deben cambiar de comportamiento:

- `tests/unit/test_config.py` con configs actuales;
- `tests/unit/test_parser_registry.py`;
- `tests/unit/test_oracle_parser.py`;
- `tests/unit/test_powerbuilder_parser.py`;
- `tests/unit/test_ingestion_service.py`;
- `tests/integration/test_ingest_incremental_cli.py`;
- `tests/unit/test_h4_symbols.py`;
- `tests/unit/test_h4_reference_extractors.py`;
- `tests/unit/test_h4_resolution.py`;
- `tests/integration/test_h4_analyze_cli.py`;
- `tests/unit/test_h4_describe_impact.py`;
- `tests/integration/test_h5_spec_create_cli.py`;
- smoke tests.

Pruebas nuevas esperadas:

- `test_data_driven_config.py`;
- `test_data_driven_dml_parser.py`;
- `test_data_driven_symbols.py`;
- `test_data_driven_references.py`;
- `test_data_driven_formula_tokens.py`;
- `test_data_driven_analyze_cli.py`;
- `test_data_driven_inventory_describe_impact.py`;
- `test_data_driven_h3_h5_integration.py`;
- golden files Data-Driven.

## 6. Compatibilidad hacia atras

Garantias:

- default deshabilitado;
- sin cambios obligatorios en `barbarion.toml`;
- `.sql` sigue siendo Oracle salvo declaracion explicita;
- schema v4 sigue valido si no se agrega tabla auxiliar;
- comandos existentes conservan opciones y codigos.

Compatibilidad de datos:

- simbolos H4 existentes no cambian IDs;
- relaciones existentes no se re-clasifican salvo re-resolucion normal de H4;
- chunks existentes no se modifican retroactivamente sin nueva ingesta.

## 7. Seguridad y privacidad

Impactos:

- DML puede contener parametros sensibles o reglas de negocio.

Controles:

- procesamiento local;
- no ejecutar SQL;
- no conectar a DB;
- no logs con valores completos por defecto;
- fixtures sinteticos;
- scan de datos sensibles en aceptacion;
- limites de tamano y literales.

## 8. Riesgos reales

| Riesgo | Probabilidad | Impacto | Mitigacion |
|---|---|---|---|
| Variantes DML fuera del subconjunto | Alta | Medio | warnings recuperables y backlog |
| Declaracion TOML insuficiente | Media | Alto | validacion estricta y preguntas pendientes |
| Falsos positivos por tokens de formula | Media | Medio | referencias ambiguas/por_confirmar |
| Duplicados entre archivos | Media | Medio | estado `ambiguous` y candidatos |
| Performance con DML grande | Media | Medio | limites y baseline |
| Sobreinterpretacion funcional | Media | Alto | evidencia obligatoria y revision humana |
| Necesidad posterior de tabla auxiliar | Media | Bajo | detener implementacion y actualizar diseno fuera de H4.1 |

## 9. Bloqueos

No hay bloqueos tecnicos para crear la especificacion.

Bloqueos o decisiones pendientes para implementacion:

- confirmar ejemplos reales o anonimizados de DML Data-Driven en archivos
  `.sql`;

## 10. Supuestos realizados

- La primera implementacion puede operar sin migracion nueva.
- `metadata_json` es suficiente para conservar trazabilidad de sentencia y
  registro en el MVP H4.1.
- Las configuraciones relevantes pueden declararse por tabla y columna en TOML.
- `INSERT` cubre el caso principal de exportaciones; `UPDATE` aporta valor solo
  cuando identifica el registro.
- DML describe sentencias dentro de archivos `.sql`; H4.1 no usa extension
  `.dml`.
- Duplicados entre archivos quedan `ambiguous`; H4.1 no define prioridad entre
  fuentes.
- `unresolved` se conserva como estado valido porque el codigo H4 vigente lo
  usa, aunque el prompt enfatice otros cuatro estados.

## 11. No impactado

- No se redisenan H2, H3, H4 ni H5.
- No se cambian modelos LLM ni embeddings.
- No se agrega API HTTP.
- No se agrega UI.
- No se agrega base de grafos.
- No se modifica codigo productivo durante esta tarea.
- No se modifican pruebas existentes durante esta tarea.

## 12. Trazabilidad

| Area impactada | Requisitos | Tareas | Pruebas |
|---|---|---|---|
| Configuracion | H4.1-REQ-001 | H4.1-T01 | TP-001, TP-002 |
| Ingesta | H4.1-REQ-002 | H4.1-T02 | TP-003, INT-01, INT-02 |
| Parser DML | H4.1-REQ-003..005 | H4.1-T03 | TP-004..010 |
| Simbolos | H4.1-REQ-006..007 | H4.1-T04, T05 | TP-011..014 |
| Referencias | H4.1-REQ-008..010 | H4.1-T06, T07 | TP-015..020 |
| Persistencia | H4.1-REQ-011 | H4.1-T05 | TP-021, INT-09 |
| Incrementalidad | H4.1-REQ-012 | H4.1-T08 | TP-022, TP-023, INT-03..08 |
| H4 visible | H4.1-REQ-013 | H4.1-T09 | TP-024, TP-025 |
| H3/H5 | H4.1-REQ-014 | H4.1-T10 | TP-026, INT-10 |
| CLI/observabilidad | H4.1-REQ-015..016 | H4.1-T11 | TP-027, TP-028 |
| Seguridad | H4.1-REQ-017 | H4.1-T12 | TP-029, INT-11 |
