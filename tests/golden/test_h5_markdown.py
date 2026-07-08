"""Golden files para Markdown H5 Spec Mode."""

from pathlib import Path

from barbarion.domain.spec_mode import (
    AffectedComponent,
    AffectedComponentRole,
    EvidenceItem,
    EvidenceSourceType,
    ExistingRule,
    RequirementIntent,
    SpecConclusionKind,
    SpecDraft,
    SpecRequest,
)
from barbarion.infrastructure.markdown import SPEC_MARKDOWN_FILES, render_spec_markdown


GENERATED_AT = "2026-01-01T00:00:00+00:00"
VALID_SHA = "a" * 64
COMPONENT_SHA = "b" * 64
EVIDENCE_ID = "F111111111111"


def test_h5_spec_markdown_matches_golden_files() -> None:
    markdown = render_spec_markdown(_draft(), generated_at=GENERATED_AT)

    assert tuple(markdown) == SPEC_MARKDOWN_FILES
    for filename in SPEC_MARKDOWN_FILES:
        expected = Path(__file__).with_name(f"h5_{filename}").read_text(
            encoding="utf-8"
        )
        assert markdown[filename] == expected


def _draft() -> SpecDraft:
    return SpecDraft(
        draft_id=VALID_SHA,
        request=SpecRequest(
            "Validar limite de credito antes de aprobar pedidos",
            name="limite-credito",
            no_llm=True,
        ),
        intent=RequirementIntent(
            original_text="Validar limite de credito antes de aprobar pedidos",
            actions=("validar", "aprobar"),
            entities=("limite_credito", "pedido"),
            search_terms=("limite credito", "aprobar pedido"),
        ),
        evidence=(_evidence(),),
        affected_components=(
            AffectedComponent(
                component_id=COMPONENT_SHA,
                name="pkg_credito",
                role=AffectedComponentRole.DIRECT,
                technology="oracle",
                classification=SpecConclusionKind.DETECTED,
                evidence_ids=(EVIDENCE_ID,),
                component_type="package",
                reason="simbolo semilla resuelto por H4",
            ),
        ),
        existing_rules=(
            ExistingRule(
                rule_id="REG-001",
                description=(
                    "Evidencia documental indica validar relacionado con "
                    "limite_credito: validar limite_credito antes de aprobar"
                ),
                classification=SpecConclusionKind.DETECTED,
                evidence_ids=(EVIDENCE_ID,),
                applies_to=("limite_credito", "pedido"),
            ),
        ),
        risks=("El impacto cruza tecnologia Oracle y requiere regresion.",),
        open_questions=("Confirmar umbral exacto de limite de credito.",),
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
