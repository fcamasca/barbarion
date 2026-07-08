"""Pruebas de contratos puros de H5 Spec Mode."""

from types import MappingProxyType

import pytest

from barbarion.domain.spec_mode import (
    AffectedComponent,
    AffectedComponentRole,
    EvidenceItem,
    EvidenceSourceType,
    ExistingRule,
    RequirementIntent,
    ReviewIssue,
    SpecConclusionKind,
    SpecDraft,
    SpecItemKind,
    SpecRequest,
    TraceLink,
    ValidationIssue,
    ValidationSeverity,
    evidence_id,
    spec_draft_id,
)


VALID_SHA = "a" * 64
OTHER_SHA = "b" * 64


def test_spec_request_validates_and_derives_stable_id() -> None:
    request = SpecRequest(
        requirement="Agregar validacion de limite de credito",
        name="limite-credito",
        retrieval_mode="Hybrid",
        depth=2,
        top_k=8,
        no_llm=True,
    )
    repeated = SpecRequest(
        requirement="Agregar validacion de limite de credito",
        name="limite-credito",
        retrieval_mode="Hybrid",
        depth=2,
        top_k=8,
        no_llm=True,
    )

    assert request.request_id == repeated.request_id
    assert len(request.request_id) == 64


def test_requirement_intent_keeps_original_and_normalized_tuples() -> None:
    intent = RequirementIntent(
        original_text="Validar limite de credito antes de aprobar pedidos",
        goals=("Validar limite",),
        actions=("validar",),
        entities=("limite_credito", "pedido"),
        search_terms=("limite credito", "aprobar pedido"),
    )

    assert intent.original_text.startswith("Validar")
    assert intent.entities == ("limite_credito", "pedido")


def test_evidence_item_freezes_metadata_and_validates_ranges() -> None:
    source_id = evidence_id(
        source_type=EvidenceSourceType.CHUNK,
        source_key="chunk-1",
    )
    item = EvidenceItem(
        evidence_id=source_id,
        source_type=EvidenceSourceType.CHUNK,
        title="Regla en package",
        citation="[F1] sources/oracle/pkg.sql lineas=10-20",
        file_path="sources/oracle/pkg.sql",
        chunk_id="chunk-1",
        start_line=10,
        end_line=20,
        metadata={"chunk_id": "chunk-1"},
    )

    assert source_id.startswith("F")
    assert isinstance(item.metadata, MappingProxyType)
    assert item.metadata["chunk_id"] == "chunk-1"
    with pytest.raises(ValueError, match="terminar despues"):
        EvidenceItem(
            evidence_id=source_id,
            source_type=EvidenceSourceType.CHUNK,
            title="Regla",
            citation="[F1]",
            start_line=20,
            end_line=10,
        )


def test_detected_components_and_rules_require_evidence() -> None:
    source_id = evidence_id(
        source_type=EvidenceSourceType.SYMBOL,
        source_key=VALID_SHA,
    )

    component = AffectedComponent(
        component_id=VALID_SHA,
        name="pkg_credito",
        role=AffectedComponentRole.DIRECT,
        technology="oracle",
        classification=SpecConclusionKind.DETECTED,
        evidence_ids=(source_id,),
        component_type="package",
    )
    rule = ExistingRule(
        rule_id="REG-001",
        description="El limite se valida antes de aprobar.",
        classification=SpecConclusionKind.DETECTED,
        evidence_ids=(source_id,),
        applies_to=("pkg_credito",),
    )

    assert component.evidence_ids == (source_id,)
    assert rule.applies_to == ("pkg_credito",)
    with pytest.raises(ValueError, match="componentes detectados"):
        AffectedComponent(
            component_id=OTHER_SHA,
            name="w_credito",
            role=AffectedComponentRole.CONSUMER,
            technology="powerbuilder",
            classification=SpecConclusionKind.DETECTED,
        )
    with pytest.raises(ValueError, match="reglas detectadas"):
        ExistingRule(
            rule_id="REG-002",
            description="Regla sin fuente.",
            classification=SpecConclusionKind.DETECTED,
        )


def test_trace_link_rejects_self_reference() -> None:
    link = TraceLink(
        source_kind=SpecItemKind.REQUIREMENT,
        source_id="REQ-001",
        target_kind=SpecItemKind.EVIDENCE,
        target_id="Fabcdef123456",
        relation="supported_by",
    )

    assert link.relation == "supported_by"
    with pytest.raises(ValueError, match="mismo elemento"):
        TraceLink(
            source_kind=SpecItemKind.TASK,
            source_id="TASK-001",
            target_kind=SpecItemKind.TASK,
            target_id="TASK-001",
            relation="depends_on",
        )


def test_spec_draft_id_is_stable_and_rejects_duplicate_evidence() -> None:
    request = SpecRequest("Agregar validacion de limite de credito")
    intent = RequirementIntent(
        original_text=request.requirement,
        search_terms=("limite credito",),
    )
    draft_id = spec_draft_id(request, intent)
    source_id = evidence_id(
        source_type=EvidenceSourceType.RELATION,
        source_key=VALID_SHA,
    )
    evidence = EvidenceItem(
        evidence_id=source_id,
        source_type=EvidenceSourceType.RELATION,
        title="Relacion calls",
        citation="[F1] relacion calls",
        relation_id=VALID_SHA,
    )

    draft = SpecDraft(
        draft_id=draft_id,
        request=request,
        intent=intent,
        evidence=(evidence,),
        requirements=("REQ-001 Validar limite",),
        warnings=("Evidencia parcial",),
    )

    assert draft.draft_id == spec_draft_id(request, intent)
    assert draft.requirements == ("REQ-001 Validar limite",)
    with pytest.raises(ValueError, match="no debe repetir"):
        SpecDraft(
            draft_id=draft_id,
            request=request,
            intent=intent,
            evidence=(evidence, evidence),
        )


def test_validation_issue_keeps_related_ids() -> None:
    issue = ValidationIssue(
        severity=ValidationSeverity.ERROR,
        code="H5_CITATION_MISSING",
        message="La cita no existe.",
        location="requirements.md",
        related_ids=("REQ-001", "Fabcdef123456"),
    )

    assert issue.severity == ValidationSeverity.ERROR
    assert issue.related_ids == ("REQ-001", "Fabcdef123456")


def test_review_issue_marks_draft_stage_and_degradation() -> None:
    issue = ReviewIssue(
        severity=ValidationSeverity.WARNING,
        code="H5_REVIEW_INSUFFICIENT_EVIDENCE",
        message="El requisito debe degradarse a evidencia insuficiente.",
        draft_section="requirements",
        related_ids=("REQ-001", "Fabcdef123456"),
        degradable=True,
    )

    assert issue.draft_section == "requirements"
    assert issue.degradable is True
    assert issue.related_ids == ("REQ-001", "Fabcdef123456")


@pytest.mark.parametrize(
    "factory",
    [
        lambda: SpecRequest(""),
        lambda: SpecRequest("ok", depth=-1),
        lambda: SpecRequest("ok", top_k=0),
        lambda: RequirementIntent("", search_terms=("x",)),
        lambda: RequirementIntent("ok", search_terms=("",)),
        lambda: EvidenceItem(
            evidence_id="Fbad",
            source_type=EvidenceSourceType.CHUNK,
            title="Fuente",
            citation="[F1]",
        ),
        lambda: EvidenceItem(
            evidence_id="Fabcdef123456",
            source_type=EvidenceSourceType.SYMBOL,
            title="Simbolo",
            citation="[F1]",
            symbol_id="bad",
        ),
        lambda: ExistingRule(
            rule_id="RULE-001",
            description="Regla",
            classification=SpecConclusionKind.ASSUMPTION,
        ),
        lambda: SpecDraft(
            draft_id="bad",
            request=SpecRequest("ok"),
            intent=RequirementIntent("ok"),
        ),
        lambda: ValidationIssue(
            severity=ValidationSeverity.WARNING,
            code="",
            message="Mensaje",
        ),
        lambda: ReviewIssue(
            severity=ValidationSeverity.ERROR,
            code="H5_REVIEW_EMPTY_SECTION",
            message="Mensaje",
            draft_section="",
        ),
    ],
)
def test_invalid_h5_models_are_rejected(factory: object) -> None:
    with pytest.raises(ValueError):
        factory()
