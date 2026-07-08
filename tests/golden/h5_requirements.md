# Requisitos - limite-credito

## Metadata
- generado_en: 2026-01-01T00:00:00+00:00
- template_version: spec.v1
- draft_id: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
- modo: hybrid

## Objetivo
- Validar limite de credito antes de aprobar pedidos

## Alcance
- REQ-001 Validar limite de credito antes de aprobar pedidos [F111111111111]

## Fuera de alcance
- generacion automatica de codigo
- aprobacion funcional sin revision humana

## Historias de usuario
- HU-001 Como mantenedor, quiero Validar limite de credito antes de aprobar pedidos para evolucionar el sistema con trazabilidad.

## Requisitos funcionales
- REQ-001 Validar limite de credito antes de aprobar pedidos [F111111111111]

## Requisitos no funcionales
- RNF-001 Mantener trazabilidad entre requisitos, decisiones, tareas, pruebas y evidencia.
- RNF-002 Generar Markdown estable y editable.

## Supuestos
- sin supuestos declarados

## Preguntas abiertas
- Confirmar umbral exacto de limite de credito.

## Evidencia
- [F111111111111] chunk: F1 sources/oracle/pkg_credito.sql; [F1] sources/oracle/pkg_credito.sql lineas=10-12

## Trazabilidad
- REQ-001 -> TASK-001, TEST-001
