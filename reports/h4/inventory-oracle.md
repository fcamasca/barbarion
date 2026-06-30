# Inventario tecnico

## Metadata
- generado_en: 2026-06-30T04:44:41.061718+00:00
- template_version: inventory.v1
- parametros: technology=oracle

## Resumen
- archivos: 1
- simbolos: 4
- referencias: 1
- relaciones: 2

## Detectado
- `pkg.dependency` tipo=procedure tecnologia=oracle estado=active confianza=high refs=0 out=0 in=1 archivo=oracle/pkg_root.pkb lineas=n/a
- `pkg.root` tipo=procedure tecnologia=oracle estado=active confianza=high refs=1 out=1 in=1 archivo=oracle/pkg_root.pkb lineas=n/a
- `duplicado` tipo=procedure tecnologia=oracle estado=active confianza=high refs=0 out=0 in=0 archivo=n/a lineas=n/a
- `duplicado` tipo=procedure tecnologia=oracle estado=active confianza=high refs=0 out=0 in=0 archivo=n/a lineas=n/a

## Inferido
- conteos derivados desde tablas vigentes de reverse engineering

## Por confirmar
- revisar simbolos ambiguos, desconocidos o de baja confianza

## Evidencia
- `pkg.dependency` archivo=oracle/pkg_root.pkb chunk=n/a lineas=n/a
- `pkg.root` archivo=oracle/pkg_root.pkb chunk=n/a lineas=n/a
- `duplicado` archivo=n/a chunk=n/a lineas=n/a
- `duplicado` archivo=n/a chunk=n/a lineas=n/a

## Limitaciones
- inventario generado solo desde SQLite; no reescanea archivos
- referencias dinamicas o ambiguas requieren revision humana

