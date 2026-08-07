"""H3.2-TP-038..043: gate real antes de prompt y frontera generativa."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from barbarion.application.privacy import (
    PrivacyPreflightBlockedError,
    PrivacyPreflightService,
    UnavailableAccountPrivacyVerifier,
)
from barbarion.application.rag import (
    AskService,
    CitationValidator,
    ContextBuilder,
    PromptBuilder,
)
from barbarion.domain.privacy import (
    InferenceTarget,
    PrivacyConstraint,
    PrivacyEvidence,
    PrivacyPolicy,
    PrivacyPolicySourceResult,
)
from barbarion.domain.rag import RagQueryStatus, RetrievalMode
from tests.unit.test_rag_search_service import service_for


NOW = datetime(2026, 8, 7, 12, tzinfo=UTC)


class RecordingLlm:
    provider = "synthetic"
    model = "synthetic-v1"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, *, prompt: str, timeout_seconds: float) -> str:
        assert timeout_seconds > 0
        self.prompts.append(prompt)
        return "order_total se selecciona desde dual [F1]."


class RecordingPromptBuilder:
    def __init__(self) -> None:
        self.delegate = PromptBuilder()
        self.build_calls = 0

    def build(self, **kwargs):  # noqa: ANN003, ANN201
        self.build_calls += 1
        return self.delegate.build(**kwargs)

    def __getattr__(self, name: str):  # noqa: ANN204
        return getattr(self.delegate, name)


class StaticPolicySource:
    def __init__(self, evidence: tuple[PrivacyEvidence, ...]) -> None:
        self.evidence = evidence
        self.calls: list[InferenceTarget] = []

    def lookup(self, target: InferenceTarget) -> PrivacyPolicySourceResult:
        self.calls.append(target)
        return PrivacyPolicySourceResult(
            source_id="synthetic-local-cache",
            source_version="v1",
            evidence=self.evidence,
        )


class ForbiddenPreflight:
    def __init__(self) -> None:
        self.calls = 0

    def authorize(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls += 1
        raise AssertionError(f"preflight no debio ejecutarse: {kwargs}")


class ForbiddenVerifier:
    def verify(self, target: InferenceTarget):  # noqa: ANN201
        raise AssertionError(f"verifier no debio ejecutarse: {target}")


def _evidence(
    constraint: PrivacyConstraint,
    value: str | int,
    *,
    conditional: bool = False,
) -> PrivacyEvidence:
    return PrivacyEvidence(
        constraint=constraint,
        value=value,
        scope="offering:synthetic",
        source_kind="external_registry",
        source_id=f"synthetic:{constraint.value}",
        verified_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=1),
        conditional_on_account=conditional,
    )


def _passing_evidence() -> tuple[PrivacyEvidence, ...]:
    return (
        _evidence(PrivacyConstraint.NO_TRAINING, "no_training_guaranteed"),
        _evidence(PrivacyConstraint.RETENTION, "zdr"),
        _evidence(PrivacyConstraint.DATA_LOCATION, "us"),
    )


def _service(
    tmp_path,
    *,
    execution: str | None,
    remote: bool,
    evidence: tuple[PrivacyEvidence, ...] = (),
    preflight=None,
) -> tuple[AskService, RecordingLlm, RecordingPromptBuilder, StaticPolicySource]:
    search = service_for(tmp_path)
    llm = RecordingLlm()
    prompt_builder = RecordingPromptBuilder()
    settings = replace(
        search.settings,
        llm=replace(
            search.settings.llm,
            provider="anthropic" if remote else "ollama",
            execution=execution,
            model="synthetic-v1",
            max_output_tokens=1024 if remote else None,
        ),
        rag=replace(search.settings.rag, input_token_budget_est=4500),
    )
    source = StaticPolicySource(evidence)
    effective_preflight = preflight or PrivacyPreflightService(
        policy=PrivacyPolicy(allowed_regions=("us",)),
        policy_source=source,
        account_verifier=UnavailableAccountPrivacyVerifier(),
        clock=lambda: NOW,
    )
    service = AskService(
        search_service=search,
        context_builder=ContextBuilder(
            token_budget=200,
            max_chunk_tokens=100,
            dedupe_min_hash_prefix=8,
            threshold=0,
        ),
        prompt_builder=prompt_builder,
        citation_validator=CitationValidator(),
        llm_provider=llm,
        settings=settings,
        privacy_preflight=effective_preflight,
    )
    return service, llm, prompt_builder, source


def _ask(service: AskService, question: str = "order_total", *, no_llm: bool = False):
    return service.ask(
        question,
        mode=RetrievalMode.KEYWORD,
        top_k=3,
        candidate_k=3,
        threshold=0,
        no_llm=no_llm,
        debug=True,
    )


def test_tp038_local_is_not_applicable_and_generates_without_sources(tmp_path) -> None:
    service, llm, builder, source = _service(
        tmp_path,
        execution="local",
        remote=False,
        preflight=PrivacyPreflightService(
            policy=PrivacyPolicy(),
            policy_source=None,
            account_verifier=ForbiddenVerifier(),
            clock=lambda: NOW,
        ),
    )

    result = _ask(service)

    assert result.status is RagQueryStatus.COMPLETED
    assert len(llm.prompts) == 1
    assert builder.build_calls == 1
    assert source.calls == []


def test_tp039_remote_all_pass_authorizes_exactly_one_generation(tmp_path) -> None:
    service, llm, builder, source = _service(
        tmp_path,
        execution=None,
        remote=True,
        evidence=_passing_evidence(),
    )

    result = _ask(service)

    assert result.status is RagQueryStatus.COMPLETED
    assert len(llm.prompts) == 1
    assert builder.build_calls == 1
    assert len(source.calls) == 1


@pytest.mark.parametrize(
    ("evidence", "constraint"),
    [
        (
            (
                _evidence(PrivacyConstraint.NO_TRAINING, "training_confirmed"),
                _evidence(PrivacyConstraint.RETENTION, "zdr"),
                _evidence(PrivacyConstraint.DATA_LOCATION, "us"),
            ),
            PrivacyConstraint.NO_TRAINING,
        ),
        (
            (
                _evidence(PrivacyConstraint.NO_TRAINING, "no_training_guaranteed"),
                _evidence(
                    PrivacyConstraint.RETENTION,
                    "zdr_available",
                    conditional=True,
                ),
                _evidence(PrivacyConstraint.DATA_LOCATION, "us"),
            ),
            PrivacyConstraint.RETENTION,
        ),
        (
            (
                _evidence(PrivacyConstraint.NO_TRAINING, "no_training_guaranteed"),
                _evidence(PrivacyConstraint.RETENTION, "zdr"),
            ),
            PrivacyConstraint.DATA_LOCATION,
        ),
    ],
)
def test_tp040_042_remote_block_never_builds_prompt_or_generates(
    tmp_path,
    caplog: pytest.LogCaptureFixture,
    evidence: tuple[PrivacyEvidence, ...],
    constraint: PrivacyConstraint,
) -> None:
    service, llm, builder, _ = _service(
        tmp_path,
        execution=None,
        remote=True,
        evidence=evidence,
    )
    caplog.set_level(logging.INFO, logger="barbarion")

    with pytest.raises(PrivacyPreflightBlockedError) as captured:
        _ask(service)

    assert captured.value.result.evaluation_for(constraint).state.value != "pass"
    assert llm.prompts == []
    assert builder.build_calls == 0
    assert not any("ask_llm_started" in record.message for record in caplog.records)


def test_tp043_unknown_execution_blocks_before_prompt_and_generation(tmp_path) -> None:
    service, llm, builder, source = _service(
        tmp_path,
        execution=None,
        remote=False,
    )

    with pytest.raises(PrivacyPreflightBlockedError):
        _ask(service)

    assert llm.prompts == []
    assert builder.build_calls == 0
    assert source.calls == []


@pytest.mark.parametrize(
    ("question", "no_llm", "expected_status"),
    [
        ("order_total", True, RagQueryStatus.COMPLETED),
        (
            "identificador_sintetico_totalmente_ausente",
            False,
            RagQueryStatus.INSUFFICIENT_EVIDENCE,
        ),
    ],
)
def test_local_returns_happen_before_preflight(
    tmp_path,
    question: str,
    no_llm: bool,
    expected_status: RagQueryStatus,
) -> None:
    forbidden = ForbiddenPreflight()
    service, llm, builder, _ = _service(
        tmp_path,
        execution=None,
        remote=True,
        preflight=forbidden,
    )

    result = _ask(service, question, no_llm=no_llm)

    assert result.status is expected_status
    assert forbidden.calls == 0
    assert llm.prompts == []
    assert builder.build_calls == 0


def test_common_generation_wrapper_rejects_missing_authorization(tmp_path) -> None:
    service, llm, _, _ = _service(
        tmp_path,
        execution=None,
        remote=True,
        evidence=_passing_evidence(),
    )

    with pytest.raises(ValueError, match="PrivacyAuthorization"):
        service._generate_with_observability(
            "synthetic prompt",
            stage="generation",
            authorization=None,  # type: ignore[arg-type]
        )

    assert llm.prompts == []
