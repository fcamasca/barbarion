from __future__ import annotations

from pathlib import Path

from tests.support.h2_corpus import (
    EXPECTED_EXTENSIONS,
    build_h2_corpus,
    fixture_inventory,
)


def test_h2_synthetic_corpus_covers_all_supported_extensions(tmp_path: Path) -> None:
    root = build_h2_corpus(tmp_path / "corpus", include_errors=True)

    inventory = fixture_inventory(root)

    assert EXPECTED_EXTENSIONS <= set(inventory)
    assert inventory[".pdf"] >= 3
    assert inventory[".docx"] >= 2
    assert inventory[".pbl"] == 1
    assert not any("barbarion" in path.name.lower() for path in root.rglob("*"))
