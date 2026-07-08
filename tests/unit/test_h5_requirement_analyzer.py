"""Pruebas de interpretacion inicial de requerimientos H5."""

import pytest

from barbarion.application.spec_mode import RequirementAnalyzer
from barbarion.domain.spec_mode import RequirementIntent, SpecRequest


def test_requirement_analyzer_extracts_concrete_intent() -> None:
    analyzer = RequirementAnalyzer()
    intent = analyzer.analyze(
        SpecRequest(
            "Validar limite de credito antes de aprobar pedidos en pkg_credito",
            no_llm=True,
        )
    )

    assert isinstance(intent, RequirementIntent)
    assert intent.original_text == (
        "Validar limite de credito antes de aprobar pedidos en pkg_credito"
    )
    assert intent.goals == (intent.original_text,)
    assert intent.actions == ("validar", "aprobar")
    assert "pkg_credito" in intent.entities
    assert "limite_de_credito" in intent.entities
    assert "antes de aprobar pedidos en pkg_credito" in intent.constraints
    assert "limite de credito" in intent.search_terms
    assert not intent.open_questions


def test_requirement_analyzer_keeps_questions_for_ambiguous_request() -> None:
    intent = RequirementAnalyzer().analyze("Mejorar el proceso")

    assert intent.actions == ()
    assert "Que accion funcional debe especificarse?" in intent.open_questions
    assert (
        "Que limite, condicion o criterio de aceptacion aplica?"
        in intent.open_questions
    )


def test_requirement_analyzer_extracts_constraints_assumptions_and_quoted_entities() -> None:
    intent = RequirementAnalyzer().analyze(
        "Agregar regla para 'orden_total' sin modificar calculo historico, "
        "asumiendo moneda local"
    )

    assert intent.actions == ("agregar", "modificar")
    assert "orden_total" in intent.entities
    assert "sin modificar calculo historico" in intent.constraints
    assert "asumiendo moneda local" in intent.assumptions
    assert "orden total" in intent.search_terms


def test_requirement_analyzer_is_deterministic() -> None:
    analyzer = RequirementAnalyzer()

    first = analyzer.analyze(
        "Mostrar deuda vencida cuando el cliente tenga facturas pendientes"
    )
    second = analyzer.analyze(
        "Mostrar deuda vencida cuando el cliente tenga facturas pendientes"
    )

    assert first == second
    assert first.actions == ("mostrar",)
    assert "cuando el cliente tenga facturas pendientes" in first.constraints


def test_requirement_analyzer_rejects_empty_request() -> None:
    with pytest.raises(ValueError, match="requirement"):
        RequirementAnalyzer().analyze("   ")
