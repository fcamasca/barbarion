"""Pruebas de inicialización, migración y salud de SQLite."""

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from barbarion import database
from barbarion.database import (
    DATABASE_TIMEOUT_SECONDS,
    DatabaseError,
    initialize_database,
)


def migration_rows(path: Path) -> list[tuple[int, str]]:
    """Lee las migraciones registradas sin modificar la base."""
    with sqlite3.connect(path) as connection:
        return connection.execute(
            "SELECT version, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()


def test_new_database_creates_schema_version_one(tmp_path: Path) -> None:
    path = tmp_path / "barbarion.db"

    status = initialize_database(path)

    assert status.path == path
    assert status.schema_version == 1
    assert status.foreign_keys_enabled is True
    assert path.is_file()
    rows = migration_rows(path)
    assert len(rows) == 1
    assert rows[0][0] == 1
    assert datetime.fromisoformat(rows[0][1]).tzinfo is not None


def test_second_initialization_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "barbarion.db"
    first_status = initialize_database(path)
    first_rows = migration_rows(path)

    second_status = initialize_database(path)

    assert second_status == first_status
    assert migration_rows(path) == first_rows


def test_schema_contains_only_migration_table(tmp_path: Path) -> None:
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

    assert tables == [("schema_migrations",)]
    assert [
        (column[1], column[2], column[3], column[5])
        for column in columns
    ] == [
        ("version", "INTEGER", 0, 1),
        ("applied_at", "TEXT", 1, 0),
    ]


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
