# Barbarion

Barbarion es un agente AI on-premise para análisis, documentación e ingeniería inversa asistida de sistemas legacy **Oracle/PLSQL + PowerBuilder**.

Su objetivo es ayudar a desarrolladores y analistas técnicos a comprender código existente, localizar dependencias y producir documentación trazable sin enviar el corpus a servicios cloud.

> El MVP se valida inicialmente sobre un dominio legacy real, pero ese dominio no forma parte del diseño público ni limita la arquitectura de Barbarion.

## Estado

`H1-Foundation` está completado y aceptado en la versión `0.1.0`:

- paquete Python instalable;
- CLI local en español;
- configuración TOML validada;
- inicialización segura de directorios;
- logging local;
- SQLite versionado;
- diagnóstico reproducible mediante `barbarion doctor`;
- pruebas unitarias, de integración y smoke.

Todavía no se implementan ingesta, parsers, RAG, embeddings, Qdrant, ingeniería inversa ni generación de documentos. Estas capacidades pertenecen a hitos posteriores.

## Requisitos

- CPython `3.12` (`>=3.12,<3.13`);
- `pip`;
- Ollama es opcional en H1.

Ollama no es necesario para instalar, probar ni aceptar H1. Cuando no está disponible, `doctor` informa `WARN` y conserva el código de salida `0` si todos los checks requeridos pasan.

## Instalación para desarrollo

Desde el checkout del repositorio:

```bash
python -m venv .venv
```

Activar el entorno:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# Linux o macOS
source .venv/bin/activate
```

Instalar Barbarion con las dependencias de desarrollo:

```bash
python -m pip install -e ".[dev]"
```

Comprobar la instalación:

```bash
barbarion --version
barbarion --help
```

## Configuración

El archivo versionado [`barbarion.example.toml`](barbarion.example.toml) documenta todas las claves disponibles en H1. Para crear una configuración local:

```powershell
# Windows PowerShell
Copy-Item barbarion.example.toml barbarion.toml
```

```bash
# Linux o macOS
cp barbarion.example.toml barbarion.toml
```

`barbarion.toml` está excluido de Git. No deben versionarse rutas personales, credenciales ni endpoints privados.

La configuración se resuelve en este orden:

1. opción global `--config RUTA`;
2. variable de entorno `BARBARION_CONFIG`;
3. `./barbarion.toml`;
4. valores predeterminados.

Las rutas relativas se resuelven desde el directorio del archivo TOML. Sin archivo, se resuelven desde el directorio de trabajo.

Para inspeccionar los valores efectivos sin crear recursos:

```bash
barbarion config show
barbarion --config ruta/al/archivo.toml config show
```

## Comandos disponibles

| Comando | Resultado | Efectos secundarios |
|---|---|---|
| `barbarion --help` | Muestra ayuda en español | Ninguno |
| `barbarion --version` | Muestra la versión instalada | Ninguno |
| `barbarion config show` | Valida y muestra la configuración efectiva | Ninguno |
| `barbarion doctor` | Inicializa recursos y diagnostica el entorno | Crea directorios, SQLite y log si faltan |

`doctor` comprueba, en orden:

1. versión de Python;
2. configuración;
3. directorio de datos;
4. directorio de salida;
5. directorio de logs;
6. SQLite;
7. disponibilidad de Ollama mediante `GET /api/tags`.

Los resultados usan `PASS`, `WARN` y `FAIL`. El detalle, los errores, la ayuda y los logs se presentan en español.

## Directorios y archivos locales

Con la configuración predeterminada, `barbarion doctor` inicializa:

```text
data/
└── barbarion.db
output/
logs/
└── barbarion.log
```

`data/`, `output/`, `logs/`, `barbarion.toml`, bases SQLite y `.venv/` están excluidos de Git.

## Códigos de salida

| Código | Significado |
|---:|---|
| `0` | Comando completado; todos los checks requeridos pasan. Puede haber advertencias opcionales |
| `1` | `doctor` encontró un fallo requerido o ocurrió un error operativo |
| `2` | Argumentos o configuración inválidos |
| `130` | Operación interrumpida por el usuario |

Los errores esperados no muestran traceback.

## Pruebas

Ejecutar toda la suite:

```bash
python -m pytest
```

Ejecutar únicamente los smoke tests contra el entry point instalado:

```bash
python -m pytest tests/smoke
```

Las pruebas usan directorios temporales y un endpoint Ollama falso en loopback. No necesitan un Ollama real ni acceso a internet.

## Alcance y principios

- local y on-premise por diseño;
- CLI-first;
- monolito Python modular de un solo proceso;
- biblioteca estándar para el runtime de H1;
- evidencia antes que elocuencia;
- un solo dominio configurado durante la validación inicial;
- entregables pequeños y verificables;
- revisión humana de resultados futuros.

No forman parte del MVP una extensión de VS Code, UI web, autenticación, microservicios, Kubernetes, base de datos empresarial ni grafo avanzado.

## Roadmap

1. `H1-Foundation`
2. `H2-Ingestion`
3. `H3-RAG`
4. `H4-ReverseEngineering`
5. `H5-SpecMode`

El plan completo contempla aproximadamente 12 semanas y 120 horas de trabajo.

## Documentación

- [Guía de documentación](docs/README.md)
- [Visión del producto](docs/VISION.md)
- [Roadmap del MVP](docs/ROADMAP.md)
- [Arquitectura](docs/ARCHITECTURE.md)
- [Decisiones técnicas](docs/DECISIONS.md)
- [Specs por hito](specs/)
- [Spec aprobada de H1](specs/H1-Foundation/)

## Licencia

Barbarion se distribuye bajo la [licencia MIT](LICENSE).
