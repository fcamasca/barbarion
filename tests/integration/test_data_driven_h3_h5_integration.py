"""Integracion Data-Driven con recuperacion RAG y Spec Mode."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from barbarion import cli
from barbarion.application.rag import IndexService, SearchService
from barbarion.application.spec_mode import SpecValidator
from barbarion.config import Settings
from barbarion.database import initialize_database
from barbarion.infrastructure.embeddings import DeterministicFakeEmbeddingProvider
from barbarion.infrastructure.sqlite import SQLiteRagRepository
from barbarion.infrastructure.sqlite_vec import SQLiteVecStore


def test_data_driven_dml_is_available_to_rag_ask_and_spec_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Recorre DML desde ingesta hasta evidencia y componentes de una spec.

    Args:
        tmp_path: Workspace temporal aislado usado por la integracion.
        monkeypatch: Reemplaza embeddings locales por un proveedor determinista.
        capsys: Captura las salidas CLI para validar sus contratos.
    """
    config = _prepare_workspace(tmp_path)
    monkeypatch.setattr(cli, "_build_index_service", _fake_index_service)
    monkeypatch.setattr(cli, "_build_search_service", _fake_search_service)

    assert cli.main(["--config", str(config), "ingest"]) == 0
    capsys.readouterr()
    assert cli.main(["--config", str(config), "analyze", "--full"]) == 0
    capsys.readouterr()
    assert cli.main(["--config", str(config), "index"]) == 0
    capsys.readouterr()

    assert cli.main(
        [
            "--config",
            str(config),
            "search",
            "pricing_rules",
            "--mode",
            "keyword",
            "--format",
            "json",
        ]
    ) == 0
    keyword = json.loads(capsys.readouterr().out)
    assert keyword["mode"] == "keyword"
    assert keyword["results"][0]["source"]["artifact_kind"] == "configuration"
    assert keyword["results"][0]["source"]["relative_path"].endswith("rules.sql")

    assert cli.main(
        [
            "--config",
            str(config),
            "search",
            "TAX_RATE",
            "--mode",
            "hybrid",
            "--format",
            "json",
        ]
    ) == 0
    hybrid = json.loads(capsys.readouterr().out)
    assert hybrid["mode"] == "hybrid"
    assert hybrid["results"][0]["source"]["artifact_kind"] == "configuration"
    assert hybrid["results"][0]["keyword_score"] is not None
    assert hybrid["results"][0]["vector_score"] is not None

    assert cli.main(
        [
            "--config",
            str(config),
            "ask",
            "Que formula de pricing_rules usa TAX_RATE?",
            "--mode",
            "keyword",
            "--no-llm",
            "--format",
            "json",
        ]
    ) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["no_llm"] is True
    assert answer["status"] == "completed"
    assert "[F1]" in answer["answer"]
    assert answer["sources"][0]["source"]["artifact_kind"] == "configuration"

    output_dir = tmp_path / "output" / "specs" / "pricing-change"
    assert cli.main(
        [
            "--config",
            str(config),
            "spec",
            "create",
            "Modificar `pricing_rules.r2` para ajustar TAX_RATE",
            "--mode",
            "keyword",
            "--top-k",
            "3",
            "--depth",
            "1",
            "--no-llm",
            "--output",
            str(output_dir),
        ]
    ) == 0
    spec_output = capsys.readouterr()
    assert "Spec escrita:" in spec_output.out

    documents = {
        name: (output_dir / name).read_text(encoding="utf-8")
        for name in ("requirements.md", "design.md", "tasks.md", "test-plan.md")
    }
    assert SpecValidator().validate(documents).valid is True
    assert (
        "`pricing_rules.r2` rol=directo tecnologia=configuration"
        in documents["design.md"]
    )
    assert "config/pricing/rules.sql" in documents["requirements.md"]


def _prepare_workspace(tmp_path: Path) -> Path:
    """Crea un corpus DML y configuracion local para la integracion.

    Args:
        tmp_path: Directorio temporal donde se crea el workspace.

    Returns:
        Ruta del archivo TOML de la prueba.
    """
    corpus = tmp_path / "sources"
    source_dir = corpus / "config" / "pricing"
    source_dir.mkdir(parents=True)
    (source_dir / "rules.sql").write_text(
        """
        INSERT INTO APP_CFG.PRICING_RULES (RULE_ID, RULE_NAME, FORMULA)
        VALUES ('R1', 'Base Rule', '{AMOUNT}');

        INSERT INTO APP_CFG.PRICING_RULES (RULE_ID, RULE_NAME, FORMULA)
        VALUES ('R2', 'Tax Rule', '{AMOUNT} + TAX_RATE()');
        """,
        encoding="utf-8",
    )
    for name in ("data", "output", "logs"):
        (tmp_path / name).mkdir()
    initialize_database(tmp_path / "data" / "barbarion.db")
    config = tmp_path / "barbarion.toml"
    config.write_text(
        "\n".join(
            (
                'domain = "integration"',
                'data_dir = "data"',
                'output_dir = "output"',
                'logs_dir = "logs"',
                'database_path = "data/barbarion.db"',
                "[ingestion]",
                f'paths = ["{corpus.as_posix()}"]',
                'extensions = [".sql"]',
                "chunk_size = 500",
                "chunk_overlap = 20",
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
            )
        ),
        encoding="utf-8",
    )
    return config


def _fake_index_service(settings: Settings) -> IndexService:
    """Construye indexacion local con embeddings deterministas.

    Args:
        settings: Configuracion efectiva cargada por la CLI.

    Returns:
        Servicio de indexacion sin dependencias de red.
    """
    return IndexService(
        settings=settings,
        repository=SQLiteRagRepository(settings.database_path),
        embedding_provider=DeterministicFakeEmbeddingProvider(dimension=4),
        vector_store=SQLiteVecStore(settings.database_path),
    )


def _fake_search_service(settings: Settings) -> SearchService:
    """Construye busqueda local compatible con el indice determinista.

    Args:
        settings: Configuracion efectiva cargada por la CLI.

    Returns:
        Servicio de busqueda keyword, semantica e hibrida sin red.
    """
    return SearchService(
        settings=settings,
        repository=SQLiteRagRepository(settings.database_path),
        embedding_provider=DeterministicFakeEmbeddingProvider(dimension=4),
        vector_store=SQLiteVecStore(settings.database_path),
    )
