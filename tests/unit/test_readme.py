from pathlib import Path

from barbarion import __version__


def test_readme_documents_portfolio_overview_and_mvp_status() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "## Problema que resuelve" in readme
    assert "## ¿Qué puede hacer?" in readme
    assert "## Cómo funciona" in readme
    assert "## Ejemplo end-to-end" in readme
    assert "## Estado del MVP" in readme
    assert f"Versión actual: `{__version__}`" in readme
    assert "Hitos completados: `5/5`" in readme
    assert "Suite de aceptación del MVP: `502 passed, 2 skipped`" in readme
    assert "Suite de aceptación del MVP: `502 passed, 2 skipped`" in readme
    assert "Smoke tests instalados: `10 passed`" in readme
    assert "Integración continua: GitHub Actions" in readme
    assert "H1.1 Gestión y Evaluación de Modelos Locales" in readme
    assert "Suite oficial H1.1: `713 passed, 3 skipped`" in readme
    assert "specs/H1.1-LocalModelManagement/acceptance.md" in readme


def test_readme_documents_short_quick_start_and_demo_placeholders() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "python -m pip install -e \".[dev]\"" in readme
    assert "barbarion doctor" in readme
    assert "barbarion ingest" in readme
    assert "barbarion index" in readme
    assert "barbarion analyze" in readme
    assert 'barbarion ask "Dónde se calcula order_total?" --mode hybrid' in readme
    assert 'barbarion impact order_total --depth 2 --no-llm' in readme
    assert 'barbarion spec create "Agregar validación de límite de crédito"' in readme
    assert "docs/images/" in readme
    assert "docs/CLI.md" in readme


def test_readme_documents_data_driven_operation() -> None:
    """Comprueba que README enlaza el flujo operativo Data-Driven."""
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "## Configuraciones Data-Driven" in readme
    assert "data_driven.enabled" in readme
    assert "barbarion analyze --dry-run" in readme
    assert "barbarion inventory --technology configuration" in readme
    assert "barbarion stats --format json" in readme


def test_readme_documents_local_model_benchmark_operation() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "## Modelos locales y benchmark" in readme
    assert "barbarion models list" in readme
    assert "barbarion models benchmark --models" in readme
    assert "model-benchmark.json" in readme
    assert "model-benchmark.md" in readme
    assert "no se calcula p95" in readme
    assert "nunca cambia el modelo activo" in readme


def test_h12_documentation_describes_remote_boundary_and_current_status() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    example = Path("barbarion.example.toml").read_text(encoding="utf-8")
    vision = Path("docs/VISION.md").read_text(encoding="utf-8")
    architecture = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    decisions = Path("docs/DECISIONS.md").read_text(encoding="utf-8")
    evolution = Path("docs/EVOLUTION.md").read_text(encoding="utf-8")
    roadmap = Path("docs/ROADMAP.md").read_text(encoding="utf-8")
    specs = Path("specs/README.md").read_text(encoding="utf-8")

    assert "### Inferencia remota con Anthropic" in readme
    assert 'provider = "anthropic"' in readme
    assert "ANTHROPIC_API_KEY" in readme
    assert "max_output_tokens" in readme
    assert "realiza retries, fallback a Ollama ni cálculo de costos" in readme
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
