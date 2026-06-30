"""Pruebas del árbol y los códigos base de la CLI."""

import json
import logging
import os
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
    )


@pytest.mark.parametrize(
    ("args", "expected_text"),
    [
        (("--help",), "comandos:"),
        (("config", "--help"), "subcomandos:"),
        (("config", "show", "--help"), "Muestra la configuración efectiva"),
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
        "rag.max_chunk_tokens",
        "rag.dedupe_min_hash_prefix",
        "rag.include_snippets",
        "llm.provider",
        "llm.model",
        "llm.timeout_seconds",
        "llm.temperature",
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
    assert list(tmp_path.iterdir()) == [source]


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
    assert "=== QUERY ===" in captured.err
    assert "=== LLM RESPONSE ===" in captured.err
    assert "=== VALIDATION ===" in captured.err
    assert "result: FAIL" in captured.err
    assert "final_result: REJECTED" in captured.err
    assert "=== QUERY ===" not in captured.out


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
    assert "=== REPAIR ATTEMPT ===" in captured.err
    assert "=== REPAIR RESPONSE ===" in captured.err
    assert "repair: FAIL" in captured.err
    assert "la respuesta no incluyo citas validas" in captured.err


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
    assert "[F1] score=0.800" in captured.err
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
    assert "Respuesta reparada [F1]" in captured.err
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
    assert "=== QUERY ===" in captured.err


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
    assert "=== LLM RESPONSE ===\nno ejecutada" in captured.err
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
    assert "secret=********" in captured.err
    assert "token=********" in captured.err
    assert "api_key=********" in captured.err
    assert "[TRUNCATED]" in captured.err
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
