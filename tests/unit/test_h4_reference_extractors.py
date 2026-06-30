"""Pruebas H4-T03 para extractores conservadores de referencias."""

from barbarion.domain.models import Confidence
from barbarion.domain.reverse_engineering import ResolutionStatus
from barbarion.infrastructure.parsers.oracle import extract_oracle_references
from barbarion.infrastructure.parsers.powerbuilder import (
    extract_powerbuilder_references,
)


def test_oracle_reference_extractor_detects_common_raw_references() -> None:
    text = """create or replace package body pkg_orders as
  procedure run is
    v_count number;
  begin
    pkg_customer.process_order(42);
    call pkg_invoice.generate_invoice(42);
    select count(*) into v_count from order_header h join order_line l on l.id = h.id;
    v_id := order_seq.nextval;
    execute immediate v_sql;
  end run;
end pkg_orders;
/
"""

    references = extract_oracle_references(
        text,
        source_file_id=10,
        source_chunk_id="chunk-oracle",
    )
    observed = {
        (
            reference.normalized_target,
            reference.reference_type,
            reference.resolution_status,
            reference.confidence,
            reference.start_line,
        )
        for reference in references
    }

    assert observed == {
        ("pkg_customer.process_order", "call", ResolutionStatus.UNRESOLVED, Confidence.MEDIUM, 5),
        ("pkg_invoice.generate_invoice", "call", ResolutionStatus.UNRESOLVED, Confidence.HIGH, 6),
        ("order_header", "table", ResolutionStatus.UNRESOLVED, Confidence.HIGH, 7),
        ("order_line", "table", ResolutionStatus.UNRESOLVED, Confidence.HIGH, 7),
        ("order_seq", "sequence", ResolutionStatus.UNRESOLVED, Confidence.HIGH, 8),
        ("dynamic.sql", "dynamic_sql", ResolutionStatus.DYNAMIC, Confidence.LOW, 9),
    }
    assert all(reference.technology == "oracle" for reference in references)
    assert all(reference.detection_method == "regex" for reference in references)


def test_oracle_reference_extractor_ignores_comments_literals_and_into_variables() -> None:
    text = """begin
  -- pkg_commented.run();
  v_text := 'pkg_literal.run() from hidden_table';
  select count(*) into v_count from visible_table;
end;
"""

    references = extract_oracle_references(text, source_file_id=11)

    assert [
        (reference.normalized_target, reference.reference_type)
        for reference in references
    ] == [("visible_table", "table")]


def test_oracle_reference_extractor_handles_two_refs_same_line_and_multiline_noise() -> None:
    text = """begin
  /*
    pkg_hidden.run();
    select * from hidden_table;
  */
  v_sql := 'select * from literal_table where pkg_literal.run() = 1';
  pkg_a.run(); pkg_b.run();
end;
"""

    references = extract_oracle_references(text, source_file_id=12)

    assert [
        (reference.normalized_target, reference.reference_type, reference.start_line)
        for reference in references
    ] == [
        ("pkg_a.run", "call", 7),
        ("pkg_b.run", "call", 7),
    ]


def test_powerbuilder_reference_extractor_detects_common_raw_references() -> None:
    text = """open(w_customer)
uo_service.process_order(li_id)
trigger event clicked
dw_orders.dataobject = "d_orders"
SELECT id INTO :li_id FROM order_header;
DECLARE proc_order PROCEDURE FOR sp_process_order;
EXECUTE proc_order;
EXECUTE IMMEDIATE :ls_sql;
"""

    references = extract_powerbuilder_references(
        text,
        source_file_id=20,
        source_chunk_id="chunk-pb",
    )
    observed = {
        (
            reference.normalized_target,
            reference.reference_type,
            reference.resolution_status,
            reference.confidence,
            reference.start_line,
        )
        for reference in references
    }

    assert observed == {
        ("w_customer", "open", ResolutionStatus.UNRESOLVED, Confidence.HIGH, 1),
        ("uo_service.process_order", "call", ResolutionStatus.UNRESOLVED, Confidence.MEDIUM, 2),
        ("clicked", "event", ResolutionStatus.UNRESOLVED, Confidence.HIGH, 3),
        ("d_orders", "datawindow", ResolutionStatus.UNRESOLVED, Confidence.HIGH, 4),
        ("order_header", "table", ResolutionStatus.UNRESOLVED, Confidence.MEDIUM, 5),
        ("sp_process_order", "stored_procedure", ResolutionStatus.UNRESOLVED, Confidence.HIGH, 6),
        ("proc_order", "stored_procedure", ResolutionStatus.UNRESOLVED, Confidence.HIGH, 7),
        ("dynamic.sql", "dynamic_sql", ResolutionStatus.DYNAMIC, Confidence.LOW, 8),
    }
    assert all(reference.technology == "powerbuilder" for reference in references)
    assert all(reference.detection_method == "regex" for reference in references)


def test_powerbuilder_reference_extractor_ignores_comments_literals_and_builtins() -> None:
    text = """// open(w_commented)
ls_text = "uo_literal.process()"
MessageBox("Aviso", "open(w_literal)")
dw_1.dataobject = "d_visible"
"""

    references = extract_powerbuilder_references(text, source_file_id=21)

    assert [
        (reference.normalized_target, reference.reference_type)
        for reference in references
    ] == [("d_visible", "datawindow")]


def test_powerbuilder_reference_extractor_detects_call_inside_event() -> None:
    text = """event clicked()
  uo_service.process_order(li_order)
end event
"""

    references = extract_powerbuilder_references(text, source_file_id=22)

    assert [
        (reference.normalized_target, reference.reference_type, reference.start_line)
        for reference in references
    ] == [("uo_service.process_order", "call", 2)]
