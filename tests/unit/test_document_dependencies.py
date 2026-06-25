from __future__ import annotations

import tomllib
from importlib.metadata import metadata, version
from pathlib import Path


def test_document_dependencies_are_declared_for_runtime() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["dependencies"] == [
        "pypdf>=6.0,<7",
        "python-docx>=1.1,<2",
    ]


def test_document_dependencies_are_python312_compatible_and_open_source() -> None:
    pypdf_metadata = metadata("pypdf")
    docx_metadata = metadata("python-docx")

    assert version("pypdf").startswith("6.")
    assert pypdf_metadata["License-Expression"] == "BSD-3-Clause"
    assert "Programming Language :: Python :: 3.12" in pypdf_metadata.get_all(
        "Classifier"
    )

    assert version("python-docx").startswith("1.")
    assert docx_metadata["License"] == "MIT"
    assert docx_metadata["Requires-Python"] == ">=3.9"
