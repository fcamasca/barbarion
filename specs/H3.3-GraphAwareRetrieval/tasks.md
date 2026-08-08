# H3.3 — Tareas

## T01 — Congelar inventario de contratos

**Objetivo:** documentar nombres reales, tipos de relación presentes, asociaciones símbolo/chunk y si existe package→miembro navegable. **Archivos:** `src/barbarion/domain/*`, repositorios SQLite, specs H3/H3.1/H4/H4.1. **Cambios:** matriz de compatibilidad, catálogo inicial de tipos, direcciones y casos soportables. **Pruebas:** consultas SQLite sobre fixtures H4/H4.1. **Fin:** no quedan supuestos sin evidencia y el caso package queda clasificado como soportado o diferido.

## T02 — Definir contrato de expansión

**Objetivo:** añadir modelos/funciones pequeñas para seed, expansión y origen de candidato. **Archivos probables:** `domain/rag.py`, `application/rag.py`. **Cambios:** contratos inmutables, orden estable y límites validados. **Pruebas:** validación de límites, empate y serialización de debug. **Fin:** contrato no depende de proveedor ni persiste contenido.

## T03 — Adaptar consulta H4/H4.1

**Objetivo:** consultar relaciones activas y símbolos sin duplicar repositorio. **Archivos:** `infrastructure/sqlite.py`, `application/reverse_engineering.py` si hace falta. **Cambios:** reutilizar `active_relations_for_symbol`, filtros explícitos y dirección por tipo. **Pruebas:** resolved/unresolved/ambiguous/dynamic/external y dominio. **Fin:** solo relaciones permitidas alcanzan expansión.

## T04 — Implementar expansión acotada

**Objetivo:** BFS con límites validados, ciclos y dedupe. **Archivos:** `application/rag.py` o módulo interno existente. **Cambios:** recorrido determinista, penalización de profundidad y trazabilidad; no fijar números hasta la baseline. **Pruebas:** ciclos, múltiples seeds, duplicados, límites y seed sin relaciones. **Fin:** resultados reproducibles y acotados.

## T05 — Resolver chunks y fusionar

**Objetivo:** convertir símbolos alcanzados en `RetrievalCandidate` citable. **Archivos:** `application/rag.py`, `domain/rag.py`. **Cambios:** enriquecer con `SQLiteRagRepository`, fusionar una sola vez y conservar H3.1. **Pruebas:** package, proceso transversal, código+configuración y regresión puntual. **Fin:** `ContextBuilder` recibe el conjunto final, sin segundo RAG.

## T06 — Configuración, debug y privacidad

**Objetivo:** hacer la función opt-in/configurable y observable. **Archivos:** `config.py`, `barbarion.example.toml`, `cli.py`, docs. **Cambios:** defaults seguros, métricas efímeras y hash/conteos persistidos. **Pruebas:** configuración inválida, `--debug`, no persistencia sensible, `--no-llm`. **Fin:** compatibilidad hacia atrás verificada.

## T07 — Validación multi-proveedor y benchmark

**Objetivo:** medir mejora, seleccionar límites y evitar regresión. **Archivos:** fixtures/publicables, `tests/unit`, `tests/integration`, specs. **Cambios:** casos del test-plan y matriz Ollama/Anthropic con fakes HTTP. **Pruebas:** citas, insuficiente, presupuesto H3.1, proveedores y retrieval actual; comparar varias configuraciones de profundidad, seeds, vecinos y candidatos. **Fin:** valores justificados por cobertura/ruido/latencia/presupuesto y resultados comparables frente a baseline.

## T08 — Aceptación técnica/funcional

**Objetivo:** ejecutar la suite, revisar observabilidad/privacidad y crear `acceptance.md` solo después de implementación real. **Archivos:** `specs/H3.3-GraphAwareRetrieval/acceptance.md`, reportes locales. **Pruebas:** todos los criterios y regresión completa. **Fin:** evidencia reproducible, decisiones de promoción/default documentadas.
