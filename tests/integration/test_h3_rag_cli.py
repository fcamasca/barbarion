from __future__ import annotations

from pathlib import Path

import pytest

from barbarion import cli
from barbarion.application.rag import IndexService
from barbarion.database import initialize_database
from barbarion.infrastructure.embeddings import DeterministicFakeEmbeddingProvider
from barbarion.infrastructure.sqlite import SQLiteRagRepository
from barbarion.infrastructure.sqlite_vec import SQLiteVecStore


def write_config(tmp_path: Path, corpus: Path) -> Path:
    source = tmp_path / "barbarion.toml"
    source.write_text(
        "\n".join(
            [
                'domain = "h3"',
                'data_dir = "data"',
                'output_dir = "output"',
                'logs_dir = "logs"',
                'database_path = "data/barbarion.db"',
                "[ingestion]",
                f'paths = ["{corpus.as_posix()}"]',
                'extensions = [".sql", ".md"]',
                "chunk_size = 500",
                "chunk_overlap = 0",
            ]
        ),
        encoding="utf-8",
    )
    return source


def prepare(tmp_path: Path) -> tuple[Path, Path]:
    corpus = tmp_path / "corpus"
    (corpus / "oracle").mkdir(parents=True)
    (corpus / "docs").mkdir()
    (corpus / "oracle" / "costos.sql").write_text(
        "create or replace procedure demo as\n"
        "begin\n"
        "  COSTO_AMORT_DIA := 10;\n"
        "end;\n",
        encoding="utf-8",
    )
    (corpus / "docs" / "manual.md").write_text(
        "# Manual\n\nCDVAL se usa para validar operaciones.",
        encoding="utf-8",
    )
    for name in ("data", "output", "logs"):
        (tmp_path / name).mkdir()
    initialize_database(tmp_path / "data" / "barbarion.db")
    return write_config(tmp_path, corpus), tmp_path / "data" / "barbarion.db"


def test_h3_cli_index_search_ask_stats_with_fakes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config, db_path = prepare(tmp_path)

    def fake_index_service(settings):
        return IndexService(
            settings=settings,
            repository=SQLiteRagRepository(settings.database_path),
            embedding_provider=DeterministicFakeEmbeddingProvider(dimension=4),
            vector_store=SQLiteVecStore(settings.database_path),
        )

    monkeypatch.setattr(cli, "_build_index_service", fake_index_service)

    assert cli.main(["--config", str(config), "ingest"]) == 0
    assert cli.main(["--config", str(config), "index"]) == 0
    first_index = capsys.readouterr().out
    assert "Indexacion RAG: completed" in first_index

    assert cli.main(["--config", str(config), "index"]) == 0
    second_index = capsys.readouterr().out
    assert "Sin cambios:" in second_index

    assert cli.main(["--config", str(config), "reindex", "--full"]) == 0
    reindex = capsys.readouterr().out
    assert "Indexacion RAG: completed" in reindex

    assert cli.main(
        [
            "--config",
            str(config),
            "search",
            "COSTO_AMORT_DIA",
            "--mode",
            "keyword",
        ]
    ) == 0
    assert "costos.sql" in capsys.readouterr().out

    assert cli.main(
        [
            "--config",
            str(config),
            "ask",
            "Que documentos hablan de CDVAL?",
            "--mode",
            "keyword",
            "--no-llm",
        ]
    ) == 0
    assert "Modo sin LLM" in capsys.readouterr().out

    assert cli.main(["--config", str(config), "stats"]) == 0
    assert "Estadisticas RAG" in capsys.readouterr().out

    assert cli.main(["--config", str(config), "embeddings"]) == 0
    assert "Embeddings RAG" in capsys.readouterr().out
    assert db_path.exists()
