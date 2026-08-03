import re
from pathlib import Path

from barbarion import __version__


def _readme() -> str:
    return Path("README.md").read_text(encoding="utf-8")


def test_readme_has_the_expected_entry_point_structure() -> None:
    readme = _readme()
    headings = [
        "## Problema que resuelve",
        "## Capacidades principales",
        "## Cómo funciona",
        "## Quick Start",
        "## Configurar Anthropic",
        "## Comandos principales",
        "## Estado del proyecto",
        "## Documentación",
        "## Licencia",
    ]

    positions = [readme.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert f"Versión actual: `{__version__}`" in readme
    assert "MVP completado: `5/5` hitos" in readme
    assert "Suite de aceptación del MVP: `502 passed, 2 skipped`" in readme
    assert "Smoke tests instalados: `10 passed`" in readme
    assert "Integración continua: GitHub Actions" in readme
    assert readme.index("specs/H5-SpecMode/acceptance.md") < readme.index(
        "Evoluciones posteriores al MVP:"
    )
    assert "Implementación técnica y documentación completadas; aceptación pendiente" in readme


def test_quick_start_remains_ollama_first_and_links_anthropic_setup() -> None:
    readme = _readme()
    quick_start = readme[readme.index("## Quick Start") : readme.index("## Configurar Anthropic")]

    assert "El flujo principal usa Ollama" in quick_start
    assert "python -m pip install -e \".[dev]\"" in quick_start
    assert "barbarion doctor" in quick_start
    assert "barbarion ingest" in quick_start
    assert "barbarion index" in quick_start
    assert "barbarion analyze" in quick_start
    assert 'barbarion ask "¿Dónde se calcula order_total?" --mode hybrid' in quick_start
    assert "[Configurar Anthropic](#configurar-anthropic)" in quick_start
    assert 'provider = "anthropic"' not in quick_start


def test_anthropic_setup_is_copyable_and_states_the_remote_boundary() -> None:
    readme = _readme()
    section = readme[readme.index("## Configurar Anthropic") : readme.index("## Comandos principales")]

    assert "Ollama es el proveedor predeterminado" in section
    assert "Anthropic es opcional" in section
    assert "únicamente la generación final" in section
    assert "El corpus, los embeddings, SQLite, la búsqueda, la ingeniería inversa" in section
    assert "la pregunta, las instrucciones y el contexto seleccionado sí se envían" in section
    assert 'provider = "anthropic"' in section
    assert 'model = "MODELO_CLAUDE"' in section
    assert "max_output_tokens = 4096" in section
    assert "`think` y `num_ctx` son exclusivos de Ollama" in section
    assert "`max_output_tokens` solo se interpreta con Anthropic" in section
    assert '$env:ANTHROPIC_API_KEY = "TU_API_KEY"' in section
    assert 'export ANTHROPIC_API_KEY="TU_API_KEY"' in section
    assert "barbarion config show" in section
    assert "`config show` no valida la API key remota" in section
    assert "no tiene fallback automático a Ollama" in section
    assert "no denomina “créditos” a los tokens ni calcula costos" in section


def test_local_model_benchmark_description_is_brief_and_non_mutating() -> None:
    readme = _readme()

    assert "`barbarion models` trabaja exclusivamente con Ollama" in readme
    assert "Su benchmark compara modelos" in readme
    assert readme.count("no cambia automáticamente el modelo activo") == 1
    assert "specs/H1.1-LocalModelManagement/" in readme
    assert "model-benchmark.json" not in readme
    assert "no se calcula p95" not in readme


def test_readme_local_markdown_links_resolve() -> None:
    readme = _readme()
    local_targets = []

    for target in re.findall(r"\[[^]]*\]\(([^)]+)\)", readme):
        if target.startswith(("http://", "https://", "#")):
            continue
        local_targets.append(target.split("#", maxsplit=1)[0])

    missing = [target for target in local_targets if not Path(target).exists()]
    assert missing == []


def test_h12_documentation_describes_remote_boundary_and_current_status() -> None:
    readme = _readme()
    example = Path("barbarion.example.toml").read_text(encoding="utf-8")
    vision = Path("docs/VISION.md").read_text(encoding="utf-8")
    architecture = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    decisions = Path("docs/DECISIONS.md").read_text(encoding="utf-8")
    evolution = Path("docs/EVOLUTION.md").read_text(encoding="utf-8")
    roadmap = Path("docs/ROADMAP.md").read_text(encoding="utf-8")
    specs = Path("specs/README.md").read_text(encoding="utf-8")

    assert "## Configurar Anthropic" in readme
    assert "ANTHROPIC_API_KEY" in readme
    assert 'provider = "ollama"' in example
    assert '# provider = "anthropic"' in example
    assert "Nunca la" in example and "escribas en este archivo" in example
    assert "Conocimiento local primero" in vision
    assert "LlmProviderPort" in architecture
    assert "AnthropicLlmProvider" in architecture
    assert "factoría cerrada de dos ramas" in architecture
    assert "D-019" in decisions
    assert "Acotada por D-019" in decisions
    assert "## H1.2 -- Inferencia Remota con Anthropic" in evolution
    assert "H1.2 — Inferencia Remota con Anthropic" in roadmap
    assert "[H1.2-RemoteInference](H1.2-RemoteInference/)" in specs
