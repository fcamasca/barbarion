# H5 — Spec Mode

**Estado:** completado y aceptado.

Spec Mode convierte evidencia documental H3 e impacto tecnico H4 en una spec
Markdown trazable, editable y lista para revision humana. No modifica codigo
fuente, no ejecuta tareas y no reemplaza aprobacion funcional.

## Entregables

- `barbarion spec create`: orquesta `RequirementAnalyzer -> H3 -> H4 -> SpecSynthesizer -> Review -> Markdown -> SpecValidator -> SafeSpecWriter`.
- `barbarion spec validate`: valida specs Markdown existentes sin regenerarlas.
- Plantillas `spec.v1` para `requirements.md`, `design.md`, `tasks.md` y `test-plan.md`.
- Review interno sobre `SpecDraft` antes del render.
- Validacion posterior sobre estructura Markdown, IDs, citas y trazabilidad.
- Escritura segura sin sobrescribir por defecto.

## Estado de aceptacion

La validacion tecnica H5 esta registrada en [acceptance.md](acceptance.md):

- suite completa: `502 passed, 2 skipped`;
- smoke instalado: `10 passed`;
- regresion H1-H4: `446 passed, 2 skipped, 56 deselected`;
- spec piloto generada y validada con advertencias;
- scan de datos sensibles aprobado.

La revision humana de la spec piloto sigue pendiente y debe cerrarse en
[acceptance.md](acceptance.md) antes de declarar aceptacion humana completa.

## Documentos del hito

- [requirements.md](requirements.md)
- [design.md](design.md)
- [tasks.md](tasks.md)
- [test-plan.md](test-plan.md)
- [acceptance.md](acceptance.md)

El alcance y criterios iniciales tambien estan resumidos en
[ROADMAP.md](../../docs/ROADMAP.md#7-h5--spec-mode).
