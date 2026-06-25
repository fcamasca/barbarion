"""Pruebas de inicialización, migración y salud de SQLite."""

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from barbarion import database
from barbarion.database import (
    DATABASE_TIMEOUT_SECONDS,
    WAL_UNAVAILABLE_CODE,
    DatabaseError,
    initialize_database,
)


def migration_rows(path: Path) -> list[tuple[int, str]]:
    """Lee las migraciones registradas sin modificar la base."""
    with sqlite3.connect(path) as connection:
        return connection.execute(
            "SELECT version, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()


def journal_mode(path: Path) -> str:
    """Lee el modo de journal persistido en la base."""
    with sqlite3.connect(path) as connection:
        return str(connection.execute("PRAGMA journal_mode").fetchone()[0])


def test_new_database_creates_schema_version_two(tmp_path: Path) -> None:
    path = tmp_path / "barbarion.db"

    status = initialize_database(path)

    assert status.path == path
    assert status.schema_version == 2
    assert status.foreign_keys_enabled is True
    assert status.wal_enabled is True
    assert path.is_file()
    assert journal_mode(path) == "wal"
    rows = migration_rows(path)
    assert [row[0] for row in rows] == [1, 2]
    assert all(datetime.fromisoformat(row[1]).tzinfo is not None for row in rows)


def test_second_initialization_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "barbarion.db"
    first_status = initialize_database(path)
    first_rows = migration_rows(path)

    second_status = initialize_database(path)

    assert second_status == first_status
    assert migration_rows(path) == first_rows


def test_schema_contains_h2_tables(tmp_path: Path) -> None:
    path = tmp_path / "barbarion.db"
    initialize_database(path)

    with sqlite3.connect(path) as connection:
        tables = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
        columns = connection.execute(
            "PRAGMA table_info(schema_migrations)"
        ).fetchall()

    assert tables == [
        ("chunks",),
        ("documents",),
        ("errors",),
        ("files",),
        ("ingestion_runs",),
        ("schema_migrations",),
    ]
    assert [
        (column[1], column[2], column[3], column[5])
        for column in columns
    ] == [
        ("version", "INTEGER", 0, 1),
        ("applied_at", "TEXT", 1, 0),
    ]


def test_existing_v1_database_upgrades_to_v2(tmp_path: Path) -> None:
    path = tmp_path / "barbarion.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO schema_migrations VALUES (1, '2026-01-01T00:00:00+00:00')"
        )

    status = initialize_database(path)

    assert status.schema_version == 2
    assert status.foreign_keys_enabled is True
    assert status.wal_enabled is True
    assert journal_mode(path) == "wal"
    assert [row[0] for row in migration_rows(path)] == [1, 2]
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'ingestion_runs'"
        ).fetchone() == ("ingestion_runs",)


def test_connection_uses_five_second_timeout_and_foreign_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "barbarion.db"
    original_connect = sqlite3.connect
    received_timeouts: list[float] = []

    def recording_connect(
        database_path: Path,
        *,
        timeout: float,
    ) -> sqlite3.Connection:
        """Registra el timeout y delega en SQLite real."""
        received_timeouts.append(timeout)
        return original_connect(database_path, timeout=timeout)

    monkeypatch.setattr(sqlite3, "connect", recording_connect)

    status = initialize_database(path)

    assert received_timeouts == [DATABASE_TIMEOUT_SECONDS]
    assert status.foreign_keys_enabled is True
    assert status.wal_enabled is True


def test_h2_schema_contains_expected_indexes(tmp_path: Path) -> None:
    path = tmp_path / "barbarion.db"
    initialize_database(path)

    with sqlite3.connect(path) as connection:
        indexes = {
            row[0]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'index' AND name NOT LIKE 'sqlite_%'
                """
            )
        }

    assert {
        "idx_ingestion_runs_started_at",
        "idx_ingestion_runs_status",
        "idx_files_status",
        "idx_files_artifact_kind",
        "idx_files_sha256",
        "idx_files_last_seen_run_id",
        "idx_files_source_root_last_seen_run_id",
        "idx_documents_content_sha256",
        "idx_chunks_document_ordinal",
        "idx_chunks_object",
        "idx_chunks_content_sha256",
        "idx_errors_run_id",
        "idx_errors_file_id",
        "idx_errors_error_code",
    }.issubset(indexes)


def test_h2_foreign_keys_and_cascade_are_enforced(tmp_path: Path) -> None:
    path = tmp_path / "barbarion.db"
    initialize_database(path)

    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            INSERT INTO ingestion_runs(
                id, domain, mode, status, roots_json, config_sha256, started_at
            )
            VALUES (1, 'default', 'incremental', 'running', '[]', ?, ?)
            """,
            ("a" * 64, "2026-01-01T00:00:00+00:00"),
        )
        connection.execute(
            """
            INSERT INTO files(
                id, domain, source_root, relative_path, extension, artifact_kind,
                media_type, size_bytes, modified_at_ns, status,
                first_seen_run_id, last_seen_run_id, created_at, updated_at
            )
            VALUES (
                10, 'default', 'sources/oracle', 'pkg/body.sql', '.sql',
                'oracle', 'text/plain', 42, 100, 'processed',
                1, 1, ?, ?
            )
            """,
            (
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO documents(
                id, file_id, source_sha256, parser_id, parser_version,
                normalizer_version, normalized_text, content_sha256,
                metadata_json, warnings_json, extracted_at
            )
            VALUES (20, 10, ?, 'oracle', '1', '1', 'select 1;', ?, '{}', '[]', ?)
            """,
            ("b" * 64, "c" * 64, "2026-01-01T00:00:00+00:00"),
        )
        connection.execute(
            """
            INSERT INTO chunks(
                id, document_id, ordinal, chunk_type, content, content_sha256,
                metadata_json, chunker_version, created_at
            )
            VALUES (?, 20, 0, 'file', 'select 1;', ?, '{}', '1', ?)
            """,
            ("chunk-1", "c" * 64, "2026-01-01T00:00:00+00:00"),
        )
        connection.execute(
            """
            INSERT INTO errors(
                run_id, file_id, stage, error_code, message, recoverable,
                details_json, occurred_at
            )
            VALUES (1, 10, 'extraction', 'WARN', 'detalle', 1, '{}', ?)
            """,
            ("2026-01-01T00:00:00+00:00",),
        )

        connection.execute("DELETE FROM files WHERE id = 10")

        assert connection.execute("SELECT COUNT(*) FROM documents").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM chunks").fetchone() == (0,)
        assert connection.execute("SELECT file_id FROM errors").fetchone() == (None,)


def test_h2_constraints_reject_invalid_status_and_negative_counts(
    tmp_path: Path,
) -> None:
    path = tmp_path / "barbarion.db"
    initialize_database(path)

    with sqlite3.connect(path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO ingestion_runs(
                    domain, mode, status, roots_json, config_sha256, started_at
                )
                VALUES ('default', 'incremental', 'unknown', '[]', ?, ?)
                """,
                ("a" * 64, "2026-01-01T00:00:00+00:00"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO ingestion_runs(
                    domain, mode, status, roots_json, config_sha256, started_at,
                    discovered_files
                )
                VALUES ('default', 'incremental', 'running', '[]', ?, ?, -1)
                """,
                ("a" * 64, "2026-01-01T00:00:00+00:00"),
            )


def test_future_schema_fails_with_stable_message_and_preserves_database(
    tmp_path: Path,
) -> None:
    path = tmp_path / "barbarion.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO schema_migrations VALUES (5, 'future')"
        )
        connection.execute("CREATE TABLE future_data(value TEXT)")

    with pytest.raises(DatabaseError) as captured:
        initialize_database(path)

    assert str(captured.value) == (
        "La versión 5 del esquema de base de datos es más reciente que la "
        "admitida por esta versión de Barbarion."
    )
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT version FROM schema_migrations"
        ).fetchone() == (5,)
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'future_data'"
        ).fetchone() == ("future_data",)


def test_failed_migration_rolls_back_schema_and_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "barbarion.db"
    broken_migration = database._Migration(
        version=1,
        statements=(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """,
            "SQL NO VÁLIDO",
        ),
    )
    monkeypatch.setattr(database, "_MIGRATIONS", (broken_migration,))

    with pytest.raises(DatabaseError, match="No se pudo inicializar"):
        initialize_database(path)

    with sqlite3.connect(path) as connection:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'schema_migrations'"
        ).fetchone()
    assert table is None


def test_failed_v2_migration_preserves_v1_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "barbarion.db"
    initialize_database(path)

    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE errors")
        connection.execute("DROP TABLE chunks")
        connection.execute("DROP TABLE documents")
        connection.execute("DROP TABLE files")
        connection.execute("DROP TABLE ingestion_runs")
        connection.execute("DELETE FROM schema_migrations WHERE version = 2")

    broken_v2 = database._Migration(
        version=2,
        statements=(
            "CREATE TABLE ingestion_runs(id INTEGER PRIMARY KEY)",
            "SQL NO VALIDO",
        ),
    )
    monkeypatch.setattr(database, "_MIGRATIONS", (database._MIGRATIONS[0], broken_v2))

    with pytest.raises(DatabaseError, match="No se pudo inicializar"):
        initialize_database(path)

    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall() == [(1,)]
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'ingestion_runs'"
        ).fetchone() is None


def test_open_error_is_reported_without_deleting_path(tmp_path: Path) -> None:
    path = tmp_path / "barbarion.db"
    path.mkdir()

    with pytest.raises(DatabaseError, match="No se pudo abrir"):
        initialize_database(path)

    assert path.is_dir()


def test_locked_database_error_is_actionable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "barbarion.db"

    def locked_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        """Simula una apertura bloqueada sin esperar el timeout real."""
        del args, kwargs
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(sqlite3, "connect", locked_connect)

    with pytest.raises(DatabaseError) as captured:
        initialize_database(path)

    assert "No se pudo abrir" in str(captured.value)
    assert "database is locked" in str(captured.value)
    assert path.exists() is False


def test_wal_unavailable_error_is_actionable_and_closes_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "barbarion.db"

    class FakeCursor:
        def __init__(self, row: tuple[str, ...]) -> None:
            self.row = row

        def fetchone(self) -> tuple[str, ...]:
            """Devuelve una respuesta controlada de SQLite."""
            return self.row

    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False

        def execute(self, statement: str) -> FakeCursor:
            """Simula una base que rechaza WAL."""
            if statement == "PRAGMA journal_mode = WAL":
                return FakeCursor(("delete",))
            return FakeCursor(("ok",))

        def close(self) -> None:
            """Registra cierre tras el fallo."""
            self.closed = True

    fake_connection = FakeConnection()

    def fake_connect(*args: object, **kwargs: object) -> FakeConnection:
        """Devuelve una conexión falsa sin tocar el filesystem."""
        del args, kwargs
        return fake_connection

    monkeypatch.setattr(sqlite3, "connect", fake_connect)

    with pytest.raises(DatabaseError) as captured:
        initialize_database(path)

    assert WAL_UNAVAILABLE_CODE in str(captured.value)
    assert "delete" in str(captured.value)
    assert fake_connection.closed is True
    assert path.exists() is False
