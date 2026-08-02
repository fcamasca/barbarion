# Barbarion -- Evolution

## Propósito

Este documento describe la evolución conceptual de Barbarion. No define
la implementación de un hito específico, sino cómo madura la capacidad
de análisis del producto a lo largo del tiempo.

La filosofía es simple:

> **H2 almacena conocimiento. H3 lo recupera. H4 lo conecta. Las
> siguientes evoluciones razonan sobre él.**

------------------------------------------------------------------------

# Principio fundamental

El objetivo no es depender de un LLM cada vez más grande.

El objetivo es entregar al LLM un contexto cada vez más inteligente.

Mientras mejor sea el conocimiento estructurado que Barbarion construye,
menos dependerá la calidad de la respuesta del modelo utilizado. El MVP usa
modelos locales mediante Ollama; cualquier soporte futuro para otros proveedores
o entornos requerirá una decisión de alcance y una spec propia.

------------------------------------------------------------------------

# Evolución del conocimiento

## H1 -- Foundation

Pregunta que responde:

**¿Dónde vivirá el conocimiento?**

Capacidades:

-   CLI
-   Configuración
-   SQLite
-   Infraestructura
-   Pruebas
-   Base del proyecto

Resultado:

Barbarion puede ejecutarse.

------------------------------------------------------------------------

## H2 -- Memoria

Pregunta que responde:

**¿Qué existe?**

Construye:

-   archivos
-   documentos
-   chunks
-   metadata
-   inventario

Resultado:

Barbarion conoce el contenido del sistema.

No interpreta relaciones.

------------------------------------------------------------------------

## H3 -- Comprensión semántica

Pregunta que responde:

**¿Dónde está la información relevante?**

Construye:

-   embeddings
-   búsqueda vectorial
-   recuperación híbrida
-   contexto para LLM

Resultado:

Barbarion encuentra la información adecuada para responder preguntas.

Todavía no entiende la arquitectura.

------------------------------------------------------------------------

## H4 -- Ingeniería inversa

Pregunta que responde:

**¿Cómo interactúan los componentes?**

Construye:

- símbolos
- referencias
- relaciones
- dependencias
- impacto
- descripciones técnicas

Alcance actual:

La primera versión de H4 reconstruye relaciones a partir del código fuente
y de sus artefactos estructurales (packages, procedures, funciones,
tablas, vistas, secuencias, etc.).

La reconstrucción de aplicaciones data-driven, donde parte importante de
la lógica reside en configuraciones persistidas, fue incorporada por H4.1
como una evolución compatible de la ingeniería inversa.

Resultado:

Barbarion entiende la estructura del sistema implementada en código y la
utiliza para análisis técnico e impacto.

------------------------------------------------------------------------

# Evoluciones implementadas

------------------------------------------------------------------------

## H1.1 -- Gestión y Evaluación de Modelos Locales

Estado: completada y aceptada técnicamente, con comparación real entre modelos
pendiente por condiciones del entorno de aceptación.

Pregunta que responde:

**¿Qué modelo local disponible se adecúa mejor al contrato RAG de Barbarion?**

Construye:

- descubrimiento y administración de modelos compatibles con Ollama;
- selección explícita del modelo generativo activo;
- validación separada de disponibilidad, instalación y capacidad de generación;
- benchmark reproducible sobre contexto sintético congelado;
- scoring determinista, agregación y reporte comparativo;
- recomendación informativa sujeta a elegibilidad y revisión humana.

H1.1 reutiliza el constructor de mensajes y el validador RAG existentes. No
modifica retrieval, chunking, embeddings, conocimiento persistido, ingeniería
inversa ni Spec Mode. La evaluación permanece completamente local y no convierte
la recomendación en una selección automática.

Resultado:

Barbarion puede comprobar la preparación técnica de un modelo y comparar varios
modelos locales bajo las mismas condiciones. La calidad funcional solo queda
demostrada por una corrida elegible del benchmark; `models validate` demuestra
únicamente `generation_ready`.

Evidencia:

[`../specs/H1.1-LocalModelManagement/acceptance.md`](../specs/H1.1-LocalModelManagement/acceptance.md).

------------------------------------------------------------------------

## H4.1 -- Configuraciones Data-Driven

Estado: completada y aceptada técnicamente.

Pregunta que responde:

**¿Dónde vive realmente la lógica del negocio cuando no está escrita directamente en el código?**

Construye:

- entidades de configuración
- reglas configuradas
- expresiones y fórmulas
- relaciones entre configuraciones
- dependencias hacia componentes de ejecución
- grafo conceptual de relaciones de configuración persistido en SQLite

Detecta de forma genérica aplicaciones cuyo comportamiento está definido por configuración persistida, por ejemplo:

- plantillas
- reglas
- parámetros
- workflows
- mappings
- metadata de negocio
- SQL dinámico
- expresiones ejecutables

Relaciona dichas configuraciones con:

- procedimientos
- funciones
- packages
- tablas
- vistas
- otros componentes técnicos

Resultado:

Barbarion incorpora al modelo relacional de conocimiento en SQLite la lógica
definida en configuraciones, permitiendo comprender arquitecturas data-driven
sin introducir una base de grafos ni depender de implementaciones específicas
del dominio.

------------------------------------------------------------------------

# Evolución futura

------------------------------------------------------------------------

## H4.2 -- Patrones técnicos

Detectar:

-   capas
-   módulos
-   componentes reutilizados
-   código duplicado
-   hotspots
-   dependencias críticas

------------------------------------------------------------------------

## H4.3 -- Flujos

Reconstruir procesos completos.

Ejemplo:

PowerBuilder

↓

Evento

↓

Package Oracle

↓

Procedure

↓

Tablas

↓

Comprobante

↓

Correo

------------------------------------------------------------------------

## H4.4 -- Contexto funcional

Agrupar componentes por dominio.

Ejemplo:

-   Facturación
-   Clientes
-   Cobranza
-   Suscripciones
-   Reportes

------------------------------------------------------------------------

## H4.5 -- Reasoning Package

Construir un paquete estructurado para cualquier LLM.

Debe incluir:

-   componentes
-   relaciones
-   dependencias
-   impacto
-   evidencia
-   ambigüedades
-   riesgos
-   contexto funcional

------------------------------------------------------------------------

## H4.6 -- Multi LLM

Esta evolución no forma parte de la implementación actual. Requiere una decisión
de alcance y una spec propia que definan despliegue, privacidad y compatibilidad
con el principio on-premise antes de incorporar proveedores distintos de Ollama.

El mismo Reasoning Package puede enviarse a:

-   Llama
-   Claude
-   GPT
-   Bedrock

La diferencia entre respuestas dependerá principalmente del modelo, no
del conocimiento disponible.

------------------------------------------------------------------------

# Filosofía final

Cada nueva versión de Barbarion debe mejorar su capacidad de comprender
el sistema sin modificar la base construida en H2 y H3.

La inteligencia evoluciona sobre conocimiento estructurado, no
reemplazando dicho conocimiento.
