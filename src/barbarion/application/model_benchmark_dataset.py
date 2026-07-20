"""Loader estricto y canonico del dataset sintetico de modelos."""

from __future__ import annotations

import hashlib
import json
import re
from importlib import resources
from pathlib import Path
from typing import Any

from barbarion.domain.model_benchmark import (
    BenchmarkCategory,
    BenchmarkContextFragment,
    BenchmarkExpectedFact,
    BenchmarkForbiddenClaim,
    BenchmarkInstruction,
    ExpectedValidator,
    InstructionKind,
    ModelBenchmarkCase,
    ModelBenchmarkDataset,
)


MODEL_BENCHMARK_SCHEMA_VERSION = 1
MODEL_BENCHMARK_DATASET_ID = "barbarion-local-llm-synthetic-v1"
MAX_DATASET_BYTES = 1_000_000
MAX_BENCHMARK_CASES = 100

_ROOT_KEYS = frozenset(("schema_version", "dataset_id", "cases"))
_CASE_KEYS = frozenset(
    (
        "id",
        "category",
        "question",
        "context",
        "expected_facts",
        "forbidden_claims",
        "instructions",
        "expected_validator",
    )
)
_CONTEXT_KEYS = frozenset(("citation_id", "content", "source"))
_FACT_KEYS = frozenset(("id", "all_terms", "citations"))
_FORBIDDEN_KEYS = frozenset(("id", "any_terms"))
_INSTRUCTION_KEYS = frozenset(("id", "kind", "value"))
_ID = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_CITATION_ID = re.compile(r"^F[1-9][0-9]{0,2}$")
_SYNTHETIC_SOURCE = re.compile(r"^synthetic/[a-z0-9][a-z0-9_-]{0,63}\.txt$")
_PRIVATE_TEXT = re.compile(
    r"(?:https?://|www\.|[A-Za-z]:[\\/]|(?:^|\s)/(?:home|users?|var|etc)/|"
    r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b(?:oracle|powerbuilder|pl/sql)\b)",
    re.IGNORECASE,
)


class ModelBenchmarkDatasetError(ValueError):
    """Dataset invalido con ubicacion estructural accionable."""


def load_model_benchmark_dataset(
    path: str | Path | None = None,
) -> ModelBenchmarkDataset:
    """Carga el recurso v1 o un JSON indicado y valida todo el contrato."""
    raw = _read_dataset(path)
    try:
        payload = json.loads(raw, object_pairs_hook=_closed_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelBenchmarkDatasetError("El dataset debe ser JSON UTF-8 valido.") from error
    if not isinstance(payload, dict):
        raise ModelBenchmarkDatasetError("dataset debe ser un objeto JSON.")
    _exact_keys(payload, _ROOT_KEYS, "dataset")
    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != MODEL_BENCHMARK_SCHEMA_VERSION
    ):
        raise ModelBenchmarkDatasetError("dataset.schema_version no es compatible.")
    dataset_id = _text(payload["dataset_id"], "dataset.dataset_id", maximum=128)
    if dataset_id != MODEL_BENCHMARK_DATASET_ID:
        raise ModelBenchmarkDatasetError("dataset.dataset_id no es el identificador v1.")
    cases_raw = _list(payload["cases"], "dataset.cases", maximum=MAX_BENCHMARK_CASES)
    cases = tuple(sorted((_case(item, index) for index, item in enumerate(cases_raw)), key=lambda item: item.id))
    _unique((case.id for case in cases), "dataset.cases[].id")
    canonical = _canonical_payload(dataset_id, cases)
    digest = hashlib.sha256(
        json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return ModelBenchmarkDataset(
        schema_version=MODEL_BENCHMARK_SCHEMA_VERSION,
        dataset_id=dataset_id,
        cases=cases,
        dataset_hash=digest,
    )


def _read_dataset(path: str | Path | None) -> bytes:
    try:
        if path is None:
            raw = resources.files("barbarion.resources").joinpath(
                "model_benchmark_v1.json"
            ).read_bytes()
        else:
            raw = Path(path).read_bytes()
    except OSError as error:
        raise ModelBenchmarkDatasetError("No se pudo leer el dataset.") from error
    if len(raw) > MAX_DATASET_BYTES:
        raise ModelBenchmarkDatasetError("El dataset supera 1000000 bytes.")
    return raw


def _closed_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ModelBenchmarkDatasetError(f"Clave JSON duplicada: {key}.")
        result[key] = value
    return result


def _case(value: Any, index: int) -> ModelBenchmarkCase:
    path = f"dataset.cases[{index}]"
    item = _object(value, path)
    _exact_keys(item, _CASE_KEYS, path)
    case_id = _identifier(item["id"], f"{path}.id")
    try:
        category = BenchmarkCategory(item["category"])
        expected_validator = ExpectedValidator(item["expected_validator"])
    except (TypeError, ValueError) as error:
        raise ModelBenchmarkDatasetError(f"{path} contiene un enum desconocido.") from error
    context = tuple(
        _context(entry, f"{path}.context[{position}]")
        for position, entry in enumerate(_list(item["context"], f"{path}.context", maximum=20))
    )
    _unique((entry.citation_id for entry in context), f"{path}.context[].citation_id")
    allowed = {entry.citation_id for entry in context}
    facts = tuple(
        _fact(entry, f"{path}.expected_facts[{position}]", allowed)
        for position, entry in enumerate(_list(item["expected_facts"], f"{path}.expected_facts", maximum=20))
    )
    forbidden = tuple(
        _forbidden(entry, f"{path}.forbidden_claims[{position}]")
        for position, entry in enumerate(_list(item["forbidden_claims"], f"{path}.forbidden_claims", maximum=20))
    )
    instructions = tuple(
        _instruction(entry, f"{path}.instructions[{position}]")
        for position, entry in enumerate(_list(item["instructions"], f"{path}.instructions", maximum=20))
    )
    _unique((entry.id for entry in facts), f"{path}.expected_facts[].id")
    _unique((entry.id for entry in forbidden), f"{path}.forbidden_claims[].id")
    _unique((entry.id for entry in instructions), f"{path}.instructions[].id")
    return ModelBenchmarkCase(
        id=case_id,
        category=category,
        question=_safe_text(item["question"], f"{path}.question", maximum=1000),
        context=context,
        expected_facts=facts,
        forbidden_claims=forbidden,
        instructions=instructions,
        expected_validator=expected_validator,
    )


def _context(value: Any, path: str) -> BenchmarkContextFragment:
    item = _object(value, path)
    _exact_keys(item, _CONTEXT_KEYS, path)
    citation_id = _text(item["citation_id"], f"{path}.citation_id", maximum=4)
    if _CITATION_ID.fullmatch(citation_id) is None:
        raise ModelBenchmarkDatasetError(f"{path}.citation_id no es F1..F999.")
    source = _text(item["source"], f"{path}.source", maximum=80)
    if _SYNTHETIC_SOURCE.fullmatch(source) is None:
        raise ModelBenchmarkDatasetError(f"{path}.source debe estar bajo synthetic/.")
    return BenchmarkContextFragment(
        citation_id=citation_id,
        content=_safe_text(item["content"], f"{path}.content", maximum=4000),
        source=source,
    )


def _fact(value: Any, path: str, allowed: set[str]) -> BenchmarkExpectedFact:
    item = _object(value, path)
    _exact_keys(item, _FACT_KEYS, path)
    terms = _text_list(item["all_terms"], f"{path}.all_terms")
    citations = _text_list(item["citations"], f"{path}.citations")
    unknown = sorted(set(citations) - allowed)
    if unknown:
        raise ModelBenchmarkDatasetError(f"{path}.citations referencia citas inexistentes: {', '.join(unknown)}.")
    return BenchmarkExpectedFact(_identifier(item["id"], f"{path}.id"), terms, citations)


def _forbidden(value: Any, path: str) -> BenchmarkForbiddenClaim:
    item = _object(value, path)
    _exact_keys(item, _FORBIDDEN_KEYS, path)
    return BenchmarkForbiddenClaim(
        _identifier(item["id"], f"{path}.id"),
        _text_list(item["any_terms"], f"{path}.any_terms"),
    )


def _instruction(value: Any, path: str) -> BenchmarkInstruction:
    item = _object(value, path)
    _exact_keys(item, _INSTRUCTION_KEYS, path)
    try:
        kind = InstructionKind(item["kind"])
    except (TypeError, ValueError) as error:
        raise ModelBenchmarkDatasetError(f"{path}.kind no es una regla admitida.") from error
    rule_value = _safe_text(item["value"], f"{path}.value", maximum=128)
    if kind is InstructionKind.MAX_SENTENCES and (
        not rule_value.isdigit() or not 1 <= int(rule_value) <= 20
    ):
        raise ModelBenchmarkDatasetError(f"{path}.value debe ser un entero entre 1 y 20.")
    if kind is InstructionKind.LANGUAGE and rule_value != "es":
        raise ModelBenchmarkDatasetError(f"{path}.value solo admite 'es' en v1.")
    return BenchmarkInstruction(_identifier(item["id"], f"{path}.id"), kind, rule_value)


def _canonical_payload(dataset_id: str, cases: tuple[ModelBenchmarkCase, ...]) -> dict[str, Any]:
    return {
        "schema_version": MODEL_BENCHMARK_SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "cases": [
            {
                "id": case.id,
                "category": case.category.value,
                "question": case.question,
                "context": [
                    {"citation_id": item.citation_id, "content": item.content, "source": item.source}
                    for item in case.context
                ],
                "expected_facts": [
                    {"id": item.id, "all_terms": list(item.all_terms), "citations": list(item.citations)}
                    for item in case.expected_facts
                ],
                "forbidden_claims": [
                    {"id": item.id, "any_terms": list(item.any_terms)}
                    for item in case.forbidden_claims
                ],
                "instructions": [
                    {"id": item.id, "kind": item.kind.value, "value": item.value}
                    for item in case.instructions
                ],
                "expected_validator": case.expected_validator.value,
            }
            for case in cases
        ],
    }


def _exact_keys(item: dict[str, Any], expected: frozenset[str], path: str) -> None:
    actual = set(item)
    if actual != expected:
        unknown = sorted(actual - expected)
        missing = sorted(expected - actual)
        detail = []
        if unknown:
            detail.append(f"desconocidas={','.join(unknown)}")
        if missing:
            detail.append(f"faltantes={','.join(missing)}")
        raise ModelBenchmarkDatasetError(f"{path} tiene claves invalidas ({'; '.join(detail)}).")


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ModelBenchmarkDatasetError(f"{path} debe ser un objeto.")
    return value


def _list(value: Any, path: str, *, maximum: int) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise ModelBenchmarkDatasetError(f"{path} debe ser una lista no vacia.")
    if len(value) > maximum:
        raise ModelBenchmarkDatasetError(f"{path} supera el maximo de {maximum} elementos.")
    return value


def _identifier(value: Any, path: str) -> str:
    text = _text(value, path, maximum=64)
    if _ID.fullmatch(text) is None:
        raise ModelBenchmarkDatasetError(f"{path} no es un identificador valido.")
    return text


def _text(value: Any, path: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ModelBenchmarkDatasetError(f"{path} debe ser texto no vacio sin bordes.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ModelBenchmarkDatasetError(f"{path} debe usar Unicode valido.") from error
    if len(value) > maximum or any(
        ord(character) < 32 or ord(character) == 127 for character in value
    ):
        raise ModelBenchmarkDatasetError(f"{path} excede limites de texto.")
    return value


def _safe_text(value: Any, path: str, *, maximum: int) -> str:
    text = _text(value, path, maximum=maximum)
    if _PRIVATE_TEXT.search(text):
        raise ModelBenchmarkDatasetError(f"{path} contiene texto o ruta no sintetica.")
    return text


def _text_list(value: Any, path: str) -> tuple[str, ...]:
    values = _list(value, path, maximum=20)
    result = tuple(_safe_text(item, f"{path}[]", maximum=128) for item in values)
    _unique(iter(result), path)
    return result


def _unique(values, path: str) -> None:  # noqa: ANN001
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ModelBenchmarkDatasetError(f"{path} contiene duplicados: {value}.")
        seen.add(value)
