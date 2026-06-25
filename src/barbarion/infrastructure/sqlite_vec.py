"""Adaptador vectorial local inicial respaldado por SQLite."""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from barbarion.domain.rag import (
    EmbeddingManifest,
    H4SymbolMetadata,
    RetrievalCandidate,
    RetrievalFilter,
    VectorMetadata,
    VectorStoreError,
)


@dataclass(frozen=True, slots=True)
class SQLiteVecStore:
    """Vector store local inicial, preparado para sqlite-vec."""

    database_path: Path
    table_prefix: str = "rag"

    def ensure_schema(self) -> None:
        """Crea las tablas locales usadas por el adaptador."""
        vector_table = self._vector_table
        with self._connect() as connection:
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {vector_table} (
                    manifest_version TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    vector_json TEXT NOT NULL,
                    dimension INTEGER NOT NULL CHECK (dimension > 0),
                    content_sha256 TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    artifact_kind TEXT,
                    language TEXT,
                    document_id INTEGER,
                    file_id INTEGER,
                    relative_path TEXT,
                    folder TEXT,
                    extension TEXT,
                    object_type TEXT,
                    object_name TEXT,
                    symbol_name TEXT,
                    symbol_kind TEXT,
                    parent_symbol TEXT,
                    package_name TEXT,
                    procedure_name TEXT,
                    class_name TEXT,
                    event_name TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(manifest_version, chunk_id)
                )
                """
            )
            connection.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{vector_table}_filters
                ON {vector_table}(
                    manifest_version, domain, artifact_kind, language,
                    document_id, folder, extension
                )
                """
            )
            connection.commit()

    def upsert(
        self,
        *,
        manifest: EmbeddingManifest,
        chunk_id: str,
        vector: Sequence[float],
        metadata: VectorMetadata,
    ) -> None:
        """Inserta o reemplaza un vector asociado a un chunk."""
        values = _validate_vector(vector, manifest)
        self.ensure_schema()
        symbols = metadata.symbols
        with self._connect() as connection:
            connection.execute(
                f"""
                INSERT INTO {self._vector_table}(
                    manifest_version, chunk_id, vector_json, dimension,
                    content_sha256, domain, artifact_kind, language, document_id,
                    file_id, relative_path, folder, extension, object_type,
                    object_name, symbol_name, symbol_kind, parent_symbol,
                    package_name, procedure_name, class_name, event_name
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(manifest_version, chunk_id) DO UPDATE SET
                    vector_json = excluded.vector_json,
                    dimension = excluded.dimension,
                    content_sha256 = excluded.content_sha256,
                    domain = excluded.domain,
                    artifact_kind = excluded.artifact_kind,
                    language = excluded.language,
                    document_id = excluded.document_id,
                    file_id = excluded.file_id,
                    relative_path = excluded.relative_path,
                    folder = excluded.folder,
                    extension = excluded.extension,
                    object_type = excluded.object_type,
                    object_name = excluded.object_name,
                    symbol_name = excluded.symbol_name,
                    symbol_kind = excluded.symbol_kind,
                    parent_symbol = excluded.parent_symbol,
                    package_name = excluded.package_name,
                    procedure_name = excluded.procedure_name,
                    class_name = excluded.class_name,
                    event_name = excluded.event_name,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    manifest.version,
                    chunk_id,
                    _vector_json(values),
                    manifest.dimension,
                    metadata.content_sha256,
                    metadata.domain,
                    metadata.artifact_kind,
                    metadata.language,
                    metadata.document_id,
                    metadata.file_id,
                    metadata.relative_path,
                    metadata.folder,
                    metadata.extension,
                    metadata.object_type,
                    metadata.object_name,
                    symbols.symbol_name,
                    symbols.symbol_kind,
                    symbols.parent_symbol,
                    symbols.package_name,
                    symbols.procedure_name,
                    symbols.class_name,
                    symbols.event_name,
                ),
            )
            connection.commit()

    def delete(self, *, manifest: EmbeddingManifest, chunk_id: str) -> None:
        """Elimina un vector asociado a un chunk."""
        self.ensure_schema()
        with self._connect() as connection:
            connection.execute(
                f"""
                DELETE FROM {self._vector_table}
                WHERE manifest_version = ? AND chunk_id = ?
                """,
                (manifest.version, chunk_id),
            )
            connection.commit()

    def search(
        self,
        *,
        manifest: EmbeddingManifest,
        query_vector: Sequence[float],
        filters: RetrievalFilter,
        top_k: int,
    ) -> tuple[RetrievalCandidate, ...]:
        """Busca los vectores mas similares usando similitud coseno."""
        if top_k <= 0:
            raise VectorStoreError("VECTOR_TOP_K_INVALID: top_k debe ser mayor que 0.")
        query = _validate_vector(query_vector, manifest)
        self.ensure_schema()
        clauses = ["manifest_version = ?"]
        parameters: list[Any] = [manifest.version]
        _append_filter(clauses, parameters, "domain", filters.domain)
        _append_filter(clauses, parameters, "artifact_kind", filters.artifact_kind)
        _append_filter(clauses, parameters, "language", filters.language)
        _append_filter(clauses, parameters, "document_id", filters.document_id)
        _append_filter(clauses, parameters, "folder", filters.folder)
        _append_filter(clauses, parameters, "extension", filters.extension)
        where = " AND ".join(clauses)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM {self._vector_table}
                WHERE {where}
                """,
                tuple(parameters),
            ).fetchall()

        candidates = []
        for row in rows:
            vector = tuple(float(value) for value in json.loads(row["vector_json"]))
            score = _cosine_similarity(query, vector)
            candidates.append(_candidate_from_row(row, score))
        candidates.sort(key=lambda item: (-item.combined_score, item.chunk_id))
        return tuple(candidates[:top_k])

    @property
    def _vector_table(self) -> str:
        return f"{_validate_identifier(self.table_prefix)}_vectors"

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def _validate_vector(
    vector: Sequence[float],
    manifest: EmbeddingManifest,
) -> tuple[float, ...]:
    values = tuple(float(value) for value in vector)
    if len(values) != manifest.dimension:
        raise VectorStoreError(
            "VECTOR_DIMENSION_MISMATCH: la dimension del vector no coincide "
            "con el manifest."
        )
    if any(math.isnan(value) or math.isinf(value) for value in values):
        raise VectorStoreError("VECTOR_VALUE_INVALID: el vector contiene NaN o infinito.")
    return values


def _vector_json(values: Sequence[float]) -> str:
    return json.dumps(tuple(values), separators=(",", ":"), ensure_ascii=False)


def _append_filter(
    clauses: list[str],
    parameters: list[Any],
    column: str,
    value: object | None,
) -> None:
    if value is not None:
        clauses.append(f"{column} = ?")
        parameters.append(value)


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return max(0.0, min(1.0, numerator / (left_norm * right_norm)))


def _candidate_from_row(row: sqlite3.Row, score: float) -> RetrievalCandidate:
    metadata = H4SymbolMetadata(
        symbol_name=row["symbol_name"],
        symbol_kind=row["symbol_kind"],
        parent_symbol=row["parent_symbol"],
        package_name=row["package_name"],
        procedure_name=row["procedure_name"],
        class_name=row["class_name"],
        event_name=row["event_name"],
    )
    return RetrievalCandidate(
        chunk_id=str(row["chunk_id"]),
        content_sha256=str(row["content_sha256"]),
        combined_score=score,
        vector_score=score,
        metadata=metadata,
        source={
            "domain": row["domain"],
            "artifact_kind": row["artifact_kind"],
            "language": row["language"],
            "document_id": row["document_id"],
            "file_id": row["file_id"],
            "relative_path": row["relative_path"],
            "folder": row["folder"],
            "extension": row["extension"],
            "object_type": row["object_type"],
            "object_name": row["object_name"],
        },
    )


def _validate_identifier(value: str) -> str:
    if (
        not value
        or not (value[0].isalpha() or value[0] == "_")
        or any(not (character.isalnum() or character == "_") for character in value)
    ):
        raise VectorStoreError("VECTOR_TABLE_PREFIX_INVALID: prefijo invalido.")
    return value
