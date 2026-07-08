# Plan de pruebas - limite-credito

## Metadata
- generado_en: 2026-01-01T00:00:00+00:00
- template_version: spec.v1
- draft_id: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa

## Estrategia
- validar REQ-001 con pruebas proporcionales al impacto y evidencia recuperada

## Unitarias
- TEST-001 cubrir reglas puras o transformaciones deterministicas de REQ-001

## Integracion
- TEST-002 cubrir componentes afectados confirmados por H4

## CLI
- verificar comandos o flujos de usuario cuando aplique

## Regresion
- ejecutar regresion sobre funcionalidades vecinas y consumidores identificados

## Casos negativos
- validar errores esperados y condiciones limite

## Golden files si aplica
- usar golden files cuando el cambio produzca Markdown o salida estable

## Evidencia esperada
- [F111111111111] chunk: F1 sources/oracle/pkg_credito.sql; [F1] sources/oracle/pkg_credito.sql lineas=10-12

## Matriz requisito-prueba
| Requisito | Prueba | Tipo |
|---|---|---|
| REQ-001 | TEST-001 | unitaria |
| REQ-001 | TEST-002 | integracion |
| REQ-001 | TEST-003 | regresion |
