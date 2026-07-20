"""Integracion RAG con conocimiento Data-Driven estructurado y sintetico."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import pytest

from barbarion import cli
from barbarion.application.rag import (
    AskService,
    CitationValidator,
    ContextBuilder,
    DataDrivenEvidenceRetriever,
    IndexService,
    PromptBuilder,
    SearchService,
)
from barbarion.config import Settings, load_settings
from barbarion.database import initialize_database
from barbarion.domain.rag import RetrievalFilter, RetrievalMode
from barbarion.infrastructure.embeddings import DeterministicFakeEmbeddingProvider
from barbarion.infrastructure.embeddings import OllamaEmbeddingProvider
from barbarion.infrastructure.sqlite import (
    SQLiteRagRepository,
    SQLiteReverseEngineeringRepository,
)
from barbarion.infrastructure.sqlite_vec import SQLiteVecStore


QUESTION = (
    "Que configuracion participa en el calculo de la bonificacion preferente "
    "y que codigo aplica ese comportamiento?"
)


def test_real_cli_pipeline_renders_structured_evidence_and_related_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Prueba el composition root real de config a ask sobre una SQLite real.

    Solo se sustituye el limite HTTP de Ollama por vectores deterministas. El
    parser CLI, los builders, servicios, repositorios y vector store usados son
    los de produccion.

    Args:
        tmp_path: Workspace sintetico aislado.
        monkeypatch: Sustituye exclusivamente la llamada externa de embeddings.
        capsys: Captura cada invocacion real de la CLI.
    """
    config = _prepare_workspace(tmp_path)
    monkeypatch.setattr(OllamaEmbeddingProvider, "_embed_one", _fake_ollama_vector)

    assert cli.main(["--config", str(config), "config", "show"]) == 0
    capsys.readouterr()
    assert cli.main(["--config", str(config), "ingest"]) == 0
    capsys.readouterr()
    assert cli.main(["--config", str(config), "analyze", "--full"]) == 0
    capsys.readouterr()
    assert cli.main(["--config", str(config), "index"]) == 0
    capsys.readouterr()

    question = (
        "Que configuracion controla el beneficio preferente de membresias "
        "y que codigo aplica ese comportamiento?"
    )
    forbidden_query_terms = (
        "APP_CONFIG",
        "CALCULATION_TEMPLATES",
        "TEMPLATE_ID",
        "apply_bonus",
        "templates.sql",
    )
    assert not any(term.lower() in question.lower() for term in forbidden_query_terms)

    for mode in RetrievalMode:
        assert cli.main(
            [
                "--config",
                str(config),
                "ask",
                question,
                "--mode",
                mode.value,
                "--top-k",
                "8",
                "--candidate-k",
                "12",
                "--threshold",
                "0",
                "--no-llm",
                "--format",
                "json",
            ]
        ) == 0
        payload = json.loads(capsys.readouterr().out)
        sources = payload["sources"]
        contents = [source["content"] for source in sources]
        rendered = "\n".join(contents)

        assert payload["status"] == "completed"
        assert any("Evidencia estructurada del catalogo tecnico" in item for item in contents)
        assert "tipo=configuration_record" in rendered
        assert "metadata_declarada=" in rendered
        assert "bonificacion preferente" in rendered.lower()
        assert "relacion_id=" in rendered
        assert "CREATE FUNCTION apply_bonus" in rendered
        assert "TEMPLATE_OLD" not in rendered
        assert "Concepto retirado" not in rendered
        assert all(source["content"].strip() != source["relative_path"] for source in sources)
        assert all(len(source["content"].strip()) > 20 for source in sources)
        assert any(source["start_line"] is not None for source in sources)
        assert any(source["end_line"] is not None for source in sources)
        assert any(source["chunk_id"] for source in sources)


def _fake_ollama_vector(self: OllamaEmbeddingProvider, text: str) -> tuple[float, ...]:
    """Genera el vector estable usado tras el adaptador HTTP del CLI real."""
    del self
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values = tuple((value + 1) / 256.0 for value in digest[:8])
    norm = math.sqrt(sum(value * value for value in values))
    return tuple(value / norm for value in values)


class StructuredFakeLlm:
    """LLM determinista que cita la evidencia estructurada y el codigo."""

    provider = "fake"
    model = "structured-responder"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, *, prompt: str, timeout_seconds: float) -> str:
        """Construye una respuesta estable desde IDs presentes en el prompt.

        Args:
            prompt: Prompt controlado construido por `AskService`.
            timeout_seconds: Timeout no usado por el fake.

        Returns:
            Respuesta en espanol con citas inline validas.
        """
        del timeout_seconds
        self.prompts.append(prompt)
        structured_id = _source_id_containing(
            prompt,
            "Evidencia estructurada del catalogo tecnico",
        )
        code_id = _source_id_containing(prompt, "CREATE FUNCTION apply_bonus")
        return (
            "La configuracion define el calculo de bonificacion preferente "
            f"[{structured_id}].\n"
            "La relacion calls apunta a apply_bonus "
            f"[{structured_id}].\n"
            "El codigo apply_bonus aplica el porcentaje configurado "
            f"[{code_id}]."
        )


def test_ask_no_llm_combines_structured_configuration_and_related_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Recupera evidencia interpretable sin depender de nombres tecnicos.

    Args:
        tmp_path: Workspace sintetico aislado.
        monkeypatch: Sustituye embeddings por un proveedor determinista.
        capsys: Captura la salida JSON de la CLI.
    """
    config = _prepare_workspace(tmp_path)
    monkeypatch.setattr(cli, "_build_index_service", _fake_index_service)
    monkeypatch.setattr(cli, "_build_search_service", _fake_search_service)
    _run_pipeline(config, capsys)

    assert cli.main(
        [
            "--config",
            str(config),
            "ask",
            QUESTION,
            "--mode",
            "hybrid",
            "--top-k",
            "8",
            "--candidate-k",
            "12",
            "--no-llm",
            "--format",
            "json",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)

    kinds = {
        source["source"].get("evidence_kind") for source in payload["sources"]
    }
    technologies = {
        source["source"].get("artifact_kind") for source in payload["sources"]
    }
    assert payload["status"] == "completed"
    assert payload["no_llm"] is True
    assert "structured_symbol" in kinds
    assert "related_code" in kinds
    assert {"oracle", "powerbuilder"}.issubset(technologies)
    assert "Evidencia estructurada del catalogo tecnico" in payload["answer"]
    assert "relacion_id=" in payload["answer"]
    assert "CREATE FUNCTION apply_bonus" in payload["answer"]
    assert "[F1]" in payload["answer"]
    assert "DO_NOT_EXPOSE" not in payload["answer"]


def test_ask_llm_receives_structured_symbols_values_relations_and_cites(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Valida prompt y respuesta citada con un LLM fake determinista.

    Args:
        tmp_path: Workspace sintetico aislado.
        capsys: Captura salidas de preparacion de la CLI.
    """
    config = _prepare_workspace(tmp_path)
    _run_pipeline(config, capsys, index=False)
    settings = load_settings(config, environ={}, cwd=tmp_path)
    search_service = _fake_search_service(settings)
    fake_llm = StructuredFakeLlm()
    service = _ask_service(settings, search_service, fake_llm)

    result = service.ask(
        QUESTION,
        mode=RetrievalMode.KEYWORD,
        top_k=8,
        candidate_k=12,
        threshold=0,
        debug=True,
    )

    prompt = fake_llm.prompts[0]
    assert result.citations_valid is True
    assert "calculation_templates" in prompt
    assert "bonificacion preferente" in prompt
    assert "configuration_variable" in prompt
    assert "relacion_id=" in prompt
    assert "oracle/function" in prompt
    assert "powerbuilder/function_object" in prompt
    assert "DO_NOT_EXPOSE" not in prompt
    assert "configuracion define el calculo" in result.answer.lower()
    assert "codigo apply_bonus" in result.answer.lower()
    assert re.search(r"\[F\d+\]", result.answer)


def test_concept_query_expands_hierarchy_and_configuration_relations(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Recupera por concepto funcional y expande relaciones del registro.

    Args:
        tmp_path: Workspace sintetico aislado.
        capsys: Captura salidas de preparacion de la CLI.
    """
    config = _prepare_workspace(tmp_path)
    _run_pipeline(config, capsys, index=False)
    settings = load_settings(config, environ={}, cwd=tmp_path)
    retriever = _structured_retriever(settings, SQLiteRagRepository(settings.database_path))

    candidates = retriever.retrieve(
        "Como se organiza el beneficio avanzado para membresias?",
        filters=RetrievalFilter(),
        limit=8,
    )

    content = "\n".join(str(candidate.source.get("content") or "") for candidate in candidates)
    assert "Beneficio avanzado para membresias" in content
    assert "tipo=parent_of" in content
    assert "calculation_templates.template_main" in content


def test_concept_query_matches_plural_question_to_singular_declared_metadata(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Relaciona variantes de numero sin exigir el identificador tecnico.

    Args:
        tmp_path: Workspace sintetico aislado.
        capsys: Captura salidas de preparacion de la CLI.
    """
    config = _prepare_workspace(tmp_path)
    _run_pipeline(config, capsys, index=False)
    settings = load_settings(config, environ={}, cwd=tmp_path)
    retriever = _structured_retriever(
        settings,
        SQLiteRagRepository(settings.database_path),
    )

    candidates = retriever.retrieve(
        "Que variables se usan para bonificaciones preferentes?",
        filters=RetrievalFilter(),
        limit=8,
    )

    content = "\n".join(
        str(candidate.source.get("content") or "") for candidate in candidates
    )
    assert candidates
    assert "Calculo de bonificacion preferente" in content
    assert "configuration_variable" in content
    assert "relacion_id=" in content


def test_structured_ranking_prefers_rare_concepts_over_frequent_generic_terms(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Prioriza cobertura discriminante sobre coincidencias genericas aisladas."""
    config = _prepare_workspace(tmp_path)
    _run_pipeline(config, capsys, index=False)
    settings = load_settings(config, environ={}, cwd=tmp_path)
    retriever = _structured_retriever(
        settings,
        SQLiteRagRepository(settings.database_path),
    )

    candidates = retriever.retrieve(
        "Que variables de configuracion intervienen en calculos y "
        "bonificaciones preferentes?",
        filters=RetrievalFilter(),
        limit=12,
    )
    structured = tuple(
        candidate
        for candidate in candidates
        if candidate.source.get("evidence_kind") == "structured_symbol"
    )

    assert len(structured) >= 2
    assert "Calculo de bonificacion preferente" in str(
        structured[0].source["content"]
    )
    generic = next(
        candidate
        for candidate in structured
        if "Variables de configuracion para calculos generales"
        in str(candidate.source["content"])
    )
    assert structured[0].combined_score > generic.combined_score


def test_structured_ranking_is_stable_for_singular_plural_and_exact_identity(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Conserva orden morfologico, consulta especifica e identidad exacta."""
    config = _prepare_workspace(tmp_path)
    _run_pipeline(config, capsys, index=False)
    settings = load_settings(config, environ={}, cwd=tmp_path)
    retriever = _structured_retriever(
        settings,
        SQLiteRagRepository(settings.database_path),
    )

    singular = retriever.retrieve(
        "bonificacion preferente",
        filters=RetrievalFilter(),
        limit=8,
    )
    plural = retriever.retrieve(
        "bonificaciones preferentes",
        filters=RetrievalFilter(),
        limit=8,
    )
    one_term = retriever.retrieve(
        "bonificacion",
        filters=RetrievalFilter(),
        limit=8,
    )
    exact = retriever.retrieve(
        "calculation_templates.template_main",
        filters=RetrievalFilter(),
        limit=8,
    )
    composite_concept = retriever.retrieve(
        "templates",
        filters=RetrievalFilter(),
        limit=8,
    )

    assert singular and plural and one_term and exact and composite_concept
    assert singular[0].source["symbol_id"] == plural[0].source["symbol_id"]
    assert "Calculo de bonificacion preferente" in str(
        one_term[0].source["content"]
    )
    assert "calculation_templates.template_main" in str(
        exact[0].source["content"]
    )
    assert "calculation_templates" in str(
        composite_concept[0].source["content"]
    )


def test_structured_retrieval_excludes_stale_out_of_scope_and_unselected_values(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Protege vigencia, alcance y metadata no declarada.

    Args:
        tmp_path: Workspace sintetico aislado.
        capsys: Captura salidas de preparacion de la CLI.
    """
    config = _prepare_workspace(tmp_path)
    _run_pipeline(config, capsys, index=False)
    settings = load_settings(config, environ={}, cwd=tmp_path)
    rag_repository = SQLiteRagRepository(settings.database_path)
    retriever = _structured_retriever(settings, rag_repository)

    assert retriever.retrieve(
        "concepto retirado",
        filters=RetrievalFilter(),
        limit=8,
    ) == ()

    service = _ask_service(settings, _fake_search_service(settings), StructuredFakeLlm())
    result = service.ask(
        QUESTION,
        mode=RetrievalMode.KEYWORD,
        filters=RetrievalFilter(folder="configuration"),
        top_k=8,
        candidate_k=12,
        threshold=0,
        no_llm=True,
    )

    context = result.context.rendered_context
    assert "Evidencia estructurada del catalogo tecnico" in context
    assert "evidencia=related_code" not in context
    assert "DO_NOT_EXPOSE" not in context
    assert all(
        source.candidate.source.get("artifact_kind") == "configuration"
        for source in result.context.sources
    )


@pytest.mark.parametrize("mode", tuple(RetrievalMode))
def test_structured_retrieval_preserves_all_search_modes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mode: RetrievalMode,
) -> None:
    """Mantiene evidencia estructurada en keyword, semantic e hybrid.

    Args:
        tmp_path: Workspace sintetico aislado.
        capsys: Captura salidas de preparacion de la CLI.
        mode: Modo de retrieval existente que se conserva.
    """
    config = _prepare_workspace(tmp_path)
    _run_pipeline(config, capsys, index=False)
    settings = load_settings(config, environ={}, cwd=tmp_path)
    service = _ask_service(
        settings,
        _fake_search_service(settings),
        StructuredFakeLlm(),
    )

    result = service.ask(
        QUESTION,
        mode=mode,
        top_k=8,
        candidate_k=12,
        threshold=0,
        no_llm=True,
    )

    assert any(
        source.candidate.source.get("evidence_kind") == "structured_symbol"
        for source in result.context.sources
    )


def _prepare_workspace(tmp_path: Path) -> Path:
    """Crea configuraciones, DML y codigo sinteticos.

    Args:
        tmp_path: Directorio temporal de la prueba.

    Returns:
        Ruta al TOML ejecutable del workspace.
    """
    sources = tmp_path / "sources"
    configuration = sources / "configuration"
    oracle = sources / "oracle"
    powerbuilder = sources / "powerbuilder"
    configuration.mkdir(parents=True)
    oracle.mkdir()
    powerbuilder.mkdir()
    (configuration / "templates.sql").write_text(
        "\n".join(
            (
                "INSERT INTO APP_CONFIG.CALCULATION_TEMPLATES ",
                "(TEMPLATE_ID, TEMPLATE_NAME, DESCRIPTION_TEXT, VARIABLE_KEY, "
                "EXPRESSION_TEXT, FUNCTION_NAME, HANDLER_NAME, PARENT_TEMPLATE_ID, "
                "NEXT_TEMPLATE_ID, STATUS_CODE, SECRET_PAYLOAD) VALUES ",
                "('TEMPLATE_MAIN', 'Plantilla preferente', "
                "'Calculo de bonificacion preferente para membresias', "
                "'INPUT_AMOUNT', 'APPLY_BONUS([@INPUT_AMOUNT])', 'apply_bonus', "
                "'n_bonus_view', NULL, 'TEMPLATE_CHILD', 'ACTIVE', "
                "'DO_NOT_EXPOSE');",
                "INSERT INTO APP_CONFIG.CALCULATION_TEMPLATES ",
                "(TEMPLATE_ID, TEMPLATE_NAME, DESCRIPTION_TEXT, VARIABLE_KEY, "
                "EXPRESSION_TEXT, FUNCTION_NAME, HANDLER_NAME, PARENT_TEMPLATE_ID, "
                "NEXT_TEMPLATE_ID, STATUS_CODE, SECRET_PAYLOAD) VALUES ",
                "('TEMPLATE_CHILD', 'Plantilla avanzada', "
                "'Beneficio avanzado para membresias', 'INPUT_LIMIT', "
                "'APPLY_BONUS([@INPUT_LIMIT])', 'apply_bonus', 'n_bonus_view', "
                "'TEMPLATE_MAIN', NULL, 'ACTIVE', 'DO_NOT_EXPOSE');",
                "INSERT INTO APP_CONFIG.CALCULATION_TEMPLATES ",
                "(TEMPLATE_ID, TEMPLATE_NAME, DESCRIPTION_TEXT, STATUS_CODE) VALUES ",
                "('TEMPLATE_OLD', 'Plantilla retirada', 'Concepto retirado', "
                "'INACTIVE');",
                "INSERT INTO APP_CONFIG.CALCULATION_TEMPLATES ",
                "(TEMPLATE_ID, TEMPLATE_NAME, DESCRIPTION_TEXT, VARIABLE_KEY, "
                "STATUS_CODE) VALUES ",
                "('TEMPLATE_GENERIC_A', 'Variables comunes A', "
                "'Variables de configuracion para calculos generales', "
                "'INPUT_COMMON_A', 'ACTIVE');",
                "INSERT INTO APP_CONFIG.CALCULATION_TEMPLATES ",
                "(TEMPLATE_ID, TEMPLATE_NAME, DESCRIPTION_TEXT, VARIABLE_KEY, "
                "STATUS_CODE) VALUES ",
                "('TEMPLATE_GENERIC_B', 'Variables comunes B', "
                "'Variables de configuracion para calculos generales', "
                "'INPUT_COMMON_B', 'ACTIVE');",
            )
        ),
        encoding="utf-8",
    )
    (oracle / "apply_bonus.fnc").write_text(
        "\n".join(
            (
                "CREATE FUNCTION apply_bonus RETURN NUMBER AS",
                "BEGIN",
                "  -- Aplica el porcentaje configurado para bonificacion preferente.",
                "  RETURN 10;",
                "END apply_bonus;",
            )
        ),
        encoding="utf-8",
    )
    (powerbuilder / "n_bonus_view.srf").write_text(
        "\n".join(
            (
                "$PBExportHeader$n_bonus_view.srf",
                "type n_bonus_view from function_object",
                "// Presenta el beneficio calculado para la membresia.",
                "end type",
            )
        ),
        encoding="utf-8",
    )
    for name in ("data", "output", "logs"):
        (tmp_path / name).mkdir()
    initialize_database(tmp_path / "data" / "barbarion.db")
    config = tmp_path / "barbarion.toml"
    config.write_text(
        "\n".join(
            (
                'domain = "structured-rag"',
                'data_dir = "data"',
                'output_dir = "output"',
                'logs_dir = "logs"',
                'database_path = "data/barbarion.db"',
                "[ingestion]",
                f'paths = ["{sources.as_posix()}"]',
                'extensions = [".sql", ".fnc", ".srf"]',
                "chunk_size = 500",
                "chunk_overlap = 20",
                "[data_driven]",
                "enabled = true",
                'file_patterns = ["configuration/*.sql"]',
                "token_patterns = ['\\[@([A-Za-z_][A-Za-z0-9_]*)\\]']",
                "[[data_driven.configurations]]",
                'name = "calculation_templates"',
                'symbol_type = "configuration_record"',
                'tables = ["APP_CONFIG.CALCULATION_TEMPLATES"]',
                'identity_columns = ["TEMPLATE_ID"]',
                'name_columns = ["TEMPLATE_NAME"]',
                'description_columns = ["DESCRIPTION_TEXT"]',
                'formula_columns = ["EXPRESSION_TEXT"]',
                'variable_columns = ["VARIABLE_KEY"]',
                "reference_columns = [",
                '  { column = "FUNCTION_NAME", target_technology = "oracle", '
                'target_type = "function", relation_type = "calls" },',
                '  { column = "HANDLER_NAME", target_technology = "powerbuilder", '
                'target_type = "function_object", relation_type = "calls" },',
                '  { column = "NEXT_TEMPLATE_ID", '
                'target_configuration = "calculation_templates", '
                'target_type = "configuration_record", '
                'relation_type = "precedes" }',
                "]",
                "parent_columns = [",
                '  { column = "PARENT_TEMPLATE_ID", '
                'target_configuration = "calculation_templates" }',
                "]",
                "status_columns = [",
                '  { column = "STATUS_CODE", active_values = ["ACTIVE"], '
                'inactive_values = ["INACTIVE"] }',
                "]",
            )
        ),
        encoding="utf-8",
    )
    return config


def _run_pipeline(
    config: Path,
    capsys: pytest.CaptureFixture[str],
    *,
    index: bool = True,
) -> None:
    """Ejecuta ingesta, analisis y opcionalmente indexacion.

    Args:
        config: Ruta al TOML sintetico.
        capsys: Captura las salidas CLI entre etapas.
        index: Indica si debe generarse el indice vectorial fake.
    """
    assert cli.main(["--config", str(config), "ingest"]) == 0
    capsys.readouterr()
    assert cli.main(["--config", str(config), "analyze", "--full"]) == 0
    capsys.readouterr()
    if index:
        assert _fake_index_service(
            load_settings(config, environ={}, cwd=config.parent)
        ).run().status.value == "completed"


def _fake_index_service(settings: Settings) -> IndexService:
    """Construye indexacion local con embeddings deterministas.

    Args:
        settings: Configuracion efectiva del workspace.

    Returns:
        Servicio de indexacion sin red.
    """
    return IndexService(
        settings=settings,
        repository=SQLiteRagRepository(settings.database_path),
        embedding_provider=DeterministicFakeEmbeddingProvider(dimension=4),
        vector_store=SQLiteVecStore(settings.database_path),
    )


def _fake_search_service(settings: Settings) -> SearchService:
    """Construye retrieval compatible con embeddings deterministas.

    Args:
        settings: Configuracion efectiva del workspace.

    Returns:
        Servicio RAG sin dependencias externas.
    """
    return SearchService(
        settings=settings,
        repository=SQLiteRagRepository(settings.database_path),
        embedding_provider=DeterministicFakeEmbeddingProvider(dimension=4),
        vector_store=SQLiteVecStore(settings.database_path),
    )


def _structured_retriever(
    settings: Settings,
    rag_repository: SQLiteRagRepository,
) -> DataDrivenEvidenceRetriever:
    """Crea retrieval estructurado sobre el mismo SQLite local.

    Args:
        settings: Configuracion efectiva del workspace.
        rag_repository: Repositorio de chunks usado para expansion.

    Returns:
        Recuperador Data-Driven de solo lectura.
    """
    return DataDrivenEvidenceRetriever(
        repository=SQLiteReverseEngineeringRepository(settings.database_path),
        rag_repository=rag_repository,
        domain=settings.domain,
    )


def _ask_service(
    settings: Settings,
    search_service: SearchService,
    llm: StructuredFakeLlm,
) -> AskService:
    """Construye `AskService` con retrieval estructurado y LLM fake.

    Args:
        settings: Configuracion efectiva del workspace.
        search_service: Retrieval de chunks local.
        llm: Proveedor determinista controlado.

    Returns:
        Servicio listo para las pruebas de respuesta.
    """
    return AskService(
        search_service=search_service,
        context_builder=ContextBuilder(
            token_budget=4000,
            max_chunk_tokens=800,
            dedupe_min_hash_prefix=16,
            threshold=0,
        ),
        prompt_builder=PromptBuilder(),
        citation_validator=CitationValidator(),
        llm_provider=llm,
        settings=settings,
        structured_retriever=_structured_retriever(
            settings,
            search_service.repository,
        ),
    )


def _source_id_containing(prompt: str, marker: str) -> str:
    """Encuentra el ID de la fuente cuyo bloque contiene un marcador.

    Args:
        prompt: Prompt completo con fuentes numeradas.
        marker: Texto distintivo esperado en una fuente.

    Returns:
        ID sin corchetes, por ejemplo `F1`.

    Raises:
        AssertionError: Si ninguna fuente contiene el marcador.
    """
    for block in re.split(r"(?=\[F\d+\])", prompt):
        if marker not in block:
            continue
        match = re.match(r"\[(F\d+)\]", block)
        if match is not None:
            return match.group(1)
    raise AssertionError(f"No se encontro una fuente con: {marker}")
