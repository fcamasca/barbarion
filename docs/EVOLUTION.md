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
menos dependerá la calidad de la respuesta del modelo utilizado. Ollama sigue
siendo el backend predeterminado y el proveedor de embeddings. H1.2 permite usar
Anthropic para la generación final sin trasladar la construcción local de
conocimiento ni establecer que sea el único proveedor remoto futuro.

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

## H1.2 -- Inferencia Remota con Anthropic

Estado: completada y aceptada técnica y funcionalmente.

Pregunta que responde:

**¿Cómo desacoplar la generación final del hardware local sin alterar RAG?**

Construye:

- selección explícita de `ollama` o `anthropic` en `[llm].provider`;
- adaptador Anthropic para Messages API con endpoint y versión fijos;
- credencial tardía y exclusiva desde `ANTHROPIC_API_KEY`;
- payload no streaming, parseo textual, timeout, cancelación y errores seguros;
- observabilidad de tokens y tiempo sin costos ni persistencia nueva;
- guardas para que H1.1 permanezca Ollama-only;
- suite offline con bloqueo de egress externo, redirects y canarios.

H1.2 conserva sin cambios ingesta, inventario, embeddings Ollama, SQLite,
búsqueda híbrida, reverse engineering, Reasoning Package, construcción de
prompts, reparación y validación de citas. Generación y reparación usan el mismo
proveedor seleccionado. `--no-llm` y evidencia insuficiente no leen la key ni
abren red.

Resultado:

Barbarion puede generar localmente con Ollama o enviar únicamente el prompt
final a Anthropic. No incorpora streaming, retries, fallback entre proveedores,
routing dinámico ni soporte cloud adicional.

Evidencia de implementación y aceptación:

[`../specs/H1.2-RemoteInference/`](../specs/H1.2-RemoteInference/) y
[`../specs/H1.2-RemoteInference/acceptance.md`](../specs/H1.2-RemoteInference/acceptance.md).
H1.2-T08 quedó completada con validación real de Anthropic, suite de regresión y
smoke instalado.

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

## H3.1 -- Optimización de contexto RAG

Estado: implementación iniciada; H3.1-T01 a H3.1-T07 completadas.

Pregunta que responde:

**¿Cómo entregar al LLM evidencia suficiente y trazable usando un contexto
medible, sin redundancia innecesaria ni dependencia de un proveedor?**

Parte de una observación real de H1.2: una consulta reportó `10,198` tokens de
entrada Anthropic frente a `6,190` estimados localmente. H3.1 no modifica H1.2
ni asume que ese consumo sea incorrecto. Primero establece una baseline
reproducible y descompone instrucciones, pregunta, metadata, evidencia y formato;
después evalúa presupuesto del input completo, selección conservadora y overlap.

La baseline T03 usa diez casos sintéticos publicables y no activa ninguna
optimización. Registra composición de `generation` y `repair`, retrieval,
cobertura de fuentes/hechos, citas, insuficiencia, duplicados exactos y overlap.
Sus resultados reproducibles están en
[`../reports/h31/t03-baseline.md`](../reports/h31/t03-baseline.md); las decisiones
T04-T08 permanecen sujetas a revisión de esos datos y no tienen objetivo de
reducción prefijado.

T04 confirmó que duplicación y overlap son marginales en el dataset vigente:
el duplicado exacto ya era omitido y el overlap enviado representa `7` tokens
estimados (`0.277%` del prompt de generación). El diagnóstico permanece
`report_only`; la evidencia favorece concentrar T07 en cobertura y permite
evaluar el diferimiento de T08.

T05 congela `rag.input_token_budget_est` como contrato opcional, sin default
numérico. Las configuraciones legadas conservan
`context_token_budget` y declarar ambas claves explícitamente se rechaza por
ambigüedad. T06 aplica la clave nueva al prompt completo estimado, con puertas
separadas para generation y repair y salida segura sin LLM cuando no cabe
evidencia relevante. La selección continúa siendo `baseline_v1`.

T07 incorpora `optimized_v1` como política opt-in. La comparación reproduce la
pérdida de la fuente relevante en posición seis y la recupera por score global:
la cobertura de fuentes/hechos y el recall de citas suben `0.111111`, sin
regresión en retrieval ni validez de citas. No se agregó reranker, diversidad
semántica ni inferencia de hechos.

La evolución mantiene retrieval, trazabilidad, citas, Ollama, Anthropic y
`--no-llm`. Sus benchmarks y fixtures deben ser públicos o sintéticos y no
pueden contener información de sistemas privados.

Spec:

[`../specs/H3.1-RAGContextOptimization/`](../specs/H3.1-RAGContextOptimization/).

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

H1.2 no implementa una plataforma multi-LLM: la factoría actual está cerrada a
Ollama y Anthropic, sin registry, routing ni comparación automática. Una futura
capacidad multi-LLM requerirá evidencia de necesidad, una decisión de alcance y
una spec propia para normalizar contratos, privacidad, evaluación y operación.

El Reasoning Package deberá seguir siendo independiente del backend. La
diferencia entre respuestas dependerá del modelo, no de una copia distinta del
conocimiento disponible.

------------------------------------------------------------------------

# Filosofía final

Cada nueva versión de Barbarion debe mejorar su capacidad de comprender
el sistema sin modificar la base construida en H2 y H3.

La inteligencia evoluciona sobre conocimiento estructurado, no
reemplazando dicho conocimiento.
