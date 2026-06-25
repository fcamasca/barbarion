"""Carga y validación de la configuración local de Barbarion."""

import os
import tomllib
import codecs
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

CONFIG_ENV_VAR = "BARBARION_CONFIG"
DEFAULT_CONFIG_FILENAME = "barbarion.toml"

_DEFAULTS: dict[str, object] = {
    "domain": "default",
    "data_dir": "./data",
    "output_dir": "./output",
    "logs_dir": "./logs",
    "database_path": "./data/barbarion.db",
    "log_level": "INFO",
    "ollama_url": "http://127.0.0.1:11434",
    "ollama_timeout_seconds": 2.0,
}
_DEFAULT_INGESTION: dict[str, object] = {
    "paths": ("sources/oracle", "sources/powerbuilder", "sources/docs"),
    "extensions": (
        ".sql",
        ".pks",
        ".pkb",
        ".prc",
        ".fnc",
        ".trg",
        ".pck",
        ".vw",
        ".vws",
        ".pkg",
        ".tps",
        ".srw",
        ".sru",
        ".srf",
        ".srm",
        ".srj",
        ".srd",
        ".pbl",
        ".md",
        ".txt",
        ".docx",
        ".pdf",
        ".yaml",
        ".yml",
        ".json",
        ".ini",
    ),
    "chunk_size": 4000,
    "chunk_overlap": 400,
    "ignore_patterns": (
        ".git/**",
        ".barbarion/**",
        ".venv/**",
        "**/__pycache__/**",
        "data/**",
        "output/**",
        "logs/**",
        "**/node_modules/**",
    ),
    "max_file_size_mb": 50,
    "max_extracted_chars": 5_000_000,
    "max_pdf_pages": 1000,
    "encodings": ("utf-8", "cp1252", "latin-1"),
}
_ALLOWED_KEYS = frozenset(_DEFAULTS) | {"ingestion"}
_ALLOWED_INGESTION_KEYS = frozenset(_DEFAULT_INGESTION)
_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


class ConfigError(ValueError):
    """Error esperado al localizar, leer o validar la configuración."""


@dataclass(frozen=True, slots=True)
class IngestionSettings:
    """Configuracion efectiva e inmutable para ingesta."""

    paths: tuple[Path, ...]
    extensions: tuple[str, ...]
    chunk_size: int
    chunk_overlap: int
    ignore_patterns: tuple[str, ...]
    max_file_size_mb: int
    max_extracted_chars: int
    max_pdf_pages: int
    encodings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Settings:
    """Configuración efectiva e inmutable de Barbarion."""

    domain: str
    data_dir: Path
    output_dir: Path
    logs_dir: Path
    database_path: Path
    log_level: str
    ollama_url: str
    ollama_timeout_seconds: float
    ingestion: IngestionSettings
    config_source: Path | None


def load_settings(
    config_path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> Settings:
    """Carga la configuración según la precedencia definida por H1."""
    working_dir = _normalize_working_dir(cwd)
    environment = os.environ if environ is None else environ
    source = _resolve_config_source(config_path, environment, working_dir)
    raw_values = _load_toml(source) if source is not None else {}
    values = {**_DEFAULTS, **raw_values}
    base_dir = source.parent if source is not None else working_dir

    unknown_keys = sorted(set(raw_values) - _ALLOWED_KEYS)
    if unknown_keys:
        formatted = ", ".join(unknown_keys)
        raise ConfigError(f"Claves de configuración desconocidas: {formatted}.")

    return Settings(
        domain=_require_non_empty_string(values["domain"], "domain"),
        data_dir=_resolve_path(values["data_dir"], "data_dir", base_dir),
        output_dir=_resolve_path(values["output_dir"], "output_dir", base_dir),
        logs_dir=_resolve_path(values["logs_dir"], "logs_dir", base_dir),
        database_path=_resolve_path(
            values["database_path"],
            "database_path",
            base_dir,
        ),
        log_level=_validate_log_level(values["log_level"]),
        ollama_url=_validate_ollama_url(values["ollama_url"]),
        ollama_timeout_seconds=_validate_timeout(
            values["ollama_timeout_seconds"]
        ),
        ingestion=_build_ingestion_settings(values.get("ingestion"), base_dir),
        config_source=source,
    )


def settings_display_items(settings: Settings) -> tuple[tuple[str, str], ...]:
    """Devuelve la configuración en el orden estable de la salida CLI."""
    source_kind = (
        "archivo"
        if settings.config_source is not None
        else "valores predeterminados"
    )
    source_path = (
        str(settings.config_source)
        if settings.config_source is not None
        else "ninguno"
    )
    return (
        ("origen", source_kind),
        ("archivo_configuracion", source_path),
        ("domain", settings.domain),
        ("data_dir", str(settings.data_dir)),
        ("output_dir", str(settings.output_dir)),
        ("logs_dir", str(settings.logs_dir)),
        ("database_path", str(settings.database_path)),
        ("log_level", settings.log_level),
        ("ollama_url", settings.ollama_url),
        ("ollama_timeout_seconds", str(settings.ollama_timeout_seconds)),
    )

def _normalize_working_dir(cwd: Path | None) -> Path:
    """Normaliza el directorio base sin exigir recursos adicionales."""
    candidate = Path.cwd() if cwd is None else Path(cwd)
    return candidate.expanduser().resolve(strict=False)


def _resolve_config_source(
    config_path: str | Path | None,
    environ: Mapping[str, str],
    working_dir: Path,
) -> Path | None:
    """Resuelve el archivo respetando CLI, entorno, cwd y defaults."""
    if config_path is not None:
        return _require_config_file(config_path, working_dir, "--config")

    environment_path = environ.get(CONFIG_ENV_VAR)
    if environment_path is not None:
        return _require_config_file(
            environment_path,
            working_dir,
            CONFIG_ENV_VAR,
        )

    implicit_path = working_dir / DEFAULT_CONFIG_FILENAME
    if implicit_path.is_file():
        return implicit_path.resolve(strict=False)
    if implicit_path.exists():
        raise ConfigError(
            f"La ruta de configuración '{implicit_path}' no es un archivo."
        )
    return None


def _require_config_file(
    raw_path: str | Path,
    working_dir: Path,
    origin: str,
) -> Path:
    """Valida una ruta de configuración indicada explícitamente."""
    if isinstance(raw_path, str) and not raw_path.strip():
        raise ConfigError(f"La ruta indicada por {origin} está vacía.")

    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = working_dir / candidate
    candidate = candidate.resolve(strict=False)

    if not candidate.exists():
        raise ConfigError(
            f"El archivo de configuración indicado por {origin} no existe: "
            f"'{candidate}'."
        )
    if not candidate.is_file():
        raise ConfigError(
            f"La ruta de configuración indicada por {origin} no es un archivo: "
            f"'{candidate}'."
        )
    return candidate


def _load_toml(source: Path) -> dict[str, object]:
    """Lee un documento TOML sin interpolar ni ejecutar contenido."""
    try:
        with source.open("rb") as file:
            return tomllib.load(file)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"El archivo TOML '{source}' no es válido.") from error
    except OSError as error:
        raise ConfigError(
            f"No se pudo leer el archivo de configuración '{source}'."
        ) from error


def _require_non_empty_string(value: object, key: str) -> str:
    """Valida una cadena obligatoria y elimina espacios externos."""
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"La clave '{key}' debe ser una cadena no vacía.")
    return value.strip()


def _resolve_path(value: object, key: str, base_dir: Path) -> Path:
    """Resuelve una ruta relativa contra el archivo que la define."""
    raw_path = _require_non_empty_string(value, key)
    if "\x00" in raw_path:
        raise ConfigError(f"La clave '{key}' contiene una ruta no válida.")

    try:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = base_dir / path
        return path.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise ConfigError(f"La clave '{key}' contiene una ruta no válida.") from error


def _validate_log_level(value: object) -> str:
    """Valida y normaliza el nivel de logging."""
    level = _require_non_empty_string(value, "log_level").upper()
    if level not in _LOG_LEVELS:
        allowed = ", ".join(sorted(_LOG_LEVELS))
        raise ConfigError(
            f"La clave 'log_level' debe ser uno de estos valores: {allowed}."
        )
    return level


def _validate_timeout(value: object) -> float:
    """Valida el timeout corto utilizado para diagnosticar Ollama."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(
            "La clave 'ollama_timeout_seconds' debe ser un número."
        )
    timeout = float(value)
    if not 0 < timeout <= 10:
        raise ConfigError(
            "La clave 'ollama_timeout_seconds' debe ser mayor que 0 y menor "
            "o igual que 10."
        )
    return timeout


def _validate_ollama_url(value: object) -> str:
    """Valida una URL HTTP(S) base y sin credenciales."""
    url = _require_non_empty_string(value, "ollama_url")
    try:
        parsed = urlsplit(url)
        parsed_port = parsed.port
    except ValueError as error:
        raise ConfigError("La clave 'ollama_url' contiene una URL no válida.") from error

    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ConfigError(
            "La clave 'ollama_url' debe contener una URL HTTP(S) válida."
        )
    if parsed.username is not None or parsed.password is not None:
        raise ConfigError(
            "La clave 'ollama_url' no debe contener credenciales."
        )
    if parsed.query or parsed.fragment:
        raise ConfigError(
            "La clave 'ollama_url' no debe contener query ni fragmento."
        )
    if parsed_port is not None and not 1 <= parsed_port <= 65535:
        raise ConfigError(
            "La clave 'ollama_url' contiene un puerto no válido."
        )
    return url.rstrip("/")


def _build_ingestion_settings(value: object, base_dir: Path) -> IngestionSettings:
    """Construye la configuracion de ingesta desde defaults y TOML."""
    if value is None:
        raw_ingestion: dict[str, object] = {}
    elif isinstance(value, dict):
        raw_ingestion = value
    else:
        raise ConfigError("La seccion 'ingestion' debe ser una tabla TOML.")

    unknown_keys = sorted(set(raw_ingestion) - _ALLOWED_INGESTION_KEYS)
    if unknown_keys:
        formatted = ", ".join(f"ingestion.{key}" for key in unknown_keys)
        raise ConfigError(f"Claves de configuracion desconocidas: {formatted}.")

    values = {**_DEFAULT_INGESTION, **raw_ingestion}
    chunk_size = _validate_int_range(
        values["chunk_size"],
        "ingestion.chunk_size",
        minimum=500,
        maximum=100_000,
    )
    chunk_overlap = _validate_int_range(
        values["chunk_overlap"],
        "ingestion.chunk_overlap",
        minimum=0,
        maximum=chunk_size - 1,
    )
    max_extracted_chars = _validate_int_range(
        values["max_extracted_chars"],
        "ingestion.max_extracted_chars",
        minimum=chunk_size,
    )

    return IngestionSettings(
        paths=_resolve_path_list(values["paths"], "ingestion.paths", base_dir),
        extensions=_validate_extensions(values["extensions"]),
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        ignore_patterns=_validate_string_list(
            values["ignore_patterns"],
            "ingestion.ignore_patterns",
        ),
        max_file_size_mb=_validate_int_range(
            values["max_file_size_mb"],
            "ingestion.max_file_size_mb",
            minimum=1,
            maximum=1024,
        ),
        max_extracted_chars=max_extracted_chars,
        max_pdf_pages=_validate_int_range(
            values["max_pdf_pages"],
            "ingestion.max_pdf_pages",
            minimum=1,
        ),
        encodings=_validate_encodings(values["encodings"]),
    )


def _validate_int_range(
    value: object,
    key: str,
    *,
    minimum: int,
    maximum: int | None = None,
) -> int:
    """Valida un entero dentro de un rango inclusivo."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"La clave '{key}' debe ser un entero.")
    if value < minimum:
        raise ConfigError(f"La clave '{key}' debe ser mayor o igual que {minimum}.")
    if maximum is not None and value > maximum:
        raise ConfigError(f"La clave '{key}' debe ser menor o igual que {maximum}.")
    return value


def _resolve_path_list(value: object, key: str, base_dir: Path) -> tuple[Path, ...]:
    """Valida y resuelve una lista de rutas."""
    raw_paths = _validate_string_list(value, key)
    if not raw_paths:
        raise ConfigError(f"La clave '{key}' debe contener al menos una ruta.")
    return tuple(_resolve_path(path, key, base_dir) for path in raw_paths)


def _validate_string_list(value: object, key: str) -> tuple[str, ...]:
    """Valida una lista de cadenas no vacias."""
    if not isinstance(value, (list, tuple)):
        raise ConfigError(f"La clave '{key}' debe ser una lista.")

    normalized: list[str] = []
    for item in value:
        normalized.append(_require_non_empty_string(item, key))
    return tuple(normalized)


def _validate_extensions(value: object) -> tuple[str, ...]:
    """Normaliza extensiones a minusculas con punto inicial."""
    raw_extensions = _validate_string_list(value, "ingestion.extensions")
    if not raw_extensions:
        raise ConfigError(
            "La clave 'ingestion.extensions' debe contener al menos una extension."
        )

    extensions: list[str] = []
    for extension in raw_extensions:
        normalized = extension.lower()
        if not normalized.startswith("."):
            normalized = f".{normalized}"
        if normalized == "." or "/" in normalized or "\\" in normalized:
            raise ConfigError(
                "La clave 'ingestion.extensions' contiene una extension no valida."
            )
        extensions.append(normalized)
    return tuple(dict.fromkeys(extensions))


def _validate_encodings(value: object) -> tuple[str, ...]:
    """Valida que los encodings existan en Python."""
    encodings = _validate_string_list(value, "ingestion.encodings")
    if not encodings:
        raise ConfigError(
            "La clave 'ingestion.encodings' debe contener al menos un encoding."
        )

    normalized: list[str] = []
    for encoding in encodings:
        try:
            normalized.append(codecs.lookup(encoding).name)
        except LookupError as error:
            raise ConfigError(
                f"La clave 'ingestion.encodings' contiene un encoding no valido: "
                f"{encoding}."
            ) from error
    return tuple(dict.fromkeys(normalized))
