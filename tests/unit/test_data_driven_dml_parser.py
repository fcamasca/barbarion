"""Pruebas del splitter DML Data-Driven."""

from barbarion.infrastructure.parsers.data_driven_dml import (
    DmlStatement,
    split_dml_statements,
)


def test_split_dml_statements_uses_semicolon_outside_strings() -> None:
    statements = split_dml_statements(
        "INSERT INTO cfg VALUES ('a;b', 'c'';d');\n"
        "UPDATE cfg SET value = 'x' WHERE id = 1;"
    )

    assert statements == (
        DmlStatement(
            text="INSERT INTO cfg VALUES ('a;b', 'c'';d')",
            start_line=1,
            end_line=1,
            terminated=True,
        ),
        DmlStatement(
            text="UPDATE cfg SET value = 'x' WHERE id = 1",
            start_line=2,
            end_line=2,
            terminated=True,
        ),
    )


def test_split_dml_statements_ignores_semicolon_inside_comments() -> None:
    statements = split_dml_statements(
        "INSERT INTO cfg VALUES ('A') -- ; ignored\n"
        ";\n"
        "/* ; ignored */ UPDATE cfg SET value = 'B' WHERE id = 1;"
    )

    assert [statement.text for statement in statements] == [
        "INSERT INTO cfg VALUES ('A') -- ; ignored",
        "/* ; ignored */ UPDATE cfg SET value = 'B' WHERE id = 1",
    ]


def test_split_dml_statements_accepts_safe_final_statement_without_semicolon() -> None:
    statements = split_dml_statements(
        "INSERT INTO cfg VALUES ('A');\n"
        "UPDATE cfg SET value = 'B' WHERE id = 1"
    )

    assert statements[-1] == DmlStatement(
        text="UPDATE cfg SET value = 'B' WHERE id = 1",
        start_line=2,
        end_line=2,
        terminated=False,
    )


def test_split_dml_statements_omits_unsafe_final_fragment() -> None:
    statements = split_dml_statements(
        "INSERT INTO cfg VALUES ('A');\n"
        "UPDATE cfg SET value = 'B WHERE id = 1"
    )

    assert statements == (
        DmlStatement(
            text="INSERT INTO cfg VALUES ('A')",
            start_line=1,
            end_line=1,
            terminated=True,
        ),
    )
