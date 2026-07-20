"""Contratos puros del dataset sintetico para benchmark de modelos."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from barbarion.domain.local_models import ModelGenerationTelemetry
from barbarion.domain.rag import CitationValidation


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


class BenchmarkRunStatus(StrEnum):
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    INTERRUPTED = "interrupted"


class BenchmarkUnitStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ModelBenchmarkCaseMetrics:
    answer_quality: float | None
    instruction_following: float | None
    groundedness: float | None
    context_use: float | None
    citation_score: float | None
    validator_acceptance: float | None


@dataclass(frozen=True, slots=True)
class ModelBenchmarkCaseScore:
    """Score lexical trazable; no representa una verdad semantica."""

    metrics: ModelBenchmarkCaseMetrics
    quality_score: float | None
    recommendation_score: float | None
    applied_weight: float
    satisfied_facts: tuple[str, ...] = ()
    missed_facts: tuple[str, ...] = ()
    detected_forbidden_claims: tuple[str, ...] = ()
    satisfied_instructions: tuple[str, ...] = ()
    failed_instructions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelBenchmarkUnitResult:
    """Resultado confirmado de una unica combinacion caso/modelo."""

    case_id: str
    category: BenchmarkCategory
    model: str
    execution_order: int
    status: BenchmarkUnitStatus
    question_hash: str
    context_hash: str
    prompt_hash: str
    duration_ms: int
    response: str | None = None
    validation: CitationValidation | None = None
    telemetry: ModelGenerationTelemetry | None = None
    score: ModelBenchmarkCaseScore | None = None
    error_code: str | None = None
    error_detail: str | None = None


@dataclass(frozen=True, slots=True)
class ModelBenchmarkRunResult:
    """Corrida completa o parcial, sin capacidad de reanudacion."""

    run_id: str
    dataset_id: str
    dataset_hash: str
    models: tuple[str, ...]
    status: BenchmarkRunStatus
    planned_units: int
    units: tuple[ModelBenchmarkUnitResult, ...]

    @property
    def completed_units(self) -> int:
        return sum(unit.status is BenchmarkUnitStatus.COMPLETED for unit in self.units)

    @property
    def failed_units(self) -> int:
        return sum(unit.status is BenchmarkUnitStatus.FAILED for unit in self.units)


@dataclass(frozen=True, slots=True)
class ModelBenchmarkAggregate:
    """Agregados por modelo con null y cobertura explicitos."""

    model: str
    planned_units: int
    confirmed_units: int
    completed_units: int
    failed_units: int
    completion_rate: float
    acceptance_rate: float | None
    mean_metrics: ModelBenchmarkCaseMetrics
    mean_quality_score: float | None
    recommendation_quality_score: float | None
    recommendation_eligible: bool
    average_duration_ms: float | None
    median_duration_ms: float | None
    prompt_tokens_total: int | None
    prompt_tokens_median: float | None
    prompt_tokens_coverage: float
    output_tokens_total: int | None
    output_tokens_median: float | None
    output_tokens_coverage: float
    failures_by_code: tuple[tuple[str, int], ...]
