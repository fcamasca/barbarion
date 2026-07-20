"""Contratos puros del dataset sintetico para benchmark de modelos."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class BenchmarkCategory(StrEnum):
    """Categorias cerradas del dataset v1."""

    FACTUAL = "respuesta_factual"
    INSTRUCTIONS = "instrucciones"
    INSUFFICIENT_EVIDENCE = "evidencia_insuficiente"
    AMBIGUITY = "ambiguedad"
    CONTEXT_AND_CITATIONS = "contexto_y_citas"


class ExpectedValidator(StrEnum):
    """Resultado esperado del validador RAG vigente."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"


class InstructionKind(StrEnum):
    """Reglas verificables admitidas; no contienen codigo ejecutable."""

    LANGUAGE = "language"
    REQUIRED_SECTION = "required_section"
    REQUIRED_PHRASE = "required_phrase"
    FORBIDDEN_PHRASE = "forbidden_phrase"
    MAX_SENTENCES = "max_sentences"


@dataclass(frozen=True, slots=True)
class BenchmarkContextFragment:
    citation_id: str
    content: str
    source: str


@dataclass(frozen=True, slots=True)
class BenchmarkExpectedFact:
    id: str
    all_terms: tuple[str, ...]
    citations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BenchmarkForbiddenClaim:
    id: str
    any_terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BenchmarkInstruction:
    id: str
    kind: InstructionKind
    value: str


@dataclass(frozen=True, slots=True)
class ModelBenchmarkCase:
    id: str
    category: BenchmarkCategory
    question: str
    context: tuple[BenchmarkContextFragment, ...]
    expected_facts: tuple[BenchmarkExpectedFact, ...]
    forbidden_claims: tuple[BenchmarkForbiddenClaim, ...]
    instructions: tuple[BenchmarkInstruction, ...]
    expected_validator: ExpectedValidator


@dataclass(frozen=True, slots=True)
class ModelBenchmarkDataset:
    schema_version: int
    dataset_id: str
    cases: tuple[ModelBenchmarkCase, ...]
    dataset_hash: str

