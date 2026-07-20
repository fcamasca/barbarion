"""Integracion CLI para analisis de configuraciones Data-Driven."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from barbarion import cli
from barbarion.application.reverse_engineering import AnalyzeScope, AnalyzeService
from barbarion.config import load_settings
from barbarion.database import initialize_database
from barbarion.domain.reverse_engineering import AnalysisRunStatus
from barbarion.infrastructure.sqlite import SQLiteReverseEngineeringRepository


def test_data_driven_analyze_cli_is_idempotent_and_respects_dry_run(
    tmp_path: Path,
    capsys: object,
) -> None:
    """Verifica dry-run, analyze por path, idempotencia y full analyze.

    Args:
        tmp_path: Directorio temporal de pytest usado como workspace aislado.
        capsys: Capturador de salida de pytest para limpiar mensajes CLI.
    """
    config = _prepare_workspace(tmp_path)
    db_path = tmp_path / "data" / "barbarion.db"

    ingest_code = cli.main(["--config", str(config), "ingest"])
    ingest_output = capsys.readouterr()

    assert ingest_code == 0, ingest_output.err
    assert _scalar(db_path, "SELECT COUNT(*) FROM files WHERE artifact_kind = 'configuration'") == 1

    dry_code = cli.main(
        [
            "--config",
            str(config),
            "analyze",
            "--path",
            "config/pricing",
            "--dry-run",
        ]
    )
    dry_output = capsys.readouterr()

    assert dry_code == 0, dry_output.err
    assert "Dry-run de analisis tecnico: completed" in dry_output.out
    assert _counts(db_path) == {
        "analysis_runs": 0,
        "symbols": 0,
        "symbol_references": 0,
        "relations": 0,
    }

    analyze_code = cli.main(
        ["--config", str(config), "analyze", "--path", "config/pricing"]
    )
    analyze_output = capsys.readouterr()

    assert analyze_code == 0, analyze_output.err
    assert "Analisis tecnico: completed" in analyze_output.out
    first_counts = _counts(db_path)
    assert first_counts["analysis_runs"] == 1
    assert first_counts["symbols"] >= 5
    assert first_counts["symbol_references"] == 3
    assert first_counts["relations"] == 2
    assert _reference_statuses(db_path) == {
        "configuration_token": ("ambiguous",),
        "function_candidate": ("unresolved",),
        "precedes": ("resolved",),
    }
    assert _active_relation_statuses(db_path) == ("resolved", "ambiguous")

    second_code = cli.main(
        ["--config", str(config), "analyze", "--path", "config/pricing"]
    )
    second_output = capsys.readouterr()

    assert second_code == 0, second_output.err
    assert "Analisis tecnico: completed" in second_output.out
    second_counts = _counts(db_path)
    assert second_counts == {
        **first_counts,
        "analysis_runs": 2,
    }

    full_code = cli.main(["--config", str(config), "analyze", "--full"])
    full_output = capsys.readouterr()

    assert full_code == 0, full_output.err
    assert "Analisis tecnico: completed" in full_output.out
    full_counts = _counts(db_path)
    assert full_counts["analysis_runs"] == 3
    assert full_counts["symbol_references"] == first_counts["symbol_references"]
    assert full_counts["relations"] == first_counts["relations"]
    assert _scalar(
        db_path,
        "SELECT COUNT(*) FROM symbols WHERE technology = 'configuration'",
    ) == _scalar(
        db_path,
        "SELECT COUNT(*) FROM symbols WHERE technology = 'configuration' AND last_run_id = 3",
    )


def test_analyze_general_counts_are_current_and_idempotent(
    tmp_path: Path,
    capsys: object,
) -> None:
    """Mantiene conteos generales coherentes entre corridas identicas.

    Args:
        tmp_path: Workspace temporal con corpus Data-Driven aislado.
        capsys: Capturador usado para limpiar la salida de ingesta.
    """
    config = _prepare_workspace(tmp_path)
    db_path = tmp_path / "data" / "barbarion.db"
    rules = tmp_path / "sources" / "config" / "pricing" / "rules.sql"
    rules.write_text(
        rules.read_text(encoding="utf-8").replace(
            "TAX_RATE()",
            "ROUND(AMOUNT)",
        ),
        encoding="utf-8",
    )
    assert cli.main(["--config", str(config), "ingest"]) == 0
    capsys.readouterr()
    settings = load_settings(config_path=config, environ={}, cwd=tmp_path)
    service = AnalyzeService(
        settings=settings,
        repository=SQLiteReverseEngineeringRepository(db_path),
    )
    scope = AnalyzeScope(path_prefix="config/pricing")

    first = service.run(scope=scope)
    first_counts = _counts(db_path)
    second = service.run(scope=scope)
    second_counts = _counts(db_path)

    first_projection = (
        first.references_detected,
        first.relations_resolved,
        first.relations_ambiguous,
        first.relations_unresolved,
    )
    second_projection = (
        second.references_detected,
        second.relations_resolved,
        second.relations_ambiguous,
        second.relations_unresolved,
    )
    assert first_projection == second_projection
    assert (
        second.relations_resolved
        + second.relations_ambiguous
        + second.relations_unresolved
        == second.references_detected
    )
    metrics = second.data_driven
    assert (
        metrics.relations_resolved
        + metrics.relations_ambiguous
        + metrics.relations_unresolved
        + metrics.relations_dynamic
        + metrics.relations_external
        == metrics.references_detected
    )
    assert second.references_detected == metrics.references_detected
    assert second.relations_resolved == metrics.relations_resolved
    assert second.relations_ambiguous == metrics.relations_ambiguous
    assert second.relations_unresolved == (
        metrics.relations_unresolved
        + metrics.relations_dynamic
        + metrics.relations_external
    )
    assert metrics.relations_external == 1
    assert second_counts["symbol_references"] == first_counts["symbol_references"]
    assert second_counts["relations"] == first_counts["relations"]


def test_data_driven_analyze_reconciles_modified_and_deleted_records(
    tmp_path: Path,
    capsys: object,
) -> None:
    """Valida reconciliacion al modificar registros y eliminar archivos.

    Args:
        tmp_path: Directorio temporal de pytest usado como workspace aislado.
        capsys: Capturador de salida de pytest para limpiar mensajes CLI.
    """
    config = _prepare_workspace(tmp_path)
    db_path = tmp_path / "data" / "barbarion.db"
    rules = tmp_path / "sources" / "config" / "pricing" / "rules.sql"

    assert cli.main(["--config", str(config), "ingest"]) == 0
    capsys.readouterr()
    assert cli.main(["--config", str(config), "analyze", "--path", "config/pricing"]) == 0
    capsys.readouterr()
    assert _active_configuration_records(db_path) == ("pricing_rules.r1", "pricing_rules.r2")
    assert _active_relation_statuses(db_path, relation_type="precedes") == ("resolved",)

    rules.write_text(
        """
        INSERT INTO APP_CFG.PRICING_RULES (
            RULE_ID, RULE_NAME, VARIABLE_NAME
        )
        VALUES ('R1', 'Base Rule Updated', 'AMOUNT');
        """,
        encoding="utf-8",
    )
    assert cli.main(["--config", str(config), "ingest"]) == 0
    capsys.readouterr()
    assert cli.main(["--config", str(config), "analyze", "--path", "config/pricing"]) == 0
    capsys.readouterr()

    assert _active_configuration_records(db_path) == ("pricing_rules.r1",)
    assert _scalar(
        db_path,
        """
        SELECT COUNT(*)
        FROM symbols
        WHERE technology = 'configuration'
          AND status = 'active'
          AND normalized_name LIKE 'pricing_rules.r2%'
        """,
    ) == 0
    assert _scalar(db_path, "SELECT COUNT(*) FROM relations WHERE status = 'active'") == 0
    assert _scalar(db_path, "SELECT COUNT(*) FROM symbol_references") == 0

    rules.unlink()
    assert cli.main(["--config", str(config), "ingest"]) == 0
    capsys.readouterr()
    assert cli.main(["--config", str(config), "analyze", "--full"]) == 0
    capsys.readouterr()

    assert _scalar(
        db_path,
        "SELECT COUNT(*) FROM symbols WHERE technology = 'configuration' AND status = 'active'",
    ) == 0
    assert _scalar(db_path, "SELECT COUNT(*) FROM relations WHERE status = 'active'") == 0
    assert _scalar(db_path, "SELECT COUNT(*) FROM symbol_references") == 0


def test_data_driven_analyze_reresolves_unresolved_to_ambiguous(
    tmp_path: Path,
    capsys: object,
) -> None:
    """Comprueba transiciones de referencias entre estados de resolucion.

    Args:
        tmp_path: Directorio temporal de pytest usado como workspace aislado.
        capsys: Capturador de salida de pytest para limpiar mensajes CLI.
    """
    config = _prepare_workspace(tmp_path, include_target=False)
    db_path = tmp_path / "data" / "barbarion.db"
    rules = tmp_path / "sources" / "config" / "pricing" / "rules.sql"

    assert cli.main(["--config", str(config), "ingest"]) == 0
    capsys.readouterr()
    assert cli.main(["--config", str(config), "analyze", "--path", "config/pricing"]) == 0
    capsys.readouterr()
    assert _reference_statuses(db_path)["precedes"] == ("unresolved",)
    assert _reference_statuses(db_path)["function_candidate"] == ("unresolved",)
    assert _active_relation_statuses(db_path, relation_type="precedes") == ()
    assert _active_relation_statuses(db_path, relation_type="calls") == ()

    rules.write_text(_rules_sql(include_target=True, duplicate_target=False), encoding="utf-8")
    oracle_dir = tmp_path / "sources" / "oracle"
    oracle_dir.mkdir()
    (oracle_dir / "tax_rate.fnc").write_text(
        """
        CREATE FUNCTION tax_rate RETURN NUMBER AS
        BEGIN
            RETURN 1;
        END tax_rate;
        """,
        encoding="utf-8",
    )
    assert cli.main(["--config", str(config), "ingest"]) == 0
    capsys.readouterr()
    assert cli.main(["--config", str(config), "analyze", "--full"]) == 0
    capsys.readouterr()
    assert _reference_statuses(db_path)["precedes"] == ("resolved",)
    assert _reference_statuses(db_path)["function_candidate"] == ("resolved",)
    assert _active_relation_statuses(db_path, relation_type="precedes") == ("resolved",)
    assert _active_relation_statuses(db_path, relation_type="calls") == ("resolved",)

    powerbuilder_dir = tmp_path / "sources" / "powerbuilder"
    powerbuilder_dir.mkdir()
    (powerbuilder_dir / "tax_rate.srf").write_text(
        """
        $PBExportHeader$tax_rate.srf
        type tax_rate from function_object
        end type
        """,
        encoding="utf-8",
    )
    assert cli.main(["--config", str(config), "ingest"]) == 0
    capsys.readouterr()
    assert cli.main(["--config", str(config), "analyze", "--full"]) == 0
    capsys.readouterr()
    assert _reference_statuses(db_path)["function_candidate"] == ("ambiguous",)
    assert _active_relation_statuses(db_path, relation_type="precedes") == ("resolved",)
    assert _active_relation_statuses(db_path, relation_type="calls") == ("ambiguous",)
    assert _scalar(db_path, "SELECT COUNT(*) FROM relation_candidates") == 4


def test_data_driven_analyze_path_scope_does_not_touch_other_files(
    tmp_path: Path,
    capsys: object,
) -> None:
    """Asegura que `--path` no reconcilia conocimiento fuera del alcance.

    Args:
        tmp_path: Directorio temporal de pytest usado como workspace aislado.
        capsys: Capturador de salida de pytest para limpiar mensajes CLI.
    """
    config = _prepare_workspace(tmp_path)
    db_path = tmp_path / "data" / "barbarion.db"
    other_dir = tmp_path / "sources" / "config" / "other"
    other_dir.mkdir()
    (other_dir / "other.sql").write_text(
        """
        INSERT INTO APP_CFG.PRICING_RULES (RULE_ID, RULE_NAME)
        VALUES ('R9', 'Other Rule');
        """,
        encoding="utf-8",
    )

    assert cli.main(["--config", str(config), "ingest"]) == 0
    capsys.readouterr()
    assert cli.main(["--config", str(config), "analyze", "--path", "config/pricing"]) == 0
    capsys.readouterr()
    assert _active_configuration_records(db_path) == ("pricing_rules.r1", "pricing_rules.r2")

    assert cli.main(["--config", str(config), "analyze", "--path", "config/other"]) == 0
    capsys.readouterr()
    assert _active_configuration_records(db_path) == (
        "pricing_rules.r1",
        "pricing_rules.r2",
        "pricing_rules.r9",
    )


def test_data_driven_analyze_cancel_before_persist_does_not_publish_partial(
    tmp_path: Path,
    capsys: object,
) -> None:
    """Verifica que cancelar tras extraer no publique conocimiento parcial.

    Args:
        tmp_path: Directorio temporal de pytest usado como workspace aislado.
        capsys: Capturador de salida de pytest para limpiar mensajes CLI.
    """
    config = _prepare_workspace(tmp_path)
    db_path = tmp_path / "data" / "barbarion.db"
    assert cli.main(["--config", str(config), "ingest"]) == 0
    capsys.readouterr()
    service = AnalyzeService(
        settings=load_settings(config),
        repository=SQLiteReverseEngineeringRepository(db_path),
    )
    cancellation = _CancelOnExtract()

    summary = service.run(
        scope=AnalyzeScope(path_prefix="config/pricing"),
        progress=cancellation,
        cancellation=cancellation,
    )

    assert summary.status == AnalysisRunStatus.INTERRUPTED
    assert _scalar(db_path, "SELECT COUNT(*) FROM analysis_runs WHERE status = 'interrupted'") == 1
    assert _scalar(db_path, "SELECT COUNT(*) FROM symbols") == 0
    assert _scalar(db_path, "SELECT COUNT(*) FROM symbol_references") == 0
    assert _scalar(db_path, "SELECT COUNT(*) FROM relations") == 0


def test_data_driven_analyze_recovers_from_invalid_document(
    tmp_path: Path,
    capsys: object,
) -> None:
    """Confirma que un SQL invalido no bloquea documentos validos del scope.

    Args:
        tmp_path: Directorio temporal de pytest usado como workspace aislado.
        capsys: Capturador de salida de pytest para limpiar mensajes CLI.
    """
    config = _prepare_workspace(tmp_path)
    invalid = tmp_path / "sources" / "config" / "pricing" / "invalid.sql"
    invalid.write_text(
        """
        INSERT INTO APP_CFG.PRICING_RULES (RULE_ID, RULE_NAME)
        SELECT RULE_ID, RULE_NAME FROM OTHER_TABLE;
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "data" / "barbarion.db"

    assert cli.main(["--config", str(config), "ingest"]) == 0
    capsys.readouterr()
    assert cli.main(["--config", str(config), "analyze", "--path", "config/pricing"]) == 0
    output = capsys.readouterr()

    assert "Analisis tecnico: completed" in output.out
    assert _active_configuration_records(db_path) == ("pricing_rules.r1", "pricing_rules.r2")
    assert _scalar(
        db_path,
        """
        SELECT COUNT(*)
        FROM symbols
        JOIN files ON files.id = symbols.file_id
        WHERE files.relative_path = 'config/pricing/invalid.sql'
        """,
    ) == 0


def _prepare_workspace(tmp_path: Path, *, include_target: bool = True) -> Path:
    """Construye un workspace minimo con configuracion Data-Driven.

    Args:
        tmp_path: Directorio temporal donde se escriben corpus, base y TOML.
        include_target: Indica si el SQL inicial incluye el registro destino R1.

    Returns:
        Ruta del archivo TOML que debe usar la CLI en la prueba.
    """
    corpus = tmp_path / "sources"
    (corpus / "config" / "pricing").mkdir(parents=True)
    (corpus / "config" / "pricing" / "rules.sql").write_text(
        _rules_sql(include_target=include_target, duplicate_target=False),
        encoding="utf-8",
    )
    (corpus / "notes.txt").write_text("Documento fuera del analisis.", encoding="utf-8")
    for name in ("data", "output", "logs"):
        (tmp_path / name).mkdir()
    initialize_database(tmp_path / "data" / "barbarion.db")
    config = tmp_path / "barbarion.toml"
    config.write_text(
        "\n".join(
            [
                'domain = "integration"',
                'data_dir = "data"',
                'output_dir = "output"',
                'logs_dir = "logs"',
                'database_path = "data/barbarion.db"',
                "[ingestion]",
                f'paths = ["{corpus.as_posix()}"]',
                "[data_driven]",
                "enabled = true",
                'file_patterns = ["config/**/*.sql"]',
                'token_patterns = ["\\\\{([A-Z_][A-Z0-9_]*)\\\\}"]',
                "[[data_driven.configurations]]",
                'name = "pricing_rules"',
                'symbol_type = "configuration_record"',
                'tables = ["APP_CFG.PRICING_RULES"]',
                'identity_columns = ["RULE_ID"]',
                'name_columns = ["RULE_NAME"]',
                'formula_columns = ["FORMULA"]',
                'variable_columns = ["VARIABLE_NAME"]',
                'reference_columns = [',
                '  { column = "NEXT_STEP_ID", target_configuration = "pricing_rules", relation_type = "precedes" }',
                "]",
            ]
        ),
        encoding="utf-8",
    )
    return config


def _rules_sql(*, include_target: bool, duplicate_target: bool) -> str:
    """Genera DML de reglas de precios para escenarios incrementales.

    Args:
        include_target: Incluye el registro R1 usado como destino explicito.
        duplicate_target: Incluye una segunda sentencia R1 para escenarios
            que necesiten probar identidad determinista.

    Returns:
        Texto SQL con las sentencias DML del corpus sintetico.
    """
    statements = []
    if include_target:
        statements.append(
            """
            INSERT INTO APP_CFG.PRICING_RULES (
                RULE_ID, RULE_NAME, VARIABLE_NAME
            )
            VALUES ('R1', 'Base Rule', 'AMOUNT');
            """
        )
    if duplicate_target:
        statements.append(
            """
            INSERT INTO APP_CFG.PRICING_RULES (RULE_ID, RULE_NAME)
            VALUES ('R1', 'Duplicate Target');
            """
        )
    statements.append(
        """
        INSERT INTO APP_CFG.PRICING_RULES (
            RULE_ID, RULE_NAME, NEXT_STEP_ID, FORMULA, VARIABLE_NAME
        )
        VALUES (
            'R2', 'Derived Rule', 'R1', '{AMOUNT} + TAX_RATE()', 'AMOUNT'
        );
        """
    )
    return "\n".join(statements)


def _counts(db_path: Path) -> dict[str, int]:
    """Cuenta filas de las tablas reverse engineering principales.

    Args:
        db_path: Ruta de la base SQLite de la prueba.

    Returns:
        Conteos por tabla para comparar idempotencia y dry-run.
    """
    return {
        table: _scalar(db_path, f"SELECT COUNT(*) FROM {table}")
        for table in ("analysis_runs", "symbols", "symbol_references", "relations")
    }


def _reference_statuses(db_path: Path) -> dict[str, tuple[str, ...]]:
    """Lee estados de referencias vigentes agrupados por tipo.

    Args:
        db_path: Ruta de la base SQLite de la prueba.

    Returns:
        Mapa de tipo de referencia a sus estados vigentes ordenados.
    """
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT symbol_references.reference_type, symbol_references.resolution_status
            FROM symbol_references
            JOIN chunks ON chunks.id = symbol_references.source_chunk_id
            JOIN documents ON documents.id = chunks.document_id
            JOIN files ON files.id = documents.file_id
            WHERE files.status = 'processed'
              AND documents.source_sha256 = files.sha256
            ORDER BY symbol_references.reference_type, symbol_references.resolution_status
            """
        ).fetchall()
    statuses: dict[str, list[str]] = {}
    for reference_type, status in rows:
        statuses.setdefault(str(reference_type), []).append(str(status))
    return {key: tuple(value) for key, value in statuses.items()}


def _active_relation_statuses(
    db_path: Path,
    *,
    relation_type: str | None = None,
) -> tuple[str, ...]:
    """Lee estados de relaciones activas, opcionalmente filtradas por tipo.

    Args:
        db_path: Ruta de la base SQLite de la prueba.
        relation_type: Tipo de relacion a consultar, o `None` para todas.

    Returns:
        Estados de resolucion de relaciones activas en orden estable.
    """
    relation_filter = ""
    parameters: tuple[str, ...] = ()
    if relation_type is not None:
        relation_filter = "AND relation_type = ?"
        parameters = (relation_type,)
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            f"""
            SELECT resolution_status
            FROM relations
            WHERE status = 'active'
              {relation_filter}
            ORDER BY relation_type, resolution_status, id
            """,
            parameters,
        ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _active_configuration_records(db_path: Path) -> tuple[str, ...]:
    """Lista nombres normalizados de registros de configuracion activos.

    Args:
        db_path: Ruta de la base SQLite de la prueba.

    Returns:
        Nombres normalizados de registros Data-Driven activos.
    """
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT normalized_name
            FROM symbols
            WHERE technology = 'configuration'
              AND symbol_type = 'configuration_record'
              AND status = 'active'
            ORDER BY normalized_name, file_id
            """
        ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _scalar(db_path: Path, sql: str) -> int:
    """Ejecuta una consulta escalar entera sobre SQLite.

    Args:
        db_path: Ruta de la base SQLite de la prueba.
        sql: Consulta que debe devolver una unica fila y columna numerica.

    Returns:
        Valor entero de la primera columna devuelta.
    """
    with sqlite3.connect(db_path) as connection:
        return int(connection.execute(sql).fetchone()[0])


@dataclass
class _CancelOnExtract:
    """Token de cancelacion que se activa al reportar la etapa `extract`.

    Attributes:
        cancelled: Bandera consultada por `AnalyzeService` para interrumpir.
    """

    cancelled: bool = False

    def start(self, stages: object) -> None:
        """Acepta el inicio de progreso sin cambiar el estado.

        Args:
            stages: Etapas configuradas por el servicio bajo prueba.
        """
        return None

    def stage(self, snapshot: object) -> None:
        """Activa la cancelacion cuando el servicio termina la extraccion.

        Args:
            snapshot: Fotografia de progreso reportada por el servicio.
        """
        if getattr(snapshot, "stage_key", None) == "extract":
            self.cancelled = True

    def finish(self, status: str) -> None:
        """Recibe el cierre de progreso sin efectos adicionales.

        Args:
            status: Estado final reportado por el servicio.
        """
        return None
