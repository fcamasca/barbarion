"""Comprobaciones estructuradas del entorno local de Barbarion."""

import json
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from barbarion.bootstrap import DirectoryResult
from barbarion.config import Settings
from barbarion.database import DatabaseError, DatabaseStatus, initialize_database

CheckStatus = Literal["PASS", "WARN", "FAIL"]


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Resultado individual mostrado posteriormente por la CLI."""

    name: str
    status: CheckStatus
    detail: str
    required: bool


@dataclass(frozen=True, slots=True)
class DoctorSummary:
    """Conteos y estado global de un diagnóstico."""

    pass_count: int
    warn_count: int
    fail_count: int
    success: bool


@dataclass(frozen=True, slots=True)
class DoctorReport:
    """Reporte completo sin responsabilidades de presentación."""

    checks: tuple[CheckResult, ...]
    summary: DoctorSummary

    @property
    def exit_code(self) -> int:
        """Devuelve el código correspondiente a checks requeridos."""
        return 0 if self.summary.success else 1


@dataclass(frozen=True, slots=True)
class OllamaProbeResult:
    """Resultado pequeño de consultar el endpoint local de Ollama."""

    available: bool
    detail: str


OllamaProbe = Callable[[str, float], OllamaProbeResult]
DatabaseInitializer = Callable[[Path], DatabaseStatus]

_DIRECTORY_CHECKS = (
    ("data", "Directorio de datos"),
    ("output", "Directorio de salida"),
    ("logs", "Directorio de logs"),
)


def run_doctor_checks(
    settings: Settings,
    directory_results: tuple[DirectoryResult, ...],
    *,
    ollama_probe: OllamaProbe | None = None,
    database_initializer: DatabaseInitializer = initialize_database,
    python_version: tuple[int, int, int] | None = None,
) -> DoctorReport:
    """Ejecuta los checks en orden estable y calcula el estado global."""
    effective_probe = probe_ollama if ollama_probe is None else ollama_probe
    effective_version = (
        (sys.version_info.major, sys.version_info.minor, sys.version_info.micro)
        if python_version is None
        else python_version
    )

    checks: list[CheckResult] = [
        _check_python(effective_version),
        _check_config(settings),
    ]
    checks.extend(_check_directories(directory_results))
    checks.append(
        _check_database(settings, directory_results, database_initializer)
    )
    checks.append(_check_ollama(settings, effective_probe))

    frozen_checks = tuple(checks)
    return DoctorReport(
        checks=frozen_checks,
        summary=_summarize(frozen_checks),
    )


def probe_ollama(url: str, timeout_seconds: float) -> OllamaProbeResult:
    """Consulta `/api/tags` y valida la respuesta mínima de Ollama."""
    endpoint = f"{url.rstrip('/')}/api/tags"
    request = urllib.request.Request(
        endpoint,
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            if response.status != 200:
                return OllamaProbeResult(
                    available=False,
                    detail=f"Ollama respondió HTTP {response.status} en {url}.",
                )
            payload = json.load(response)
    except (
        json.JSONDecodeError,
        OSError,
        TimeoutError,
        UnicodeDecodeError,
        urllib.error.URLError,
    ) as error:
        return OllamaProbeResult(
            available=False,
            detail=f"Ollama no está disponible en {url}: {error}.",
        )

    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        return OllamaProbeResult(
            available=False,
            detail=f"Ollama devolvió una respuesta no válida en {url}.",
        )
    return OllamaProbeResult(
        available=True,
        detail=f"Ollama está disponible en {url}.",
    )


def _check_python(version: tuple[int, int, int]) -> CheckResult:
    """Comprueba la versión mínima y máxima fijada por H1."""
    detail = ".".join(str(part) for part in version)
    if (3, 12) <= version[:2] < (3, 13):
        return CheckResult("Python", "PASS", detail, True)
    return CheckResult(
        "Python",
        "FAIL",
        f"Versión {detail}; Barbarion requiere Python >=3.12,<3.13.",
        True,
    )


def _check_config(settings: Settings) -> CheckResult:
    """Describe el origen de una configuración ya validada."""
    source = (
        str(settings.config_source)
        if settings.config_source is not None
        else "valores predeterminados"
    )
    return CheckResult("Configuración", "PASS", source, True)


def _check_directories(
    directory_results: tuple[DirectoryResult, ...],
) -> tuple[CheckResult, ...]:
    """Convierte los resultados únicos en checks visibles por rol."""
    return tuple(
        _check_directory_role(role, name, directory_results)
        for role, name in _DIRECTORY_CHECKS
    )


def _check_directory_role(
    role: str,
    name: str,
    directory_results: tuple[DirectoryResult, ...],
) -> CheckResult:
    """Busca y representa el resultado de un rol de directorio."""
    result = _result_for_role(role, directory_results)
    if result is None:
        return CheckResult(
            name,
            "FAIL",
            f"No existe resultado de inicialización para el rol '{role}'.",
            True,
        )
    return CheckResult(
        name,
        "PASS" if result.success else "FAIL",
        str(result.path) if result.success else result.detail,
        True,
    )


def _check_database(
    settings: Settings,
    directory_results: tuple[DirectoryResult, ...],
    initializer: DatabaseInitializer,
) -> CheckResult:
    """Inicializa SQLite solo si su directorio está disponible."""
    parent_result = _result_for_role("database", directory_results)
    if parent_result is None:
        return CheckResult(
            "SQLite",
            "FAIL",
            "No existe resultado para el directorio de la base de datos.",
            True,
        )
    if not parent_result.success:
        return CheckResult("SQLite", "FAIL", parent_result.detail, True)

    try:
        status = initializer(settings.database_path)
    except DatabaseError as error:
        return CheckResult("SQLite", "FAIL", str(error), True)
    return CheckResult(
        "SQLite",
        "PASS",
        f"Esquema versión {status.schema_version} en '{status.path}'.",
        True,
    )


def _check_ollama(settings: Settings, probe: OllamaProbe) -> CheckResult:
    """Representa Ollama como dependencia opcional de H1."""
    result = probe(settings.ollama_url, settings.ollama_timeout_seconds)
    return CheckResult(
        "Ollama",
        "PASS" if result.available else "WARN",
        result.detail,
        False,
    )


def _result_for_role(
    role: str,
    directory_results: tuple[DirectoryResult, ...],
) -> DirectoryResult | None:
    """Obtiene el resultado que contiene un rol determinado."""
    return next(
        (result for result in directory_results if role in result.roles),
        None,
    )


def _summarize(checks: tuple[CheckResult, ...]) -> DoctorSummary:
    """Cuenta estados y decide si todos los checks requeridos pasan."""
    return DoctorSummary(
        pass_count=sum(check.status == "PASS" for check in checks),
        warn_count=sum(check.status == "WARN" for check in checks),
        fail_count=sum(check.status == "FAIL" for check in checks),
        success=not any(
            check.required and check.status == "FAIL" for check in checks
        ),
    )
