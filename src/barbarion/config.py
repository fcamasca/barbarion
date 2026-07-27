"""Carga y validación de la configuracion local de Barbarion."""

import codecs
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
_DEFAULT_INGESTION: dict[str, object] = {
    "paths": ("sources",),
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
_DEFAULT_EMBEDDINGS: dict[str, object] = {
    "provider": "ollama",
    "model": "nomic-embed-text",
    "batch_size": 16,
    "timeout_seconds": 60.0,
    "normalize": True,
}
_DEFAULT_VECTOR_STORE: dict[str, object] = {
    "provider": "sqlite_vec",
    "table_prefix": "rag",
    "distance": "cosine",
}
_DEFAULT_RETRIEVAL: dict[str, object] = {
    "mode": "hybrid",
    "top_k": 10,
    "candidate_k": 40,
    "similarity_threshold": 0.20,
    "vector_weight": 0.70,
    "keyword_weight": 0.30,
}
_DEFAULT_RAG: dict[str, object] = {
    "context_token_budget": 6000,
    "max_chunk_tokens": 1200,
    "dedupe_min_hash_prefix": 16,
    "include_snippets": True,
}
_DEFAULT_LLM: dict[str, object] = {
    "provider": "ollama",
    "model": "llama3.1:8b",
    "timeout_seconds": 120.0,
    "temperature": 0.1,
    "think": None,
    "num_ctx": None,
}
_DEFAULT_DATA_DRIVEN: dict[str, object] = {
    "enabled": False,
    "file_patterns": (),
    "max_statements_per_file": 10_000,
    "max_literal_chars": 200_000,
    "token_patterns": (
        r"\{([A-Za-z_][A-Za-z0-9_]*)\}",
        r"\$\{([^}]+)\}",
        r":([A-Za-z_][A-Za-z0-9_]*)",
    ),
    "configurations": (),
}
_ALLOWED_KEYS = frozenset(_DEFAULTS) | {
    "ingestion",
    "embeddings",
    "vector_store",
    "retrieval",
    "rag",
    "llm",
    "data_driven",
}
_ALLOWED_INGESTION_KEYS = frozenset(_DEFAULT_INGESTION)
_ALLOWED_EMBEDDINGS_KEYS = frozenset(_DEFAULT_EMBEDDINGS)
_ALLOWED_VECTOR_STORE_KEYS = frozenset(_DEFAULT_VECTOR_STORE)
_ALLOWED_RETRIEVAL_KEYS = frozenset(_DEFAULT_RETRIEVAL)
_ALLOWED_RAG_KEYS = frozenset(_DEFAULT_RAG)
_ALLOWED_LLM_KEYS = frozenset(_DEFAULT_LLM)
_ALLOWED_DATA_DRIVEN_KEYS = frozenset(_DEFAULT_DATA_DRIVEN)
_ALLOWED_DATA_DRIVEN_CONFIGURATION_KEYS = frozenset(
    {
        "name",
        "symbol_type",
        "tables",
        "identity_columns",
        "file_patterns",
        "default_column_order",
        "name_columns",
        "description_columns",
        "rule_columns",
        "formula_columns",
        "variable_columns",
        "parameter_columns",
        "mapping_columns",
        "reference_columns",
        "parent_columns",
        "sequence_columns",
        "status_columns",
        "effective_from_columns",
        "effective_to_columns",
        "metadata_columns",
    }
)
_ALLOWED_REFERENCE_COLUMN_KEYS = frozenset(
    {
        "column",
        "target_technology",
        "target_type",
        "target_configuration",
        "relation_type",
    }
)
_ALLOWED_PARENT_COLUMN_KEYS = frozenset({"column", "target_configuration"})
_ALLOWED_STATUS_COLUMN_KEYS = frozenset(
    {"column", "active_values", "inactive_values"}
)
_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
_RETRIEVAL_MODES = frozenset({"semantic", "keyword", "hybrid"})
_DATA_DRIVEN_TARGET_TECHNOLOGIES = frozenset(
    {"configuration", "oracle", "powerbuilder"}
)
_DATA_DRIVEN_REFERENCE_RELATION_TYPES = frozenset(
    {"references", "parent_of", "precedes", "uses", "calls"}
)


class ConfigError(ValueError):
    """Error esperado al localizar, leer o validar la configuracion."""


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
class EmbeddingsSettings:
    """Configuracion efectiva para embeddings locales."""

    provider: str
    model: str
    batch_size: int
    timeout_seconds: float
    normalize: bool


@dataclass(frozen=True, slots=True)
class VectorStoreSettings:
    """Configuracion efectiva del almacenamiento vectorial inicial."""

    provider: str
    table_prefix: str
    distance: str


@dataclass(frozen=True, slots=True)
class RetrievalSettings:
    """Configuracion efectiva de recuperacion semantica/hibrida."""

    mode: str
    top_k: int
    candidate_k: int
    similarity_threshold: float
    vector_weight: float
    keyword_weight: float


@dataclass(frozen=True, slots=True)
class RagSettings:
    """Configuracion efectiva del ensamblado de contexto RAG."""

    context_token_budget: int
    max_chunk_tokens: int
    dedupe_min_hash_prefix: int
    include_snippets: bool


@dataclass(frozen=True, slots=True)
class LlmSettings:
    """Configuracion efectiva del proveedor LLM local."""

    provider: str
    model: str
    timeout_seconds: float
    temperature: float
    think: bool | None = None
    num_ctx: int | None = None


@dataclass(frozen=True, slots=True)
class DataDrivenReferenceColumn:
    """Columna que declara una referencia explicita.

    Attributes:
        column: Columna que contiene el texto de la referencia.
        target_technology: Tecnologia esperada del destino, si aplica.
        target_type: Tipo tecnico esperado del destino, si aplica.
        target_configuration: Configuracion destino para referencias entre registros.
        relation_type: Relacion deseada; `precedes` requiere una columna explicita.
    """

    column: str
    target_technology: str | None = None
    target_type: str | None = None
    target_configuration: str | None = None
    relation_type: str | None = None


@dataclass(frozen=True, slots=True)
class DataDrivenParentColumn:
    """Columna que expresa jerarquia entre registros de configuracion.

    Attributes:
        column: Columna que contiene la identidad del padre.
        target_configuration: Configuracion donde debe buscarse el padre.
    """

    column: str
    target_configuration: str


@dataclass(frozen=True, slots=True)
class DataDrivenStatusColumn:
    """Columna que distingue registros activos e inactivos.

    Attributes:
        column: Columna que contiene el estado.
        active_values: Valores declarados como activos.
        inactive_values: Valores declarados como inactivos.
    """

    column: str
    active_values: tuple[str, ...]
    inactive_values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DataDrivenConfiguration:
    """Contrato declarativo para una familia de configuraciones en tablas.

    La declaracion describe como identificar registros, que columnas producen
    simbolos derivados y que columnas producen referencias. `sequence_columns`
    conserva metadata de orden y no genera relaciones por si sola.
    """

    name: str
    symbol_type: str
    tables: tuple[str, ...]
    identity_columns: tuple[str, ...]
    file_patterns: tuple[str, ...]
    default_column_order: tuple[str, ...]
    name_columns: tuple[str, ...]
    description_columns: tuple[str, ...]
    rule_columns: tuple[str, ...]
    formula_columns: tuple[str, ...]
    variable_columns: tuple[str, ...]
    parameter_columns: tuple[str, ...]
    mapping_columns: tuple[str, ...]
    reference_columns: tuple[DataDrivenReferenceColumn, ...]
    parent_columns: tuple[DataDrivenParentColumn, ...]
    sequence_columns: tuple[str, ...]
    status_columns: tuple[DataDrivenStatusColumn, ...]
    effective_from_columns: tuple[str, ...]
    effective_to_columns: tuple[str, ...]
    metadata_columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DataDrivenSettings:
    """Configuracion efectiva para deteccion Data-Driven declarativa.

    Attributes:
        enabled: Habilita la clasificacion y analisis de configuraciones.
        file_patterns: Patrones globales de archivos SQL candidatos.
        max_statements_per_file: Limite defensivo de sentencias por documento.
        max_literal_chars: Longitud maxima de literales aceptados.
        token_patterns: Patrones de tokens usados en reglas y formulas.
        configurations: Declaraciones de familias de configuracion.
    """

    enabled: bool
    file_patterns: tuple[str, ...]
    max_statements_per_file: int
    max_literal_chars: int
    token_patterns: tuple[str, ...]
    configurations: tuple[DataDrivenConfiguration, ...]


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
    embeddings: EmbeddingsSettings
    vector_store: VectorStoreSettings
    retrieval: RetrievalSettings
    rag: RagSettings
    llm: LlmSettings
    data_driven: DataDrivenSettings
    config_source: Path | None


def load_settings(
    config_path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> Settings:
    """Carga la configuracion según la precedencia definida por base."""
    working_dir = _normalize_working_dir(cwd)
    environment = os.environ if environ is None else environ
    source = _resolve_config_source(config_path, environment, working_dir)
    raw_values = _load_toml(source) if source is not None else {}
    values = {**_DEFAULTS, **raw_values}
    base_dir = source.parent if source is not None else working_dir

    unknown_keys = sorted(set(raw_values) - _ALLOWED_KEYS)
    if unknown_keys:
        formatted = ", ".join(unknown_keys)
        raise ConfigError(f"Claves de configuracion desconocidas: {formatted}.")

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
        embeddings=_build_embeddings_settings(values.get("embeddings")),
        vector_store=_build_vector_store_settings(values.get("vector_store")),
        retrieval=_build_retrieval_settings(values.get("retrieval")),
        rag=_build_rag_settings(values.get("rag")),
        llm=_build_llm_settings(values.get("llm")),
        data_driven=_build_data_driven_settings(values.get("data_driven")),
        config_source=source,
    )


def settings_display_items(settings: Settings) -> tuple[tuple[str, str], ...]:
    """Devuelve la configuracion en el orden estable de la salida CLI."""
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
        ("ingestion.paths", _format_paths(settings.ingestion.paths)),
        ("ingestion.extensions", _format_items(settings.ingestion.extensions)),
        ("ingestion.chunk_size", str(settings.ingestion.chunk_size)),
        ("ingestion.chunk_overlap", str(settings.ingestion.chunk_overlap)),
        (
            "ingestion.ignore_patterns",
            _format_items(settings.ingestion.ignore_patterns),
        ),
        ("ingestion.max_file_size_mb", str(settings.ingestion.max_file_size_mb)),
        (
            "ingestion.max_extracted_chars",
            str(settings.ingestion.max_extracted_chars),
        ),
        ("ingestion.max_pdf_pages", str(settings.ingestion.max_pdf_pages)),
        ("ingestion.encodings", _format_items(settings.ingestion.encodings)),
        ("embeddings.provider", settings.embeddings.provider),
        ("embeddings.model", settings.embeddings.model),
        ("embeddings.batch_size", str(settings.embeddings.batch_size)),
        ("embeddings.timeout_seconds", str(settings.embeddings.timeout_seconds)),
        ("embeddings.normalize", str(settings.embeddings.normalize).lower()),
        ("vector_store.provider", settings.vector_store.provider),
        ("vector_store.table_prefix", settings.vector_store.table_prefix),
        ("vector_store.distance", settings.vector_store.distance),
        ("retrieval.mode", settings.retrieval.mode),
        ("retrieval.top_k", str(settings.retrieval.top_k)),
        ("retrieval.candidate_k", str(settings.retrieval.candidate_k)),
        (
            "retrieval.similarity_threshold",
            str(settings.retrieval.similarity_threshold),
        ),
        ("retrieval.vector_weight", str(settings.retrieval.vector_weight)),
        ("retrieval.keyword_weight", str(settings.retrieval.keyword_weight)),
        ("rag.context_token_budget", str(settings.rag.context_token_budget)),
        ("rag.max_chunk_tokens", str(settings.rag.max_chunk_tokens)),
        ("rag.dedupe_min_hash_prefix", str(settings.rag.dedupe_min_hash_prefix)),
        ("rag.include_snippets", str(settings.rag.include_snippets).lower()),
        ("llm.provider", settings.llm.provider),
        ("llm.model", settings.llm.model),
        ("llm.timeout_seconds", str(settings.llm.timeout_seconds)),
        ("llm.temperature", str(settings.llm.temperature)),
        (
            "llm.think",
            "no configurado"
            if settings.llm.think is None
            else str(settings.llm.think).lower(),
        ),
        (
            "llm.num_ctx",
            "no configurado"
            if settings.llm.num_ctx is None
            else str(settings.llm.num_ctx),
        ),
        ("data_driven.enabled", str(settings.data_driven.enabled).lower()),
        (
            "data_driven.file_patterns",
            _format_items(settings.data_driven.file_patterns),
        ),
        (
            "data_driven.max_statements_per_file",
            str(settings.data_driven.max_statements_per_file),
        ),
        (
            "data_driven.max_literal_chars",
            str(settings.data_driven.max_literal_chars),
        ),
        (
            "data_driven.token_patterns",
            _format_items(settings.data_driven.token_patterns),
        ),
        (
            "data_driven.configurations",
            str(len(settings.data_driven.configurations)),
        ),
    )


def _normalize_working_dir(cwd: Path | None) -> Path:
    """Normaliza el directorio base sin exigir recursos adicionales."""
    candidate = Path.cwd() if cwd is None else Path(cwd)
    return candidate.expanduser().resolve(strict=False)


def _format_paths(paths: tuple[Path, ...]) -> str:
    """Formatea rutas para la salida humana de configuracion."""
    return _format_items(tuple(str(path) for path in paths))


def _format_items(items: tuple[str, ...]) -> str:
    """Formatea listas pequenas para `config show`."""
    return "[" + ", ".join(items) + "]"


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
            f"La ruta de configuracion '{implicit_path}' no es un archivo."
        )
    return None


def _require_config_file(
    raw_path: str | Path,
    working_dir: Path,
    origin: str,
) -> Path:
    """Valida una ruta de configuracion indicada explícitamente."""
    if isinstance(raw_path, str) and not raw_path.strip():
        raise ConfigError(f"La ruta indicada por {origin} está vacia.")

    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = working_dir / candidate
    candidate = candidate.resolve(strict=False)

    if not candidate.exists():
        raise ConfigError(
            f"El archivo de configuracion indicado por {origin} no existe: "
            f"'{candidate}'."
        )
    if not candidate.is_file():
        raise ConfigError(
            f"La ruta de configuracion indicada por {origin} no es un archivo: "
            f"'{candidate}'."
        )
    return candidate


def _load_toml(source: Path) -> dict[str, object]:
    """Lee un documento TOML sin interpolar ni ejecutar contenido."""
    try:
        with source.open("rb") as file:
            return tomllib.load(file)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"El archivo TOML '{source}' no es valido.") from error
    except OSError as error:
        raise ConfigError(
            f"No se pudo leer el archivo de configuracion '{source}'."
        ) from error


def _require_non_empty_string(value: object, key: str) -> str:
    """Valida una cadena obligatoria y elimina espacios externos."""
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"La clave '{key}' debe ser una cadena no vacia.")
    return value.strip()


def _resolve_path(value: object, key: str, base_dir: Path) -> Path:
    """Resuelve una ruta relativa contra el archivo que la define."""
    raw_path = _require_non_empty_string(value, key)
    if "\x00" in raw_path:
        raise ConfigError(f"La clave '{key}' contiene una ruta no valida.")

    try:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = base_dir / path
        return path.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise ConfigError(f"La clave '{key}' contiene una ruta no valida.") from error


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
            "La clave 'ollama_timeout_seconds' debe ser un numero."
        )
    timeout = float(value)
    if not 0 < timeout <= 10:
        raise ConfigError(
            "La clave 'ollama_timeout_seconds' debe ser mayor que 0 y menor "
            "o igual que 10."
        )
    return timeout


def _validate_positive_timeout(value: object, key: str) -> float:
    """Valida timeouts operativos de RAG."""
    timeout = _validate_float(value, key)
    if timeout <= 0 or timeout > 1800:
        raise ConfigError(
            f"La clave '{key}' debe ser mayor que 0 y menor o igual que 600."
        )
    return timeout


def _validate_ollama_url(value: object) -> str:
    """Valida una URL HTTP(S) base y sin credenciales."""
    url = _require_non_empty_string(value, "ollama_url")
    try:
        parsed = urlsplit(url)
        parsed_port = parsed.port
    except ValueError as error:
        raise ConfigError("La clave 'ollama_url' contiene una URL no valida.") from error

    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ConfigError(
            "La clave 'ollama_url' debe contener una URL HTTP(S) valida."
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
            "La clave 'ollama_url' contiene un puerto no valido."
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


def _build_embeddings_settings(value: object) -> EmbeddingsSettings:
    """Construye la configuracion de embeddings RAG."""
    values = _merge_section(
        value,
        "embeddings",
        _DEFAULT_EMBEDDINGS,
        _ALLOWED_EMBEDDINGS_KEYS,
    )
    provider = _validate_choice(
        values["provider"],
        "embeddings.provider",
        {"ollama"},
    )
    return EmbeddingsSettings(
        provider=provider,
        model=_require_non_empty_string(values["model"], "embeddings.model"),
        batch_size=_validate_int_range(
            values["batch_size"],
            "embeddings.batch_size",
            minimum=1,
            maximum=128,
        ),
        timeout_seconds=_validate_positive_timeout(
            values["timeout_seconds"],
            "embeddings.timeout_seconds",
        ),
        normalize=_validate_bool(values["normalize"], "embeddings.normalize"),
    )


def _build_vector_store_settings(value: object) -> VectorStoreSettings:
    """Construye la configuracion del vector store RAG."""
    values = _merge_section(
        value,
        "vector_store",
        _DEFAULT_VECTOR_STORE,
        _ALLOWED_VECTOR_STORE_KEYS,
    )
    provider = _validate_choice(
        values["provider"],
        "vector_store.provider",
        {"sqlite_vec"},
    )
    return VectorStoreSettings(
        provider=provider,
        table_prefix=_validate_identifier(
            values["table_prefix"],
            "vector_store.table_prefix",
        ),
        distance=_validate_choice(
            values["distance"],
            "vector_store.distance",
            {"cosine"},
        ),
    )


def _build_retrieval_settings(value: object) -> RetrievalSettings:
    """Construye la configuracion de recuperacion RAG."""
    values = _merge_section(
        value,
        "retrieval",
        _DEFAULT_RETRIEVAL,
        _ALLOWED_RETRIEVAL_KEYS,
    )
    top_k = _validate_int_range(
        values["top_k"],
        "retrieval.top_k",
        minimum=1,
        maximum=100,
    )
    candidate_k = _validate_int_range(
        values["candidate_k"],
        "retrieval.candidate_k",
        minimum=top_k,
        maximum=1000,
    )
    vector_weight = _validate_unit_float(
        values["vector_weight"],
        "retrieval.vector_weight",
    )
    keyword_weight = _validate_unit_float(
        values["keyword_weight"],
        "retrieval.keyword_weight",
    )
    if vector_weight + keyword_weight <= 0:
        raise ConfigError(
            "La suma de 'retrieval.vector_weight' y "
            "'retrieval.keyword_weight' debe ser mayor que 0."
        )
    return RetrievalSettings(
        mode=_validate_choice(values["mode"], "retrieval.mode", _RETRIEVAL_MODES),
        top_k=top_k,
        candidate_k=candidate_k,
        similarity_threshold=_validate_unit_float(
            values["similarity_threshold"],
            "retrieval.similarity_threshold",
        ),
        vector_weight=vector_weight,
        keyword_weight=keyword_weight,
    )


def _build_rag_settings(value: object) -> RagSettings:
    """Construye la configuracion del context builder RAG."""
    values = _merge_section(value, "rag", _DEFAULT_RAG, _ALLOWED_RAG_KEYS)
    return RagSettings(
        context_token_budget=_validate_int_range(
            values["context_token_budget"],
            "rag.context_token_budget",
            minimum=501,
            maximum=200_000,
        ),
        max_chunk_tokens=_validate_int_range(
            values["max_chunk_tokens"],
            "rag.max_chunk_tokens",
            minimum=1,
            maximum=200_000,
        ),
        dedupe_min_hash_prefix=_validate_int_range(
            values["dedupe_min_hash_prefix"],
            "rag.dedupe_min_hash_prefix",
            minimum=8,
            maximum=64,
        ),
        include_snippets=_validate_bool(
            values["include_snippets"],
            "rag.include_snippets",
        ),
    )


def _build_llm_settings(value: object) -> LlmSettings:
    """Construye la configuracion del LLM local RAG."""
    values = _merge_section(value, "llm", _DEFAULT_LLM, _ALLOWED_LLM_KEYS)
    return LlmSettings(
        provider=_validate_choice(values["provider"], "llm.provider", {"ollama"}),
        model=_require_non_empty_string(values["model"], "llm.model"),
        timeout_seconds=_validate_positive_timeout(
            values["timeout_seconds"],
            "llm.timeout_seconds",
        ),
        temperature=_validate_unit_float(values["temperature"], "llm.temperature"),
        think=_validate_optional_bool(values["think"], "llm.think"),
        num_ctx=_validate_optional_positive_int(values["num_ctx"], "llm.num_ctx"),
    )


def _build_data_driven_settings(value: object) -> DataDrivenSettings:
    """Construye la configuracion Data-Driven sin ejecutar analisis SQL."""
    values = _merge_section(
        value,
        "data_driven",
        _DEFAULT_DATA_DRIVEN,
        _ALLOWED_DATA_DRIVEN_KEYS,
    )
    enabled = _validate_bool(values["enabled"], "data_driven.enabled")

    return DataDrivenSettings(
        enabled=enabled,
        file_patterns=_validate_sql_file_patterns(
            values["file_patterns"],
            "data_driven.file_patterns",
            required=enabled,
        ),
        max_statements_per_file=_validate_int_range(
            values["max_statements_per_file"],
            "data_driven.max_statements_per_file",
            minimum=1,
            maximum=1_000_000,
        ),
        max_literal_chars=_validate_int_range(
            values["max_literal_chars"],
            "data_driven.max_literal_chars",
            minimum=1,
            maximum=50_000_000,
        ),
        token_patterns=_validate_required_string_list(
            values["token_patterns"],
            "data_driven.token_patterns",
        ),
        configurations=_build_data_driven_configurations(
            values["configurations"],
            enabled=enabled,
        ),
    )


def _build_data_driven_configurations(
    value: object,
    *,
    enabled: bool,
) -> tuple[DataDrivenConfiguration, ...]:
    """Valida la lista de familias de configuracion declaradas."""
    if not isinstance(value, (list, tuple)):
        raise ConfigError("La clave 'data_driven.configurations' debe ser una lista.")
    if enabled and not value:
        raise ConfigError(
            "La clave 'data_driven.configurations' debe contener al menos "
            "una configuracion cuando data_driven.enabled es true."
        )

    configurations: list[DataDrivenConfiguration] = []
    seen_names: set[str] = set()
    for index, item in enumerate(value, start=1):
        key = f"data_driven.configurations[{index}]"
        configuration = _build_data_driven_configuration(item, key)
        if configuration.name in seen_names:
            raise ConfigError(
                f"La clave '{key}.name' contiene un nombre duplicado: "
                f"{configuration.name}."
            )
        seen_names.add(configuration.name)
        configurations.append(configuration)
    return tuple(configurations)


def _build_data_driven_configuration(
    value: object,
    key: str,
) -> DataDrivenConfiguration:
    """Valida una tabla TOML de configuracion Data-Driven."""
    if not isinstance(value, dict):
        raise ConfigError(f"La clave '{key}' debe ser una tabla TOML.")

    unknown_keys = sorted(set(value) - _ALLOWED_DATA_DRIVEN_CONFIGURATION_KEYS)
    if unknown_keys:
        formatted = ", ".join(f"{key}.{unknown}" for unknown in unknown_keys)
        raise ConfigError(f"Claves de configuracion desconocidas: {formatted}.")

    return DataDrivenConfiguration(
        name=_validate_identifier(value.get("name"), f"{key}.name"),
        symbol_type=_validate_identifier(
            value.get("symbol_type"),
            f"{key}.symbol_type",
        ),
        tables=_validate_required_string_list(value.get("tables"), f"{key}.tables"),
        identity_columns=_validate_column_list(
            value.get("identity_columns"),
            f"{key}.identity_columns",
            required=True,
        ),
        file_patterns=_validate_sql_file_patterns(
            value.get("file_patterns", ()),
            f"{key}.file_patterns",
            required=False,
        ),
        default_column_order=_validate_column_list(
            value.get("default_column_order", ()),
            f"{key}.default_column_order",
        ),
        name_columns=_validate_column_list(
            value.get("name_columns", ()),
            f"{key}.name_columns",
        ),
        description_columns=_validate_column_list(
            value.get("description_columns", ()),
            f"{key}.description_columns",
        ),
        rule_columns=_validate_column_list(
            value.get("rule_columns", ()),
            f"{key}.rule_columns",
        ),
        formula_columns=_validate_column_list(
            value.get("formula_columns", ()),
            f"{key}.formula_columns",
        ),
        variable_columns=_validate_column_list(
            value.get("variable_columns", ()),
            f"{key}.variable_columns",
        ),
        parameter_columns=_validate_column_list(
            value.get("parameter_columns", ()),
            f"{key}.parameter_columns",
        ),
        mapping_columns=_validate_column_list(
            value.get("mapping_columns", ()),
            f"{key}.mapping_columns",
        ),
        reference_columns=_validate_reference_columns(
            value.get("reference_columns", ()),
            f"{key}.reference_columns",
        ),
        parent_columns=_validate_parent_columns(
            value.get("parent_columns", ()),
            f"{key}.parent_columns",
        ),
        sequence_columns=_validate_column_list(
            value.get("sequence_columns", ()),
            f"{key}.sequence_columns",
        ),
        status_columns=_validate_status_columns(
            value.get("status_columns", ()),
            f"{key}.status_columns",
        ),
        effective_from_columns=_validate_column_list(
            value.get("effective_from_columns", ()),
            f"{key}.effective_from_columns",
        ),
        effective_to_columns=_validate_column_list(
            value.get("effective_to_columns", ()),
            f"{key}.effective_to_columns",
        ),
        metadata_columns=_validate_column_list(
            value.get("metadata_columns", ()),
            f"{key}.metadata_columns",
        ),
    )


def _merge_section(
    value: object,
    section: str,
    defaults: dict[str, object],
    allowed_keys: frozenset[str],
) -> dict[str, object]:
    """Mezcla defaults y una seccion TOML RAG validando claves."""
    if value is None:
        raw_section: dict[str, object] = {}
    elif isinstance(value, dict):
        raw_section = value
    else:
        raise ConfigError(f"La seccion '{section}' debe ser una tabla TOML.")

    unknown_keys = sorted(set(raw_section) - allowed_keys)
    if unknown_keys:
        formatted = ", ".join(f"{section}.{key}" for key in unknown_keys)
        raise ConfigError(f"Claves de configuracion desconocidas: {formatted}.")
    return {**defaults, **raw_section}


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


def _validate_bool(value: object, key: str) -> bool:
    """Valida un booleano TOML estricto."""
    if not isinstance(value, bool):
        raise ConfigError(f"La clave '{key}' debe ser booleana.")
    return value


def _validate_optional_bool(value: object, key: str) -> bool | None:
    """Valida un booleano TOML opcional."""
    if value is None:
        return None
    return _validate_bool(value, key)


def _validate_optional_positive_int(value: object, key: str) -> int | None:
    """Valida un entero positivo TOML opcional."""
    if value is None:
        return None
    return _validate_int_range(value, key, minimum=1)


def _validate_float(value: object, key: str) -> float:
    """Valida un numero real TOML."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"La clave '{key}' debe ser un numero.")
    return float(value)


def _validate_unit_float(value: object, key: str) -> float:
    """Valida un flotante entre 0 y 1 inclusivo."""
    number = _validate_float(value, key)
    if not 0 <= number <= 1:
        raise ConfigError(f"La clave '{key}' debe estar entre 0 y 1.")
    return number


def _validate_choice(value: object, key: str, allowed: frozenset[str] | set[str]) -> str:
    """Valida una cadena contra un conjunto de opciones."""
    normalized = _require_non_empty_string(value, key).lower()
    if normalized not in allowed:
        formatted = ", ".join(sorted(allowed))
        raise ConfigError(f"La clave '{key}' debe ser uno de estos valores: {formatted}.")
    return normalized


def _validate_identifier(value: object, key: str) -> str:
    """Valida identificadores simples para prefijos de tablas locales."""
    identifier = _require_non_empty_string(value, key)
    if (
        not (identifier[0].isalpha() or identifier[0] == "_")
        or any(not (character.isalnum() or character == "_") for character in identifier)
    ):
        raise ConfigError(
            f"La clave '{key}' debe ser un identificador compuesto por letras, "
            "numeros o guion bajo, y no debe iniciar con numero."
        )
    return identifier


def _validate_required_string_list(value: object, key: str) -> tuple[str, ...]:
    """Valida una lista no vacia de cadenas y elimina duplicados."""
    items = _validate_string_list(value, key)
    if not items:
        raise ConfigError(f"La clave '{key}' debe contener al menos un valor.")
    return tuple(dict.fromkeys(items))


def _validate_column_list(
    value: object,
    key: str,
    *,
    required: bool = False,
) -> tuple[str, ...]:
    """Valida una lista de columnas declarativas."""
    columns = _validate_string_list(value, key)
    if required and not columns:
        raise ConfigError(f"La clave '{key}' debe contener al menos una columna.")
    return tuple(dict.fromkeys(columns))


def _validate_sql_file_patterns(
    value: object,
    key: str,
    *,
    required: bool,
) -> tuple[str, ...]:
    """Valida patrones destinados a DML contenido en archivos `.sql`."""
    patterns = _validate_string_list(value, key)
    if required and not patterns:
        raise ConfigError(f"La clave '{key}' debe contener al menos un patron .sql.")

    for pattern in patterns:
        normalized = pattern.lower()
        if ".dml" in normalized:
            raise ConfigError(
                f"La clave '{key}' no debe incluir archivos .dml; "
                "data-driven analiza DML dentro de archivos .sql."
            )
        if not normalized.endswith(".sql"):
            raise ConfigError(f"La clave '{key}' debe apuntar a archivos .sql.")
    return tuple(dict.fromkeys(patterns))


def _validate_reference_columns(
    value: object,
    key: str,
) -> tuple[DataDrivenReferenceColumn, ...]:
    """Valida columnas que producen referencias explicitas.

    `relation_type = "precedes"` solo declara una relacion cuando la columna
    identifica el destino; las columnas de orden se validan como metadata.
    """
    if not isinstance(value, (list, tuple)):
        raise ConfigError(f"La clave '{key}' debe ser una lista.")

    references: list[DataDrivenReferenceColumn] = []
    for index, item in enumerate(value, start=1):
        item_key = f"{key}[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(f"La clave '{item_key}' debe ser una tabla TOML.")
        unknown_keys = sorted(set(item) - _ALLOWED_REFERENCE_COLUMN_KEYS)
        if unknown_keys:
            formatted = ", ".join(f"{item_key}.{unknown}" for unknown in unknown_keys)
            raise ConfigError(f"Claves de configuracion desconocidas: {formatted}.")

        target_technology = item.get("target_technology")
        target_configuration = item.get("target_configuration")
        if target_technology is None and target_configuration is None:
            raise ConfigError(
                f"La clave '{item_key}' debe indicar target_technology "
                "o target_configuration."
            )

        references.append(
            DataDrivenReferenceColumn(
                column=_require_non_empty_string(
                    item.get("column"),
                    f"{item_key}.column",
                ),
                target_technology=(
                    _validate_choice(
                        target_technology,
                        f"{item_key}.target_technology",
                        _DATA_DRIVEN_TARGET_TECHNOLOGIES,
                    )
                    if target_technology is not None
                    else None
                ),
                target_type=(
                    _validate_identifier(item["target_type"], f"{item_key}.target_type")
                    if "target_type" in item
                    else None
                ),
                target_configuration=(
                    _validate_identifier(
                        target_configuration,
                        f"{item_key}.target_configuration",
                    )
                    if target_configuration is not None
                    else None
                ),
                relation_type=(
                    _validate_choice(
                        item["relation_type"],
                        f"{item_key}.relation_type",
                        _DATA_DRIVEN_REFERENCE_RELATION_TYPES,
                    )
                    if "relation_type" in item
                    else None
                ),
            )
        )
    return tuple(references)


def _validate_parent_columns(
    value: object,
    key: str,
) -> tuple[DataDrivenParentColumn, ...]:
    """Valida columnas de jerarquia entre registros de configuracion."""
    if not isinstance(value, (list, tuple)):
        raise ConfigError(f"La clave '{key}' debe ser una lista.")

    parents: list[DataDrivenParentColumn] = []
    for index, item in enumerate(value, start=1):
        item_key = f"{key}[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(f"La clave '{item_key}' debe ser una tabla TOML.")
        unknown_keys = sorted(set(item) - _ALLOWED_PARENT_COLUMN_KEYS)
        if unknown_keys:
            formatted = ", ".join(f"{item_key}.{unknown}" for unknown in unknown_keys)
            raise ConfigError(f"Claves de configuracion desconocidas: {formatted}.")
        parents.append(
            DataDrivenParentColumn(
                column=_require_non_empty_string(
                    item.get("column"),
                    f"{item_key}.column",
                ),
                target_configuration=_validate_identifier(
                    item.get("target_configuration"),
                    f"{item_key}.target_configuration",
                ),
            )
        )
    return tuple(parents)


def _validate_status_columns(
    value: object,
    key: str,
) -> tuple[DataDrivenStatusColumn, ...]:
    """Valida columnas de estado data-driven."""
    if not isinstance(value, (list, tuple)):
        raise ConfigError(f"La clave '{key}' debe ser una lista.")

    statuses: list[DataDrivenStatusColumn] = []
    for index, item in enumerate(value, start=1):
        item_key = f"{key}[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(f"La clave '{item_key}' debe ser una tabla TOML.")
        unknown_keys = sorted(set(item) - _ALLOWED_STATUS_COLUMN_KEYS)
        if unknown_keys:
            formatted = ", ".join(f"{item_key}.{unknown}" for unknown in unknown_keys)
            raise ConfigError(f"Claves de configuracion desconocidas: {formatted}.")
        statuses.append(
            DataDrivenStatusColumn(
                column=_require_non_empty_string(
                    item.get("column"),
                    f"{item_key}.column",
                ),
                active_values=_validate_required_string_list(
                    item.get("active_values"),
                    f"{item_key}.active_values",
                ),
                inactive_values=_validate_required_string_list(
                    item.get("inactive_values"),
                    f"{item_key}.inactive_values",
                ),
            )
        )
    return tuple(statuses)


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
