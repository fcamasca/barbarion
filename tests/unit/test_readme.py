from pathlib import Path


def test_quick_start_documents_ollama_model_and_list() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "ollama pull llama3.1:8b" in readme
    assert "ollama list" in readme
    assert 'barbarion doctor' in readme
    assert 'barbarion search "consulta"' in readme
    assert 'barbarion search "donde se calcula order_total"' in readme
    assert 'barbarion ask "pregunta"' in readme
    assert 'barbarion ask "que fuentes explican order_total?"' in readme
    assert 'barbarion spec create "Agregar validacion de limite de credito"' in readme
    assert 'barbarion spec validate output/specs/limite-credito' in readme
    assert "`--mode keyword`: coincidencia textual" in readme
    assert "`--mode semantic`: similitud por significado" in readme
    assert "`--mode hybrid`: combina keyword y semantic" in readme
