# H3.1 - Optimizacion de contexto RAG: Plan de pruebas

## 1. Objetivo

Demostrar que H3.1 mide y reduce contexto innecesario sin degradar retrieval,
cobertura de evidencia, trazabilidad, citas ni calidad funcional, y sin mezclar
estimaciones locales con uso real de proveedores.

## 2. Principio de validacion

Reducir caracteres o tokens no constituye exito aislado. Una configuracion
optimizada es elegible solo si pasa las puertas de calidad derivadas de la
baseline aprobada. Las pruebas se ejecutan primero con la politica vigente,
despues con la propuesta, sobre el mismo dataset, configuracion y fakes.

## 3. Alcance

Incluye:

- caracterizacion del pipeline vigente;
- composicion y reconciliacion del prompt;
- retrieval semantic/keyword/hybrid y evidencia estructurada;
- top-k, candidate-k, ranking/fusion y seleccion final;
- dedupe exacto y overlap; redundancia lexical solo como diagnostico Should;
- presupuesto por chunk, contexto e input completo;
- prompt inicial y reparacion;
- citas, insuficiencia y no-LLM;
- observabilidad, privacidad y compatibilidad;
- benchmark baseline/optimized y regresion completa.

Excluye:

- calidad universal de LLM;
- benchmark con datos privados;
- llamadas cloud obligatorias;
- evaluador LLM externo;
- pruebas de nuevos proveedores o redisenos H2.

## 4. Ambientes

- Python `>=3.12,<3.13`;
- Windows principal y contratos portables Linux;
- SQLite temporal y sqlite-vec cuando corresponda;
- suite normal offline con egress bloqueado;
- embeddings y LLM fake deterministas;
- Ollama/Anthropic reales solo opt-in durante aceptacion autorizada;
- `pytest --basetemp .pytest-tmp/h31` recomendado.

## 5. Datos publicables

### Corpus sintetico propuesto

```text
tests/fixtures/h31_context_corpus/
  oracle/
    pkg_components.pks
    pkg_components.pkb
    fn_status.fnc
  powerbuilder/
    w_components.srw
    d_components.srd
  docs/
    component-guide.md
    operations.md
  configuration/
    component_rules.sql
```

El dominio usa nombres neutrales como `component_alpha`, `unit_beta` y
`status_code`; no replica nombres, formulas, consultas ni reglas de negocio.
Los archivos incluyen deliberadamente:

- chunks contiguos con overlap conocido;
- contenido exactamente duplicado;
- similitud lexical sin equivalencia factual;
- hechos distribuidos entre dos fuentes;
- evidencia contradictoria etiquetada;
- pregunta sin respuesta;
- configuracion estructurada y codigo relacionado;
- texto Unicode y codigo con alta densidad de simbolos.

Cada fixture incluye declaracion de origen `synthetic-for-barbarion` y canarios
que permiten comprobar que datos externos no fueron copiados.

## 6. Baseline y comparacion

Cada run congela:

- commit/version Barbarion;
- dataset y checksum;
- politica de seleccion y estimador;
- configuracion retrieval/RAG;
- fake/modelo y proveedor cuando aplique;
- metricas por caso y agregadas.

El comparador produce JSON y Markdown con `baseline`, `candidate`, delta absoluto,
delta relativo y resultado de cada puerta. Un valor ausente permanece `null`.

## 7. Pruebas unitarias

### H3.1-TP-001 - Caracterizacion de fusion hibrida

Verificar candidatos por canal, normalizacion, pesos, dedupe por `chunk_id`,
threshold, desempate y corte `top_k`. Confirmar que no se etiqueta como
cross-encoder.

### H3.1-TP-002 - Merge estructurado vigente

Congelar precedencia H4.1, exclusion del chunk de configuracion equivalente,
dedupe por ID y limite. Servira para detectar cambios de T07.

### H3.1-TP-003 - Composicion reconciliable

Para ASCII, espanol, Unicode y codigo:

- concatenar componentes reproduce exactamente el prompt;
- suma de caracteres y bytes coincide con el render;
- suma local por componente usa el mismo estimador/version;
- componentes vacios y separadores quedan contabilizados una sola vez.

### H3.1-TP-004 - Taxonomia de uso

Probar estimacion sin proveedor, uso real completo, parcial, invalido y ausente.
No sumar contadores incompletos; `null` no se vuelve cero. Separar generation y
repair y comprobar el total del run solo cuando procede.

### H3.1-TP-005 - Duplicados exactos

Cubrir mismo ID, hash completo, prefijo configurado, colision de prefijo
controlada y mismo contenido con ID distinto. Cada omision tiene razon estable.

### H3.1-TP-006 - Overlap report-only

Cubrir rangos contiguos con texto comun, rangos sin contenido comun, mismo texto
en documentos distintos, codigo boilerplate y fuentes contradictorias. Reportar
sin cambiar seleccion baseline.

### H3.1-TP-007 - Trim conservador

Si se implementa T08, comprobar que solo se recorta interseccion demostrable,
no se pierden hechos esperados, rango original/enviado es trazable y contenido
final coincide con la cita.

### H3.1-TP-008 - Presupuesto completo

Casos:

- overhead menor, igual y mayor al presupuesto;
- pregunta e instrucciones largas;
- headers variables y muchas fuentes;
- fuente que cabe completa, truncada o no cabe;
- estimacion final nunca supera el limite;
- presupuesto insuficiente retorna estado seguro.

### H3.1-TP-009 - Seleccion relevance-first

Una fuente de score alto no puede ser desplazada solo por `document_id`; empates
son deterministas; duplicados y overlap demostrado reciben la penalizacion
definida; una fuente unica no se elimina por similitud aproximada.

### H3.1-TP-010 - IDs y citas

Despues de omitir/truncar/reordenar, IDs son F1..Fn, el prompt lista solo esos
IDs y `CitationValidator` rechaza cualquier ID ausente. Rangos corresponden al
contenido enviado.

### H3.1-TP-011 - Reparacion presupuestada

El prompt de reparacion se mide por separado, incluye la respuesta rechazada y
respeta la politica definida. Si no puede construirse de forma segura, no se
envia una solicitud fuera de presupuesto.

### H3.1-TP-012 - Debug seguro

Sin `--debug` no aparece contenido. Con debug, el contenido es efimero y los
resumenes incluyen componentes, decisiones y razones. Logs nunca incluyen
pregunta, prompt, respuesta, key o contenido.

## 8. Pruebas de integracion

### H3.1-INT-001 - Ask completo por modo

Ingestar/indexar corpus sintetico y ejecutar `ask --no-llm` en keyword, semantic
e hybrid. Validar candidatos, seleccion, contexto y metricas sin LLM.

### H3.1-INT-002 - Ollama fake

Comprobar prompt exacto, contadores opcionales, respuesta citada y reparacion.
La composicion no contiene campos especificos de Anthropic.

### H3.1-INT-003 - Anthropic HTTP fake

Comprobar que el payload contiene exactamente el prompt compuesto y que usage
real se muestra separado de estimacion. No usar `count_tokens` ni red externa.

### H3.1-INT-004 - Evidencia insuficiente

Sin fuentes o sin presupuesto suficiente no se invoca LLM, no se lee
`ANTHROPIC_API_KEY` y se conservan metricas estructurales.

### H3.1-INT-005 - H4.1 estructurado

Mezclar evidencia de configuracion sintetica y chunks relacionados; validar
ranking/seleccion global, trazabilidad de simbolos/relaciones y citas.

### H3.1-INT-006 - H4/H5 consumidores

Ejecutar describe/impact/spec create sobre fakes existentes y confirmar que la
evolucion de ContextBuilder no rompe sus contratos.

### H3.1-INT-007 - Persistencia segura

Inspeccionar `connection.iterdump()`, logs y reportes locales con canarios de
pregunta, fuente, prompt, respuesta y key. Solo hashes/conteos/versiones pueden
persistir.

### H3.1-INT-008 - Configuracion compatible

Cargar TOML 0.6.0, nueva configuracion, combinaciones ambiguas y limites.
`config show` refleja valores efectivos sin secreto.

### H3.1-INT-009 - Formatos y Unicode

Text/JSON/Markdown y pipes/redirecciones mantienen UTF-8; campos nuevos son
aditivos y no alteran contenido de respuesta/citas.

## 9. Benchmark

### 9.1 Retrieval

- recall@5;
- recall@10;
- MRR;
- expected-document recall;
- candidatos por canal y fusionados.

### 9.2 Seleccion/contexto

- expected-source recall despues de presupuesto;
- fact coverage del contexto;
- fuentes seleccionadas y omitidas;
- exact duplicate ratio;
- overlap chars/ratio;
- redundancia lexical aproximada solo si se implementa la metrica Should
  `report-only`;
- contenido/header caracteres, bytes y estimacion;
- truncamientos y razones;
- evidencia seleccionada no citada.

### 9.3 Citas/calidad

- citation precision/recall;
- IDs invalidos;
- accepted/insufficient/error;
- repair attempted/success;
- claims esperados/prohibidos mediante rubrica determinista.

### 9.4 Eficiencia

- input chars/bytes/tokens estimados por componente;
- uso real y error relativo cuando existe;
- latencias por etapa;
- delta baseline/optimized.

## 10. Puertas de aceptacion

Los numeros definitivos se fijan despues de H3.1-T03. Deben incluir como minimo:

1. no bajar del criterio H3 de 8/10 con fuente relevante en top-5;
2. no reducir recall@5, recall@10 ni MRR fuera de tolerancia aprobada;
3. expected-source recall y fact coverage Must no inferiores a baseline;
4. cero citas a fuentes no enviadas;
5. todos los casos de respuesta insuficiente conservan comportamiento seguro;
6. ninguna regresion de Ollama, Anthropic, no-LLM, H4.1, H4 o H5;
7. privacidad y determinismo pasan;
8. reduccion de input demostrada en los casos con redundancia, sin exigir un
   porcentaje universal para todos los casos;
9. si una politica reduce tamano pero falla calidad, queda desactivada/rechazada.

## 11. Pruebas no funcionales

### Privacidad

- scanner de patrones prohibidos, rutas personales, secrets y canarios;
- revision de licencia/procedencia si se incorpora una fuente publica;
- reportes versionados generados solo desde corpus H3.1.

### Determinismo

Dos runs consecutivos producen decisiones y metricas estructurales iguales,
ignorando timestamps y latencias.

### Rendimiento

Medir complejidad con `candidate_k` maximo admitido. La deteccion de pares opera
solo sobre candidatos de la consulta y cumple un umbral definido en T03.

### Portabilidad

Rutas, encoding y comandos cubiertos en Windows; pruebas sin supuestos de
separador para Linux.

## 12. Regresion

- suite completa H1-H5, H4.1, H1.1 y H1.2;
- tests unitarios de rag, config, providers, model benchmark y spec mode;
- integraciones de CLI RAG, Anthropic fake y seguridad offline;
- golden files afectados solo con cambios aditivos aprobados;
- smoke del entrypoint instalado en T12.

## 13. Aceptacion final

H3.1-T12 crea `acceptance.md` unicamente despues de registrar:

- commit/version y ambiente;
- comandos y resultados de suite/smoke;
- baseline y candidato;
- puertas y deltas;
- privacidad;
- uso real solo si fue autorizado y ejecutado;
- riesgos/diferimientos;
- decision ACCEPTED/REJECTED/condicionada.

Hasta entonces, la ausencia de `acceptance.md` es intencional.

## 14. Matriz de trazabilidad

| Requisito | Pruebas principales |
|---|---|
| REQ-001 | TP-001/002, INT-001, benchmark baseline |
| REQ-002 | TP-003, INT-002/003 |
| REQ-003 | TP-003/004, INT-002/003 |
| REQ-004 | TP-012, INT-007 |
| REQ-005 | TP-005/006/007 |
| REQ-006 | TP-005-010, INT-005 |
| REQ-007 | TP-008, INT-008 |
| REQ-008 | TP-007/009, benchmark seleccion |
| REQ-009 | TP-001/002/009, INT-001 |
| REQ-010 | TP-010/011, INT-004 |
| REQ-011 | corpus/dataset y scanner de privacidad |
| REQ-012 | benchmark secciones 9.1-9.4 |
| REQ-013 | puertas seccion 10 y regresion |
| REQ-014 | INT-001-009 |
| REQ-015 | revision documental y acta T12 |
