from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from barbarion import cli
from barbarion.database import initialize_database
from tests.support.h2_corpus import build_h2_corpus
from tests.support.h2_corpus import powerbuilder_overlap_content


def write_config(
    tmp_path: Path,
    corpus: Path,
    *,
    chunk_size: int = 500,
    chunk_overlap: int = 0,
) -> Path:
    source = tmp_path / "barbarion.toml"
    source.write_text(
        "\n".join(
            [
                'domain = "integration"',
                'data_dir = "data"',
                'output_dir = "output"',
                'logs_dir = "logs"',
                'database_path = "data/barbarion.db"',
                'log_level = "INFO"',
                "[ingestion]",
                f'paths = ["{corpus.as_posix()}"]',
                f"chunk_size = {chunk_size}",
                f"chunk_overlap = {chunk_overlap}",
                'encodings = ["utf-8", "cp1252", "latin-1"]',
            ]
        ),
        encoding="utf-8",
    )
    return source


def prepare_workspace(tmp_path: Path, *, include_errors: bool = False) -> tuple[Path, Path]:
    corpus = build_h2_corpus(tmp_path / "corpus", include_errors=include_errors)
    for name in ("data", "output", "logs"):
        (tmp_path / name).mkdir()
    initialize_database(tmp_path / "data" / "barbarion.db")
    return write_config(tmp_path, corpus), corpus


def run_ingest(
    config: Path,
    *extra_args: str,
    capsys: pytest.CaptureFixture[str],
) -> str:
    exit_code = cli.main(["--config", str(config), "ingest", *extra_args])
    captured = capsys.readouterr()
    assert exit_code == 0, captured.err
    assert "Ingesta finalizada:" in captured.out
    return captured.out


def metrics(db_path: Path) -> dict[str, int | str]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT status, discovered_files, processed_files, unchanged_files,
                   skipped_files, deleted_files, error_count, chunk_count
            FROM ingestion_runs
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    return dict(row)


def scalar(db_path: Path, sql: str) -> int:
    with sqlite3.connect(db_path) as connection:
        return int(connection.execute(sql).fetchone()[0])


def chunk_ids(db_path: Path) -> tuple[str, ...]:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute("SELECT id FROM chunks ORDER BY id").fetchall()
    return tuple(row[0] for row in rows)


def test_cli_ingest_incremental_touch_change_delete_and_full(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config, corpus = prepare_workspace(tmp_path)
    db_path = tmp_path / "data" / "barbarion.db"
    total_files = sum(1 for path in corpus.rglob("*") if path.is_file())
    processed_files = total_files - 1

    first_output = run_ingest(config, capsys=capsys)
    first_metrics = metrics(db_path)
    first_chunk_ids = chunk_ids(db_path)

    assert "Procesados:" in first_output
    assert first_metrics["status"] == "completed"
    assert first_metrics["discovered_files"] == total_files
    assert first_metrics["processed_files"] == processed_files
    assert first_metrics["skipped_files"] == 1
    assert first_metrics["error_count"] == 0
    assert scalar(db_path, "SELECT COUNT(*) FROM files WHERE status = 'processed'") == processed_files
    assert scalar(db_path, "SELECT COUNT(*) FROM files WHERE status = 'skipped'") == 1
    assert scalar(db_path, "SELECT COUNT(*) FROM documents") == processed_files

    run_ingest(config, capsys=capsys)
    second_metrics = metrics(db_path)
    assert second_metrics["processed_files"] == 0
    assert second_metrics["unchanged_files"] == processed_files
    assert second_metrics["skipped_files"] == 1
    assert chunk_ids(db_path) == first_chunk_ids

    touched = corpus / "docs" / "notes.txt"
    os.utime(touched, None)
    run_ingest(config, capsys=capsys)
    touch_metrics = metrics(db_path)
    assert touch_metrics["processed_files"] == 0
    assert touch_metrics["unchanged_files"] == processed_files
    assert chunk_ids(db_path) == first_chunk_ids

    touched.write_text(
        "Primera nota sintetica modificada.\n\nContenido nuevo para ingesta.",
        encoding="utf-8",
    )
    run_ingest(config, capsys=capsys)
    changed_metrics = metrics(db_path)
    changed_chunk_ids = chunk_ids(db_path)
    assert changed_metrics["processed_files"] == 1
    assert changed_metrics["unchanged_files"] == processed_files - 1
    assert changed_chunk_ids != first_chunk_ids

    deleted = corpus / "oracle" / "standalone_function.fnc"
    deleted.unlink()
    run_ingest(config, capsys=capsys)
    deleted_metrics = metrics(db_path)
    assert deleted_metrics["deleted_files"] == 1
    assert scalar(db_path, "SELECT COUNT(*) FROM files WHERE status = 'deleted'") == 1
    assert scalar(
        db_path,
        """
        SELECT COUNT(*)
        FROM chunks
        LEFT JOIN documents ON documents.id = chunks.document_id
        WHERE documents.id IS NULL
        """,
    ) == 0

    run_ingest(config, "--full", capsys=capsys)
    full_metrics = metrics(db_path)
    assert full_metrics["processed_files"] == processed_files - 1
    assert full_metrics["unchanged_files"] == 0
    assert scalar(db_path, "SELECT COUNT(*) FROM files WHERE status = 'processed'") == processed_files - 1


def test_cli_ingest_partial_errors_return_one_and_keep_valid_files(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config, _ = prepare_workspace(tmp_path, include_errors=True)
    exit_code = cli.main(["--config", str(config), "ingest"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Ingesta finalizada: completed_with_errors" in captured.out
    latest = metrics(tmp_path / "data" / "barbarion.db")
    assert latest["error_count"] >= 1
    assert latest["processed_files"] > 0


def test_cli_ingest_powerbuilder_overlap_root_persists_unique_chunks(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "powerbuilder"
    root.mkdir()
    (root / "w_overlap.srw").write_text(
        powerbuilder_overlap_content("w_overlap"),
        encoding="utf-8",
    )
    (root / "w_other.srw").write_text(
        "$PBExportHeader$w_other.srw\n"
        "global type w_other from window\n"
        "event open;\n"
        "messagebox('ok', 'ok')\n"
        "end event\n"
        "end type\n",
        encoding="utf-8",
    )
    for name in ("data", "output", "logs"):
        (tmp_path / name).mkdir()
    db_path = tmp_path / "data" / "barbarion.db"
    initialize_database(db_path)
    config = write_config(tmp_path, root, chunk_size=4000, chunk_overlap=400)

    output = run_ingest(config, "--full", capsys=capsys)
    latest = metrics(db_path)

    assert "Ingesta finalizada: completed" in output
    assert latest["status"] == "completed"
    assert latest["discovered_files"] == 2
    assert latest["processed_files"] == 2
    assert latest["error_count"] == 0
    assert scalar(db_path, "SELECT COUNT(*) FROM documents") == 2
    assert scalar(db_path, "SELECT COUNT(*) FROM errors") == 0
    assert scalar(db_path, "SELECT COUNT(*) FROM chunks") > 2
    assert scalar(db_path, "SELECT COUNT(DISTINCT id) FROM chunks") == scalar(
        db_path,
        "SELECT COUNT(*) FROM chunks",
    )
