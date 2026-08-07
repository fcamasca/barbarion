"""Pruebas del árbol y los códigos base de la CLI."""

import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from barbarion import __version__
from barbarion import cli
from barbarion.database import initialize_database
from barbarion.domain.models import (
    ErrorStage,
    IngestionMetrics,
    IngestionMode,
    IngestionOutcome,
    IngestionRunStatus,
    PipelineError,
)
from barbarion.domain.progress import ProgressSnapshot
from barbarion.domain.rag import (
    AnswerResult,
    ContextBuildResult,
    ContextQualityMetrics,
    ContextSource,
    EmbeddingRunStatus,
    IndexRunSummary,
    LlmProviderError,
    RagQueryStatus,
    RetrievalCandidate,
    RetrievalMode,
    SearchResponse,
    SearchTimings,
)
from barbarion.infrastructure.anthropic import (
    AnthropicLlmProvider,
    AnthropicUsage,
)
from barbarion.logging_config import LOGGER_NAME, LOG_FILENAME


@pytest.fixture(autouse=True)
def isolate_barbarion_logger() -> None:
    """Evita que handlers de logging sobrevivan entre pruebas."""
    logger = logging.getLogger(LOGGER_NAME)
    original_handlers = list(logger.handlers)
    original_level = logger.level
    original_propagate = logger.propagate
    logger.handlers.clear()

    yield

    for handler in tuple(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.handlers[:] = original_handlers
    logger.setLevel(original_level)
    logger.propagate = original_propagate


def run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Ejecuta la CLI como módulo en un proceso aislado."""
    environment = os.environ.copy()
    environment.pop("BARBARION_CONFIG", None)
    return subprocess.run(
        [sys.executable, "-m", "barbarion", *args],
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
    )


def test_source_json_keeps_content_path_and_lines_as_separate_fields() -> None:
    """Impide reemplazar silenciosamente contenido de evidencia por su ruta."""
    content = "CREATE FUNCTION synthetic_rule RETURN NUMBER AS BEGIN RETURN 1; END;"
    candidate = RetrievalCandidate(
        chunk_id="chunk-source-contract",
        content_sha256="a" * 64,
        combined_score=0.9,
        source={
            "relative_path": "oracle/synthetic_rule.fnc",
            "start_line": 4,
            "end_line": 7,
            "content": content,
        },
    )
    source = ContextSource(
        source_id="F1",
        candidate=candidate,
        content=content,
        token_estimate=17,
        original_token_estimate=17,
    )

    rendered = cli._source_json(source)

    assert rendered["content"] == content
    assert rendered["relative_path"] == "oracle/synthetic_rule.fnc"
    assert rendered["start_line"] == 4
    assert rendered["end_line"] == 7
    assert rendered["content"] != rendered["relative_path"]


@pytest.mark.parametrize(
    ("args", "expected_text"),
    [
        (("--help",), "comandos:"),
        (("config", "--help"), "subcomandos:"),
        (("config", "show", "--help"), "Muestra la configuración efectiva"),
        (("models", "--help"), "subcomandos:"),
        (("models", "list", "--help"), "Lista modelos instalados"),
        (("models", "show", "--help"), "Muestra metadata segura"),
        (("models", "install", "--help"), "Solicita a Ollama"),
        (("models", "validate", "--help"), "Valida readiness"),
        (("models", "select", "--help"), "Valida y selecciona"),
        (("models", "benchmark", "--help"), "benchmark secuencial"),
        (("doctor", "--help"), "Diagnostica el entorno local"),
        (("ingest", "--help"), "Ejecuta ingesta local"),
        (("index", "--help"), "Ejecuta indexacion RAG incremental"),
        (("reindex", "--help"), "Ejecuta reindexacion RAG"),
        (("search", "--help"), "Busca evidencia RAG local"),
        (("ask", "--help"), "Responde una pregunta"),
        (("embeddings", "--help"), "Muestra manifests"),
        (("stats", "--help"), "Muestra estadisticas"),
        (("generate-report", "--help"), "Genera reportes"),
    ],
)
def test_help_is_in_spanish_and_has_no_side_effects(
    args: tuple[str, ...],
    expected_text: str,
    tmp_path: Path,
) -> None:
    result = run_cli(*args, cwd=tmp_path)

    assert result.returncode == 0
    assert "uso:" in result.stdout
    assert "muestra esta ayuda y finaliza" in result.stdout
    assert expected_text in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_version_uses_package_version_without_side_effects(tmp_path: Path) -> None:
    result = run_cli("--version", cwd=tmp_path)

    assert result.returncode == 0
    assert result.stdout.strip() == f"barbarion {__version__}"
    assert list(tmp_path.iterdir()) == []


def test_invalid_arguments_return_two_without_traceback() -> None:
    result = run_cli("comando-inexistente")

    assert result.returncode == 2
    assert "argumentos inválidos" in result.stderr
    assert "Traceback" not in result.stderr



def test_keyboard_interrupt_returns_130(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class InterruptedParser:
        """Doble mínimo que simula una interrupción durante el parsing."""

        def parse_args(self, args: object) -> object:
            """Interrumpe el flujo antes de producir argumentos."""
            del args
            raise KeyboardInterrupt

    monkeypatch.setattr(cli, "build_parser", InterruptedParser)

    assert cli.main([]) == 130
    assert "Operación interrumpida por el usuario." in capsys.readouterr().err

def test_config_show_uses_defaults_without_side_effects(tmp_path: Path) -> None:
    result = run_cli("config", "show", cwd=tmp_path)

    assert result.returncode == 0
    lines = result.stdout.splitlines()
    assert lines[0] == "origen = valores predeterminados"
    assert lines[1] == "archivo_configuracion = ninguno"
    assert f"data_dir = {tmp_path / 'data'}" in lines
    assert f"database_path = {tmp_path / 'data' / 'barbarion.db'}" in lines
    assert "ingestion.max_file_size_mb = 50" in lines
    assert list(tmp_path.iterdir()) == []


def test_config_show_uses_file_and_stable_field_order(tmp_path: Path) -> None:
    source = tmp_path / "settings.toml"
    source.write_text('domain = "legacy"\nlog_level = "debug"\n', encoding="utf-8")

    result = run_cli("--config", str(source), "config", "show", cwd=tmp_path)

    assert result.returncode == 0
    lines = result.stdout.splitlines()
    keys = [line.partition(" = ")[0] for line in lines]
    assert keys == [
        "origen",
        "archivo_configuracion",
        "domain",
        "data_dir",
        "output_dir",
        "logs_dir",
        "database_path",
        "log_level",
        "ollama_url",
        "ollama_timeout_seconds",
        "ingestion.paths",
        "ingestion.extensions",
        "ingestion.chunk_size",
        "ingestion.chunk_overlap",
        "ingestion.ignore_patterns",
        "ingestion.max_file_size_mb",
        "ingestion.max_extracted_chars",
        "ingestion.max_pdf_pages",
        "ingestion.encodings",
        "embeddings.provider",
        "embeddings.model",
        "embeddings.batch_size",
        "embeddings.timeout_seconds",
        "embeddings.normalize",
        "vector_store.provider",
        "vector_store.table_prefix",
        "vector_store.distance",
        "retrieval.mode",
        "retrieval.top_k",
        "retrieval.candidate_k",
        "retrieval.similarity_threshold",
        "retrieval.vector_weight",
        "retrieval.keyword_weight",
        "rag.context_token_budget",
        "rag.input_token_budget_est",
        "rag.context_selection_policy",
        "rag.max_chunk_tokens",
        "rag.dedupe_min_hash_prefix",
        "rag.include_snippets",
        "llm.provider",
        "llm.model",
        "llm.execution",
        "llm.timeout_seconds",
        "llm.temperature",
        "llm.max_output_tokens",
        "llm.think",
        "llm.num_ctx",
        "data_driven.enabled",
        "data_driven.file_patterns",
        "data_driven.max_statements_per_file",
        "data_driven.max_literal_chars",
        "data_driven.token_patterns",
        "data_driven.configurations",
    ]
    assert lines[0] == "origen = archivo"
    assert lines[1] == f"archivo_configuracion = {source}"
    assert "domain = legacy" in lines
    assert "log_level = DEBUG" in lines
    assert "ingestion.chunk_size = 4000" in lines
    assert "ingestion.max_file_size_mb = 50" in lines
    assert "vector_store.provider = sqlite_vec" in lines
    assert "retrieval.mode = hybrid" in lines
    assert "rag.context_token_budget = 6000" in lines
    assert "rag.input_token_budget_est = no configurado" in lines
    assert "rag.context_selection_policy = baseline_v1" in lines
    assert "llm.execution = auto" in lines
    assert "llm.max_output_tokens = no configurado" in lines
    assert "data_driven.enabled = false" in lines
    assert list(tmp_path.iterdir()) == [source]


def test_config_show_reports_configured_input_budget_contract(tmp_path: Path) -> None:
    source = tmp_path / "input-budget.toml"
    source.write_text(
        "[rag]\ninput_token_budget_est = 9000\n",
        encoding="utf-8",
    )

    result = run_cli("--config", str(source), "config", "show", cwd=tmp_path)

    assert result.returncode == 0
    assert "rag.input_token_budget_est = 9000" in result.stdout.splitlines()
    assert "rag.context_token_budget = 6000" in result.stdout.splitlines()


def test_config_show_reports_anthropic_limit_without_exposing_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canary = "sk-ant-test-NEVER-LOG-H12-0123456789"
    monkeypatch.setenv("ANTHROPIC_API_KEY", canary)
    source = tmp_path / "anthropic.toml"
    source.write_text(
        "\n".join(
            (
                "[llm]",
                'provider = "anthropic"',
                'model = "claude-test"',
                "max_output_tokens = 8192",
            )
        ),
        encoding="utf-8",
    )

    result = run_cli("--config", str(source), "config", "show", cwd=tmp_path)

    assert result.returncode == 0
    assert "llm.provider = anthropic" in result.stdout
    assert "llm.model = claude-test" in result.stdout
    assert "llm.max_output_tokens = 8192" in result.stdout
    assert canary not in result.stdout
    assert canary not in result.stderr


def test_main_configures_stdio_before_parsing_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class Parser:
        def parse_args(self, argv):  # noqa: ANN001, ANN201
            del argv
            events.append("parse")
            return type(
                "Args",
                (),
                {"handler": staticmethod(lambda args: events.append("handler") or 0)},
            )()

    monkeypatch.setattr(
        cli,
        "_configure_stdio_encoding",
        lambda: events.append("stdio"),
    )
    monkeypatch.setattr(cli, "build_parser", Parser)

    assert cli.main([]) == 0
    assert events == ["stdio", "parse", "handler"]


def test_windows_stdio_uses_utf8_strict_for_redirected_streams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Stream:
        def __init__(self) -> None:
            self.calls: list[dict[str, str]] = []

        @staticmethod
        def isatty() -> bool:
            return False

        def reconfigure(self, **kwargs: str) -> None:
            self.calls.append(kwargs)

    stdout = Stream()
    stderr = Stream()
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli.sys, "stdout", stdout)
    monkeypatch.setattr(cli.sys, "stderr", stderr)

    cli._configure_stdio_encoding()

    expected = [{"encoding": "utf-8", "errors": "strict"}]
    assert stdout.calls == expected
    assert stderr.calls == expected


def test_windows_stdio_preserves_interactive_console_streams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ConsoleStream:
        def __init__(self) -> None:
            self.calls: list[dict[str, str]] = []

        @staticmethod
        def isatty() -> bool:
            return True

        def reconfigure(self, **kwargs: str) -> None:
            self.calls.append(kwargs)

    stdout = ConsoleStream()
    stderr = ConsoleStream()
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli.sys, "stdout", stdout)
    monkeypatch.setattr(cli.sys, "stderr", stderr)

    cli._configure_stdio_encoding()

    assert stdout.calls == []
    assert stderr.calls == []


def test_config_show_reports_invalid_file_without_traceback(tmp_path: Path) -> None:
    result = run_cli(
        "--config",
        str(tmp_path / "missing.toml"),
        "config",
        "show",
        cwd=tmp_path,
    )

    assert result.returncode == 2
    assert "Error de configuración:" in result.stderr
    assert "no existe" in result.stderr
    assert "Traceback" not in result.stderr
    assert list(tmp_path.iterdir()) == []


def write_ingest_config(tmp_path: Path) -> Path:
    """Crea una configuracion minima para pruebas de ingesta CLI."""
    source = tmp_path / "barbarion.toml"
    source.write_text(
        "\n".join(
            [
                'data_dir = "data"',
                'output_dir = "output"',
                'logs_dir = "logs"',
                'database_path = "data/barbarion.db"',
                'log_level = "INFO"',
                "[ingestion]",
                'paths = ["sources"]',
                'extensions = [".txt"]',
            ]
        ),
        encoding="utf-8",
    )
    return source


def test_ingest_help_documents_repeatable_path_without_side_effects(tmp_path: Path) -> None:
    result = run_cli("ingest", "--help", cwd=tmp_path)

    assert result.returncode == 0
    assert "--path RUTA" in result.stdout
    assert "puede repetirse" in result.stdout
    assert "--incremental" in result.stdout
    assert "--full" in result.stdout
    assert "--stats" in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_ingest_stats_rejects_execution_options(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_ingest_config(tmp_path)

    exit_code = cli.main(["--config", str(source), "ingest", "--stats", "--full"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "--stats no se combina" in captured.err


def test_ingest_requires_doctor_bootstrap_without_creating_resources(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_ingest_config(tmp_path)

    exit_code = cli.main(["--config", str(source), "ingest"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Ejecuta 'barbarion doctor'" in captured.err
    assert not (tmp_path / "data").exists()
    assert not (tmp_path / "logs").exists()


def test_ingest_stats_without_database_is_read_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_ingest_config(tmp_path)

    exit_code = cli.main(["--config", str(source), "ingest", "--stats"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "No hay base SQLite de Barbarion" in captured.out
    assert sorted(path.name for path in tmp_path.iterdir()) == ["barbarion.toml"]


def test_ingest_stats_reads_persisted_inventory(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_ingest_config(tmp_path)
    (tmp_path / "data").mkdir()
    database_path = tmp_path / "data" / "barbarion.db"
    initialize_database(database_path)

    exit_code = cli.main(["--config", str(source), "ingest", "--stats"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Estadisticas de ingesta" in captured.out
    assert "ultimo_run = ninguno" in captured.out
    assert "archivos_vigentes = 0" in captured.out
    assert "chunks_vigentes = 0" in captured.out


@dataclass
class FakeService:
    modes: list[IngestionMode]

    def run(self, *, mode: IngestionMode) -> IngestionOutcome:
        self.modes.append(mode)
        return IngestionOutcome(
            status=IngestionRunStatus.COMPLETED,
            metrics=IngestionMetrics(
                discovered_files=2,
                processed_files=1,
                skipped_files=1,
                source_bytes=32,
                processed_bytes=16,
                chunk_count=3,
                duration_ms=7,
            ),
        )


def test_ingest_runs_full_mode_and_logs_context_without_corpus(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_ingest_config(tmp_path)
    for name in ("data", "output", "logs", "sources", "override"):
        (tmp_path / name).mkdir()
    initialize_database(tmp_path / "data" / "barbarion.db")
    service = FakeService(modes=[])
    monkeypatch.setattr(
        cli,
        "_build_ingestion_service",
        lambda settings, logger=None: service,
    )

    exit_code = cli.main(
        [
            "--config",
            str(source),
            "ingest",
            "--full",
            "--path",
            str(tmp_path / "override"),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert service.modes == [IngestionMode.FULL]
    assert "Ingesta finalizada: completed" in captured.out
    assert "Procesados: 1" in captured.out
    log_content = (tmp_path / "logs" / LOG_FILENAME).read_text(encoding="utf-8")
    assert "Inicio de ingesta mode=full" in log_content
    assert "Fin de ingesta status=completed" in log_content
    assert "contenido valido" not in log_content


def test_ingest_interrupted_status_maps_to_130(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_ingest_config(tmp_path)
    for name in ("data", "output", "logs", "sources"):
        (tmp_path / name).mkdir()
    initialize_database(tmp_path / "data" / "barbarion.db")

    class InterruptedService:
        def run(self, *, mode: IngestionMode) -> IngestionOutcome:
            del mode
            return IngestionOutcome(
                status=IngestionRunStatus.INTERRUPTED,
                metrics=IngestionMetrics(),
                error=PipelineError(
                    stage=ErrorStage.RECONCILIATION,
                    error_code="INGEST_INTERRUPTED",
                    message="Ingesta interrumpida.",
                    recoverable=False,
                ),
            )

    monkeypatch.setattr(
        cli,
        "_build_ingestion_service",
        lambda settings, logger=None: InterruptedService(),
    )

    assert cli.main(["--config", str(source), "ingest"]) == 130
    assert "Ingesta finalizada: interrupted" in capsys.readouterr().out


class FakeIndexService:
    """Servicio de indexacion fake para CLI."""

    def __init__(self, summary: IndexRunSummary) -> None:
        self.summary = summary
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self.summary


class TtyBuffer:
    def __init__(self) -> None:
        self.parts: list[str] = []

    def write(self, value: str) -> int:
        self.parts.append(value)
        return len(value)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return True

    @property
    def text(self) -> str:
        return "".join(self.parts)


def test_console_progress_reporter_refreshes_interactive_block() -> None:
    stream = TtyBuffer()
    reporter = cli.ConsoleProgressReporter(
        stream,
        min_interval_seconds=0.0,
    )
    reporter.start(())

    reporter.stage(
        ProgressSnapshot(
            stage_key="embeddings",
            stage_label="Generando embeddings",
            current=1,
            total=10,
            global_current=3,
            global_total=20,
            counters={"new": 1, "update": 0, "unchanged": 2, "delete": 0, "errores": 0},
        )
    )
    reporter.stage(
        ProgressSnapshot(
            stage_key="embeddings",
            stage_label="Generando embeddings",
            current=2,
            total=10,
            global_current=4,
            global_total=20,
            counters={"new": 2, "update": 0, "unchanged": 2, "delete": 0, "errores": 0},
        )
    )
    reporter.finish("completed")

    assert "Barbarion Index" in stream.text
    assert "Ctrl+C cancela de forma segura; puedes reanudar luego." in stream.text
    assert "Global  [" in stream.text
    assert "Etapa   [" in stream.text
    assert "Generando embeddings" in stream.text
    assert "Procesados : 2 / 10" in stream.text
    assert "Nuevos       : 2" in stream.text
    assert "Actualizados : 0" in stream.text
    assert "Sin cambios  : 2" in stream.text
    assert "Eliminados   : 0" in stream.text
    assert "Errores      : 0" in stream.text
    assert "Ver log:" not in stream.text
    assert "Velocidad    :" not in stream.text
    assert "ETA          :" not in stream.text
    assert "\x1b[15F" in stream.text
    assert "Progreso finalizado: completed" in stream.text


def test_console_progress_reporter_points_to_embeddings_errors_command() -> None:
    stream = TtyBuffer()
    reporter = cli.ConsoleProgressReporter(
        stream,
        min_interval_seconds=0.0,
    )
    reporter.start(())

    reporter.stage(
        ProgressSnapshot(
            stage_key="metadata",
            stage_label="Actualizando metadata",
            current=5,
            total=10,
            global_current=5,
            global_total=20,
            counters={"errores": 2},
        )
    )

    assert (
        "Errores      : 2  Detalle disponible en: barbarion embeddings --errors"
        in stream.text
    )


def test_analyze_progress_reporter_renders_domain_counters() -> None:
    stream = TtyBuffer()
    reporter = cli.ConsoleProgressReporter(
        stream,
        min_interval_seconds=0.0,
        title="Barbarion Analyze",
        counter_labels={
            "new": "Simbolos",
            "update": "Referencias",
            "unchanged": "Resueltas",
            "delete": "Ambiguas",
            "errores": "No resueltas",
        },
        error_detail_command=None,
    )
    reporter.start(())

    reporter.stage(
        ProgressSnapshot(
            stage_key="resolve",
            stage_label="Resolviendo relaciones",
            current=5,
            total=5,
            global_current=5,
            global_total=5,
            counters={
                "new": 1,
                "update": 3,
                "unchanged": 1,
                "delete": 0,
                "errores": 2,
            },
        )
    )

    assert "Barbarion Analyze" in stream.text
    assert "Simbolos     : 1" in stream.text
    assert "Referencias  : 3" in stream.text
    assert "Resueltas    : 1" in stream.text
    assert "Ambiguas     : 0" in stream.text
    assert "No resueltas : 2" in stream.text
    assert "barbarion embeddings --errors" not in stream.text


def test_index_dry_run_uses_index_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_ingest_config(tmp_path)
    (tmp_path / "data").mkdir()
    initialize_database(tmp_path / "data" / "barbarion.db")
    service = FakeIndexService(
        IndexRunSummary(
            status=EmbeddingRunStatus.COMPLETED,
            new_chunks=2,
            dry_run=True,
        )
    )
    monkeypatch.setattr(cli, "_build_index_service", lambda settings: service)

    exit_code = cli.main(["--config", str(source), "index", "--dry-run"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert service.calls[0]["mode"] == cli.EmbeddingRunMode.INCREMENTAL
    assert service.calls[0]["dry_run"] is True
    assert service.calls[0]["delete_obsolete"] is True
    assert isinstance(service.calls[0]["progress"], cli.ConsoleProgressReporter)
    assert isinstance(service.calls[0]["cancellation"], cli.CliCancellationToken)
    assert "Dry-run de indexacion RAG: completed" in captured.out
    assert "Nuevos: 2" in captured.out


def test_reindex_requires_scope_or_full(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_ingest_config(tmp_path)

    exit_code = cli.main(["--config", str(source), "reindex"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "reindex requiere" in captured.err


def test_reindex_full_invokes_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_ingest_config(tmp_path)
    (tmp_path / "data").mkdir()
    initialize_database(tmp_path / "data" / "barbarion.db")
    service = FakeIndexService(
        IndexRunSummary(status=EmbeddingRunStatus.COMPLETED, updated_chunks=3)
    )
    monkeypatch.setattr(cli, "_build_index_service", lambda settings: service)

    exit_code = cli.main(
        ["--config", str(source), "reindex", "--full", "--delete-obsolete"]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert service.calls[0]["mode"] == cli.EmbeddingRunMode.FULL
    assert service.calls[0]["scope"] is None
    assert service.calls[0]["delete_obsolete"] is True
    assert isinstance(service.calls[0]["progress"], cli.ConsoleProgressReporter)
    assert isinstance(service.calls[0]["cancellation"], cli.CliCancellationToken)
    assert "Actualizados: 3" in captured.out


def test_index_interrupted_returns_130_and_renders_operational_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_ingest_config(tmp_path)
    (tmp_path / "data").mkdir()
    initialize_database(tmp_path / "data" / "barbarion.db")
    service = FakeIndexService(
        IndexRunSummary(
            status=EmbeddingRunStatus.INTERRUPTED,
            processed_chunks=1,
            pending_chunks=2,
            embeddings_generated=1,
            vectors_persisted=1,
            run_id=9,
        )
    )
    monkeypatch.setattr(cli, "_build_index_service", lambda settings: service)

    exit_code = cli.main(["--config", str(source), "index"])
    captured = capsys.readouterr()

    assert exit_code == 130
    assert "Indexacion RAG: interrupted" in captured.out
    assert "Run: 9" in captured.out
    assert "Procesados: 1" in captured.out
    assert "Pendientes: 2" in captured.out
    assert "Embeddings generados: 1" in captured.out
    assert "Vectores persistidos: 1" in captured.out


def test_index_logs_error_summary_when_failures_exist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from barbarion.domain.rag import EmbeddingManifest
    from barbarion.infrastructure.sqlite import SQLiteRagRepository
    from tests.unit.test_rag_index_service import seed_chunks

    source = write_ingest_config(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "logs").mkdir()
    db_path = tmp_path / "data" / "barbarion.db"
    initialize_database(db_path)
    seed_chunks(db_path)
    repository = SQLiteRagRepository(db_path)
    manifest = repository.get_or_create_manifest(
        EmbeddingManifest("fake", "sha256", 4)
    )
    run_id = repository.begin_embedding_run(
        manifest_id=manifest.id,
        mode=cli.EmbeddingRunMode.INCREMENTAL,
        scope=None,
    )
    chunk = repository.indexable_chunks(domain="default")[0]
    repository.record_chunk_error(
        run_id=run_id,
        manifest_id=manifest.id,
        chunk=chunk,
        error_code="OLLAMA_EMBEDDINGS_UNAVAILABLE",
        error_message="no se pudo contactar Ollama local",
    )
    service = FakeIndexService(
        IndexRunSummary(
            status=EmbeddingRunStatus.INTERRUPTED,
            failed_chunks=1,
            run_id=run_id,
        )
    )
    monkeypatch.setattr(cli, "_build_index_service", lambda settings: service)

    assert cli.main(["--config", str(source), "index"]) == 130

    log_content = (tmp_path / "logs" / LOG_FILENAME).read_text(encoding="utf-8")
    assert (
        f"WARNING barbarion index run_id={run_id} status=interrupted "
        "failed_chunks=1 error_code=OLLAMA_EMBEDDINGS_UNAVAILABLE"
    ) in log_content


class FakeSearchService:
    def __init__(self) -> None:
        self.requests = []

    def search(self, request):
        self.requests.append(request)
        return SearchResponse(
            query_id=7,
            mode=RetrievalMode.KEYWORD,
            candidates=(
                RetrievalCandidate(
                    chunk_id="chunk-1",
                    content_sha256="a" * 64,
                    combined_score=0.8,
                    keyword_score=0.8,
                    source={
                        "relative_path": "pkg/demo.sql",
                        "start_line": 10,
                        "end_line": 12,
                    },
                ),
            ),
            timings=SearchTimings(keyword_ms=1, ranking_ms=1),
        )


def test_search_json_invokes_service_with_filters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_ingest_config(tmp_path)
    (tmp_path / "data").mkdir()
    initialize_database(tmp_path / "data" / "barbarion.db")
    service = FakeSearchService()
    monkeypatch.setattr(cli, "_build_search_service", lambda settings: service)

    exit_code = cli.main(
        [
            "--config",
            str(source),
            "search",
            "order_total",
            "--mode",
            "keyword",
            "--extension",
            ".sql",
            "--format",
            "json",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert service.requests[0].query == "order_total"
    assert service.requests[0].filters.extension == ".sql"
    assert payload["query_id"] == 7
    assert payload["results"][0]["chunk_id"] == "chunk-1"
    assert payload["results"][0]["source"]["start_line"] == 10
    assert payload["results"][0]["source"]["end_line"] == 12


class FakeAskService:
    def __init__(
        self,
        citations_valid: bool = True,
        *,
        debug_payload: dict[str, object] | None = None,
        answer: str = "## Conclusion\nRespuesta [F1]",
        content: str = "contenido",
    ) -> None:
        self.calls = []
        self.citations_valid = citations_valid
        self.debug_payload = debug_payload or {}
        self.answer = answer
        self.content = content

    def ask(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        candidate = RetrievalCandidate(
            chunk_id="chunk-1",
            content_sha256="a" * 64,
            combined_score=0.8,
            source={
                "relative_path": "pkg/demo.sql",
                "start_line": 10,
                "end_line": 12,
            },
        )
        source = ContextSource(
            source_id="F1",
            candidate=candidate,
            content=self.content,
            token_estimate=2,
        )
        context = ContextBuildResult(
            sources=(source,),
            omitted=(),
            rendered_context="[F1] contenido",
            token_estimate=2,
            metrics=ContextQualityMetrics(duplicate_ratio=0, token_waste=0.5),
        )
        return AnswerResult(
            query_id=8,
            question=args[0],
            answer=self.answer,
            context=context,
            status=RagQueryStatus.COMPLETED,
            no_llm=kwargs["no_llm"],
            citations_valid=self.citations_valid,
            debug=self.debug_payload if kwargs["debug"] else {},
        )


class RaisingAskService:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    def ask(self, *args, **kwargs):  # noqa: ANN002, ANN003
        del args, kwargs
        raise self.error


class LoggingAskService(FakeAskService):
    """Emite los eventos públicos de observabilidad durante una llamada CLI."""

    def ask(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        """Registra eventos INFO y devuelve una respuesta válida."""
        logger = logging.getLogger(LOGGER_NAME)
        logger.info("ask_llm_started stage=generation")
        logger.info("ask_llm_finished stage=generation result=completed")
        logger.info("ask_citation_validation stage=generation result=PASS")
        return super().ask(*args, **kwargs)


def test_ask_no_llm_markdown_invokes_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_ingest_config(tmp_path)
    (tmp_path / "data").mkdir()
    initialize_database(tmp_path / "data" / "barbarion.db")
    service = FakeAskService()
    monkeypatch.setattr(cli, "_build_ask_service", lambda settings: service)

    exit_code = cli.main(
        [
            "--config",
            str(source),
            "ask",
            "Donde esta?",
            "--no-llm",
            "--format",
            "markdown",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert service.calls[0][1]["no_llm"] is True
    assert "## Conclusion" in captured.out
    assert "## Fuentes" in captured.out
    assert "lineas=10-12" in captured.out


def test_ask_hides_info_events_without_debug_but_keeps_them_in_log_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_ingest_config(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "logs").mkdir()
    initialize_database(tmp_path / "data" / "barbarion.db")
    monkeypatch.setattr(
        cli,
        "_build_ask_service",
        lambda settings: LoggingAskService(),
    )

    exit_code = cli.main(["--config", str(source), "ask", "Donde esta?"])
    captured = capsys.readouterr()
    log_content = (tmp_path / "logs" / LOG_FILENAME).read_text(encoding="utf-8")

    assert exit_code == 0
    for event in (
        "ask_llm_started",
        "ask_llm_finished",
        "ask_citation_validation",
    ):
        assert event not in captured.err
        assert log_content.count(event) == 1
    response_separator = "──────────────────── RESPUESTA ────────────────────"
    sources_separator = "──────────────────── FUENTES ──────────────────────"
    assert captured.out.startswith("Barbarion Ask\n")
    assert "Modelo: llama3.1:8b\n" in captured.out
    assert "Validación: PASS\n" in captured.out
    assert re.search(r"Tiempo: \d+\.\d{2}s\n", captured.out)
    assert response_separator in captured.out
    assert sources_separator in captured.out
    assert captured.out.index(response_separator) < captured.out.index(
        "## Conclusion"
    )
    assert captured.out.index("## Conclusion") < captured.out.index(
        sources_separator
    )


def test_ask_debug_keeps_info_events_on_console_and_in_log_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_ingest_config(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "logs").mkdir()
    initialize_database(tmp_path / "data" / "barbarion.db")
    monkeypatch.setattr(
        cli,
        "_build_ask_service",
        lambda settings: LoggingAskService(
            debug_payload=_ask_debug_payload(valid=True),
        ),
    )

    exit_code = cli.main(
        ["--config", str(source), "ask", "Donde esta?", "--debug"]
    )
    captured = capsys.readouterr()
    log_content = (tmp_path / "logs" / LOG_FILENAME).read_text(encoding="utf-8")

    assert exit_code == 0
    for event in (
        "ask_llm_started",
        "ask_llm_finished",
        "ask_citation_validation",
    ):
        assert captured.err.count(event) == 1
        assert log_content.count(event) == 1


def _ask_debug_payload(
    *,
    valid: bool = False,
    repair_attempted: bool = False,
    repair_valid: bool | None = None,
    prompt: str = "Prompt password=abc",
    response: str = "Respuesta sin cita token=abc",
) -> dict[str, object]:
    validation = {
        "expected_citations": ("F1",),
        "found_citations": ("F1",) if valid else (),
        "valid_citations": ("F1",) if valid else (),
        "missing_citations": () if valid else ("F1",),
        "invalid_citations": (),
        "result": "PASS" if valid else "FAIL",
        "reason": "ok" if valid else "la respuesta no incluyo citas validas",
    }
    payload: dict[str, object] = {
        "retrieved_chunks": 3,
        "reranked_chunks": 1,
        "prompt_chars": len(prompt),
        "prompt_tokens_est": 10,
        "prompt": prompt,
        "llm_response": response,
        "validation": validation,
        "citation_repair_attempted": repair_attempted,
        "citation_repair_valid": repair_valid,
        "repair_prompt": None,
        "repair_response": None,
        "repair_validation": None,
        "observability": {
            "schema_version": "h31_observability_v1",
            "selection_policy": "optimized_v1",
            "estimator_id": "chars4_v1",
            "candidate_selection": (
                {
                    "chunk_id": "chunk-safe",
                    "action": "selected",
                    "reasons": ("relevance",),
                    "combined_score": 0.9,
                },
            ),
            "context_decisions": (),
            "redundancy": {
                "exact_duplicate_count": 0,
                "exact_duplicate_prompt_tokens_est_local": 0,
                "overlap_chars": 0,
                "overlap_tokens_est_local": 0,
            },
            "input_budget": {
                "configured_tokens_est_local": 9000,
                "fixed_overhead_tokens_est_local": 180,
                "evidence_budget_tokens_est_local": 8820,
                "final_prompt_tokens_est_local": 10,
                "result": "fits",
            },
            "generation": {
                "chars": len(prompt),
                "utf8_bytes": len(prompt.encode("utf-8")),
                "tokens_est_local": 10,
            },
            "repair": None,
            "repair_outcome": {
                "triggered": repair_attempted,
                "trigger_categories": (
                    ("no_valid_citations",) if repair_attempted else ()
                ),
                "trigger_counts": (
                    {"no_valid_citations": 1} if repair_attempted else {}
                ),
                "attempted": repair_attempted,
                "succeeded": repair_valid,
                "result": (
                    "succeeded"
                    if repair_valid
                    else "failed_validation"
                    if repair_attempted
                    else "not_needed"
                ),
            },
            "citation_coverage": {
                "selected_source_count": 1,
                "cited_source_count": 1 if valid else 0,
                "uncited_selected_source_ids": () if valid else ("F1",),
            },
            "context": {
                "selected_sources": 1,
                "omitted_candidates": 0,
                "chars": 20,
                "tokens_est_local": 5,
            },
            "provider_usage": None,
        },
    }
    if repair_attempted:
        repair_response = "Respuesta reparada [F1]" if repair_valid else "Sin cita"
        repair_result = "PASS" if repair_valid else "FAIL"
        payload.update(
            {
                "repair_prompt": "Repara api_key=abc",
                "repair_response": repair_response,
                "repair_validation": {
                    "expected_citations": ("F1",),
                    "found_citations": ("F1",) if repair_valid else (),
                    "valid_citations": ("F1",) if repair_valid else (),
                    "missing_citations": () if repair_valid else ("F1",),
                    "invalid_citations": (),
                    "result": repair_result,
                    "reason": "ok"
                    if repair_valid
                    else "la respuesta no incluyo citas validas",
                },
            }
        )
    return payload


def test_anthropic_debug_distinguishes_local_estimate_from_actual_usage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_ingest_config(tmp_path)
    source.write_text(
        source.read_text(encoding="utf-8")
        + '\n[llm]\nprovider = "anthropic"\nmodel = "claude-test"\n',
        encoding="utf-8",
    )
    (tmp_path / "data").mkdir()
    initialize_database(tmp_path / "data" / "barbarion.db")
    service = FakeAskService(
        citations_valid=True,
        debug_payload={
            **_ask_debug_payload(valid=True),
            "prompt_tokens_est_local": 6190,
        },
    )
    service.debug_payload.pop("prompt_tokens_est", None)
    service.llm_provider = AnthropicLlmProvider(
        model="claude-test",
        temperature=0.1,
        max_output_tokens=4096,
        _api_key_resolver=lambda: None,
        _usage_records=[
            AnthropicUsage(
                input_tokens=10198,
                output_tokens=612,
                total_tokens=10810,
                elapsed_seconds=6.17,
                request_count=1,
            )
        ],
    )
    monkeypatch.setattr(cli, "_build_ask_service", lambda settings: service)

    exit_code = cli.main(
        ["--config", str(source), "ask", "¿Dónde?", "--debug"]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "prompt_tokens_est_local=6190" in captured.err
    assert "prompt_tokens_est=" not in captured.err
    assert "Input tokens : 10,198" in captured.err
    assert "Output tokens: 612" in captured.err
    assert "Total tokens : 10,810" in captured.err
    assert "provider_input_tokens=10198" in captured.err
    assert "provider_output_tokens=612" in captured.err
    assert "provider_total_tokens=10810" in captured.err
    assert "provider_request_count=1" in captured.err
    assert "Elapsed time : 6.17s" in captured.err


def test_ask_debug_with_invalid_citations_writes_diagnostics_to_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_ingest_config(tmp_path)
    (tmp_path / "data").mkdir()
    initialize_database(tmp_path / "data" / "barbarion.db")
    service = FakeAskService(citations_valid=False, debug_payload=_ask_debug_payload())
    monkeypatch.setattr(cli, "_build_ask_service", lambda settings: service)

    exit_code = cli.main(
        ["--config", str(source), "ask", "Donde esta?", "--debug"]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "=== QUERY ===" not in captured.err
    assert "=== LLM RESPONSE ===" not in captured.err
    assert "=== VALIDATION ===" not in captured.err
    assert "final_result: REJECTED" in captured.err
    assert "=== QUERY ===" not in captured.out
    assert "Validación: FAIL" in captured.out


def test_ask_debug_with_failed_repair_reports_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_ingest_config(tmp_path)
    (tmp_path / "data").mkdir()
    initialize_database(tmp_path / "data" / "barbarion.db")
    service = FakeAskService(
        citations_valid=False,
        debug_payload=_ask_debug_payload(repair_attempted=True, repair_valid=False),
    )
    monkeypatch.setattr(cli, "_build_ask_service", lambda settings: service)

    exit_code = cli.main(
        ["--config", str(source), "ask", "Donde esta?", "--debug"]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "=== REPAIR ATTEMPT ===" not in captured.err
    assert "=== REPAIR RESPONSE ===" not in captured.err
    assert "repair: FAIL" in captured.err
    assert "la respuesta final no incluyo citas validas" in captured.err


def test_ask_debug_with_successful_validation_reports_models_and_retrieval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_ingest_config(tmp_path)
    (tmp_path / "data").mkdir()
    initialize_database(tmp_path / "data" / "barbarion.db")
    service = FakeAskService(
        citations_valid=True,
        debug_payload=_ask_debug_payload(valid=True, response="Respuesta [F1]"),
    )
    monkeypatch.setattr(cli, "_build_ask_service", lambda settings: service)

    exit_code = cli.main(
        ["--config", str(source), "ask", "Donde esta?", "--debug"]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "llm_provider=ollama" in captured.err
    assert "embedding_provider=ollama" in captured.err
    assert "mode=hybrid" in captured.err
    assert "retrieved_chunks=3" in captured.err
    assert "=== H3.1 OBSERVABILITY ===" in captured.err
    assert "selection_policy=optimized_v1" in captured.err
    assert "estimator_id=chars4_v1" in captured.err
    assert "candidate_decision" not in captured.err
    assert "input_budget_configured_tokens_est_local=9000" in captured.err
    assert "generation_tokens_est_local=10" in captured.err
    assert "repair_outcome triggered=False attempted=False" in captured.err
    assert "result=not_needed causes=[]" in captured.err
    assert "[F1] score=0.800" not in captured.err
    assert "validation: PASS" in captured.err
    assert "final_result: ACCEPTED" in captured.err


def test_ask_debug_with_successful_repair_reports_acceptance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_ingest_config(tmp_path)
    (tmp_path / "data").mkdir()
    initialize_database(tmp_path / "data" / "barbarion.db")
    service = FakeAskService(
        citations_valid=True,
        answer="## Conclusion\nRespuesta reparada [F1]",
        debug_payload=_ask_debug_payload(repair_attempted=True, repair_valid=True),
    )
    monkeypatch.setattr(cli, "_build_ask_service", lambda settings: service)

    exit_code = cli.main(["--config", str(source), "ask", "Donde esta?", "--debug"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Respuesta reparada [F1]" not in captured.err
    assert "repair_outcome triggered=True attempted=True succeeded=True" in captured.err
    assert "result=succeeded causes=[no_valid_citations]" in captured.err
    assert "repair: PASS" in captured.err
    assert "final_result: ACCEPTED" in captured.err


def test_ask_debug_keeps_json_stdout_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_ingest_config(tmp_path)
    (tmp_path / "data").mkdir()
    initialize_database(tmp_path / "data" / "barbarion.db")
    service = FakeAskService(
        citations_valid=True,
        debug_payload=_ask_debug_payload(valid=True, response="Respuesta [F1]"),
    )
    monkeypatch.setattr(cli, "_build_ask_service", lambda settings: service)

    exit_code = cli.main(
        ["--config", str(source), "ask", "Donde esta?", "--debug", "--format", "json"]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["debug"] == {}
    assert "=== QUERY ===" not in captured.out
    assert "=== MODEL ===" in captured.err
    assert "=== QUERY ===" not in captured.err


def test_ask_no_llm_debug_reports_not_executed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_ingest_config(tmp_path)
    (tmp_path / "data").mkdir()
    initialize_database(tmp_path / "data" / "barbarion.db")
    service = FakeAskService(debug_payload={"retrieved_chunks": 1, "reranked_chunks": 1})
    monkeypatch.setattr(cli, "_build_ask_service", lambda settings: service)

    exit_code = cli.main(
        ["--config", str(source), "ask", "Donde esta?", "--no-llm", "--debug"]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "=== LLM RESPONSE ===" not in captured.err
    assert "repair: NOT_EXECUTED" in captured.err
    assert "modo --no-llm" in captured.err


def test_ask_without_debug_keeps_normal_stdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_ingest_config(tmp_path)
    (tmp_path / "data").mkdir()
    initialize_database(tmp_path / "data" / "barbarion.db")
    service = FakeAskService(debug_payload=_ask_debug_payload(valid=True))
    monkeypatch.setattr(cli, "_build_ask_service", lambda settings: service)

    exit_code = cli.main(["--config", str(source), "ask", "Donde esta?"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "=== QUERY ===" not in captured.err
    assert "Debug:" not in captured.out
    assert "## Conclusion" in captured.out


def test_ask_anthropic_usage_is_rendered_on_stderr_without_breaking_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_ingest_config(tmp_path)
    (tmp_path / "data").mkdir()
    initialize_database(tmp_path / "data" / "barbarion.db")
    service = FakeAskService(citations_valid=True)
    service.llm_provider = AnthropicLlmProvider(
        model="claude-test",
        temperature=0.1,
        max_output_tokens=4096,
        _api_key_resolver=lambda: None,
        _usage_records=[
            AnthropicUsage(
                input_tokens=7842,
                output_tokens=612,
                total_tokens=8454,
                elapsed_seconds=4.18,
                request_count=1,
            )
        ],
    )
    monkeypatch.setattr(cli, "_build_ask_service", lambda settings: service)

    exit_code = cli.main(
        ["--config", str(source), "ask", "Donde esta?", "--format", "json"]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["status"] == "completed"
    assert "Input tokens : 7,842" in captured.err
    assert "Output tokens: 612" in captured.err
    assert "Total tokens : 8,454" in captured.err
    assert "Elapsed time : 4.18s" in captured.err
    assert "credito" not in captured.err.lower()
    assert "$" not in captured.err


@pytest.mark.parametrize(
    ("usage", "expected", "absent"),
    [
        (
            AnthropicUsage(
                input_tokens=None,
                output_tokens=12,
                total_tokens=None,
                elapsed_seconds=1.25,
                request_count=1,
            ),
            ("Output tokens: 12", "Elapsed time : 1.25s"),
            ("Input tokens", "Total tokens"),
        ),
        (None, (), ("Input tokens", "Output tokens", "Total tokens", "Elapsed time")),
    ],
)
def test_anthropic_usage_never_invents_missing_counters(
    capsys: pytest.CaptureFixture[str],
    usage: AnthropicUsage | None,
    expected: tuple[str, ...],
    absent: tuple[str, ...],
) -> None:
    provider = AnthropicLlmProvider(
        model="claude-test",
        temperature=0.1,
        max_output_tokens=4096,
        _api_key_resolver=lambda: None,
        _usage_records=[] if usage is None else [usage],
    )
    service = type("Service", (), {"llm_provider": provider})()

    cli._render_anthropic_usage(service)
    captured = capsys.readouterr()

    for value in expected:
        assert value in captured.err
    for value in absent:
        assert value not in captured.err


def test_ask_debug_truncates_and_masks_sensitive_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_ingest_config(tmp_path)
    (tmp_path / "data").mkdir()
    initialize_database(tmp_path / "data" / "barbarion.db")
    prompt = "inicio " + ("p" * 4100) + " secret=visible final"
    response = "token=visible " + ("r" * 4100)
    content = "api_key=visible " + ("c" * 600)
    service = FakeAskService(
        debug_payload=_ask_debug_payload(prompt=prompt, response=response),
        content=content,
    )
    monkeypatch.setattr(cli, "_build_ask_service", lambda settings: service)

    exit_code = cli.main(["--config", str(source), "ask", "Donde esta?", "--debug"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "secret=********" not in captured.err
    assert "token=********" not in captured.err
    assert "api_key=********" not in captured.err
    assert "[TRUNCATED]" not in captured.err
    assert "secret=visible" not in captured.err
    assert "token=visible" not in captured.err
    assert "api_key=visible" not in captured.err


def test_ask_llm_timeout_does_not_print_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_ingest_config(tmp_path)
    (tmp_path / "data").mkdir()
    initialize_database(tmp_path / "data" / "barbarion.db")
    monkeypatch.setattr(
        cli,
        "_build_ask_service",
        lambda settings: RaisingAskService(
            LlmProviderError("OLLAMA_LLM_TIMEOUT: timeout")
        ),
    )

    exit_code = cli.main(["--config", str(source), "ask", "Donde esta?"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Ollama no respondio dentro del timeout configurado" in captured.err
    assert "Sugerencias:" in captured.err
    assert "Traceback" not in captured.err


def test_ask_anthropic_error_is_actionable_and_preserves_request_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_ingest_config(tmp_path)
    source.write_text(
        source.read_text(encoding="utf-8")
        + "\n[llm]\nprovider = \"anthropic\"\nmodel = \"claude-test\"\n",
        encoding="utf-8",
    )
    (tmp_path / "data").mkdir()
    initialize_database(tmp_path / "data" / "barbarion.db")
    monkeypatch.setattr(
        cli,
        "_build_ask_service",
        lambda settings: RaisingAskService(
            LlmProviderError(
                "ANTHROPIC_RATE_LIMITED: limite remoto "
                "[request-id=req_safe-123]"
            )
        ),
    )

    exit_code = cli.main(["--config", str(source), "ask", "Donde esta?"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Anthropic aplico un limite" in captured.err
    assert "Request ID: req_safe-123" in captured.err
    assert "reintenta manualmente" in captured.err
    assert "ANTHROPIC_API_KEY" in captured.err
    assert "ollama run" not in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("ANTHROPIC_API_KEY_MISSING", "ANTHROPIC_API_KEY"),
        ("ANTHROPIC_AUTHENTICATION_ERROR", "autenticacion"),
        ("ANTHROPIC_BILLING_ERROR", "cuenta Anthropic"),
        ("ANTHROPIC_PERMISSION_ERROR", "permiso"),
        ("ANTHROPIC_MODEL_NOT_FOUND", "modelo Anthropic"),
        ("ANTHROPIC_REQUEST_INVALID", "solicitud generativa"),
        ("ANTHROPIC_REQUEST_TOO_LARGE", "tamano"),
        ("ANTHROPIC_RATE_LIMITED", "limite de solicitudes"),
        ("ANTHROPIC_TIMEOUT", "timeout configurado"),
        ("ANTHROPIC_OVERLOADED", "sobrecargado"),
        ("ANTHROPIC_UNAVAILABLE", "contactar el servicio"),
        ("ANTHROPIC_LLM_TRUNCATED", "max_output_tokens"),
        ("ANTHROPIC_RESPONSE_INVALID", "respuesta invalida"),
        ("ANTHROPIC_HTTP_ERROR", "error HTTP"),
    ],
)
def test_anthropic_error_codes_have_provider_specific_messages(
    code: str,
    expected: str,
) -> None:
    message = cli._llm_error_message(
        LlmProviderError(f"{code}: detalle remoto no confiable"),
        provider="anthropic",
    )

    assert expected in message
    assert "detalle remoto no confiable" not in message
    assert "Ollama" not in message


def test_ask_keyboard_interrupt_returns_130(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = write_ingest_config(tmp_path)
    (tmp_path / "data").mkdir()
    initialize_database(tmp_path / "data" / "barbarion.db")
    monkeypatch.setattr(
        cli,
        "_build_ask_service",
        lambda settings: RaisingAskService(KeyboardInterrupt()),
    )

    exit_code = cli.main(["--config", str(source), "ask", "Donde esta?"])
    captured = capsys.readouterr()

    assert exit_code == 130
    assert "interrumpida por el usuario" in captured.err
    assert "Traceback" not in captured.err


def test_embeddings_and_stats_are_read_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from barbarion.domain.rag import EmbeddingManifest
    from barbarion.infrastructure.sqlite import SQLiteRagRepository
    from tests.unit.test_rag_index_service import seed_chunks

    source = write_ingest_config(tmp_path)
    (tmp_path / "data").mkdir()
    db_path = tmp_path / "data" / "barbarion.db"
    initialize_database(db_path)
    seed_chunks(db_path)
    repository = SQLiteRagRepository(db_path)
    manifest = repository.get_or_create_manifest(
        EmbeddingManifest("fake", "sha256", 4)
    )
    run_id = repository.begin_embedding_run(
        manifest_id=manifest.id,
        mode=cli.EmbeddingRunMode.INCREMENTAL,
        scope=None,
    )
    chunk = repository.indexable_chunks(domain="default")[0]
    repository.record_chunk_indexed(
        run_id=run_id,
        manifest_id=manifest.id,
        chunk=chunk,
    )
    with sqlite3.connect(db_path) as connection:
        before_counts = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM embedding_manifests),
                (SELECT COUNT(*) FROM chunk_embeddings),
                (SELECT COUNT(*) FROM rag_queries)
            """
        ).fetchone()

    embeddings_exit = cli.main(["--config", str(source), "embeddings"])
    embeddings_out = capsys.readouterr().out
    stats_exit = cli.main(["--config", str(source), "stats"])
    stats_out = capsys.readouterr().out
    with sqlite3.connect(db_path) as connection:
        after_counts = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM embedding_manifests),
                (SELECT COUNT(*) FROM chunk_embeddings),
                (SELECT COUNT(*) FROM rag_queries)
            """
        ).fetchone()

    assert embeddings_exit == 0
    assert "Embeddings RAG" in embeddings_out
    assert "indexed=1" in embeddings_out
    assert stats_exit == 0
    assert "Estadisticas RAG" in stats_out
    assert "chunks_indexed = 1" in stats_out
    assert before_counts == after_counts


def test_embeddings_errors_renders_persisted_index_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from barbarion.domain.rag import EmbeddingManifest
    from barbarion.infrastructure.sqlite import SQLiteRagRepository
    from tests.unit.test_rag_index_service import seed_chunks

    source = write_ingest_config(tmp_path)
    (tmp_path / "data").mkdir()
    db_path = tmp_path / "data" / "barbarion.db"
    initialize_database(db_path)
    seed_chunks(db_path)
    repository = SQLiteRagRepository(db_path)
    manifest = repository.get_or_create_manifest(
        EmbeddingManifest("fake", "sha256", 4)
    )
    run_id = repository.begin_embedding_run(
        manifest_id=manifest.id,
        mode=cli.EmbeddingRunMode.INCREMENTAL,
        scope=None,
    )
    chunk = repository.indexable_chunks(domain="default")[0]
    repository.record_chunk_error(
        run_id=run_id,
        manifest_id=manifest.id,
        chunk=chunk,
        error_code="OLLAMA_EMBEDDINGS_UNAVAILABLE",
        error_message="no se pudo contactar Ollama local",
    )

    exit_code = cli.main(["--config", str(source), "embeddings", "--errors"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"Run: {run_id}" in output
    assert "Errores: 1" in output
    assert f"1. chunk_id={chunk.chunk_id}" in output
    assert "error=OLLAMA_EMBEDDINGS_UNAVAILABLE" in output
    assert "mensaje=no se pudo contactar Ollama local" in output


def test_generate_report_command_writes_artifacts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "reports" / "rag"

    exit_code = cli.main(
        [
            "generate-report",
            "--dataset",
            "tests/fixtures/rag_evaluation.json",
            "--output",
            str(output),
            "--test-summary",
            "tests ok",
            "--smoke-summary",
            "smoke ok",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Reporte RAG generado" in captured.out
    assert (output / "metrics.json").exists()
    assert (output / "topk-report.md").exists()
    assert (output / "smoke-report.md").exists()
    assert "## Baseline" in (output / "benchmark.md").read_text(encoding="utf-8")
