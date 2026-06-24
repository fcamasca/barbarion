"""Pruebas de carga y validación de configuración."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from barbarion.config import ConfigError, Settings, load_settings


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

    with pytest.raises(ConfigError, match="no es válido"):
        load_settings(source, environ={}, cwd=tmp_path)


@pytest.mark.parametrize(
    "content",
    [
        'unknown = "value"\n',
        '[ingestion]\nenabled = true\n',
    ],
)
def test_unknown_keys_and_future_sections_are_rejected(
    content: str,
    tmp_path: Path,
) -> None:
    source = write_config(tmp_path / "unknown.toml", content)

    with pytest.raises(ConfigError, match="desconocidas"):
        load_settings(source, environ={}, cwd=tmp_path)


@pytest.mark.parametrize(
    ("content", "expected_message"),
    [
        ('domain = "  "\n', "domain"),
        ('data_dir = 42\n', "data_dir"),
        ('log_level = "verbose"\n', "log_level"),
        ('ollama_timeout_seconds = true\n', "debe ser un número"),
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
