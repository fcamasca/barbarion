"""Integracion H4-T05 para `barbarion analyze`."""

import sqlite3
from pathlib import Path

from barbarion import cli
from barbarion.database import initialize_database


def test_h4_analyze_dry_run_does_not_mutate_sqlite(
    tmp_path: Path,
    capsys: object,
) -> None:
    config = _prepare_workspace(tmp_path)
    db_path = tmp_path / "data" / "barbarion.db"
    _insert_oracle_chunk(
        db_path,
        file_id=1,
        relative_path="oracle/pkg_caller.pkb",
        object_name="caller",
        object_type="procedure",
        content="begin call procesar(); end;",
        metadata={"format": "oracle", "package_name": "pkg_caller"},
    )

    exit_code = cli.main(["--config", str(config), "analyze", "--dry-run"])
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    assert "Dry-run de analyze H4: completed" in captured.out
    assert _scalar(db_path, "SELECT COUNT(*) FROM analysis_runs") == 0
    assert _scalar(db_path, "SELECT COUNT(*) FROM symbols") == 0
    assert _scalar(db_path, 'SELECT COUNT(*) FROM symbol_references') == 0


def test_h4_analyze_incremental_resolution_transitions(
    tmp_path: Path,
    capsys: object,
) -> None:
    config = _prepare_workspace(tmp_path)
    db_path = tmp_path / "data" / "barbarion.db"
    _insert_oracle_chunk(
        db_path,
        file_id=1,
        relative_path="oracle/pkg_caller.pkb",
        object_name="caller",
        object_type="procedure",
        content="begin call procesar(); end;",
        metadata={"format": "oracle", "package_name": "pkg_caller"},
    )

    _run_analyze(config, capsys)
    assert _reference_status(db_path, "procesar") == "unresolved"
    assert _active_relation_statuses(db_path, "procesar") == ()

    _insert_oracle_chunk(
        db_path,
        file_id=2,
        relative_path="oracle/pkg_cliente_a.pkb",
        object_name="procesar",
        object_type="procedure",
        content="procedure procesar is begin null; end;",
        metadata={"format": "oracle", "package_name": "pkg_cliente"},
    )
    _run_analyze(config, capsys)
    assert _reference_status(db_path, "procesar") == "resolved"
    assert _active_relation_statuses(db_path, "procesar") == ("resolved",)

    _insert_oracle_chunk(
        db_path,
        file_id=3,
        relative_path="oracle/pkg_cliente_b.pkb",
        object_name="procesar",
        object_type="procedure",
        content="procedure procesar is begin null; end;",
        metadata={"format": "oracle", "package_name": "pkg_otro"},
    )
    _run_analyze(config, capsys)
    assert _reference_status(db_path, "procesar") == "ambiguous"
    assert _active_relation_statuses(db_path, "procesar") == ("ambiguous",)
    assert _scalar(db_path, "SELECT COUNT(*) FROM relation_candidates") == 2

    _mark_file_deleted(db_path, file_id=3)
    _run_analyze(config, capsys)
    assert _reference_status(db_path, "procesar") == "resolved"
    assert _active_relation_statuses(db_path, "procesar") == ("resolved",)

    _mark_file_deleted(db_path, file_id=2)
    _run_analyze(config, capsys)
    assert _reference_status(db_path, "procesar") == "unresolved"
    assert _active_relation_statuses(db_path, "procesar") == ()


def _prepare_workspace(tmp_path: Path) -> Path:
    for name in ("data", "output", "logs"):
        (tmp_path / name).mkdir()
    db_path = tmp_path / "data" / "barbarion.db"
    initialize_database(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO ingestion_runs(
                id, domain, mode, status, roots_json, config_sha256, started_at
            )
            VALUES (1, 'integration', 'incremental', 'completed', '[]', ?, ?)
            """,
            ("a" * 64, "2026-01-01T00:00:00+00:00"),
        )
        connection.commit()
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
                'paths = ["sources"]',
            ]
        ),
        encoding="utf-8",
    )
    return config


def _insert_oracle_chunk(
    db_path: Path,
    *,
    file_id: int,
    relative_path: str,
    object_name: str,
    object_type: str,
    content: str,
    metadata: dict[str, str],
) -> None:
    now = "2026-01-01T00:00:00+00:00"
    source_sha = f"{file_id:064x}"[-64:]
    content_sha = f"{file_id + 100:064x}"[-64:]
    chunk_sha = f"{file_id + 200:064x}"[-64:]
    metadata_json = "{" + ",".join(
        f'"{key}":"{value}"' for key, value in sorted(metadata.items())
    ) + "}"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO files(
                id, domain, source_root, relative_path, extension, artifact_kind,
                media_type, size_bytes, modified_at_ns, sha256, status,
                first_seen_run_id, last_seen_run_id, created_at, updated_at
            )
            VALUES (
                ?, 'integration', 'root', ?, '.pkb', 'oracle',
                'text/plain', 10, ?, ?, 'processed', 1, 1, ?, ?
            )
            """,
            (file_id, relative_path, file_id, source_sha, now, now),
        )
        connection.execute(
            """
            INSERT INTO documents(
                id, file_id, source_sha256, parser_id, parser_version,
                normalizer_version, normalized_text, content_sha256,
                metadata_json, warnings_json, extracted_at
            )
            VALUES (?, ?, ?, 'oracle', '1', '1', ?, ?, '{}', '[]', ?)
            """,
            (file_id, file_id, source_sha, content, content_sha, now),
        )
        connection.execute(
            """
            INSERT INTO chunks(
                id, document_id, ordinal, chunk_type, content, content_sha256,
                start_line, end_line, object_type, object_name, metadata_json,
                chunker_version, created_at
            )
            VALUES (?, ?, 0, ?, ?, ?, 1, 1, ?, ?, ?, '1', ?)
            """,
            (
                f"chunk-{file_id}",
                file_id,
                object_type,
                content,
                chunk_sha,
                object_type,
                object_name,
                metadata_json,
                now,
            ),
        )
        connection.commit()


def _run_analyze(config: Path, capsys: object) -> str:
    exit_code = cli.main(["--config", str(config), "analyze"])
    captured = capsys.readouterr()
    assert exit_code == 0, captured.err
    assert "Analyze H4: completed" in captured.out
    return captured.out


def _mark_file_deleted(db_path: Path, *, file_id: int) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE files SET status = 'deleted', updated_at = ? WHERE id = ?",
            ("2026-01-01T00:00:00+00:00", file_id),
        )
        connection.commit()


def _reference_status(db_path: Path, target: str) -> str:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT resolution_status
            FROM symbol_references
            WHERE normalized_target = ?
            ORDER BY updated_at DESC, id
            LIMIT 1
            """,
            (target,),
        ).fetchone()
    assert row is not None
    return str(row[0])


def _active_relation_statuses(db_path: Path, target: str) -> tuple[str, ...]:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT relations.resolution_status
            FROM relations
            JOIN symbol_references AS reference_rows
              ON reference_rows.id = relations.reference_id
            WHERE reference_rows.normalized_target = ?
              AND relations.status = 'active'
            ORDER BY relations.resolution_status
            """,
            (target,),
        ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _scalar(db_path: Path, sql: str) -> int:
    with sqlite3.connect(db_path) as connection:
        return int(connection.execute(sql).fetchone()[0])
