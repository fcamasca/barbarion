# H1.1 - Gestion y Evaluacion de Modelos Locales: Plan de pruebas

## 1. Objetivo

Verificar que H1.1 descubre, instala, selecciona, valida y compara LLM locales
administrados por Ollama de manera segura y reproducible, usando datos sinteticos
y sin modificar el pipeline RAG, embeddings, conocimiento H2/H4/H4.1 ni Spec
Mode.

## 2. Alcance

Incluye:

- cliente API Ollama con fakes;
- catalogo y detalle de modelos;
- instalacion explicita con progreso/interrupcion;
- seleccion atomica en `[llm].model`;
- sonda funcional sintetica;
- dataset y loader estrictos;
- contexto congelado y reutilizacion de prompt/validador RAG;
- runner secuencial, una ejecucion por caso/modelo y rotacion;
- scoring determinista y telemetria opcional;
- reportes JSON/Markdown;
- CLI, errores, privacidad y regresion H1-H5/H4.1;
- validacion manual opcional con Ollama real.

Excluye:

- cloud, proveedores externos o LLM juez;
- embeddings y benchmark de retrieval H3;
- entrenamiento, conversion o eliminacion de modelos;
- corpus real o datos de dominio;
- pruebas obligatorias de descarga real en la suite;
- benchmarks universales de hardware o modelos.

## 3. Estrategia

- unit tests para dominio, cliente, editor TOML, dataset, runner y scoring;
- integration tests CLI con servidor/cliente Ollama fake y filesystem temporal;
- pruebas de caracterizacion para prompt y validador RAG vigentes;
- golden files para Markdown y JSON normalizado;
- casos parametrizados para invariantes de scores y orden;
- pruebas negativas para respuestas Ollama variables y archivos inseguros;
- regresion completa, smoke instalado y scan de privacidad;
- prueba real manual separada, nunca requisito de la suite normal.

Prioridad de ejecucion:

- **P0 - Must:** caminos exitosos, privacidad, rollback TOML, sonda, contexto
  identico, validador, scoring, reporte y regresion critica. Deben cerrar con la
  tarea que implementa cada capacidad.
- **P1 - Defensiva:** variaciones de payload, metadata desconocida, colisiones y
  fallas poco frecuentes. Se implementan despues del P0 de la misma tarea y no
  justifican ampliar el diseno productivo.

La cantidad de casos de prueba no es una meta. Se prefieren pruebas
parametrizadas por riesgo e invariantes sobre duplicar escenarios equivalentes.

## 4. Ambientes

- Windows local como ambiente principal;
- Python `>=3.12,<3.13`;
- filesystem y configuracion temporales;
- SQLite/sqlite-vec vigentes solo para regresion, no para persistir benchmark;
- suite normal sin internet, Ollama ni modelo real;
- Ollama real opcional ya instalado para validacion manual;
- `pytest --basetemp .pytest-tmp/h11` recomendado.

## 5. Fixtures y datos

### Fake Ollama minimo

Debe poder simular:

- lista vacia, uno y varios modelos;
- campos completos, opcionales y desconocidos;
- modelo activo presente/ausente;
- show exitoso y 404;
- pull completo, ya instalado, progreso, error y corte;
- generacion valida, marcador ausente, vacia, timeout y HTTP invalido;
- telemetria completa, parcial y ausente;
- respuestas deterministas distintas por modelo/caso.

### Dataset sintetico minimo

Al menos 8 casos con fuentes como:

```text
synthetic/
  component-a.txt
  component-b.txt
  guide.md
  constraints.txt
```

Los contenidos describen componentes abstractos, atributos inventados,
alternativas, limites y referencias F1..Fn. No contienen nombres de negocio,
sistemas reales, rutas personales, secretos ni fragmentos de corpus.

## 6. Pruebas unitarias

### H1.1-TP-001 - Listado normalizado

Ordena por nombre exacto, marca activo y conserva `null` para metadata ausente.

### H1.1-TP-002 - Listado tolerante y errores

Campos desconocidos se ignoran; payload invalido, timeout y Ollama ausente
producen errores tipados sin traceback.

### H1.1-TP-003 - Detalle de modelo

Normaliza metadata segura, limita campos extensos y diferencia modelo ausente de
servidor no disponible.

### H1.1-TP-004 - Instalacion y progreso

Un pull completo reporta progreso monotono cuando es calculable y confirma el
modelo mediante list final. Ya instalado no descarga de nuevo. `--dry-run`
reporta ambos estados posibles sin invocar pull ni modificar configuracion.

### H1.1-TP-005 - Instalacion fallida/interrumpida

Error, timeout, stream truncado y Ctrl+C no cambian config; se informa que
Ollama puede continuar el pull tras cerrar el cliente.

### H1.1-TP-006 - Edicion TOML exacta

Cambia solo `[llm].model`, conserva comentarios, secciones homonimas, newline y
demas bytes, y el resultado pasa `load_settings`.

### H1.1-TP-007 - Edicion TOML rechazada

Defaults, seccion ausente, duplicado, multilinea no soportada, encoding invalido,
archivo no escribible, symlink fuera de alcance y cambio concurrente dejan el
original intacto.

### H1.1-TP-008 - Dry-run y atomicidad

Dry-run no escribe ni genera; falla antes/durante validacion del temporal o
reemplazo conserva original y limpia solo su temporal.

### H1.1-TP-009 - Sonda valida

Modelo indicado/activo instalado devuelve checks separados, marcador y duracion
sin exponer el texto completo.

### H1.1-TP-010 - Sonda negativa

Ausente, vacio, marcador faltante, timeout y respuesta invalida quedan
diferenciados. La sonda nunca contiene corpus ni entrada del usuario.

### H1.1-TP-011 - Dataset valido

Carga 8 o mas casos, categorias requeridas, IDs/citas consistentes, orden
canonico y hash estable independiente de formato JSON superficial.

### H1.1-TP-012 - Dataset invalido y privacidad

Rechaza version, claves, reglas o pesos desconocidos; duplicados; rubrica vacia;
cita inexistente; mas de 100 casos; texto/ruta prohibidos segun scan acordado.

### H1.1-TP-013 - Matriz y contexto identico

Cada combinacion modelo/caso se ejecuta una vez y conserva igual hash
de pregunta, contexto y prompt entre modelos.

### H1.1-TP-014 - Preparacion, rotacion y secuencia

La sonda previa no entra en metricas; la formula de rotacion produce orden
esperado, hay una generacion por caso/modelo y no existen llamadas solapadas.

### H1.1-TP-015 - Fallas y cancelacion

Una unidad fallida no borra confirmadas; timeout continua segun politica; Ctrl+C
marca corrida `interrupted`, escribe un parcial no reanudable y devuelve 130.

### H1.1-TP-016 - Calidad e instrucciones

Casos controlados acreditan cobertura total/parcial, prohibiciones, secciones,
idioma/formato verificable y renormalizacion cuando una metrica no aplica.

### H1.1-TP-017 - Groundedness, contexto y citas

Respuestas soportadas, contradichas, con cita incorrecta, cita inexistente,
cobertura parcial y rechazo por evidencia insuficiente producen scores exactos.

### H1.1-TP-018 - Telemetria y agregacion

Wall-clock siempre existe; tokens/duraciones Ollama se normalizan o quedan null.
Media, mediana, coverage y score ponderado cumplen ejemplos calculados; el
validador aporta el peso predominante.

### H1.1-TP-019 - Reporte comparativo

JSON contiene trazabilidad completa y Markdown contiene todas las secciones,
metricas, fallas, formulas y limitaciones con orden canonico.

### H1.1-TP-020 - Recomendacion y escritura

Aplica elegibilidad/tie-break exactos, no recomienda corrida incompleta, crea un
directorio unico y aborta una colision sin sobrescribir ni salir del alcance.

### H1.1-TP-021 - CLI y codigos

Help en espanol; argumentos invalidos 2; errores operativos 1; exito 0;
interrupcion 130; JSON mantiene codigos tecnicos.

### H1.1-TP-022 - Logs y privacidad

Logs y Markdown no contienen prompt completo, contexto, respuesta, variables,
rutas personales ni contenido fuera del dataset sintetico.

### H1.1-TP-023 - Compatibilidad RAG

Pruebas de caracterizacion verifican que `ask`, constructor de contexto, prompt,
reparacion y validacion de citas no cambian antes/despues de H1.1.

### H1.1-TP-024 - Extensibilidad generica

Nombres/tag desconocidos y metadata nueva funcionan sin registrar clases,
familias, allowlists o configuracion por modelo.

## 7. Pruebas de integracion

### INT-H1.1-01 - List/show con fake

CLI carga config temporal, consulta fake y marca exactamente el activo.

### INT-H1.1-02 - Ollama ausente

Todos los comandos de red fallan de forma accionable; `config show` y comandos
H1-H5 no relacionados siguen operativos.

### INT-H1.1-03 - Install completo

Fake emite progreso, confirma presencia y no modifica `[llm].model`.

### INT-H1.1-04 - Select completo

Modelo instalado pasa sonda, TOML se reemplaza y una nueva composicion de
`OllamaLlmProvider` usa el nuevo nombre.

### INT-H1.1-05 - Select rollback

Falla de sonda, config invalida, permisos o reemplazo deja el modelo anterior.

### INT-H1.1-06 - Validate activo/explicito

Sin argumento usa activo; con argumento no cambia activo. Text y JSON coinciden.

### INT-H1.1-07 - Benchmark de dos modelos

Dos fakes y el dataset completo producen dos unidades por caso, mismos hashes, orden
rotado, validacion y agregados esperados.

### INT-H1.1-08 - Benchmark con falla parcial

Una unidad falla y las demas terminan; reporte queda incompleto, sin candidato y
exit code 1.

### INT-H1.1-09 - Benchmark interrumpido

Interrupcion conserva artefacto parcial simple, estado y unidades confirmadas,
sin prometer reanudacion.

### INT-H1.1-10 - Dataset externo sintetico

Ruta valida dentro del alcance carga; dataset invalido o con mas limites falla
antes de invocar modelos.

### INT-H1.1-11 - Sin persistencia de conocimiento

Hash/conteos de tablas H2/H3/H4/H4.1 permanecen iguales tras validate y benchmark.

### INT-H1.1-12 - Sin red externa

La suite intercepta conexiones y demuestra que solo se intentaria
`settings.ollama_url`; install fake no accede a registry real.

## 8. Pruebas CLI

- `barbarion models --help`;
- `barbarion models list --format text|json`;
- `barbarion models show synthetic-model:tag --format text|json`;
- `barbarion models install synthetic-model:tag --dry-run` con fake;
- `barbarion models install synthetic-model:tag` con fake;
- `barbarion models validate`;
- `barbarion models validate synthetic-model:tag --format json`;
- `barbarion models select synthetic-model:tag --dry-run`;
- `barbarion models select synthetic-model:tag` sobre config temporal;
- `barbarion models benchmark --models model-a:tag model-b:tag`;
- dataset, timeout, output y modelo invalidos;
- config por defaults/no editable;
- Ollama ausente, modelo ausente y Ctrl+C.

## 9. Golden files

Golden files minimos:

- `model-benchmark-complete.md`;
- `model-benchmark-incomplete.md`;
- `model-benchmark-no-candidate.md`;
- `model-benchmark.json` normalizado;
- `models-list.json`;
- `model-validation.json`.

Reglas:

- clock y duraciones fake;
- run IDs, dataset hash y orden deterministas;
- modelos completamente sinteticos;
- sin rutas absolutas, prompts ni respuestas completas;
- newline y encoding estables;
- campos opcionales ausentes representados como null/no disponible.

## 10. Casos negativos

| Caso | Esperado |
|---|---|
| Ollama no disponible | error operativo accionable, sin traceback |
| lista con campo nuevo | se ignora/conserva de forma acotada |
| modelo no instalado | no valida, selecciona ni benchmarkea |
| un solo modelo en benchmark | argumentos invalidos; comparar requiere dos |
| pull ya satisfecho | exito idempotente, sin cambio de activo |
| install `--dry-run` | informa accion prevista, sin pull ni escritura |
| pull truncado | error y verificacion final negativa |
| nombre vacio/control chars | argumentos invalidos, sin request |
| URL como nombre de modelo | rechazo, no cambia destino HTTP |
| config solo defaults | select explica crear/indicar TOML |
| `[llm]` duplicado/no simple | select aborta sin reserializar |
| cambio concurrente del TOML | aborta y conserva version externa |
| marcador de sonda ausente | `generation_ready=false`; no acredita benchmark |
| dataset con cita inexistente | codigo 2 antes de generar |
| caso sin rubrica | dataset invalido |
| respuesta con cita inventada | cita/validador penalizados |
| respuesta elocuente no grounded | groundedness y calidad penalizados |
| telemetria sin tokens | null, no cero |
| una unidad timeout | resultado parcial/incompleto visible |
| todos bajo elegibilidad | sin candidato recomendado |
| colision de `run-id` | aborta sin sobrescribir |
| Ctrl+C | 130 y parcial `interrupted` |

## 11. Pruebas de regresion

La aceptacion final ejecuta:

- H1 configuracion, doctor, bootstrap y CLI;
- H2 ingesta e incrementalidad;
- H3 index, search, ask, citas y benchmark de retrieval;
- H4 analyze, inventory, describe e impact;
- H4.1 Data-Driven y retrieval estructurado;
- H5 spec create/validate;
- smoke test instalado.

Adicionalmente:

- configs sin claves nuevas cargan igual;
- `OllamaLlmProvider.generate()` conserva contrato y mensajes;
- seleccionar en un TOML temporal cambia solo futuras generaciones;
- benchmark no toca base, indice, corpus ni outputs previos.

## 12. Pruebas de rendimiento

Con fakes se mide overhead del runner/rendering. Con Ollama real opcional se
registran, sin umbral universal:

1. sonda previa por modelo, fuera de metricas;
2. una ejecucion completa;
3. generacion individual de validacion;
4. escritura de reporte.

Metricas:

- wall-clock por unidad/modelo/corrida;
- promedio y mediana;
- duraciones Ollama cuando existan;
- prompt/output tokens cuando existan;
- throughput derivable solo si counts y duration estan presentes;
- overhead de scoring/rendering;
- cobertura de telemetria.

No se fija un SLA sin baseline del hardware objetivo. No se ejecutan modelos en
paralelo.

## 13. Evaluacion de calidad

Para cada modelo/categoria:

- casos completados y fallidos;
- hechos esperados cubiertos;
- afirmaciones prohibidas detectadas;
- instrucciones cumplidas;
- groundedness acotado a rubrica;
- hechos con uso correcto de contexto;
- citas presentes, validas y suficientes;
- aceptacion/rechazo y diagnostics;
- latencia y tokens con coverage;
- ejemplos fallidos seleccionados sin exponer razonamiento interno.

La revision humana debe considerar que el scoring lexical puede producir falsos
positivos/negativos. Cualquier ajuste a reglas cambia `schema_version` o
`scoring_version` y requiere nuevos golden files.

## 14. Validacion manual con Ollama real

Opcional cuando existan modelos y hardware disponibles:

1. registrar versiones y carga local;
2. ejecutar `models list` y `validate`;
3. comparar al menos dos modelos instalados con la ejecucion unica de v1;
4. revisar cinco resultados: mejor, peor, rechazo, insuficiencia y cita multiple;
5. confirmar que el candidato y los compromisos son razonables;
6. registrar que una ejecucion no mide variabilidad;
7. no ejecutar `select` sobre configuracion real sin decision humana separada.

Si no se dispone de dos modelos, se registra pendiente; no se fabrican resultados
ni se bloquea la verificacion automatica del comportamiento.

## 15. Matriz requisito-prueba

| Requisito | Pruebas principales |
|---|---|
| H1.1-RF-001 | TP-001, TP-002, INT-01, INT-02 |
| H1.1-RF-002 | TP-003, INT-01 |
| H1.1-RF-003 | TP-004, TP-005, INT-03 |
| H1.1-RF-004 | TP-006..008, INT-04, INT-05 |
| H1.1-RF-005 | TP-009, TP-010, INT-06 |
| H1.1-RF-006 | TP-011, TP-012, INT-10 |
| H1.1-RF-007 | TP-013..015, INT-07..09 |
| H1.1-RF-008 | TP-016..018, INT-07 |
| H1.1-RF-009 | TP-019, TP-020, INT-07..09 |
| H1.1-RF-010 | TP-021, TP-022, INT-01..12 |
| H1.1-RNF-001 | TP-010, TP-012, TP-022, INT-12 |
| H1.1-RNF-002 | TP-006, TP-023, regresion |
| H1.1-RNF-003 | TP-023, INT-11, regresion |
| H1.1-RNF-004 | TP-011, TP-013, TP-018 |
| H1.1-RNF-005 | TP-007, TP-008, TP-020 |
| H1.1-RNF-006 | TP-024 |
| H1.1-RNF-007 | TP-014, TP-015, rendimiento |
| H1.1-RNF-008 | TP-018..020, golden |
| H1.1-RNF-009 | TP-006..008, smoke Windows |
| H1.1-RNF-010 | TP-023, revision de dependencias/imports |
| H1.1-RNF-011 | fake suite, INT-01..12 |
| H1.1-RNF-012 | TP-016..020 |

## 16. Evidencia esperada para aceptacion

- comandos y codigos ejecutados;
- suite completa y duracion;
- smoke instalado y regresion H1-H5/H4.1;
- config y fake Ollama sinteticos;
- dataset/version/hash y scan de privacidad;
- resultados list/show/install/validate/select temporal;
- reporte completo e incompleto;
- hashes identicos de contexto por modelo;
- formulas y resultados de scoring comprobados;
- coverage de telemetria/tokens;
- confirmacion de no cambio a SQLite, indice o pipelines;
- ausencia de conexiones cloud;
- validacion real si fue posible, o pendiente explicita;
- revision humana y decision final.

## 17. Criterios para declarar H1.1 listo para aceptacion

- todos los requisitos Must tienen pruebas pasando;
- modelos se descubren sin catalogo duplicado;
- install es la unica operacion con descarga implicita de Ollama;
- select valida y actualiza solo TOML de forma atomica;
- configs existentes y comandos H1-H5/H4.1 no cambian;
- dataset tiene al menos 8 casos sinteticos validos;
- todos los modelos reciben contexto y prompt equivalentes por caso;
- validador RAG vigente procesa cada salida;
- scores, fallas, latencia y tokens disponibles son trazables;
- corrida incompleta nunca produce candidato;
- reporte no selecciona automaticamente;
- suite normal no necesita red, Ollama ni modelo real;
- no hay datos reales, secretos, rutas personales, prompts/contextos productivos
  ni llamadas cloud;
- aceptacion se documenta solo durante H1.1-T12.
