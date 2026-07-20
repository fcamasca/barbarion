"""Contrato del loader y dataset sintetico v1."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

import pytest

from barbarion.application.model_benchmark_dataset import (
    MODEL_BENCHMARK_DATASET_ID,
    ModelBenchmarkDatasetError,
    load_model_benchmark_dataset,
)
from barbarion.domain.model_benchmark import BenchmarkCategory


FIXTURE = Path(__file__).parents[1] / "fixtures" / "model_benchmark.json"


def _payload() -> dict:  # noqa: ANN401
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _write(tmp_path: Path, payload: dict, *, indent: int | None = None) -> Path:  # noqa: ANN401
    path = tmp_path / "dataset.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=indent),
        encoding="utf-8",
    )
    return path


def test_default_and_fixture_are_equivalent_neutral_datasets() -> None:
    packaged = load_model_benchmark_dataset()
    fixture = load_model_benchmark_dataset(FIXTURE)

    assert packaged.dataset_id == MODEL_BENCHMARK_DATASET_ID
    assert packaged.schema_version == 1
    assert packaged.cases == fixture.cases
    assert packaged.dataset_hash == fixture.dataset_hash
    assert len(packaged.dataset_hash) == 64
    assert [case.id for case in packaged.cases] == [f"syn-{index:03d}" for index in range(1, 9)]
    assert Counter(case.category for case in packaged.cases) == {
        BenchmarkCategory.FACTUAL: 2,
        BenchmarkCategory.INSTRUCTIONS: 1,
        BenchmarkCategory.INSUFFICIENT_EVIDENCE: 2,
        BenchmarkCategory.AMBIGUITY: 1,
        BenchmarkCategory.CONTEXT_AND_CITATIONS: 2,
    }
    for case in packaged.cases:
        assert case.context
        assert case.expected_facts
        assert case.forbidden_claims
        assert case.instructions
        assert all(fragment.source.startswith("synthetic/") for fragment in case.context)


def test_canonical_hash_ignores_json_format_key_and_case_order(tmp_path: Path) -> None:
    payload = _payload()
    reordered = {
        "cases": list(reversed(payload["cases"])),
        "dataset_id": payload["dataset_id"],
        "schema_version": payload["schema_version"],
    }
    compact = _write(tmp_path, reordered)

    assert load_model_benchmark_dataset(compact).dataset_hash == (
        load_model_benchmark_dataset(FIXTURE).dataset_hash
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.update({"unknown": True}),
        lambda data: data["cases"][0].update({"weight": 1}),
        lambda data: data["cases"][0]["context"][0].update({"blob": "x"}),
        lambda data: data["cases"][0]["expected_facts"][0].update({"weight": 1}),
        lambda data: data["cases"][0]["instructions"][0].update({"kind": "callback"}),
    ],
)
def test_closed_schema_rejects_unknown_keys_rules_and_weights(
    tmp_path: Path,
    mutation,  # noqa: ANN001
) -> None:
    payload = _payload()
    mutation(payload)

    with pytest.raises(ModelBenchmarkDatasetError):
        load_model_benchmark_dataset(_write(tmp_path, payload))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.update({"schema_version": 2}),
        lambda data: data.update({"schema_version": 1.0}),
        lambda data: data["cases"].__setitem__(1, deepcopy(data["cases"][0])),
        lambda data: data["cases"][0].update({"expected_facts": []}),
        lambda data: data["cases"][0]["expected_facts"][0].update({"citations": ["F9"]}),
        lambda data: data["cases"][0]["context"].append(deepcopy(data["cases"][0]["context"][0])),
    ],
)
def test_rejects_invalid_version_duplicates_empty_rubric_and_unknown_citation(
    tmp_path: Path,
    mutation,  # noqa: ANN001
) -> None:
    payload = _payload()
    mutation(payload)

    with pytest.raises(ModelBenchmarkDatasetError):
        load_model_benchmark_dataset(_write(tmp_path, payload))


def test_rejects_more_than_one_hundred_cases(tmp_path: Path) -> None:
    payload = _payload()
    template = payload["cases"][0]
    payload["cases"] = []
    for index in range(101):
        case = deepcopy(template)
        case["id"] = f"case-{index:03d}"
        payload["cases"].append(case)

    with pytest.raises(ModelBenchmarkDatasetError, match="maximo de 100"):
        load_model_benchmark_dataset(_write(tmp_path, payload))


@pytest.mark.parametrize(
    "unsafe_text",
    [
        "Consulta https://example.invalid para completar la respuesta.",
        "Ruta C:\\Users\\Persona\\archivo.txt.",
        "Contacto persona@example.invalid.",
    ],
)
def test_privacy_scan_rejects_external_or_domain_specific_text(
    tmp_path: Path,
    unsafe_text: str,
) -> None:
    payload = _payload()
    payload["cases"][0]["question"] = unsafe_text

    with pytest.raises(ModelBenchmarkDatasetError, match="no sintetica"):
        load_model_benchmark_dataset(_write(tmp_path, payload))


def test_rejects_duplicate_json_keys_before_schema_validation(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text(
        '{"schema_version":1,"schema_version":1,'
        '"dataset_id":"barbarion-local-llm-synthetic-v1","cases":[]}',
        encoding="utf-8",
    )

    with pytest.raises(ModelBenchmarkDatasetError, match="duplicada"):
        load_model_benchmark_dataset(path)
