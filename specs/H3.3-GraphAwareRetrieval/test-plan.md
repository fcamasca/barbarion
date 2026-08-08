# H3.3 — Plan de pruebas

## Fixtures publicables

Crear un corpus sintético mínimo con chunks separados: `PKG_X` (package, dos procedures y una function), `PROC_START` que llama `PKG_X.PROC_A`, `TABLE_X` leída/modificada, y `CFG_X` con relación H4.1 hacia el código. Añadir una variante con ciclo `A -> B -> A`, un símbolo sin relaciones, un destino sin chunk y dos seeds que convergen en el mismo chunk. Las relaciones deben usar los constructores reales y persistirse en SQLite, no mocks de tablas inventadas.

## Matriz

| Caso | Preparación / expectativa |
|---|---|
| Puntual | Chunk directo basta; cero expansión útil; mismas fuentes que H3. |
| Package completo | Ejecutar solo si T01 confirma una relación package→miembro o equivalente. Medir la profundidad necesaria y citar chunks de miembros; si no existe esa relación, registrar el caso como capacidad diferida y verificar que H3.3 no prometa cobertura inexistente. |
| Proceso transversal | Llamadas y tablas permitidas aportan evidencia; relaciones externas no se expanden. |
| Código + configuración | Seed código alcanza `CFG_X` mediante H4.1 y conserva fuente citable. |
| Seed sin relaciones | Resultado idéntico al retrieval H3. |
| Ciclo | BFS termina, marca ciclo y no duplica candidatos. |
| Múltiples seeds | Orden estable; convergencia deduplicada y orígenes acumulados. |
| Duplicados | Mismo `chunk_id` aparece una vez antes de H3.1. |
| Límites | Probar una matriz de profundidades, seeds, vecinos y candidatos; ningún valor se considera default hasta que T07 lo justifique. Verificar que nunca se excedan y que `limit_hit` sea visible. |
| Presupuesto H3.1 | `baseline_v1` y `optimized_v1` aplican selección/presupuesto una sola vez. |
| Insuficiente | Sin fuente suficiente devuelve estado seguro, sin invención. |
| Citas | Todos los `[F#]` apuntan a fuentes del contexto; relación sola nunca valida cita. |
| `--no-llm` | Ejecuta retrieval/contexto sin proveedor generativo. |
| Ollama | Contexto lógico y citas iguales usando fake/local provider. |
| Anthropic | Preflight y proveedor reciben solo prompt final permitido; mismo conjunto lógico. |
| Regresión H3 | keyword, semántico, híbrido, filtros y top-k conservan resultados sin seeds. |

## Criterios de medición

Comparar baseline H3/H3.1 contra H3.3 en recall de fuentes esperadas, fuentes seleccionadas, cobertura de hechos, citas válidas, estado accepted/insufficient, latencia local y límites alcanzados. Seleccionar los límites solo después de comparar la matriz experimental. Verificar que la mejora aparezca en casos multi-componente sin empeorar el caso puntual ni aumentar contenido persistido.

## Seguridad y determinismo

Ejecutar con red bloqueada salvo pruebas explícitas de adaptadores; inspeccionar `rag_queries` para confirmar hash/conteos sin pregunta, prompt, respuesta o código adicional. Repetir cada fixture varias veces y comparar IDs, orden, scores y debug estructural.
