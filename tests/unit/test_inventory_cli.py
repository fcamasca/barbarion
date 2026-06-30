"""Pruebas H4-T08 para `barbarion inventory`."""

import json
import sqlite3
from pathlib import Path

from barbarion import cli
from barbarion.database import initialize_database


def test_inventory_cli_filters_and_json(
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
    _insert_oracle_chunk(
        db_path,
        file_id=2,
        relative_path="oracle/pkg_target.pkb",
        object_name="procesar",
        object_type="procedure",
        content="procedure procesar is begin null; end;",
        metadata={"format": "oracle", "package_name": "pkg_target"},
    )
    assert cli.main(["--config", str(config), "analyze"]) == 0
    capsys.readouterr()

    exit_code = cli.main(
        [
            "--config",
            str(config),
            "inventory",
            "--technology",
            "oracle",
            "--type",
            "procedure",
            "--name",
            "procesar",
            "--format",
            "json",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    payload = json.loads(captured.out)
    assert payload["summary"]["symbols"] == 1
    assert payload["items"][0]["normalized_name"] == "procesar"
    assert payload["items"][0]["relative_path"] == "oracle/pkg_target.pkb"


def test_inventory_cli_empty_text_output(
    tmp_path: Path,
    capsys: object,
) -> None:
    config = _prepare_workspace(tmp_path)

    exit_code = cli.main(
        ["--config", str(config), "inventory", "--name", "no_existe"]
    )
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    assert "simbolos = 0" in captured.out
    assert "sin simbolos para los filtros indicados" in captured.out


def test_inventory_cli_safe_output_and_no_overwrite(
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
        content="begin null; end;",
        metadata={"format": "oracle", "package_name": "pkg_caller"},
    )
    assert cli.main(["--config", str(config), "analyze"]) == 0
    capsys.readouterr()
    output_path = tmp_path / "output" / "inventario.md"

    first = cli.main(
        [
            "--config",
            str(config),
            "inventory",
            "--format",
            "markdown",
            "--output",
            str(output_path),
        ]
    )
    first_capture = capsys.readouterr()
    second = cli.main(
        [
            "--config",
            str(config),
            "inventory",
            "--format",
            "markdown",
            "--output",
            str(output_path),
        ]
    )
    second_capture = capsys.readouterr()
    third = cli.main(
        [
            "--config",
            str(config),
            "inventory",
            "--format",
            "markdown",
            "--output",
            str(output_path),
            "--overwrite",
        ]
    )
    third_capture = capsys.readouterr()

    assert first == 0, first_capture.err
    assert output_path.exists()
    assert "# Inventario tecnico" in output_path.read_text(encoding="utf-8")
    assert second == 1
    assert "El archivo ya existe" in second_capture.err
    assert third == 0, third_capture.err


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
