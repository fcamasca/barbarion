"""Carga y validación de la configuración local de Barbarion."""

import os
import tomllib
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
_ALLOWED_KEYS = frozenset(_DEFAULTS)
_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


class ConfigError(ValueError):
    """Error esperado al localizar, leer o validar la configuración."""


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
