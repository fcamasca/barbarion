# Analisis de impacto

## Metadata
- generado_en: 2026-01-01T00:00:00+00:00
- template_version: impact.v1
- parametros: query=pkg.root
- modo_llm: no_llm

## Componente
- nombre: pkg.root
- nombre_original: pkg.root
- tipo: procedure
- tecnologia: oracle
- estado: active
- confianza: high
- archivo_id: 1
- chunk: chunk-a
- lineas: 1-4
- symbol_id: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa

## Alcance
- direccion: both
- profundidad: 2
- limite_nodos: 500
- nodos: 3
- relaciones: 2

## Resumen
- Impacto basico de pkg.root.

## Detectado
### Consumidores
- `w.root` -> `pkg.root` tipo=calls direccion=incoming profundidad=1 estado=resolved clasificacion=detectado confianza=medium

### Dependencias
- `pkg.root` -> `pkg.dependency` tipo=calls direccion=outgoing profundidad=1 estado=resolved clasificacion=detectado confianza=medium

### Cruces de tecnologia
- `w.root` -> `pkg.root` tipo=calls direccion=incoming profundidad=1 estado=resolved clasificacion=detectado confianza=medium

## Inferido
- hay consumidores que podrian requerir verificacion

## Por confirmar
- sin puntos por confirmar

## Evidencia
- relation: calls resolved ref=dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd rel=eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee chunk=n/a

## Limitaciones
- sin limitaciones adicionales
