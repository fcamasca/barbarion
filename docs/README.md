# Documentación de Barbarion

Esta carpeta reúne la definición pública del producto, su plan de ejecución y las decisiones que guían el MVP.

## Orden de lectura recomendado

1. [VISION.md](VISION.md) — problema, propósito, alcance y definición de éxito.
2. [ROADMAP.md](ROADMAP.md) — hitos, esfuerzo, entregables, riesgos y criterios de aceptación.
3. [ARCHITECTURE.md](ARCHITECTURE.md) — componentes, flujos, estructura del repositorio y límites técnicos.
4. [DECISIONS.md](DECISIONS.md) — registro liviano de decisiones vigentes e históricas.
5. [INGESTION.md](INGESTION.md) — operación local de ingesta H2.
6. [RAG.md](RAG.md) — operación local RAG H3.
7. [`../specs/`](../specs/) — especificaciones por hito conforme sean elaboradas y aprobadas.

## Alcance público

Barbarion está enfocado en sistemas legacy Oracle/PLSQL + PowerBuilder. El MVP se valida con un único dominio legacy real y un corpus autorizado, sin publicar ni incorporar ese caso al diseño del producto.

La documentación pública no debe contener nombres de sistemas internos, objetos privados, rutas personales, datos organizacionales ni ejemplos sin sanitizar.

## Fuentes de verdad

- `VISION.md` define el porqué y los límites del producto.
- `ROADMAP.md` define el orden y los criterios para ejecutar el MVP.
- `ARCHITECTURE.md` define las decisiones técnicas actuales.
- `DECISIONS.md` registra por qué se eligieron y cómo se reemplazan.
- Cada carpeta de `specs/` define el trabajo aprobado para un hito.

Si dos documentos entran en conflicto, debe corregirse la inconsistencia antes de implementar. Una decisión que cambie alcance, arquitectura o planificación requiere actualizar el documento maestro correspondiente.

## Referencias

La carpeta [`references/`](references/) admite únicamente material complementario apto para publicación. No es una fuente de verdad del producto.
