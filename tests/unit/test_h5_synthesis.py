"""Pruebas de sintesis analitica H5."""

from barbarion.application.spec_mode import (
    DocumentEvidenceResult,
    RequirementAnalyzer,
    SpecSynthesizer,
    SpecSynthesisRequest,
    TechnicalImpactResult,
)
from barbarion.domain.rag import ContextBuildResult, ContextQualityMetrics
from barbarion.domain.spec_mode import (
    AffectedComponent,
    AffectedComponentRole,
    EvidenceItem,
    EvidenceSourceType,
    SpecConclusionKind,
    SpecRequest,
    evidence_id,
)


VALID_SHA = "a" * 64


def test_synthesizer_detects_rule_only_from_document_evidence() -> None:
    request = SpecRequest("Validar limite de credito antes de aprobar pedidos")
    intent = RequirementAnalyzer().analyze(request)
    evidence = _chunk_evidence(
        "validar limite_credito antes de aprobar pedido si excede cupo"
    )

    draft = SpecSynthesizer().synthesize(
        SpecSynthesisRequest(
            request=request,
            intent=intent,
            document_evidence=_document_result(evidence),
            technical_impact=TechnicalImpactResult(components=(), evidence=()),
        )
    )

    assert len(draft.existing_rules) == 1
    assert draft.existing_rules[0].classification == SpecConclusionKind.DETECTED
    assert draft.existing_rules[0].evidence_ids == (evidence.evidence_id,)
    assert evidence in draft.evidence


def test_synthesizer_does_not_create_detected_rule_from_h4_evidence() -> None:
    request = SpecRequest("Validar limite de credito en pkg_credito")
    intent = RequirementAnalyzer().analyze(request)
    h4_evidence = EvidenceItem(
        evidence_id=evidence_id(
            source_type=EvidenceSourceType.SYMBOL,
            source_key="symbol:pkg_credito",
        ),
        source_type=EvidenceSourceType.SYMBOL,
        title="Simbolo H4 pkg_credito",
        citation="[H4] simbolo pkg_credito",
        symbol_id=VALID_SHA,
        detail="procedure oracle",
    )

    draft = SpecSynthesizer().synthesize(
        SpecSynthesisRequest(
            request=request,
            intent=intent,
            technical_impact=TechnicalImpactResult(
                components=(),
                evidence=(h4_evidence,),
            ),
        )
    )

    assert draft.existing_rules == ()
    assert h4_evidence in draft.evidence
    assert any("regla existente" in question for question in draft.open_questions)
    assert any("No se genero ninguna regla detectada" in warning for warning in draft.warnings)


def test_synthesizer_keeps_h4_uncertainty_as_risk_and_question() -> None:
    request = SpecRequest("Validar limite de credito en pkg_credito")
    intent = RequirementAnalyzer().analyze(request)
    uncertain = AffectedComponent(
        component_id="unresolved:pkg_dinamico",
        name="pkg_dinamico",
        role=AffectedComponentRole.UNKNOWN,
        technology="unknown",
        classification=SpecConclusionKind.TO_CONFIRM,
        unresolved_reason="dynamic",
    )

    draft = SpecSynthesizer().synthesize(
        SpecSynthesisRequest(
            request=request,
            intent=intent,
            document_evidence=_document_result(
                _chunk_evidence("validar limite_credito antes de aprobar")
            ),
            technical_impact=TechnicalImpactResult(
                components=(uncertain,),
                evidence=(),
                warnings=("H4 no resolvio pkg_dinamico.",),
                insufficient_catalog=True,
            ),
        )
    )

    assert draft.affected_components == (uncertain,)
    assert any("por confirmar" in risk for risk in draft.risks)
    assert any("pkg_dinamico" in question for question in draft.open_questions)
    assert "H4 no resolvio pkg_dinamico." in draft.warnings


def test_synthesizer_deduplicates_evidence_across_h3_and_h4_results() -> None:
    request = SpecRequest("Validar limite de credito")
    intent = RequirementAnalyzer().analyze(request)
    evidence = _chunk_evidence("validar limite_credito")

    draft = SpecSynthesizer().synthesize(
        SpecSynthesisRequest(
            request=request,
            intent=intent,
            document_evidence=_document_result(evidence),
            technical_impact=TechnicalImpactResult(
                components=(),
                evidence=(evidence,),
            ),
        )
    )

    assert draft.evidence == (evidence,)


def _chunk_evidence(detail: str) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id(
            source_type=EvidenceSourceType.CHUNK,
            source_key=detail,
        ),
        source_type=EvidenceSourceType.CHUNK,
        title="F1 sources/oracle/pkg_credito.sql",
        citation="[F1] sources/oracle/pkg_credito.sql lineas=10-12",
        file_path="sources/oracle/pkg_credito.sql",
        chunk_id="chunk-1",
        start_line=10,
        end_line=12,
        detail=detail,
    )


def _document_result(*evidence: EvidenceItem) -> DocumentEvidenceResult:
    return DocumentEvidenceResult(
        query="limite credito",
        evidence=tuple(evidence),
        context=ContextBuildResult(
            sources=(),
            omitted=(),
            rendered_context="",
            token_estimate=0,
            metrics=ContextQualityMetrics(),
        ),
        insufficient_evidence=not evidence,
    )
