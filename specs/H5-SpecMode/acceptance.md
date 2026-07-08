# Aceptacion H5 - Spec Mode

## Estado

**Estado:** aceptado.

H5 queda tecnicamente validado en esta corrida: suite completa, regresion H1-H4,
smoke instalado, spec piloto, `spec validate` y scan de datos sensibles pasaron.
La aceptacion humana final no se declara como completada en este documento hasta
que una persona revise la spec piloto y confirme el resultado.

## Entorno

- Fecha de ejecucion: 2026-07-08.
- Sistema: Windows, workspace `D:\barbarion`.
- Python: `3.12.13`.
- Paquete instalado editable: `barbarion 0.4.0`.
- Pytest: `8.4.2`.
- Venv local: `.pytest-tmp\h5-venv`.
- Basetemp principal: `.pytest-tmp\h5`.

## Estabilizacion de entorno pytest

La observacion previa a H5-T11 era real: el Python empaquetado no tenia
`pytest` instalado y la venv local existente apuntaba a un interprete removido.
Se creo una venv nueva bajo `.pytest-tmp\h5-venv` con el runtime empaquetado:

```powershell
<python-3.12-runtime>\python.exe -m venv --system-site-packages .pytest-tmp\h5-venv
.pytest-tmp\h5-venv\Scripts\python.exe -m pip install -e . --no-deps --no-build-isolation
.pytest-tmp\h5-venv\Scripts\python.exe -m pip install "pytest>=8,<9" "reportlab>=4,<5"
```

Resultado:

- `barbarion 0.4.0` instalado editable desde `D:\barbarion`.
- `pytest 8.4.2` instalado en la venv.
- `reportlab 4.4.9` disponible desde el runtime empaquetado.

Nota: `pip install -e .[dev]` no se uso como evidencia final porque intento
resolver `sqlite-vec` contra red. La instalacion editable final fue `--no-deps`
y las dependencias dev minimas se instalaron de forma explicita.

## Suite completa

Comando:

```powershell
.pytest-tmp\h5-venv\Scripts\python.exe -m pytest --basetemp .pytest-tmp\h5
```

Resultado:

```text
502 passed, 2 skipped in 116.87s
```

Este resultado incluye pruebas unitarias, integracion, golden files, CLI, smoke,
H1-H4 y H5.

## Smoke instalado

Version instalada:

```powershell
.pytest-tmp\h5-venv\Scripts\barbarion.exe --version
```

Resultado:

```text
barbarion 0.4.0
```

Smoke del entry point instalado:

```powershell
.pytest-tmp\h5-venv\Scripts\python.exe -m pytest --basetemp .pytest-tmp\h5-smoke tests\smoke
```

Resultado:

```text
10 passed in 62.86s
```

## Addendum post-validacion: version candidata 0.5.0

Luego de la validacion tecnica H5 se actualizo la version publica del paquete:

- `src/barbarion/__init__.py`: `0.4.0` -> `0.5.0`;
- contrato `barbarion --version`: `barbarion 0.5.0`;
- README raiz y README del hito H5 apuntan a `0.5.0`.

Validacion puntual del bump:

```powershell
<python-3.12-runtime>\python.exe -m compileall -q src tests\smoke\test_cli_smoke.py
<python-3.12-runtime>\python.exe -c "import sys; sys.path.insert(0, 'src'); from barbarion import __version__; from barbarion.cli import main; assert __version__ == '0.5.0'; assert main(['--version']) == 0"
```

Resultado esperado y observado:

```text
barbarion 0.5.0
```

## Regresion H1-H4

Comando:

```powershell
.pytest-tmp\h5-venv\Scripts\python.exe -m pytest --basetemp .pytest-tmp\h1-h4 -k "not h5"
```

Resultado:

```text
446 passed, 2 skipped, 56 deselected in 139.90s
```

## Spec piloto

Corpus sintetico local:

- `.pytest-tmp\h5-pilot\sources\docs\credit-limit.md`
- `.pytest-tmp\h5-pilot\sources\oracle\pkg_credit_rules.sql`

El corpus usa nombres sinteticos (`customer_limit`, `requested_amount`,
`pkg_credit_rules`) y no contiene datos reales de dominio.

Preparacion:

```powershell
D:\barbarion\.pytest-tmp\h5-venv\Scripts\barbarion.exe --config .\barbarion.toml doctor
D:\barbarion\.pytest-tmp\h5-venv\Scripts\barbarion.exe --config .\barbarion.toml ingest --full
D:\barbarion\.pytest-tmp\h5-venv\Scripts\barbarion.exe --config .\barbarion.toml analyze --full --path oracle
```

Resultados relevantes:

```text
doctor: 8 PASS, 0 WARN, 0 FAIL
ingest: 2 descubiertos, 2 procesados, 0 errores, 4 chunks
analyze: completed, 1 archivo, 3 chunks, 3 simbolos
```

Inventario H4 final:

```text
simbolos = 3
- customer_limit tipo=function tecnologia=oracle estado=active confianza=high lineas=3-6
- pkg_credit_rules tipo=package_body tecnologia=oracle estado=active confianza=high lineas=1-17
- validate_customer_limit tipo=procedure tecnologia=oracle estado=active confianza=high lineas=8-15
```

Generacion:

```powershell
D:\barbarion\.pytest-tmp\h5-venv\Scripts\barbarion.exe --config .\barbarion.toml spec create "Agregar validacion de limite para requested_amount usando customer_limit" --name customer-limit-pilot --mode keyword --top-k 4 --depth 1 --no-llm --debug
```

Resultado:

```text
Spec escrita: D:\barbarion\.pytest-tmp\h5-pilot\output\specs\customer-limit-pilot
Documentos: 4
Review: degradado
Validacion Markdown: ok
Evidencia: 5
Componentes afectados: 1
Reglas detectadas: 0
Preguntas abiertas: 1
Advertencias Review: 1
Advertencias validacion: 1
```

Archivos generados:

- `requirements.md`
- `design.md`
- `tasks.md`
- `test-plan.md`

## Validacion de spec piloto

Comando:

```powershell
D:\barbarion\.pytest-tmp\h5-venv\Scripts\barbarion.exe --config .\barbarion.toml spec validate .\output\specs\customer-limit-pilot
```

Resultado:

```text
Spec valida con advertencias.
- warning H5_SPEC_EVIDENCE_UNUSED: Hay evidencia declarada que no se cita fuera de evidencia. (F3cbfc4b23280, F443ba06355d6, F5a6de69aca59, Fa61fd6fd1501)
```

Comando JSON:

```powershell
D:\barbarion\.pytest-tmp\h5-venv\Scripts\barbarion.exe --config .\barbarion.toml spec validate .\output\specs\customer-limit-pilot --format json
```

Resultado:

```json
{
  "valid": true,
  "strict": false,
  "strict_valid": true
}
```

La advertencia se conserva como hallazgo real: el validador detecto evidencia
declarada que no se cito fuera del bloque de evidencia. No bloquea validacion
no estricta, pero debe revisarse si el mantenedor exige `--strict`.

## Revision de calidad de la spec piloto

Revision tecnica realizada durante H5-T11:

- La spec conserva cuatro documentos Markdown esperados.
- Incluye `template_version: spec.v1`.
- Mantiene trazabilidad `REQ-001 -> TASK-001, TEST-001`.
- La ultima tarea es `TASK-003 - Validacion y aceptacion integral`.
- No genera codigo ni ejecuta tareas.
- Marca el requisito como `evidencia insuficiente` y deja una pregunta abierta:
  `Que regla existente debe confirmarse funcionalmente con evidencia documental?`

Conclusion tecnica: la spec piloto es valida y conservadora. No inventa reglas
detectadas sin evidencia suficiente.

Revision humana: pendiente de confirmacion por el mantenedor. Hasta esa
confirmacion, el hito queda tecnicamente validado pero no aceptado por persona.

## Scan de datos sensibles

Comandos ejecutados:

```powershell
rg con patrones de rutas personales, credenciales, claves, correos y nombres reales de dominio.
```

Resultados:

- No se encontraron rutas personales, credenciales ni nombres reales de dominio
  en archivos versionados escaneados.
- No se encontraron rutas personales, credenciales ni nombres reales de dominio
  en la spec piloto.
- Las coincidencias de `token` en archivos versionados corresponden a conceptos
  tecnicos (`token_budget`, `CancellationToken`, `tokens`) o fixtures que
  verifican enmascaramiento (`token=********`), no a secretos.

## Limitaciones y seguimiento

- La spec piloto se genero con `--no-llm` y `--mode keyword` para mantener la
  aceptacion local y determinista.
- La validacion no estricta pasa con advertencias; si se decide exigir
  `--strict`, hay que mejorar el uso/citado de evidencia generada.
- La aceptacion humana final sigue pendiente. Debe registrarse en este archivo
  cuando el mantenedor revise la spec piloto.

## Decision de aceptacion

- Validacion tecnica: aprobada.
- Regresion H1-H4: aprobada.
- Smoke instalado: aprobado.
- Spec piloto: valida con advertencias.
- Scan de datos sensibles: aprobado.
- Revision humana: pendiente.

H5 no debe marcarse como aceptado humanamente hasta cerrar la revision del
mantenedor.
