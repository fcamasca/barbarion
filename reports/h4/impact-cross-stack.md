# Analisis de impacto

## Metadata
- generado_en: 2026-06-30T04:44:41.214234+00:00
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
- chunk: n/a
- lineas: n/a
- symbol_id: b7e5088f327c48b0fb4fbbbebc361659547417eede4192b7a34d2194fc5384c9

## Alcance
- direccion: both
- profundidad: 1
- limite_nodos: 500
- nodos: 3
- relaciones: 2

## Resumen
- Impacto basico de pkg.root: 3 nodos y 2 relaciones evaluadas hasta profundidad 1.

## Detectado
### Consumidores
- `w_root` -> `pkg.root` tipo=calls direccion=incoming profundidad=1 estado=resolved clasificacion=detectado confianza=medium

### Dependencias
- `pkg.root` -> `pkg.dependency` tipo=calls direccion=outgoing profundidad=1 estado=resolved clasificacion=detectado confianza=medium

### Cruces de tecnologia
- `w_root` -> `pkg.root` tipo=calls direccion=incoming profundidad=1 estado=resolved clasificacion=detectado confianza=medium

## Inferido
- hay consumidores que podrian requerir verificacion
- existen cruces entre tecnologias

## Por confirmar
- sin puntos por confirmar

## Evidencia
- relation: calls resolved ref=8d344c2db0342e5d34580e054f5bd2899cfafc19b507740a5ad2e5c56a521c67 rel=b0040700833b72a2f0c43d5abbb4cefe62ff8ed06771f7a1e7b29963cf460be3 chunk=n/a
- relation: calls resolved ref=a7ca69ad3b7a3a342e7666741a3837ca669843532627eaa1e7b68a58390d37db rel=9637e4c6403a91bfdbced27408e9ef8e19ee3d70bd7c85ef959e0f7a8eb381fb chunk=n/a

## Limitaciones
- sin limitaciones adicionales

