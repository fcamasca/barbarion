"""Pruebas de carga y validación de configuración."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from barbarion.config import (
    ConfigError,
    DataDrivenConfiguration,
    DataDrivenParentColumn,
    DataDrivenReferenceColumn,
    DataDrivenSettings,
    DataDrivenStatusColumn,
    EmbeddingsSettings,
    IngestionSettings,
    LlmSettings,
    RagSettings,
    RetrievalSettings,
    Settings,
    VectorStoreSettings,
    load_settings,
)


def write_config(path: Path, content: str) -> Path:
    """Escribe un TOML de prueba y devuelve su ruta."""
    path.write_text(content, encoding="utf-8")
    return path


def test_defaults_are_resolved_from_working_directory(tmp_path: Path) -> None:
    settings = load_settings(environ={}, cwd=tmp_path)

    assert settings == Settings(
        domain="default",
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        logs_dir=tmp_path / "logs",
        database_path=tmp_path / "data" / "barbarion.db",
        log_level="INFO",
        ollama_url="http://127.0.0.1:11434",
        ollama_timeout_seconds=2.0,
            ingestion=IngestionSettings(
                paths=(tmp_path / "sources",),
            extensions=(
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
            chunk_size=4000,
            chunk_overlap=400,
            ignore_patterns=(
                ".git/**",
                ".barbarion/**",
                ".venv/**",
                "**/__pycache__/**",
                "data/**",
                "output/**",
                "logs/**",
                "**/node_modules/**",
            ),
            max_file_size_mb=50,
            max_extracted_chars=5_000_000,
            max_pdf_pages=1000,
            encodings=("utf-8", "cp1252", "iso8859-1"),
        ),
        embeddings=EmbeddingsSettings(
            provider="ollama",
            model="nomic-embed-text",
            batch_size=16,
            timeout_seconds=60.0,
            normalize=True,
        ),
        vector_store=VectorStoreSettings(
            provider="sqlite_vec",
            table_prefix="rag",
            distance="cosine",
        ),
        retrieval=RetrievalSettings(
            mode="hybrid",
            top_k=10,
            candidate_k=40,
            similarity_threshold=0.20,
            vector_weight=0.70,
            keyword_weight=0.30,
        ),
        rag=RagSettings(
            context_token_budget=6000,
            max_chunk_tokens=1200,
            dedupe_min_hash_prefix=16,
            include_snippets=True,
        ),
        llm=LlmSettings(
            provider="ollama",
            model="llama3.1:8b",
            timeout_seconds=120.0,
            temperature=0.1,
        ),
        data_driven=DataDrivenSettings(
            enabled=False,
            file_patterns=(),
            max_statements_per_file=10_000,
            max_literal_chars=200_000,
            token_patterns=(
                r"\{([A-Za-z_][A-Za-z0-9_]*)\}",
                r"\$\{([^}]+)\}",
                r":([A-Za-z_][A-Za-z0-9_]*)",
            ),
            configurations=(),
        ),
        config_source=None,
    )
    assert list(tmp_path.iterdir()) == []


def test_implicit_file_resolves_paths_from_its_directory(tmp_path: Path) -> None:
    source = write_config(
        tmp_path / "barbarion.toml",
        'domain = "legacy"\ndata_dir = "./local-data"\n',
    )

    settings = load_settings(environ={}, cwd=tmp_path)

    assert settings.domain == "legacy"
    assert settings.data_dir == tmp_path / "local-data"
    assert settings.config_source == source


def test_environment_file_precedes_implicit_file(tmp_path: Path) -> None:
    write_config(tmp_path / "barbarion.toml", 'domain = "implicit"\n')
    environment_file = write_config(
        tmp_path / "environment.toml",
        'domain = "environment"\n',
    )

    settings = load_settings(
        environ={"BARBARION_CONFIG": str(environment_file)},
        cwd=tmp_path,
    )

    assert settings.domain == "environment"
    assert settings.config_source == environment_file


def test_explicit_file_has_highest_precedence(tmp_path: Path) -> None:
    write_config(tmp_path / "barbarion.toml", 'domain = "implicit"\n')
    environment_file = write_config(
        tmp_path / "environment.toml",
        'domain = "environment"\n',
    )
    explicit_file = write_config(
        tmp_path / "explicit.toml",
        'domain = "explicit"\n',
    )

    settings = load_settings(
        explicit_file,
        environ={"BARBARION_CONFIG": str(environment_file)},
        cwd=tmp_path,
    )

    assert settings.domain == "explicit"
    assert settings.config_source == explicit_file


@pytest.mark.parametrize(
    ("config_path", "environ", "origin"),
    [
        ("missing.toml", {}, "--config"),
        (None, {"BARBARION_CONFIG": "missing.toml"}, "BARBARION_CONFIG"),
    ],
)
def test_missing_explicit_source_is_an_error(
    config_path: str | None,
    environ: dict[str, str],
    origin: str,
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigError, match=origin):
        load_settings(config_path, environ=environ, cwd=tmp_path)


def test_invalid_toml_is_rejected(tmp_path: Path) -> None:
    source = write_config(tmp_path / "invalid.toml", "domain = [")

    with pytest.raises(ConfigError, match="no es valido"):
        load_settings(source, environ={}, cwd=tmp_path)


@pytest.mark.parametrize(
    "content",
    [
        'unknown = "value"\n',
    ],
)
def test_unknown_keys_and_future_sections_are_rejected(
    content: str,
    tmp_path: Path,
) -> None:
    source = write_config(tmp_path / "unknown.toml", content)

    with pytest.raises(ConfigError, match="desconocidas"):
        load_settings(source, environ={}, cwd=tmp_path)


def test_unknown_ingestion_keys_are_rejected(tmp_path: Path) -> None:
    source = write_config(
        tmp_path / "unknown-ingestion.toml",
        "[ingestion]\nenabled = true\n",
    )

    with pytest.raises(ConfigError, match="ingestion.enabled"):
        load_settings(source, environ={}, cwd=tmp_path)


@pytest.mark.parametrize(
    ("section", "content", "expected_message"),
    [
        ("embeddings", "[embeddings]\nunknown = true\n", "embeddings.unknown"),
        ("vector_store", "[vector_store]\nunknown = true\n", "vector_store.unknown"),
        ("retrieval", "[retrieval]\nunknown = true\n", "retrieval.unknown"),
        ("rag", "[rag]\nunknown = true\n", "rag.unknown"),
        ("llm", "[llm]\nunknown = true\n", "llm.unknown"),
    ],
)
def test_unknown_h3_section_keys_are_rejected(
    section: str,
    content: str,
    expected_message: str,
    tmp_path: Path,
) -> None:
    del section
    source = write_config(tmp_path / "unknown-rag.toml", content)

    with pytest.raises(ConfigError, match=expected_message):
        load_settings(source, environ={}, cwd=tmp_path)


@pytest.mark.parametrize(
    ("content", "expected_message"),
    [
        ('domain = "  "\n', "domain"),
        ('data_dir = 42\n', "data_dir"),
        ('log_level = "verbose"\n', "log_level"),
        ('ollama_timeout_seconds = true\n', "debe ser un numero"),
        ('ollama_timeout_seconds = 0\n', "mayor que 0"),
        ('ollama_timeout_seconds = 11\n', "menor o igual que 10"),
        ('ollama_url = "ftp://localhost"\n', "HTTP"),
        ('ollama_url = "http://user:secret@localhost"\n', "credenciales"),
        ('ollama_url = "http://localhost?secret=value"\n', "query"),
    ],
)
def test_invalid_values_are_rejected(
    content: str,
    expected_message: str,
    tmp_path: Path,
) -> None:
    source = write_config(tmp_path / "invalid-value.toml", content)

    with pytest.raises(ConfigError, match=expected_message):
        load_settings(source, environ={}, cwd=tmp_path)


def test_values_are_normalized(tmp_path: Path) -> None:
    source = write_config(
        tmp_path / "normalized.toml",
        '\n'.join(
            [
                'domain = " legacy "',
                'log_level = "debug"',
                'ollama_url = "http://localhost:11434/"',
                'ollama_timeout_seconds = 3',
            ]
        ),
    )

    settings = load_settings(source, environ={}, cwd=tmp_path)

    assert settings.domain == "legacy"
    assert settings.log_level == "DEBUG"
    assert settings.ollama_url == "http://localhost:11434"
    assert settings.ollama_timeout_seconds == 3.0


def test_ingestion_values_are_resolved_from_config_directory(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    source = write_config(
        config_dir / "settings.toml",
        "\n".join(
            [
                "[ingestion]",
                'paths = ["../src-a", "src-b"]',
                'extensions = ["SQL", ".PkB", "sql"]',
                "chunk_size = 1200",
                "chunk_overlap = 1199",
                'ignore_patterns = ["build/**", "tmp/**"]',
                "max_file_size_mb = 12",
                "max_extracted_chars = 1200",
                "max_pdf_pages = 25",
                'encodings = ["utf-8", "latin-1", "utf8"]',
            ]
        ),
    )

    settings = load_settings(source, environ={}, cwd=tmp_path)

    assert settings.ingestion.paths == (
        tmp_path / "src-a",
        config_dir / "src-b",
    )
    assert settings.ingestion.extensions == (".sql", ".pkb")
    assert settings.ingestion.chunk_size == 1200
    assert settings.ingestion.chunk_overlap == 1199
    assert settings.ingestion.ignore_patterns == ("build/**", "tmp/**")
    assert settings.ingestion.max_file_size_mb == 12
    assert settings.ingestion.max_extracted_chars == 1200
    assert settings.ingestion.max_pdf_pages == 25
    assert settings.ingestion.encodings == ("utf-8", "iso8859-1")
    assert list(config_dir.iterdir()) == [source]


@pytest.mark.parametrize(
    ("content", "expected_message"),
    [
        ("[ingestion]\npaths = []\n", "paths"),
        ('[ingestion]\npaths = ["ok", 1]\n', "paths"),
        ('[ingestion]\nextensions = []\n', "extensions"),
        ('[ingestion]\nextensions = ["."]\n', "extension"),
        ("[ingestion]\nchunk_size = 499\n", "chunk_size"),
        ("[ingestion]\nchunk_size = 100001\n", "chunk_size"),
        ("[ingestion]\nchunk_size = 500\nchunk_overlap = 500\n", "chunk_overlap"),
        ("[ingestion]\nchunk_overlap = -1\n", "chunk_overlap"),
        ("[ingestion]\nmax_file_size_mb = 0\n", "max_file_size_mb"),
        ("[ingestion]\nmax_file_size_mb = 1025\n", "max_file_size_mb"),
        (
            "[ingestion]\nchunk_size = 1000\nmax_extracted_chars = 999\n",
            "max_extracted_chars",
        ),
        ("[ingestion]\nmax_pdf_pages = 0\n", "max_pdf_pages"),
        ('[ingestion]\nencodings = ["utf-8", "fake-encoding"]\n', "encoding"),
        ("ingestion = 42\n", "ingestion"),
    ],
)
def test_invalid_ingestion_values_are_rejected(
    content: str,
    expected_message: str,
    tmp_path: Path,
) -> None:
    source = write_config(tmp_path / "invalid-ingestion.toml", content)

    with pytest.raises(ConfigError, match=expected_message):
        load_settings(source, environ={}, cwd=tmp_path)


def test_h3_values_are_loaded_and_normalized(tmp_path: Path) -> None:
    source = write_config(
        tmp_path / "rag.toml",
        "\n".join(
            [
                "[embeddings]",
                'provider = "OLLAMA"',
                'model = "bge-small"',
                "batch_size = 8",
                "timeout_seconds = 30",
                "normalize = false",
                "[vector_store]",
                'provider = "SQLITE_VEC"',
                'table_prefix = "rag_test"',
                'distance = "COSINE"',
                "[retrieval]",
                'mode = "SEMANTIC"',
                "top_k = 5",
                "candidate_k = 25",
                "similarity_threshold = 0.15",
                "vector_weight = 1.0",
                "keyword_weight = 0.0",
                "[rag]",
                "context_token_budget = 2000",
                "max_chunk_tokens = 500",
                "dedupe_min_hash_prefix = 20",
                "include_snippets = false",
                "[llm]",
                'provider = "OLLAMA"',
                'model = "llama-local"',
                "timeout_seconds = 90",
                "temperature = 0.0",
                "think = false",
                "num_ctx = 16384",
            ]
        ),
    )

    settings = load_settings(source, environ={}, cwd=tmp_path)

    assert settings.embeddings == EmbeddingsSettings(
        provider="ollama",
        model="bge-small",
        batch_size=8,
        timeout_seconds=30.0,
        normalize=False,
    )
    assert settings.vector_store == VectorStoreSettings(
        provider="sqlite_vec",
        table_prefix="rag_test",
        distance="cosine",
    )
    assert settings.retrieval == RetrievalSettings(
        mode="semantic",
        top_k=5,
        candidate_k=25,
        similarity_threshold=0.15,
        vector_weight=1.0,
        keyword_weight=0.0,
    )
    assert settings.rag == RagSettings(
        context_token_budget=2000,
        max_chunk_tokens=500,
        dedupe_min_hash_prefix=20,
        include_snippets=False,
    )
    assert settings.llm == LlmSettings(
        provider="ollama",
        model="llama-local",
        timeout_seconds=90.0,
        temperature=0.0,
        think=False,
        num_ctx=16384,
    )


def test_llm_think_is_absent_by_default(tmp_path: Path) -> None:
    source = write_config(
        tmp_path / "llm-default.toml",
        '[llm]\nmodel = "modelo-local"\n',
    )

    settings = load_settings(source, environ={}, cwd=tmp_path)

    assert settings.llm.think is None
    assert settings.llm.num_ctx is None


@pytest.mark.parametrize(
    ("content", "expected_message"),
    [
        ("[embeddings]\nprovider = \"other\"\n", "embeddings.provider"),
        ("[embeddings]\nbatch_size = 0\n", "embeddings.batch_size"),
        ("[embeddings]\ntimeout_seconds = 0\n", "embeddings.timeout_seconds"),
        ("[embeddings]\nnormalize = \"yes\"\n", "embeddings.normalize"),
        ("[vector_store]\nprovider = \"qdrant_local\"\n", "vector_store.provider"),
        ("[vector_store]\ntable_prefix = \"1bad\"\n", "vector_store.table_prefix"),
        ("[vector_store]\ndistance = \"dot\"\n", "vector_store.distance"),
        ("[retrieval]\nmode = \"bad\"\n", "retrieval.mode"),
        ("[retrieval]\ntop_k = 0\n", "retrieval.top_k"),
        ("[retrieval]\ntop_k = 10\ncandidate_k = 5\n", "retrieval.candidate_k"),
        ("[retrieval]\nsimilarity_threshold = 2\n", "retrieval.similarity_threshold"),
        ("[retrieval]\nvector_weight = 0\nkeyword_weight = 0\n", "suma"),
        ("[rag]\ncontext_token_budget = 500\n", "rag.context_token_budget"),
        ("[rag]\ndedupe_min_hash_prefix = 7\n", "rag.dedupe_min_hash_prefix"),
        ("[rag]\ninclude_snippets = 1\n", "rag.include_snippets"),
        ("[llm]\nprovider = \"other\"\n", "llm.provider"),
        ("[llm]\ntimeout_seconds = 0\n", "llm.timeout_seconds"),
        ("[llm]\ntemperature = 2\n", "llm.temperature"),
        ("[llm]\nthink = \"false\"\n", "llm.think"),
        ("[llm]\nnum_ctx = 0\n", "llm.num_ctx"),
        ("[llm]\nnum_ctx = true\n", "llm.num_ctx"),
        ("embeddings = 1\n", "embeddings"),
    ],
)
def test_invalid_h3_values_are_rejected(
    content: str,
    expected_message: str,
    tmp_path: Path,
) -> None:
    source = write_config(tmp_path / "invalid-rag.toml", content)

    with pytest.raises(ConfigError, match=expected_message):
        load_settings(source, environ={}, cwd=tmp_path)


def test_data_driven_values_are_loaded(tmp_path: Path) -> None:
    source = write_config(
        tmp_path / "data-driven.toml",
        "\n".join(
            [
                "[data_driven]",
                "enabled = true",
                'file_patterns = ["config/**/*.sql"]',
                "max_statements_per_file = 2500",
                "max_literal_chars = 120000",
                "token_patterns = ['\\{([A-Z_]+)\\}', ':([A-Z_]+)']",
                "[[data_driven.configurations]]",
                'name = "pricing_rules"',
                'symbol_type = "configuration_record"',
                'tables = ["APP_CFG.PRICING_RULES"]',
                'identity_columns = ["RULE_ID"]',
                'file_patterns = ["config/pricing/**/*.sql"]',
                'default_column_order = ["RULE_ID", "RULE_NAME", "FORMULA"]',
                'name_columns = ["RULE_NAME"]',
                'description_columns = ["DESCRIPTION"]',
                'rule_columns = ["RULE_SQL"]',
                'formula_columns = ["FORMULA"]',
                'variable_columns = ["VARIABLE_NAME"]',
                'parameter_columns = ["PARAMETER_NAME"]',
                'mapping_columns = ["MAPPING_NAME"]',
                'reference_columns = [',
                '  { column = "FUNCTION_NAME", target_technology = "oracle", target_type = "function" },',
                '  { column = "NEXT_RULE_ID", target_configuration = "pricing_rules", relation_type = "precedes" }',
                "]",
                "parent_columns = [",
                '  { column = "PARENT_RULE_ID", target_configuration = "pricing_rules" }',
                "]",
                'sequence_columns = ["DISPLAY_ORDER"]',
                "status_columns = [",
                '  { column = "STATUS", active_values = ["A"], inactive_values = ["I"] }',
                "]",
                'effective_from_columns = ["VALID_FROM"]',
                'effective_to_columns = ["VALID_TO"]',
                'metadata_columns = ["CREATED_BY", "UPDATED_AT"]',
            ]
        ),
    )

    settings = load_settings(source, environ={}, cwd=tmp_path)

    assert settings.data_driven == DataDrivenSettings(
        enabled=True,
        file_patterns=("config/**/*.sql",),
        max_statements_per_file=2500,
        max_literal_chars=120000,
        token_patterns=(r"\{([A-Z_]+)\}", r":([A-Z_]+)"),
        configurations=(
            DataDrivenConfiguration(
                name="pricing_rules",
                symbol_type="configuration_record",
                tables=("APP_CFG.PRICING_RULES",),
                identity_columns=("RULE_ID",),
                file_patterns=("config/pricing/**/*.sql",),
                default_column_order=("RULE_ID", "RULE_NAME", "FORMULA"),
                name_columns=("RULE_NAME",),
                description_columns=("DESCRIPTION",),
                rule_columns=("RULE_SQL",),
                formula_columns=("FORMULA",),
                variable_columns=("VARIABLE_NAME",),
                parameter_columns=("PARAMETER_NAME",),
                mapping_columns=("MAPPING_NAME",),
                reference_columns=(
                    DataDrivenReferenceColumn(
                        column="FUNCTION_NAME",
                        target_technology="oracle",
                        target_type="function",
                    ),
                    DataDrivenReferenceColumn(
                        column="NEXT_RULE_ID",
                        target_configuration="pricing_rules",
                        relation_type="precedes",
                    ),
                ),
                parent_columns=(
                    DataDrivenParentColumn(
                        column="PARENT_RULE_ID",
                        target_configuration="pricing_rules",
                    ),
                ),
                sequence_columns=("DISPLAY_ORDER",),
                status_columns=(
                    DataDrivenStatusColumn(
                        column="STATUS",
                        active_values=("A",),
                        inactive_values=("I",),
                    ),
                ),
                effective_from_columns=("VALID_FROM",),
                effective_to_columns=("VALID_TO",),
                metadata_columns=("CREATED_BY", "UPDATED_AT"),
            ),
        ),
    )


@pytest.mark.parametrize(
    ("content", "expected_message"),
    [
        ("[data_driven]\nunknown = true\n", "data_driven.unknown"),
        ("[data_driven]\nenabled = \"yes\"\n", "data_driven.enabled"),
        (
            "[data_driven]\nenabled = true\nfile_patterns = []\n",
            "data_driven.file_patterns",
        ),
        (
            "\n".join(
                [
                    "[data_driven]",
                    "enabled = true",
                    'file_patterns = ["config/**/*.dml"]',
                    "[[data_driven.configurations]]",
                    'name = "pricing_rules"',
                    'symbol_type = "configuration_record"',
                    'tables = ["APP_CFG.PRICING_RULES"]',
                    'identity_columns = ["RULE_ID"]',
                ]
            ),
            ".dml",
        ),
        (
            "[data_driven]\nenabled = true\nfile_patterns = [\"config/**/*.sql\"]\n",
            "data_driven.configurations",
        ),
        (
            "\n".join(
                [
                    "[data_driven]",
                    "enabled = true",
                    'file_patterns = ["config/**/*.sql"]',
                    "[[data_driven.configurations]]",
                    'name = "pricing_rules"',
                    'symbol_type = "configuration_record"',
                    'tables = ["APP_CFG.PRICING_RULES"]',
                ]
            ),
            "identity_columns",
        ),
        (
            "\n".join(
                [
                    "[data_driven]",
                    "enabled = true",
                    'file_patterns = ["config/**/*.sql"]',
                    "[[data_driven.configurations]]",
                    'name = "pricing_rules"',
                    'symbol_type = "configuration_record"',
                    'tables = ["APP_CFG.PRICING_RULES"]',
                    'identity_columns = ["RULE_ID"]',
                    'reference_columns = [{ column = "NEXT_RULE_ID" }]',
                ]
            ),
            "target_technology",
        ),
        (
            "\n".join(
                [
                    "[data_driven]",
                    "enabled = true",
                    'file_patterns = ["config/**/*.sql"]',
                    "[[data_driven.configurations]]",
                    'name = "pricing_rules"',
                    'symbol_type = "configuration_record"',
                    'tables = ["APP_CFG.PRICING_RULES"]',
                    'identity_columns = ["RULE_ID"]',
                    "status_columns = [",
                    '  { column = "STATUS", active_values = [], inactive_values = ["I"] }',
                    "]",
                ]
            ),
            "active_values",
        ),
    ],
)
def test_invalid_data_driven_values_are_rejected(
    content: str,
    expected_message: str,
    tmp_path: Path,
) -> None:
    source = write_config(tmp_path / "invalid-data-driven.toml", content)

    with pytest.raises(ConfigError, match=expected_message):
        load_settings(source, environ={}, cwd=tmp_path)


def test_settings_are_immutable(tmp_path: Path) -> None:
    settings = load_settings(environ={}, cwd=tmp_path)

    with pytest.raises(FrozenInstanceError):
        settings.domain = "changed"  # type: ignore[misc]


def test_example_configuration_is_valid(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    example = project_root / "barbarion.example.toml"
    copied_example = tmp_path / "barbarion.toml"
    copied_example.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")

    settings = load_settings(copied_example, environ={}, cwd=tmp_path)

    assert settings.domain == "default"
    assert settings.data_dir == tmp_path / "data"
    assert settings.database_path == tmp_path / "data" / "barbarion.db"
    assert settings.ingestion.paths == (tmp_path / "sources",)
    assert settings.ingestion.extensions[:11] == (
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
    )
    assert settings.ingestion.max_file_size_mb == 50
    assert settings.ingestion.max_extracted_chars == 5_000_000
    assert settings.ingestion.max_pdf_pages == 1000
    assert settings.ingestion.encodings == ("utf-8", "cp1252", "iso8859-1")
    assert ".dml" not in settings.ingestion.extensions
    assert settings.vector_store.provider == "sqlite_vec"
    assert settings.embeddings.model == "nomic-embed-text"
    assert settings.retrieval.mode == "hybrid"
    assert settings.rag.context_token_budget == 6000
    assert settings.llm.provider == "ollama"
    assert settings.data_driven.enabled is False
    assert settings.data_driven.file_patterns == ("config/**/*.sql",)
    assert settings.data_driven.configurations[0].name == "pricing_rules"


def test_relative_explicit_source_is_resolved_from_cwd(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    source = write_config(
        config_dir / "settings.toml",
        'data_dir = "./relative-data"\n',
    )

    settings = load_settings(
        Path("config/settings.toml"),
        environ={},
        cwd=tmp_path,
    )

    assert settings.config_source == source
    assert settings.data_dir == config_dir / "relative-data"
