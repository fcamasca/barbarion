"""Inicialización y verificación de la base SQLite local."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from barbarion.infrastructure.sqlite import (
    INGESTION_SCHEMA_STATEMENTS,
    RAG_SCHEMA_STATEMENTS,
)

DATABASE_TIMEOUT_SECONDS = 5.0
WAL_UNAVAILABLE_CODE = "DATABASE_WAL_UNAVAILABLE"
FUTURE_SCHEMA_MESSAGE = (
    "La versión {version} del esquema de base de datos es más reciente que la "
    "admitida por esta versión de Barbarion."
)


class DatabaseError(RuntimeError):
    """Error esperado al abrir, migrar o comprobar SQLite."""


@dataclass(frozen=True, slots=True)
class DatabaseStatus:
    """Estado mínimo de una base SQLite preparada correctamente."""

    path: Path
    schema_version: int
    foreign_keys_enabled: bool
    wal_enabled: bool


@dataclass(frozen=True, slots=True)
class _Migration:
    """Migración SQL pequeña y ordenada por versión."""

    version: int
    statements: tuple[str, ...]


_MIGRATIONS = (
    _Migration(
        version=1,
        statements=(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """,
        ),
    ),
    _Migration(
        version=2,
        statements=INGESTION_SCHEMA_STATEMENTS,
    ),
    _Migration(
        version=3,
        statements=RAG_SCHEMA_STATEMENTS,
    ),
)


def initialize_database(database_path: Path) -> DatabaseStatus:
    """Crea, migra y comprueba una base SQLite de forma idempotente."""
    path = Path(database_path).expanduser().resolve(strict=False)
    connection = _open_connection(path)
    try:
        current_version = _read_schema_version(connection)
        supported_version = _supported_schema_version()
        if current_version > supported_version:
            raise DatabaseError(
                FUTURE_SCHEMA_MESSAGE.format(version=current_version)
            )

        for migration in _MIGRATIONS:
            if migration.version > current_version:
                _apply_migration(connection, migration)

        schema_version = _read_schema_version(connection)
        foreign_keys_enabled, wal_enabled = _check_health(connection)
        return DatabaseStatus(
            path=path,
            schema_version=schema_version,
            foreign_keys_enabled=foreign_keys_enabled,
            wal_enabled=wal_enabled,
        )
    except DatabaseError:
        raise
    except sqlite3.Error as error:
        raise DatabaseError(
            f"No se pudo inicializar la base SQLite '{path}': {error}."
        ) from error
    finally:
        connection.close()


def _open_connection(path: Path) -> sqlite3.Connection:
    """Abre una conexión y activa las claves foráneas."""
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(path, timeout=DATABASE_TIMEOUT_SECONDS)
        connection.execute("PRAGMA foreign_keys = ON")
        _enable_wal(connection)
        return connection
    except DatabaseError:
        if connection is not None:
            connection.close()
        raise
    except sqlite3.Error as error:
        if connection is not None:
            connection.close()
        raise DatabaseError(
            f"No se pudo abrir la base SQLite '{path}': {error}."
        ) from error


def _enable_wal(connection: sqlite3.Connection) -> None:
    """Activa WAL y falla si SQLite no confirma el modo solicitado."""
    row = connection.execute("PRAGMA journal_mode = WAL").fetchone()
    if row is None or str(row[0]).lower() != "wal":
        observed = "sin respuesta" if row is None else str(row[0])
        raise DatabaseError(
            f"{WAL_UNAVAILABLE_CODE}: SQLite no pudo activar journal_mode=WAL "
            f"(respuesta: {observed})."
        )


def _read_schema_version(connection: sqlite3.Connection) -> int:
    """Obtiene la versión registrada o cero si la base está vacía."""
    table_exists = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = 'schema_migrations'
        """
    ).fetchone()
    if table_exists is None:
        return 0

    row = connection.execute(
        "SELECT MAX(version) FROM schema_migrations"
    ).fetchone()
    if row is None or row[0] is None:
        return 0
    return int(row[0])


def _supported_schema_version() -> int:
    """Devuelve la mayor versión incluida en esta aplicación."""
    return max(migration.version for migration in _MIGRATIONS)


def _apply_migration(
    connection: sqlite3.Connection,
    migration: _Migration,
) -> None:
    """Aplica una migración completa dentro de una transacción explícita."""
    try:
        connection.execute("BEGIN IMMEDIATE")
        for statement in migration.statements:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (
                migration.version,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def _check_health(connection: sqlite3.Connection) -> tuple[bool, bool]:
    """Comprueba consulta básica, claves foráneas, WAL y versión registrada."""
    health_row = connection.execute("SELECT 1").fetchone()
    if health_row != (1,):
        raise DatabaseError("La comprobación básica de SQLite falló.")

    foreign_keys_row = connection.execute("PRAGMA foreign_keys").fetchone()
    if foreign_keys_row != (1,):
        raise DatabaseError("SQLite no tiene habilitadas las claves foráneas.")

    journal_mode_row = connection.execute("PRAGMA journal_mode").fetchone()
    if journal_mode_row is None or str(journal_mode_row[0]).lower() != "wal":
        observed = (
            "sin respuesta" if journal_mode_row is None else str(journal_mode_row[0])
        )
        raise DatabaseError(
            f"{WAL_UNAVAILABLE_CODE}: SQLite no conserva journal_mode=WAL "
            f"(respuesta: {observed})."
        )

    schema_version = _read_schema_version(connection)
    if schema_version != _supported_schema_version():
        raise DatabaseError(
            "La versión del esquema SQLite no coincide con la versión esperada."
        )
    return True, True
