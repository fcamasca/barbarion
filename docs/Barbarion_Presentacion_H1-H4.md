# Barbarion - Presentación Ejecutiva (H1-H4)

## Introducción

> "Quisiera empezar con una situación que seguramente todos hemos
> vivido."

Imaginemos que mañana el negocio nos pide un cambio muy simple:

**"A partir del próximo mes queremos cobrar la membresía de manera
distinta para los clientes Premium."**

La primera pregunta normalmente no es:

> ¿Cómo lo programamos?

La primera pregunta siempre es:

> ¿Dónde está implementado?

Empiezan las reuniones:

-   ¿Está en Oracle?
-   ¿Está en PowerBuilder?
-   ¿Qué package lo hace?
-   ¿Qué pantalla lo invoca?
-   ¿Existe documentación?
-   ¿Quién conoce ese proceso?

Muchas veces investigar toma más tiempo que desarrollar.

Ese es exactamente el problema que Barbarion intenta resolver.

------------------------------------------------------------------------

# La idea general

Barbarion no pretende reemplazar al desarrollador.

Su objetivo es reducir el tiempo necesario para comprender un sistema
legacy antes de modificarlo.

Cada hito agrega una nueva capacidad.

# H1 --- Foundation

Construimos los cimientos.

-   CLI
-   Configuración
-   SQLite
-   Infraestructura
-   Pruebas

Es como construir una biblioteca.

Primero existe el edificio.

Sin edificio no podemos guardar libros.

------------------------------------------------------------------------

# H2 --- Ingesta

Ahora llenamos esa biblioteca.

Supongamos un sistema de streaming.

Encontramos:

-   PCK_FACTURACION.pkb
-   PCK_CLIENTES.pkb
-   PCK_CORREO.pkb
-   W_FACTURACION.srw
-   DW_CLIENTES.srd

Barbarion organiza toda esa información.

Detecta:

-   archivos
-   documentos
-   objetos Oracle
-   objetos PowerBuilder
-   líneas
-   chunks

Toda esa información queda almacenada en SQLite.

En este momento Barbarion sabe:

-   Tengo 850 archivos.
-   Encontré 120 packages.
-   Encontré 3500 chunks.

Pero todavía no entiende cómo interactúan.

Solo construyó un inventario estructurado.

------------------------------------------------------------------------

# H3 --- RAG

Ahora aparece la IA.

Muchas personas creen que el LLM lee todo el sistema.

En realidad no.

Barbarion localiza primero únicamente los fragmentos más relevantes y
recién entonces los entrega al LLM.

Por eso puede responder preguntas como:

"¿Cómo se realiza el cobro mensual?"

H3 conoce información.

Todavía no conoce relaciones.

------------------------------------------------------------------------

# H4 --- Ingeniería Reversa

Aquí Barbarion empieza a entender el sistema.

Tenemos:

PCK_FACTURACION

Dentro existe:

PRC_COBRAR_MEMBRESIA

Y ese procedimiento hace:

-   valida cliente
-   inserta factura
-   actualiza suscripción
-   envía correo

Hasta H3 todo era texto.

H4 identifica:

-   packages
-   procedures
-   funciones
-   tablas
-   ventanas
-   DataWindows

Después identifica referencias.

Luego las convierte en relaciones.

Ejemplo:

PRC_COBRAR_MEMBRESIA

↓

llama

↓

PRC_VALIDAR_CLIENTE

También descubre:

PRC_COBRAR_MEMBRESIA

↓

actualiza

↓

FACTURAS

Y además:

PRC_COBRAR_MEMBRESIA

↓

usa

↓

PKG_CORREO

Ahora Barbarion ya no solamente sabe leer código.

Empieza a reconstruir la arquitectura del sistema.

------------------------------------------------------------------------

# ¿Qué ganamos?

Ahora alguien pregunta:

¿Qué pasa si modificamos PRC_VALIDAR_CLIENTE?

Antes había que revisar packages, preguntar a otros desarrolladores y
reconstruir manualmente el impacto.

Con Barbarion:

barbarion impact PRC_VALIDAR_CLIENTE

Puede responder:

-   Lo utiliza el cobro mensual.
-   También lo usan las renovaciones.
-   Actualiza CLIENTES.
-   Dispara el envío de correo.

Y cada afirmación viene acompañada de evidencia.

No responde "porque la IA lo dice".

Responde porque encontró esa relación en el código.

------------------------------------------------------------------------

# ¿Por qué no dejamos que el LLM haga todo?

Porque un LLM explica muy bien.

Pero no conoce nuestro sistema.

Barbarion prepara primero el conocimiento:

-   componentes
-   relaciones
-   dependencias
-   evidencia
-   ambigüedades

Luego entrega ese conocimiento al LLM.

El LLM ya no descubre el sistema.

Solo lo explica.

------------------------------------------------------------------------

# Evolución

El siguiente paso será reconstruir procesos completos.

Pantalla PowerBuilder

↓

Evento

↓

PCK_FACTURACION

↓

PRC_COBRAR_MEMBRESIA

↓

CLIENTES

↓

FACTURAS

↓

PKG_CORREO

↓

Correo al cliente

Después podrá agrupar procesos por dominio funcional y generar un
"Reasoning Package" que podrá enviarse a cualquier LLM.

------------------------------------------------------------------------

# Cierre

Barbarion evoluciona igual que un analista cuando llega a un proyecto.

Primero organiza la información.

Luego aprende a encontrarla.

Después entiende cómo interactúan los componentes.

Y finalmente podrá razonar sobre el sistema para entregar respuestas
consistentes independientemente del LLM utilizado.
