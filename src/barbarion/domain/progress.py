"""Contratos livianos de progreso y cancelacion para procesos batch."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ProgressStage:
    """Etapa observable de un proceso batch."""

    key: str
    label: str
    total: int | None = None


@dataclass(frozen=True, slots=True)
class ProgressSnapshot:
    """Estado puntual reportado por una etapa."""

    stage_key: str
    stage_label: str
    current: int = 0
    total: int | None = None
    global_current: int = 0
    global_total: int | None = None
    counters: dict[str, int] = field(default_factory=dict)
    message: str | None = None


class ProgressReporterPort(Protocol):
    """Puerto para reportar progreso sin acoplar la aplicacion a la consola."""

    def start(self, stages: tuple[ProgressStage, ...]) -> None:
        """Inicia el reporte de progreso."""

    def stage(self, snapshot: ProgressSnapshot) -> None:
        """Reporta avance de la etapa actual."""

    def finish(self, status: str) -> None:
        """Finaliza el reporte."""


class CancellationTokenPort(Protocol):
    """Token cooperativo para cancelar procesos largos."""

    @property
    def cancelled(self) -> bool:
        """Indica si el usuario solicito cancelacion."""
