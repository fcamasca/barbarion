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
