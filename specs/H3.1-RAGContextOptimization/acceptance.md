# Aceptacion H3.1 - Optimizacion de contexto RAG

## Estado

**Estado tecnico y funcional:** ACCEPTED.

**Estado de H3.1-T12:** completada por autorizacion explicita del usuario el
2026-08-07.

H3.1 queda aceptada como evolucion provider-agnostic del contexto RAG. La
aceptacion no cambia el default: `baseline_v1` permanece vigente y
`optimized_v1` continua disponible de forma opt-in. Su promocion se difiere
hasta reunir validaciones adicionales en corpus distintos.

## Version y entorno

- fecha: 2026-08-07;
- sistema: Windows 11 `10.0.26200`;
- PowerShell: `5.1.26100.8875`;
- rama: `feature/h3.1-rag-context-optimization`;
- revision evaluada: `fe2b776` mas este cierre documental;
- Barbarion: `0.6.0`;
- Python: `3.12.13`;
- pytest: `8.4.2`.

Se creo una venv temporal de aceptacion y se instalo Barbarion editable, sin
resolver dependencias por red:

```powershell
<python-3.12-runtime>\python.exe -m venv --system-site-packages .pytest-tmp\h31-acceptance-venv
.pytest-tmp\h31-acceptance-venv\Scripts\python.exe -m pip install -e . --no-deps --no-build-isolation
.pytest-tmp\h31-acceptance-venv\Scripts\barbarion.exe --version
```

Resultado de version: `barbarion 0.6.0`. Pytest y las dependencias de prueba se
reutilizaron desde la instalacion local existente; no hubo descarga ni egress.

## Suite completa y smoke instalado

Suite de aceptacion:

```powershell
.pytest-tmp\h31-acceptance-venv\Scripts\python.exe -m pytest --basetemp .pytest-tmp\h31-acceptance-suite -q
```

Resultado:

```text
924 passed, 3 skipped in 153.34s
```

Los tres skips corresponden a pruebas que requieren crear symlinks, operacion
no permitida por este entorno Windows. No se omitieron pruebas H3.1, de
presupuesto, seleccion, overlap, citas, formatos ni proveedores fake.

Smoke independiente contra el entry point instalado:

```powershell
.pytest-tmp\h31-acceptance-venv\Scripts\python.exe -m pytest tests\smoke --basetemp .pytest-tmp\h31-acceptance-smoke -q
```

Resultado:

```text
11 passed in 39.34s
```

## Benchmark publico y sintetico

Comandos:

```powershell
.pytest-tmp\h31-acceptance-venv\Scripts\python.exe -m tests.support.h31_baseline_benchmark --output reports\h31
.pytest-tmp\h31-acceptance-venv\Scripts\python.exe -m pytest tests\unit\test_h31_baseline_benchmark.py --basetemp .pytest-tmp\h31-acceptance-benchmark -q
```

Reproducibilidad: `7 passed in 0.42s`; los reportes regenerados coinciden byte
a byte con los artefactos versionados.

| Metrica | `baseline_v1` | `optimized_v1` | Delta |
|---|---:|---:|---:|
| recall@5 | 0.888889 | 0.888889 | 0.000000 |
| recall@10 | 1.000000 | 1.000000 | 0.000000 |
| MRR | 0.851852 | 0.851852 | 0.000000 |
| recall de fuentes seleccionadas | 0.888889 | 1.000000 | +0.111111 |
| cobertura de hechos | 0.888889 | 1.000000 | +0.111111 |
| precision de citas | 1.000000 | 1.000000 | 0.000000 |
| recall de citas | 0.888889 | 1.000000 | +0.111111 |
| validez de citas | 1.000000 | 1.000000 | 0.000000 |

El caso sintetico clave pasa de `insufficient` a `completed`. No hay regresion
de retrieval ni citas. El benchmark offline no llama proveedores y deja
`provider_*_tokens` como no disponibles; `chars4_v1` sigue siendo solo una
estimacion local.

## Privacidad

El benchmark usa exclusivamente fixtures publicos o sinteticos y los reportes
versionados contienen agregados. El contrato `h31_observability_v1` declara:

- preguntas: no incluidas;
- prompts: no incluidos;
- respuestas: no incluidas;
- contenido de fuentes: no incluido;
- persistencia: solo agregados sinteticos versionados.

Se ejecuto un scanner case-insensitive sobre reportes H3.1, fixtures y soporte
del benchmark para credenciales, cabeceras de autorizacion, cadenas de conexion
y rutas personales. Resultado: `PASS`, cero coincidencias.

## Evidencia privada resumida

Las validaciones reales autorizadas se usan solo como evidencia privada
agregada. No se copian aqui consultas, identificadores, formulas, contenido ni
rutas del corpus. Esas validaciones confirmaron cuatro clases de hallazgo:

1. candidatos vectoriales sin contenido vigente no deben consumir `top_k`;
2. el overlap exacto puede ser material y liberar presupuesto util;
3. los empates entre candidatos estructurados no deben crear prioridad por
   posicion incidental y una identidad exacta debe conservar su precision;
4. inferencias sintacticas directas y limites verificables de evidencia deben
   validarse sin aceptar afirmaciones inventadas.

Cada hallazgo produjo una correccion acotada y pruebas sinteticas. La suite final
cubre backfill, limpieza de huerfanos, rango denso, identidad exacta, trim
exacto/continuo, presupuesto, reparacion, citas, contradicciones y claims no
soportados. No se realiza una nueva llamada a un proveedor durante T12 y no se
declaran tokens reales nuevos.

## Contratos aceptados

- `baseline_v1` permanece como default y conserva compatibilidad;
- `optimized_v1` sigue opt-in y requiere `input_token_budget_est`;
- no existe default numerico para el presupuesto nuevo;
- el valor local de `4500` usado en la validacion privada no se generaliza;
- generation y repair se presupuestan por separado sobre el prompt completo;
- si no cabe evidencia suficiente, no se llama al LLM;
- si repair excede el presupuesto, se omite de forma segura;
- los scores originales y la familia permanecen trazables;
- los empates comparten rango relativo y la identidad exacta es explicita;
- dedupe exacto y trim de overlap exacto/continuo permanecen conservadores;
- claims positivos, contradicciones e invenciones siguen bajo validacion
  estricta;
- Ollama, Anthropic fake, `--no-llm`, JSON, Unicode y consumidores H3/H4.1/H4/H5
  permanecen cubiertos por regresion.

## Riesgos y diferimientos

- el benchmark es pequeno, sintetico y no representa todos los corpus legacy;
- `chars4_v1` no sustituye la tokenizacion efectiva del proveedor;
- la calibracion entre familias se basa en ranking relativo y senales cerradas,
  no en un reranker aprendido;
- no se implementa similitud semantica para dedupe u overlap;
- la promocion de `optimized_v1` a default queda diferida hasta contar con mas
  validaciones en corpus independientes.

## Decision final

**H3.1: ACCEPTED.**

La suite completa, el smoke instalado, el benchmark reproducible, el scanner de
privacidad y las validaciones privadas resumidas respaldan el cierre. La
decision de despliegue permanece deliberadamente conservadora:

- default: `baseline_v1`;
- candidata opt-in: `optimized_v1`;
- promocion a default: diferida.

## Addendum post-H3.1: cobertura de citas por bloque

Una validación posterior detectó que el validador comprobaba la existencia y el
soporte de las citas presentes, pero no exigía la cita inline prometida por el
prompt en cada párrafo o bullet factual. La corrección clasifica esos bloques
sin cita como claims no soportados, conserva la detección de citas inexistentes,
contradicciones e invenciones, y mantiene el repair y su presupuesto seguro.
Encabezados, líneas vacías y bloques de código quedan fuera de esta regla.

## Addendum post-H3.1: presupuesto independiente de repair

El validador estricto hizo visible que generation podía ocupar todo el
presupuesto y dejar a repair sin espacio para agregar la respuesta rechazada.
La corrección recalcula repair desde cero y trunca proporcionalmente solo el
contenido de las mismas fuentes, conservando IDs, candidatos y trazabilidad. No
hay nuevo retrieval ni aumento del presupuesto configurado. Si aun así no cabe
evidencia suficiente, repair permanece sin ejecutar y el resultado se rechaza.

El posible falso negativo de soporte factual observado en otra afirmación se
mantiene separado de este cambio y no se usa para relajar el validador.

## Addendum post-H3.1: contrato compartido de grounding

Una ejecución real confirmó que el repair presupuestado se ejecutaba, pero su
prompt había divergido de generation y no exigía una cita por cada párrafo o
bullet factual. Ambos prompts reutilizan ahora las mismas reglas literales de
citas y no inferencia. Repair agrega solo la instrucción de corregir los
problemas de soporte y citación de la respuesta rechazada. El prompt de
generation quedó caracterizado en ese punto; la caracterización y métricas de
repair se actualizaron de forma explícita.

## Addendum post-H3.1: salida compacta y repair dirigido

La sección `Supuestos y limites` pasa a ser opcional y solo puede aparecer con
límites o supuestos demostrados y citados. Generation y repair comparten además
la instrucción de responder de forma compacta, sin conclusiones generales ni
comentarios accesorios. Este ajuste cambia deliberadamente la caracterización
de ambos prompts sin alterar retrieval ni el presupuesto configurado.

Repair recibe las categorías y conteos seguros del fallo de generation, nunca
el texto de los claims, y tiene prohibido agregar hechos, interpretaciones o
conclusiones nuevas. La observabilidad expone `repair_outcome` para
distinguir causa, intento y resultado. `CitationValidator`, la política de
selección y el valor privado de `4500` permanecen intactos; tampoco se introduce
clasificación por tipo de consulta.
