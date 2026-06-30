# Inventario tecnico

## Metadata
- generado_en: 2026-01-01T00:00:00+00:00
- template_version: inventory.v1
- parametros: technology=oracle, type=procedure

## Resumen
- archivos: 1
- simbolos: 1
- referencias: 2
- relaciones: 1

## Detectado
- `pkg_demo.procesar` tipo=procedure tecnologia=oracle estado=active confianza=high refs=2 out=1 in=0 archivo=oracle/pkg_demo.pkb lineas=10-15

## Inferido
- conteos derivados desde tablas vigentes de reverse engineering

## Por confirmar
- revisar simbolos ambiguos, desconocidos o de baja confianza

## Evidencia
- `pkg_demo.procesar` archivo=oracle/pkg_demo.pkb chunk=chunk-1 lineas=10-15

## Limitaciones
- inventario generado solo desde SQLite; no reescanea archivos
- referencias dinamicas o ambiguas requieren revision humana
