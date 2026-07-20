"""Pruebas del editor atomico de `[llm].model`."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from barbarion.config import load_settings
from barbarion.infrastructure.model_config import (
    MODEL_CONFIG_NOT_EDITABLE,
    ModelConfigEditError,
    TomlLlmModelEditor,
)


SIMPLE_CONFIG = """domain = "synthetic"
data_dir = "./data"

[llm]
provider = "ollama"
model = "modelo-anterior:tag" # conservar comentario
timeout_seconds = 120.0
temperature = 0.1

[rag]
context_token_budget = 6000
"""


def _config(tmp_path: Path, content: str = SIMPLE_CONFIG) -> Path:
    path = tmp_path / "barbarion.toml"
    path.write_text(content, encoding="utf-8", newline="")
    return path


def test_editor_changes_only_model_assignment_and_preserves_bytes(
    tmp_path: Path,
) -> None:
    source = _config(tmp_path)
    before = source.read_bytes()
    settings = load_settings(source, environ={}, cwd=tmp_path)

    result = TomlLlmModelEditor().edit(settings, "modelo-nuevo:tag")

    after = source.read_bytes()
    assert result.previous_model == "modelo-anterior:tag"
    assert result.new_model == "modelo-nuevo:tag"
    assert result.changed is True
    assert result.dry_run is False
    assert after == before.replace(
        b'model = "modelo-anterior:tag"',
        b'model = "modelo-nuevo:tag"',
    )
    assert load_settings(source, environ={}, cwd=tmp_path).llm.model == (
        "modelo-nuevo:tag"
    )
    assert not tuple(tmp_path.glob(".barbarion.toml.*.tmp"))


def test_editor_preserves_crlf_and_escapes_toml_string(tmp_path: Path) -> None:
    content = SIMPLE_CONFIG.replace("\n", "\r\n")
    source = _config(tmp_path, content)
    settings = load_settings(source, environ={}, cwd=tmp_path)

    TomlLlmModelEditor().edit(settings, 'modelo-"especial":tag')

    raw = source.read_bytes()
    assert b"\r\n" in raw
    assert b'model = "modelo-\\\"especial\\\":tag"' in raw
    assert load_settings(source, environ={}, cwd=tmp_path).llm.model == (
        'modelo-"especial":tag'
    )


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    source = _config(tmp_path)
    before = source.read_bytes()
    settings = load_settings(source, environ={}, cwd=tmp_path)

    result = TomlLlmModelEditor().edit(
        settings,
        "modelo-nuevo",
        dry_run=True,
    )

    assert result.changed is True
    assert result.dry_run is True
    assert source.read_bytes() == before
    assert not tuple(tmp_path.glob(".*.tmp"))


def test_same_model_is_successful_noop(tmp_path: Path) -> None:
    source = _config(tmp_path)
    settings = load_settings(source, environ={}, cwd=tmp_path)

    result = TomlLlmModelEditor().edit(settings, settings.llm.model)

    assert result.changed is False
    assert source.read_text(encoding="utf-8") == SIMPLE_CONFIG


def test_editor_rejects_default_only_configuration(tmp_path: Path) -> None:
    settings = load_settings(environ={}, cwd=tmp_path)

    with pytest.raises(ModelConfigEditError, match="valores predeterminados") as error:
        TomlLlmModelEditor().edit(settings, "modelo")

    assert error.value.code == MODEL_CONFIG_NOT_EDITABLE


@pytest.mark.parametrize(
    "content",
    [
        'domain = "synthetic"\n',
        SIMPLE_CONFIG + '\n[llm]\nmodel = "duplicado"\n',
        SIMPLE_CONFIG.replace(
            'model = "modelo-anterior:tag" # conservar comentario',
            'model = """modelo-anterior:tag"""',
        ),
        SIMPLE_CONFIG.replace(
            'model = "modelo-anterior:tag" # conservar comentario',
            'model = "modelo-anterior:tag"\nmodel = "duplicado"',
        ),
    ],
)
def test_editor_rejects_unsupported_toml_shapes(
    tmp_path: Path,
    content: str,
) -> None:
    source = _config(tmp_path)
    settings = load_settings(source, environ={}, cwd=tmp_path)
    source.write_text(content, encoding="utf-8", newline="")
    before = source.read_bytes()

    with pytest.raises(ModelConfigEditError):
        TomlLlmModelEditor().edit(settings, "modelo-nuevo")

    assert source.read_bytes() == before


def test_editor_rejects_invalid_encoding(tmp_path: Path) -> None:
    source = _config(tmp_path)
    settings = load_settings(source, environ={}, cwd=tmp_path)
    source.write_bytes(b"[llm]\nmodel = \"\xff\"\n")

    with pytest.raises(ModelConfigEditError, match="UTF-8"):
        TomlLlmModelEditor().edit(settings, "modelo-nuevo")


def test_editor_detects_loaded_model_mismatch(tmp_path: Path) -> None:
    source = _config(tmp_path)
    settings = load_settings(source, environ={}, cwd=tmp_path)
    source.write_text(
        SIMPLE_CONFIG.replace("modelo-anterior:tag", "cambio-externo"),
        encoding="utf-8",
    )

    with pytest.raises(ModelConfigEditError, match="no coincide"):
        TomlLlmModelEditor().edit(settings, "modelo-nuevo")


def test_editor_detects_concurrent_change_and_cleans_temporary(
    tmp_path: Path,
) -> None:
    source = _config(tmp_path)
    settings = load_settings(source, environ={}, cwd=tmp_path)

    def change_source() -> None:
        source.write_text(SIMPLE_CONFIG + "# cambio externo\n", encoding="utf-8")

    with pytest.raises(ModelConfigEditError, match="cambio durante"):
        TomlLlmModelEditor().edit(
            settings,
            "modelo-nuevo",
            _before_replace=change_source,
        )

    assert source.read_text(encoding="utf-8").endswith("# cambio externo\n")
    assert not tuple(tmp_path.glob(".barbarion.toml.*.tmp"))


def test_editor_preserves_original_when_atomic_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _config(tmp_path)
    before = source.read_bytes()
    settings = load_settings(source, environ={}, cwd=tmp_path)

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("fallo sintetico")

    monkeypatch.setattr(
        "barbarion.infrastructure.model_config.os.replace",
        fail_replace,
    )

    with pytest.raises(ModelConfigEditError, match="atomicamente"):
        TomlLlmModelEditor().edit(settings, "modelo-nuevo")

    assert source.read_bytes() == before
    assert not tuple(tmp_path.glob(".barbarion.toml.*.tmp"))


def test_editor_rejects_control_characters(tmp_path: Path) -> None:
    source = _config(tmp_path)
    settings = load_settings(source, environ={}, cwd=tmp_path)

    with pytest.raises(ModelConfigEditError, match="caracteres de control"):
        TomlLlmModelEditor().edit(settings, "modelo\nnuevo")


def test_editor_rejects_symlink_when_supported(tmp_path: Path) -> None:
    target = _config(tmp_path)
    link = tmp_path / "linked.toml"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("El entorno no permite crear symlinks.")
    settings = replace(
        load_settings(target, environ={}, cwd=tmp_path),
        config_source=link,
    )

    with pytest.raises(ModelConfigEditError, match="enlace simbolico"):
        TomlLlmModelEditor().edit(settings, "modelo-nuevo")
