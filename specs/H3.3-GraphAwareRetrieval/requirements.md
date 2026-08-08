# H3.3 — Graph-Aware Retrieval: Requisitos

## 1. Problema y objetivo

H3 recupera chunks por búsqueda híbrida y H3.1 selecciona el contexto bajo presupuesto. Una pregunta que cruza varios componentes puede encontrar solo una parte de la evidencia. H4/H4.1 ya persisten símbolos, referencias y relaciones en SQLite, pero ese conocimiento no se usa como expansión general del retrieval.

H3.3 debe ampliar de forma conservadora los candidatos de H3 a partir de seeds recuperadas, resolver la expansión a chunks existentes y dejar la selección final, presupuesto, prompt y validación de citas en el pipeline RAG vigente.

La pregunta de diseño es: **¿qué evidencia relacionada falta para responder una consulta que abarca múltiples componentes?**

## 2. Alcance funcional

- Ejecutar siempre el retrieval híbrido H3 como descubrimiento inicial.
- Identificar seeds únicamente entre candidatos con símbolo o metadata estructural trazable; no usar un LLM para navegar.
- Consultar relaciones activas reales de H4/H4.1 mediante el repositorio existente.
- Expandir solo relaciones resueltas con destino `target_symbol_id`; las relaciones ambiguas, dinámicas, externas o no resueltas se registran como descartadas/no expandibles, no como evidencia fuente nueva.
- Considerar inicialmente relaciones de llamadas/dependencias entre componentes y relaciones de configuración-código ya producidas por H4.1. El `relation_type` permitido debe ser una configuración explícita, no un comodín.
- Admitir profundidad limitada, máximo de seeds y máximo de vecinos/candidatos, ciclos y duplicados controlados.
- Resolver cada símbolo alcanzado al chunk vigente asociado y enriquecerlo con el repositorio RAG existente. Si no existe chunk vigente del símbolo, se podrá usar `evidence_chunk_id` de la relación únicamente cuando ese chunk exista, esté vigente y su contenido documente realmente el vínculo utilizado; de lo contrario no se genera evidencia citable.
- Fusionar candidatos directos y estructurales por `chunk_id`, conservando el origen y el camino de expansión.
- Entregar la colección fusionada al selector H3.1 (`baseline_v1` u `optimized_v1`) y al `ContextBuilder` existente.
- Mantener citas únicamente sobre fuentes/chunks entregados al prompt; una relación puede explicar el origen de un candidato, pero no es una cita `[F#]` salvo que el contrato futuro lo defina expresamente.

## 3. Requisitos funcionales

| ID | Requisito |
|---|---|
| H33-RF-001 | Una consulta ejecuta el retrieval H3 vigente antes de expandir. |
| H33-RF-002 | Cada seed debe poder vincularse determinísticamente a un símbolo activo o a una asociación estructural ya persistida. |
| H33-RF-003 | La expansión usa solo relaciones `active`, dentro de los tipos configurados, y respeta dominio/filtros RAG. |
| H33-RF-004 | La primera versión usa profundidad máxima 1 por defecto; la configuración puede acotarla, nunca eliminar el límite. |
| H33-RF-005 | El límite de seeds, vecinos por seed y candidatos estructurales es obligatorio y produce orden estable. |
| H33-RF-006 | Se impide reexpandir símbolos visitados y se deduplican chunks antes del ensamblado. |
| H33-RF-007 | Un candidato conserva `retrieval_mode`, seed, relación(es), profundidad y razón de inclusión en metadata efímera de debug. |
| H33-RF-008 | La resolución primaria es el chunk vigente del símbolo. El fallback a `evidence_chunk_id` solo es válido si el chunk existe, está vigente y contiene evidencia del vínculo; en cualquier otro caso no genera evidencia citable y se contabiliza como no resoluble a fuente. |
| H33-RF-009 | La fusión no desplaza silenciosamente el contrato H3.1: `top_k`, dedupe, overlap y presupuesto siguen aplicándose una sola vez. |
| H33-RF-010 | Si no hay relaciones útiles, el resultado equivale al retrieval H3 actual, sujeto a los mismos límites. |
| H33-RF-011 | Si la evidencia sigue siendo insuficiente, `ask` conserva `insufficient_evidence` y no fuerza una respuesta. |
| H33-RF-012 | `--no-llm` ejecuta y expone retrieval/expansión/contexto sin llamadas generativas. |

## 4. No funcionales y compatibilidad

- Determinismo: orden por score/rango de familia y luego IDs estables; no depender de generación.
- Rendimiento: no recorrer el grafo completo ni ejecutar una consulta SQL por candidato sin límites.
- Privacidad: no persistir pregunta, prompt, respuesta ni contenido adicional; solo hash/conteos/métricas seguras ya permitidas por H3.
- Proveedores: el conjunto lógico de evidencia es idéntico para Ollama y Anthropic.
- SQLite sigue siendo fuente persistente; no se introduce base de grafos ni tabla paralela de conocimiento.
- Una consulta simple que ya funciona no debe degradarse; la activación debe poder quedar deshabilitada o sin efecto cuando no haya seed estructural.
- Los límites y tipos permitidos deben ser configurables sin modificar el contrato del proveedor LLM.

## 5. Observabilidad y trazabilidad

En `--debug` se reportan seeds, relaciones inspeccionadas/aceptadas/descartadas, profundidad, ciclos, candidatos por origen, deduplicados, límites alcanzados, tiempos y motivo de evidencia insuficiente. SQLite conserva únicamente métricas agregadas/hash según el contrato actual de `rag_queries`.

Cada candidato estructural debe poder reconstruir: `chunk_id` → símbolo → relación → seed. La respuesta solo cita el `source_id` asignado por el `ContextBuilder` a un chunk seleccionado.

## 6. Casos de uso

1. Package: seed del package o componente y recuperación de procedimientos/functions relacionados, únicamente si T01 confirma que el modelo H4 vigente persiste relaciones package→miembro o una relación equivalente navegable. Si no existe esa relación, el caso se limita a la evidencia que H3 pueda recuperar directamente y se documenta como capacidad diferida, no como fallo de H3.3.
2. Proceso transversal: recorrido limitado de llamadas y objetos leídos/modificados.
3. Código + configuración: relación H4.1 desde símbolo de código a configuración y retorno al chunk fuente.
4. Pregunta puntual: sin expansión útil; comportamiento H3 intacto.

## 7. Fuera de alcance

No incluye cambio de chunking, AST nuevo, clasificación LLM de preguntas, navegación autónoma, reranker nuevo, memoria, base de grafos, H4.2–H4.5, expansión ilimitada, inferencia sobre relaciones ambiguas/dinámicas, ni citas de relaciones derivadas.

## 8. Criterio de evidencia insuficiente

El resultado es insuficiente si, tras H3.3 y la selección H3.1, no queda al menos la evidencia mínima definida por el contrato actual para generar una respuesta grounded. Debe indicarse la limitación y las fuentes disponibles; nunca rellenar con conocimiento no recuperado.
