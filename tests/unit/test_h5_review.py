"""Pruebas del Review interno H5."""

from barbarion.application.spec_mode import SpecReviewer
from barbarion.domain.spec_mode import (
    EvidenceItem,
    EvidenceSourceType,
    ExistingRule,
    RequirementIntent,
    SpecConclusionKind,
    SpecDraft,
    SpecRequest,
)


VALID_SHA = "a" * 64
EVIDENCE_ID = "F111111111111"
MISSING_EVIDENCE_ID = "F222222222222"


def test_spec_reviewer_allows_degradable_draft_with_insufficient_evidence() -> None:
    draft = SpecDraft(
        draft_id=VALID_SHA,
        request=SpecRequest("Validar limite de credito", name="limite-credito"),
        intent=RequirementIntent(
            original_text="Validar limite de credito",
            actions=("validar",),
            entities=("limite_credito",),
        ),
    )

    result = SpecReviewer().review(draft)

    assert result.can_render is True
    assert result.degraded is True
    assert {issue.code for issue in result.issues} == {
        "H5_REVIEW_INSUFFICIENT_EVIDENCE",
        "H5_REVIEW_RULES_TO_CONFIRM",
    }


def test_spec_reviewer_blocks_detected_rule_with_missing_evidence() -> None:
    draft = SpecDraft(
        draft_id=VALID_SHA,
        request=SpecRequest("Validar limite de credito", name="limite-credito"),
        intent=RequirementIntent(original_text="Validar limite de credito"),
        existing_rules=(
            ExistingRule(
                rule_id="REG-001",
                description="Regla detectada sin fuente presente.",
                classification=SpecConclusionKind.DETECTED,
                evidence_ids=(MISSING_EVIDENCE_ID,),
            ),
        ),
    )

    result = SpecReviewer().review(draft)

    assert result.can_render is False
    assert any(
        issue.code == "H5_REVIEW_RULE_EVIDENCE_MISSING"
        for issue in result.issues
    )


def test_spec_reviewer_detects_missing_citations_and_orphan_items() -> None:
    draft = SpecDraft(
        draft_id=VALID_SHA,
        request=SpecRequest("Validar limite de credito", name="limite-credito"),
        intent=RequirementIntent(original_text="Validar limite de credito"),
        evidence=(_evidence(),),
        requirements=(f"REQ-001 Validar limite [{EVIDENCE_ID}]",),
        tasks=("Implementar cambio sin requisito asociado.",),
        tests=(f"TEST-001 cita inexistente [{MISSING_EVIDENCE_ID}]",),
    )

    result = SpecReviewer().review(draft)

    assert result.can_render is False
    assert any(issue.code == "H5_REVIEW_CITATION_MISSING" for issue in result.issues)
    assert any(
        issue.code == "H5_REVIEW_ITEM_WITHOUT_REQUIREMENT"
        and issue.degradable
        for issue in result.issues
    )


def _evidence() -> EvidenceItem:
    return EvidenceItem(
        evidence_id=EVIDENCE_ID,
        source_type=EvidenceSourceType.CHUNK,
        title="F1 sources/oracle/pkg_credito.sql",
        citation="[F1] sources/oracle/pkg_credito.sql lineas=10-12",
        file_path="sources/oracle/pkg_credito.sql",
        chunk_id="chunk-1",
        start_line=10,
        end_line=12,
        detail="validar limite_credito antes de aprobar",
    )
