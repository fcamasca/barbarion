# Barbarion

Barbarion es un agente AI on-premise para análisis, documentación e ingeniería inversa asistida de sistemas legacy **Oracle/PLSQL + PowerBuilder**.

El proyecto ayuda a desarrolladores y analistas técnicos a comprender código existente, localizar dependencias, recuperar conocimiento autorizado y producir documentación Markdown trazable sin enviar el corpus a servicios cloud.

## Estado del proyecto

Barbarion se encuentra en la fase de definición de su MVP. La implementación seguirá cinco hitos pequeños y verificables bajo un enfoque Spec-Driven Development.

> El MVP se valida inicialmente sobre un dominio legacy real, pero ese dominio no forma parte del diseño público ni limita la arquitectura de Barbarion.

El MVP trabaja con un solo sistema legacy objetivo y un corpus autorizado. Esta restricción permite validar utilidad real antes de considerar más dominios, interfaces o infraestructura.

## Capacidades previstas

- ingesta incremental de código Oracle/PLSQL, exports de PowerBuilder y documentación técnica;
- inventario local de archivos, objetos y relaciones básicas;
- RAG local con referencias verificables a las fuentes recuperadas;
- explicación de componentes y análisis de impacto asistido;
- generación de inventarios, análisis y specs en Markdown;
- operación local mediante CLI y modelos ejecutados con Ollama.

## Principios

- local y on-premise por diseño;
- evidencia antes que elocuencia;
- CLI-first;
- un monolito Python modular;
- parsers heurísticos y honestos antes que analizadores perfectos;
- entregables pequeños y verificables;
- profundidad en Oracle/PLSQL + PowerBuilder, no soporte genérico para cualquier tecnología;
- revisión humana de conclusiones y documentos generados.

## Arquitectura del MVP

El diseño inicial utiliza una aplicación Python de un solo proceso, SQLite para metadata, Qdrant en modo local para búsqueda vectorial, Ollama para embeddings e inferencia, y Markdown para los entregables.

No forman parte del MVP una extensión de VS Code, UI web, autenticación, microservicios, Kubernetes, una base de datos empresarial ni un grafo avanzado.

## Roadmap

1. `H1-Foundation`
2. `H2-Ingestion`
3. `H3-RAG`
4. `H4-ReverseEngineering`
5. `H5-SpecMode`

El plan completo contempla aproximadamente 12 semanas y 120 horas de trabajo.

## Documentación

- [Guía de documentación](docs/README.md)
- [Visión del producto](docs/VISION.md)
- [Roadmap del MVP](docs/ROADMAP.md)
- [Arquitectura](docs/ARCHITECTURE.md)
- [Decisiones técnicas](docs/DECISIONS.md)
- [Specs por hito](specs/)
- [Referencias públicas](docs/references/)

## Desarrollo

El código de aplicación se incorporará al iniciar `H1-Foundation`. Hasta entonces, el repositorio conserva únicamente la documentación y estructura necesarias para acordar el alcance.

## Licencia

Consulta [LICENSE](LICENSE).
