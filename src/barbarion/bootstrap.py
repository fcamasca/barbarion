"""Inicialización segura de los directorios locales de Barbarion."""

import tempfile
from dataclasses import dataclass
from pathlib import Path

from barbarion.config import Settings


@dataclass(frozen=True, slots=True)
class DirectoryResult:
    """Resultado de crear y comprobar un directorio único."""

    roles: tuple[str, ...]
    path: Path
    success: bool
    detail: str


def initialize_directories(settings: Settings) -> tuple[DirectoryResult, ...]:
    """Crea y comprueba las rutas configuradas sin imprimir resultados."""
    targets = _unique_targets(settings)
    return tuple(
        _initialize_directory(path, tuple(roles))
        for path, roles in targets.items()
    )


def _unique_targets(settings: Settings) -> dict[Path, list[str]]:
    """Agrupa roles que apuntan al mismo directorio conservando el orden."""
    targets: dict[Path, list[str]] = {}
    configured_paths = (
        ("data", settings.data_dir),
        ("output", settings.output_dir),
        ("logs", settings.logs_dir),
        ("database", settings.database_path.parent),
    )

    for role, configured_path in configured_paths:
        path = configured_path.resolve(strict=False)
        targets.setdefault(path, []).append(role)
    return targets


def _initialize_directory(path: Path, roles: tuple[str, ...]) -> DirectoryResult:
    """Inicializa un directorio y confirma que admite escritura temporal."""
    try:
        if path.exists() and not path.is_dir():
            return DirectoryResult(
                roles=roles,
                path=path,
                success=False,
                detail=f"La ruta '{path}' existe, pero no es un directorio.",
            )

        path.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=path) as probe:
            probe.write(b"barbarion")
            probe.flush()
    except OSError as error:
        return DirectoryResult(
            roles=roles,
            path=path,
            success=False,
            detail=f"No se puede preparar el directorio '{path}': {error}.",
        )

    return DirectoryResult(
        roles=roles,
        path=path,
        success=True,
        detail=f"Directorio disponible: '{path}'.",
    )
