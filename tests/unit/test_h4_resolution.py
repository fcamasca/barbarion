"""Pruebas H4-T04 para resolucion conservadora de referencias."""

from barbarion.application.reverse_engineering import relation_from_reference
from barbarion.domain.models import Confidence
from barbarion.domain.reverse_engineering import (
    H4Classification,
    H4Reference,
    H4ResolutionStatus,
    H4Symbol,
    h4_reference_id,
    h4_symbol_id,
)


def test_qualified_reference_resolves_only_compatible_container_and_type() -> None:
    target = _symbol("procesar", "procedure", container_name="pkg_cliente")
    wrong_type = _symbol("procesar", "table", container_name="pkg_cliente")
    wrong_container = _symbol("procesar", "procedure", container_name="pkg_otro")
    reference = _reference(
        "PKG_CLIENTE.PROCESAR",
        normalized_target="pkg_cliente.procesar",
        reference_type="call",
    )

    relation, candidates = relation_from_reference(
        reference,
        (target, wrong_type, wrong_container),
    ) or (None, ())

    assert relation is not None
    assert relation.resolution_status == H4ResolutionStatus.RESOLVED
    assert relation.target_symbol_id == target.symbol_id
    assert relation.target_key == "pkg_cliente.procesar"
    assert relation.relation_type == "calls"
    assert candidates == ()


def test_unqualified_reference_uses_source_container_when_available() -> None:
    source = _symbol("actual", "procedure", container_name="pkg_cliente")
    same_container = _symbol("procesar", "procedure", container_name="pkg_cliente")
    other_container = _symbol("procesar", "procedure", container_name="pkg_otro")
    reference = _reference(
        "PROCESAR",
        normalized_target="procesar",
        reference_type="call",
        source_symbol_id=source.symbol_id,
    )

    relation, candidates = relation_from_reference(
        reference,
        (source, same_container, other_container),
    ) or (None, ())

    assert relation is not None
    assert relation.resolution_status == H4ResolutionStatus.RESOLVED
    assert relation.target_symbol_id == same_container.symbol_id
    assert candidates == ()


def test_multiple_compatible_candidates_become_ambiguous_with_candidates() -> None:
    first = _symbol("procesar", "procedure", container_name="pkg_a")
    second = _symbol("procesar", "procedure", container_name="pkg_b")
    reference = _reference(
        "PROCESAR",
        normalized_target="procesar",
        reference_type="call",
    )

    relation, candidates = relation_from_reference(reference, (first, second)) or (
        None,
        (),
    )

    assert relation is not None
    assert relation.resolution_status == H4ResolutionStatus.AMBIGUOUS
    assert relation.classification == H4Classification.TO_CONFIRM
    assert relation.target_symbol_id is None
    assert tuple(candidate.candidate_symbol_id for candidate in candidates) == (
        first.symbol_id,
        second.symbol_id,
    )


def test_no_candidate_does_not_create_low_quality_unresolved_relation() -> None:
    reference = _reference(
        "NO_EXISTE",
        normalized_target="no_existe",
        reference_type="call",
    )

    assert relation_from_reference(reference, ()) is None


def test_dynamic_and_external_references_keep_explicit_statuses() -> None:
    dynamic_reference = _reference(
        "execute immediate v_sql",
        normalized_target="dynamic.sql",
        reference_type="dynamic_sql",
        resolution_status=H4ResolutionStatus.DYNAMIC,
    )
    external_reference = _reference(
        "remote_pkg.process@erp_link",
        normalized_target="remote_pkg.process",
        reference_type="call",
        metadata={"scope": "external"},
    )

    dynamic_relation, dynamic_candidates = relation_from_reference(
        dynamic_reference,
        (),
    ) or (None, ())
    external_relation, external_candidates = relation_from_reference(
        external_reference,
        (),
    ) or (None, ())

    assert dynamic_relation is not None
    assert dynamic_relation.resolution_status == H4ResolutionStatus.DYNAMIC
    assert dynamic_relation.classification == H4Classification.TO_CONFIRM
    assert dynamic_relation.target_key == "dynamic.sql"
    assert dynamic_candidates == ()
    assert external_relation is not None
    assert external_relation.resolution_status == H4ResolutionStatus.EXTERNAL
    assert external_relation.target_key == "remote_pkg.process"
    assert external_candidates == ()


def _symbol(
    normalized_name: str,
    symbol_type: str,
    *,
    container_name: str | None = None,
    technology: str = "oracle",
) -> H4Symbol:
    symbol_id = h4_symbol_id(
        normalized_name=normalized_name,
        symbol_type=symbol_type,
        technology=technology,
        container_name=container_name,
    )
    return H4Symbol(
        symbol_id=symbol_id,
        original_name=normalized_name,
        normalized_name=normalized_name,
        symbol_type=symbol_type,
        technology=technology,
        extraction_method="fixture",
        confidence=Confidence.HIGH,
        container_name=container_name,
    )


def _reference(
    raw_text: str,
    *,
    normalized_target: str,
    reference_type: str,
    technology: str = "oracle",
    source_symbol_id: str | None = None,
    resolution_status: H4ResolutionStatus = H4ResolutionStatus.UNRESOLVED,
    metadata: dict[str, object] | None = None,
) -> H4Reference:
    reference_id = h4_reference_id(
        source_file_id=1,
        raw_text=raw_text,
        normalized_target=normalized_target,
        reference_type=reference_type,
        start_line=1,
        end_line=1,
    )
    return H4Reference(
        reference_id=reference_id,
        source_file_id=1,
        source_symbol_id=source_symbol_id,
        raw_text=raw_text,
        normalized_target=normalized_target,
        reference_type=reference_type,
        technology=technology,
        detection_method="fixture",
        confidence=Confidence.MEDIUM,
        resolution_status=resolution_status,
        start_line=1,
        end_line=1,
        metadata=metadata or {},
    )
