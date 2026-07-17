# Inventario tecnico

## Metadata
- generado_en: 2026-01-01T00:00:00+00:00
- template_version: inventory.v1
- parametros: technology=configuration

## Resumen
- archivos: 1
- simbolos: 1
- referencias: 2
- relaciones: 1

## Detectado
- `pricing_rules.r1` tipo=configuration_record tecnologia=configuration estado=active confianza=high refs=2 out=1 in=0 archivo=config/pricing/rules.sql lineas=3-9 configuracion=pricing_rules tabla=APP_CFG.PRICING_RULES

## Inferido
- conteos derivados desde tablas vigentes de reverse engineering

## Por confirmar
- revisar simbolos ambiguos, desconocidos o de baja confianza

## Evidencia
- `pricing_rules.r1` archivo=config/pricing/rules.sql chunk=chunk-config-1 lineas=3-9

## Limitaciones
- inventario generado solo desde SQLite; no reescanea archivos
- referencias dinamicas o ambiguas requieren revision humana

---
# Ficha de componente

## Metadata
- generado_en: 2026-01-01T00:00:00+00:00
- template_version: component.v1
- parametros: query=pricing_rules.r1
- modo_llm: no_llm

## Identificacion
- nombre: pricing_rules.r1
- nombre_original: Base Rule
- tipo: configuration_record
- tecnologia: configuration
- estado: active
- confianza: high
- archivo_id: 7
- chunk: chunk-config-1
- lineas: 3-9
- symbol_id: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
- configuracion: pricing_rules
- tabla: APP_CFG.PRICING_RULES
- operacion: insert
- registro: R1
- identidad: R1
- valores: Base Rule
- columnas_declaradas: RULE_ID, RULE_NAME, FORMULA

## Resumen
- pricing_rules.r1 es un registro Data-Driven de pricing_rules.

## Detectado
- responsabilidad: registro Data-Driven pricing_rules.r1 de pricing_rules
- responsabilidad: proviene de la tabla APP_CFG.PRICING_RULES

## Inferido
- sin inferencias derivadas

## Por confirmar
- sin puntos por confirmar

## Evidencia
- sin evidencia persistida para listar

## Limitaciones
- sin limitaciones adicionales

---
# Analisis de impacto

## Metadata
- generado_en: 2026-01-01T00:00:00+00:00
- template_version: impact.v1
- parametros: query=pricing_rules.r1
- modo_llm: no_llm

## Componente
- nombre: pricing_rules.r1
- nombre_original: Base Rule
- tipo: configuration_record
- tecnologia: configuration
- estado: active
- confianza: high
- archivo_id: 7
- chunk: chunk-config-1
- lineas: 3-9
- symbol_id: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
- configuracion: pricing_rules
- tabla: APP_CFG.PRICING_RULES
- operacion: insert
- registro: R1
- identidad: R1
- valores: Base Rule
- columnas_declaradas: RULE_ID, RULE_NAME, FORMULA

## Alcance
- direccion: outgoing
- profundidad: 1
- limite_nodos: 500
- nodos: 2
- relaciones: 1

## Resumen
- Impacto Data-Driven de pricing_rules.r1.

## Detectado
### Consumidores
- sin consumidores detectados

### Dependencias
- `pricing_rules.r1` -> `tax_rate` tipo=calls direccion=outgoing profundidad=1 estado=resolved clasificacion=detectado confianza=high

### Cruces de tecnologia
- `pricing_rules.r1` -> `tax_rate` tipo=calls direccion=outgoing profundidad=1 estado=resolved clasificacion=detectado confianza=high

## Inferido
- existen cruces entre tecnologias

## Por confirmar
- sin puntos por confirmar

## Evidencia
- sin evidencia persistida para listar

## Limitaciones
- sin limitaciones adicionales
