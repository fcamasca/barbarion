"""Pruebas de observabilidad operativa para configuraciones Data-Driven."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from barbarion import cli
from tests.integration.test_data_driven_analyze_cli import _prepare_workspace


def test_analyze_and_stats_report_data_driven_metrics_and_diagnostics(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Valida metricas, errores parciales y conteos persistidos.

    Args:
        tmp_path: Workspace temporal con corpus y SQLite aislados.
        capsys: Capturador de las salidas emitidas por la CLI.
    """
    config = _prepare_workspace(tmp_path)
    rules = tmp_path / "sources" / "config" / "pricing" / "rules.sql"
    rules.write_text(
        rules.read_text(encoding="utf-8")
        + """
        DELETE FROM APP_CFG.PRICING_RULES WHERE RULE_ID = 'R9';
        INSERT INTO APP_CFG.PRICING_RULES (RULE_ID, RULE_NAME)
        VALUES ('BROKEN');
        """,
        encoding="utf-8",
    )

    assert cli.main(["--config", str(config), "ingest"]) == 0
    capsys.readouterr()
    assert cli.main(["--config", str(config), "analyze", "--dry-run"]) == 0
    dry_run = capsys.readouterr()

    assert "Archivos DML identificados: 1" in dry_run.out
    assert "Sentencias procesadas: 4" in dry_run.out
    assert "Sentencias soportadas: 2" in dry_run.out
    assert "Sentencias omitidas: 1" in dry_run.out
    assert "Sentencias con error: 1" in dry_run.out
    assert "Registros extraidos: 2" in dry_run.out
    assert "Configuraciones reconciliadas: 1" in dry_run.out
    assert "Relaciones Data-Driven resueltas: 1" in dry_run.out
    assert "Relaciones Data-Driven ambiguas: 1" in dry_run.out
    assert "Relaciones Data-Driven no resueltas: 1" in dry_run.out
    assert "Advertencias Data-Driven: 1" in dry_run.out
    assert "Diagnosticos Data-Driven: 2" in dry_run.out
    assert "motivo=unsupported_statement" in dry_run.out
    assert "motivo=column_value_mismatch" in dry_run.out
    assert "accion=alinear columnas y valores" in dry_run.out
    assert "Duracion por etapa: discover=" in dry_run.out

    assert cli.main(["--config", str(config), "analyze", "--full"]) == 0
    completed = capsys.readouterr()
    assert "Analisis tecnico: completed" in completed.out
    assert "Sentencias con error: 1" in completed.out
    log_text = (tmp_path / "logs" / "barbarion.log").read_text(encoding="utf-8")
    assert "analyze_data_driven" in log_text
    assert "reason=column_value_mismatch" in log_text
    assert "VALUES ('BROKEN')" not in log_text
    with sqlite3.connect(tmp_path / "data" / "barbarion.db") as connection:
        persisted = connection.execute(
            "SELECT warning_count, error_count FROM analysis_runs ORDER BY id DESC"
        ).fetchone()
    assert persisted == (1, 1)

    assert cli.main(["--config", str(config), "stats", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    metrics = payload["reverse_engineering"]["data_driven"]
    assert metrics["files"] == 1
    assert metrics["symbols_active"] >= 5
    assert metrics["references_active"] == 3
    assert metrics["relations"]["resolved"] == 1
    assert metrics["relations"]["ambiguous"] == 1
    assert metrics["relations"]["unresolved"] == 1
