# Barbarion -- Knowledge Pipeline

## Propósito

Este documento describe cómo Barbarion transforma código fuente en
conocimiento útil para un LLM.

La calidad de la respuesta depende principalmente de la calidad del
pipeline de conocimiento.

------------------------------------------------------------------------

# Pipeline

``` text
Código fuente
        │
        ▼
H2 Ingesta
        │
        ▼
Metadata
        │
        ▼
Chunks
        │
        ▼
Embeddings
        │
        ▼
Búsqueda RAG
        │
        ▼
H4 Símbolos
        │
        ▼
Referencias
        │
        ▼
Relaciones
        │
        ▼
Dependencias
        │
        ▼
Patrones
        │
        ▼
Flujos
        │
        ▼
Contexto funcional
        │
        ▼
Reasoning Package
        │
        ▼
LLM
        │
        ▼
Respuesta con evidencia
```

------------------------------------------------------------------------

# Descripción de cada etapa

## Código fuente

Entrada del sistema.

-   Oracle
-   PowerBuilder
-   Documentación

------------------------------------------------------------------------

## Ingesta (H2)

Organiza el conocimiento.

Produce:

-   archivos
-   documentos
-   chunks
-   metadata

------------------------------------------------------------------------

## Embeddings (H3)

Representación semántica del contenido para búsqueda eficiente.

------------------------------------------------------------------------

## Recuperación RAG (H3)

Selecciona únicamente el contexto relevante para una consulta.

------------------------------------------------------------------------

## Ingeniería inversa (H4)

Construye conocimiento estructural:

-   símbolos
-   referencias
-   relaciones
-   dependencias

------------------------------------------------------------------------

## Patrones

Identifica estructuras repetidas y componentes relacionados.

------------------------------------------------------------------------

## Flujos

Reconstruye procesos técnicos completos atravesando Oracle y
PowerBuilder.

------------------------------------------------------------------------

## Contexto funcional

Agrupa componentes según el proceso de negocio al que pertenecen.

------------------------------------------------------------------------

## Reasoning Package

Es el producto final del análisis.

Debe contener únicamente información estructurada y verificable:

-   evidencia
-   relaciones
-   impacto
-   riesgos
-   ambigüedades
-   limitaciones

------------------------------------------------------------------------

## LLM

El modelo ya no necesita descubrir el sistema.

Su responsabilidad es:

-   sintetizar
-   explicar
-   responder

------------------------------------------------------------------------

# Principio de diseño

Mientras mejor sea el Reasoning Package, menor será la diferencia entre
utilizar un modelo local pequeño o un modelo comercial grande.
