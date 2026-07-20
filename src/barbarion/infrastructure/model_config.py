"""Edicion acotada y atomica del modelo LLM en la configuracion TOML."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from barbarion.config import ConfigError, Settings, load_settings


MODEL_CONFIG_NOT_EDITABLE = "MODEL_CONFIG_NOT_EDITABLE"

_LLM_SECTION = re.compile(r"^\s*\[llm\]\s*(?:#.*)?(?:\r?\n|\r)?$")
_ANY_SECTION = re.compile(r"^\s*\[\[?[^\]]+\]\]?\s*(?:#.*)?(?:\r?\n|\r)?$")
_MODEL_KEY = re.compile(r"^\s*model\s*=")
_SIMPLE_MODEL = re.compile(
    r"^(?P<prefix>\s*model\s*=\s*)"
    r"(?P<value>\"(?:[^\"\\]|\\.)*\"|'[^']*')"
    r"(?P<suffix>\s*(?:#.*)?(?:\r?\n|\r)?)$"
)


class ModelConfigEditError(RuntimeError):
    """Error estable cuando el TOML no cumple el contrato editable."""

    code = MODEL_CONFIG_NOT_EDITABLE

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"{self.code}: {detail}")


@dataclass(frozen=True, slots=True)
class LlmModelConfigChange:
    """Resumen seguro del cambio previsto o aplicado."""

    config_path: Path
    previous_model: str
    new_model: str
    changed: bool
    dry_run: bool


@dataclass(frozen=True, slots=True)
class TomlLlmModelEditor:
    """Cambia solo `[llm].model` sin reserializar el documento completo."""

    def edit(
        self,
        settings: Settings,
        new_model: str,
        *,
        dry_run: bool = False,
        _before_replace: Callable[[], None] | None = None,
    ) -> LlmModelConfigChange:
        """Valida, previsualiza o aplica un reemplazo atomico.

        `_before_replace` es un seam de prueba para simular cambios concurrentes
        o fallas justo antes de publicar el temporal.
        """
        normalized_model = _validate_model_name(new_model)
        source = _editable_source(settings)
        original = _read_bytes(source)
        updated = _replace_model_assignment(
            original,
            expected_model=settings.llm.model,
            new_model=normalized_model,
        )
        change = LlmModelConfigChange(
            config_path=source,
            previous_model=settings.llm.model,
            new_model=normalized_model,
            changed=updated != original,
            dry_run=dry_run,
        )
        if dry_run or not change.changed:
            return change

        temporary = _write_validated_temporary(source, updated, normalized_model)
        try:
            if _before_replace is not None:
                _before_replace()
            current = _read_bytes(source)
            if not _same_content(current, original):
                raise ModelConfigEditError(
                    "El archivo cambio durante la operacion; no se reemplazo."
                )
            os.replace(temporary, source)
        except ModelConfigEditError:
            raise
        except OSError as error:
            raise ModelConfigEditError(
                f"No se pudo reemplazar atomicamente '{source}'."
            ) from error
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        return change


def _editable_source(settings: Settings) -> Path:
    source = settings.config_source
    if source is None:
        raise ModelConfigEditError(
            "La configuracion usa valores predeterminados; indique un TOML activo."
        )
    candidate = Path(source).expanduser()
    if candidate.is_symlink():
        raise ModelConfigEditError(
            "No se edita una configuracion a traves de un enlace simbolico."
        )
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise ModelConfigEditError(
            f"El archivo de configuracion no existe: '{candidate}'."
        ) from error
    if not resolved.is_file():
        raise ModelConfigEditError(
            f"La configuracion efectiva no es un archivo: '{resolved}'."
        )
    return resolved


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise ModelConfigEditError(
            f"No se pudo leer el archivo de configuracion '{path}'."
        ) from error


def _replace_model_assignment(
    raw: bytes,
    *,
    expected_model: str,
    new_model: str,
) -> bytes:
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ModelConfigEditError(
            "El archivo de configuracion debe usar UTF-8 valido."
        ) from error
    lines = content.splitlines(keepends=True)
    section_indexes = [
        index for index, line in enumerate(lines) if _LLM_SECTION.fullmatch(line)
    ]
    if len(section_indexes) != 1:
        raise ModelConfigEditError(
            "Se requiere una unica seccion simple [llm]."
        )
    start = section_indexes[0] + 1
    end = next(
        (
            index
            for index in range(start, len(lines))
            if _ANY_SECTION.fullmatch(lines[index])
        ),
        len(lines),
    )
    model_indexes = [
        index for index in range(start, end) if _MODEL_KEY.match(lines[index])
    ]
    if len(model_indexes) != 1:
        raise ModelConfigEditError(
            "Se requiere una unica asignacion model dentro de [llm]."
        )
    model_index = model_indexes[0]
    match = _SIMPLE_MODEL.fullmatch(lines[model_index])
    if match is None:
        raise ModelConfigEditError(
            "[llm].model debe ser una cadena TOML simple de una sola linea."
        )
    try:
        parsed_current = _parse_toml_string(match.group("value"))
    except (ConfigError, ValueError) as error:
        raise ModelConfigEditError(
            "No se pudo interpretar la asignacion [llm].model."
        ) from error
    if parsed_current != expected_model:
        raise ModelConfigEditError(
            "El modelo del archivo no coincide con la configuracion cargada."
        )
    replacement = (
        match.group("prefix")
        + json.dumps(new_model, ensure_ascii=False)
        + match.group("suffix")
    )
    lines[model_index] = replacement
    return "".join(lines).encode("utf-8")


def _parse_toml_string(literal: str) -> str:
    import tomllib

    parsed = tomllib.loads(f"model = {literal}\n")
    value = parsed.get("model")
    if not isinstance(value, str):
        raise ValueError("model no es texto.")
    return value


def _write_validated_temporary(
    source: Path,
    content: bytes,
    expected_model: str,
) -> Path:
    temporary_path: Path | None = None
    try:
        descriptor, raw_path = tempfile.mkstemp(
            dir=source.parent,
            prefix=f".{source.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(raw_path)
        with os.fdopen(descriptor, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary_path, stat.S_IMODE(source.stat().st_mode))
        validated = load_settings(
            temporary_path,
            environ={},
            cwd=source.parent,
        )
        if validated.llm.model != expected_model:
            raise ModelConfigEditError(
                "El TOML temporal no conserva el modelo solicitado."
            )
        return temporary_path
    except ModelConfigEditError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
    except (ConfigError, OSError) as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise ModelConfigEditError(
            "No se pudo crear y validar el TOML temporal."
        ) from error


def _validate_model_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModelConfigEditError("El nombre del modelo no puede estar vacio.")
    normalized = value.strip()
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise ModelConfigEditError(
            "El nombre del modelo contiene caracteres de control."
        )
    return normalized


def _same_content(current: bytes, expected: bytes) -> bool:
    return hashlib.sha256(current).digest() == hashlib.sha256(expected).digest()
