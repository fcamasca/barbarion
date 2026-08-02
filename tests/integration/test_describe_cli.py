"""Pruebas CLI para `barbarion describe`."""

import json
import sqlite3
from pathlib import Path

import pytest

from barbarion import cli
from barbarion.database import initialize_database
from barbarion.domain.models import Confidence
from barbarion.domain.reverse_engineering import (
    AnalysisRunMode,
    EvidenceClassification,
    ResolutionStatus,
    TechnicalReference,
    TechnicalRelation,
    TechnicalSymbol,
    technical_reference_id,
    technical_relation_id,
    technical_symbol_id,
)
from barbarion.infrastructure.sqlite import SQLiteReverseEngineeringRepository


def test_describe_cli_help_lists_formats(capsys: object) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(["describe", "--help"])
    captured = capsys.readouterr()

    assert error.value.code == 0
    assert "describe" in captured.out
    assert "--format" in captured.out
    assert "--no-llm" in captured.out


def test_describe_cli_json_and_ambiguous_candidates(
    tmp_path: Path,
    capsys: object,
) -> None:
    config = _prepare_workspace(tmp_path)
    repository = _seed_graph(tmp_path / "data" / "barbarion.db")

    exit_code = cli.main(
        [
            "--config",
            str(config),
            "describe",
            "duplicado",
            "--format",
            "json",
            "--no-llm",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    payload = json.loads(captured.out)
    assert payload["template_version"] == "component.v1"
    assert payload["resolution"]["status"] == "ambiguous"
    assert {
        candidate["symbol_id"] for candidate in payload["resolution"]["candidates"]
    } == {
        repository["duplicate_a"].symbol_id,
        repository["duplicate_b"].symbol_id,
    }


def test_describe_cli_markdown_output_is_safe(
    tmp_path: Path,
    capsys: object,
) -> None:
    config = _prepare_workspace(tmp_path)
    _seed_graph(tmp_path / "data" / "barbarion.db")
    output_path = tmp_path / "output" / "component.md"

    first = cli.main(
        [
            "--config",
            str(config),
            "describe",
            "pkg.root",
            "--format",
            "markdown",
            "--output",
            str(output_path),
            "--no-llm",
        ]
    )
    first_capture = capsys.readouterr()
    second = cli.main(
        [
            "--config",
            str(config),
            "describe",
            "pkg.root",
            "--format",
            "markdown",
            "--output",
            str(output_path),
            "--no-llm",
        ]
    )
    second_capture = capsys.readouterr()

    assert first == 0, first_capture.err
    content = output_path.read_text(encoding="utf-8")
    assert "# Ficha de componente" in content
    assert "template_version: component.v1" in content
    assert second == 1
    assert "El archivo ya existe" in second_capture.err


def test_describe_with_llm_uses_provider_selected_by_shared_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _prepare_workspace(tmp_path)
    _enable_anthropic(config)
    _seed_graph(tmp_path / "data" / "barbarion.db")
    provider = _RecordingLlmProvider("Sintesis Anthropic controlada.")
    configured_providers: list[str] = []

    def build_provider(settings):  # noqa: ANN001, ANN202
        configured_providers.append(settings.llm.provider)
        return provider

    monkeypatch.setattr(cli, "_build_llm_provider", build_provider)

    assert cli.main(
        [
            "--config",
            str(config),
            "describe",
            "pkg.root",
            "--with-llm",
            "--format",
            "json",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["summary"] == "Sintesis Anthropic controlada."
    assert payload["no_llm"] is False
    assert configured_providers == ["anthropic"]
    assert len(provider.calls) == 1
    assert "Datos deterministas:" in provider.calls[0][0]


class _RecordingLlmProvider:
    def __init__(self, response: str, *, fail: bool = False) -> None:
        self.response = response
        self.fail = fail
        self.calls: list[tuple[str, float]] = []

    def generate(self, *, prompt: str, timeout_seconds: float) -> str:
        self.calls.append((prompt, timeout_seconds))
        if self.fail:
            raise RuntimeError("fallo remoto sintetico")
        return self.response


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
        connection.execute(
            """
            INSERT INTO files(
                id, domain, source_root, relative_path, extension, artifact_kind,
                media_type, size_bytes, modified_at_ns, sha256, status,
                first_seen_run_id, last_seen_run_id, created_at, updated_at
            )
            VALUES (
                1, 'integration', 'root', 'oracle/pkg_root.pkb', '.pkb',
                'oracle', 'text/plain', 10, 1, ?, 'processed', 1, 1, ?, ?
            )
            """,
            ("b" * 64, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
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
            ]
        ),
        encoding="utf-8",
    )
    return config


def _enable_anthropic(config: Path) -> None:
    with config.open("a", encoding="utf-8") as stream:
        stream.write(
            """

[llm]
provider = "anthropic"
model = "claude-synthetic"
timeout_seconds = 12.0
temperature = 0.1
max_output_tokens = 1024
"""
        )


def _seed_graph(db_path: Path) -> dict[str, TechnicalSymbol]:
    repository = SQLiteReverseEngineeringRepository(db_path)
    run_id = repository.begin_analysis_run(
        mode=AnalysisRunMode.INCREMENTAL,
        scope={"stage": "describe-fixture"},
    )
    root = _symbol("pkg.root", file_id=1)
    dependency = _symbol("pkg.dependency", file_id=1)
    consumer = _symbol(
        "w_root",
        technology="powerbuilder",
        container_name="w",
        file_id=1,
    )
    duplicate_a = _symbol("duplicado", container_name="pkg_a")
    duplicate_b = _symbol("duplicado", container_name="pkg_b")
    for symbol in (root, dependency, consumer, duplicate_a, duplicate_b):
        repository.upsert_symbol(run_id=run_id, symbol=symbol)
    for relation in (_relation(root, dependency), _relation(consumer, root)):
        repository.upsert_reference(
            run_id=run_id,
            reference=_reference_for_relation(relation),
        )
        repository.upsert_relation(run_id=run_id, relation=relation)
    return {
        "root": root,
        "dependency": dependency,
        "consumer": consumer,
        "duplicate_a": duplicate_a,
        "duplicate_b": duplicate_b,
    }


def _symbol(
    normalized_name: str,
    *,
    technology: str = "oracle",
    container_name: str = "pkg",
    file_id: int | None = None,
    chunk_id: str | None = None,
) -> TechnicalSymbol:
    symbol_id = technical_symbol_id(
        normalized_name=normalized_name,
        symbol_type="procedure",
        technology=technology,
        container_name=container_name,
    )
    return TechnicalSymbol(
        symbol_id=symbol_id,
        original_name=normalized_name,
        normalized_name=normalized_name,
        symbol_type="procedure",
        technology=technology,
        extraction_method="fixture",
        confidence=Confidence.HIGH,
        file_id=file_id,
        chunk_id=chunk_id,
        container_name=container_name,
    )


def _reference_for_relation(relation: TechnicalRelation) -> TechnicalReference:
    return TechnicalReference(
        reference_id=relation.reference_id,
        source_file_id=relation.evidence_file_id,
        source_symbol_id=relation.source_symbol_id,
        source_chunk_id=relation.evidence_chunk_id,
        raw_text=relation.target_key or relation.target_symbol_id or "target",
        normalized_target=relation.target_key or "target",
        reference_type=relation.relation_type,
        technology="oracle",
        detection_method="fixture",
        confidence=relation.confidence,
        resolution_status=relation.resolution_status,
    )


def _relation(source: TechnicalSymbol, target: TechnicalSymbol) -> TechnicalRelation:
    reference_id = technical_reference_id(
        source_file_id=1,
        raw_text=f"{source.normalized_name}->{target.normalized_name}",
        normalized_target=target.normalized_name,
        reference_type="calls",
    )
    relation_id = technical_relation_id(
        reference_id=reference_id,
        relation_type="calls",
        source_symbol_id=source.symbol_id,
        target_symbol_id=target.symbol_id,
    )
    return TechnicalRelation(
        relation_id=relation_id,
        reference_id=reference_id,
        source_symbol_id=source.symbol_id,
        target_symbol_id=target.symbol_id,
        target_key=target.normalized_name,
        relation_type="calls",
        classification=EvidenceClassification.DETECTED,
        resolution_status=ResolutionStatus.RESOLVED,
        confidence=Confidence.MEDIUM,
        evidence_file_id=1,
    )
